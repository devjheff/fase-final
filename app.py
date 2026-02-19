from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta
import bcrypt
import re
import os
import secrets
import logging
from logging.handlers import RotatingFileHandler
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# ==================== CONFIGURAÇÕES DE SEGURANÇA ====================
app.config.update(
    SESSION_COOKIE_SECURE=True,  # Apenas HTTPS
    SESSION_COOKIE_HTTPONLY=True,  # Não acessível via JavaScript
    SESSION_COOKIE_SAMESITE='Lax',  # Proteção contra CSRF
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),  # Sessão expira em 2h
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_HTTPONLY=True,
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,  # Limite de 16MB para uploads
)

# ==================== RATE LIMITING ====================
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"  # Para produção, use Redis
)

# ==================== LOGGING SEGURO ====================
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

# ==================== CONFIGURAÇÃO DO BANCO ====================
def get_connection():
    """Obtém conexão com o banco de dados usando DATABASE_URL do ambiente"""
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        error_msg = "❌ ERRO: DATABASE_URL não configurada nas variáveis de ambiente!"
        app.logger.error(error_msg)
        raise Exception(error_msg)
    
    try:
        if 'sslmode' not in database_url:
            if '?' in database_url:
                database_url += '&sslmode=require'
            else:
                database_url += '?sslmode=require'
        
        app.logger.info("🔄 Tentando conectar ao banco...")
        conn = psycopg2.connect(database_url)
        app.logger.info("✅ Conexão estabelecida com sucesso!")
        return conn
        
    except Exception as e:
        app.logger.error(f"❌ Erro de conexão: {str(e)}")
        raise

# ==================== FUNÇÕES DE SEGURANÇA ====================

def sanitizar_input(texto):
    """Remove caracteres perigosos do input"""
    if not texto:
        return texto
    if not isinstance(texto, str):
        texto = str(texto)
    return bleach.clean(texto.strip(), tags=[], strip=True)

def hash_senha(senha):
    """Gera hash seguro da senha usando bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(senha.encode('utf-8'), salt).decode('utf-8')

def verificar_senha(senha, hash_armazenado):
    """Verifica se a senha corresponde ao hash"""
    try:
        return bcrypt.checkpw(senha.encode('utf-8'), hash_armazenado.encode('utf-8'))
    except:
        return False

def validar_senha_forte(senha):
    """Valida se a senha é forte"""
    if len(senha) < 8:
        return False, "Senha deve ter no mínimo 8 caracteres"
    
    if not re.search(r"[A-Z]", senha):
        return False, "Senha deve ter pelo menos uma letra maiúscula"
    
    if not re.search(r"[a-z]", senha):
        return False, "Senha deve ter pelo menos uma letra minúscula"
    
    if not re.search(r"\d", senha):
        return False, "Senha deve ter pelo menos um número"
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", senha):
        return False, "Senha deve ter pelo menos um caractere especial"
    
    return True, "Senha válida"

def validar_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validar_email_seguro(email):
    """Valida email e rejeita emails temporários"""
    if not validar_email(email):
        return False, "Formato de email inválido"
    
    # Lista de domínios de email temporário
    dominios_temporarios = [
        'temp-mail.org', 'guerrillamail.com', 'yopmail.com',
        'mailinator.com', '10minutemail.com', 'throwawaymail.com',
        'tempmail.com', 'fakeinbox.com', 'maildrop.cc'
    ]
    
    dominio = email.split('@')[-1].lower()
    if dominio in dominios_temporarios:
        return False, "Emails temporários não são permitidos"
    
    return True, "Email válido"

def validate_date(date_string):
    """Valida data no formato YYYY-MM-DD"""
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def converter_data_br_para_iso(data_br):
    """Converte data do formato DD/MM/YYYY para YYYY-MM-DD"""
    try:
        data_br = data_br.strip()
        if re.match(r'\d{2}/\d{2}/\d{4}', data_br):
            dia, mes, ano = data_br.split('/')
            return f"{ano}-{mes}-{dia}"
        return data_br
    except:
        return data_br

def calcular_idade(data_nascimento_str):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, '%Y-%m-%d').date()
        hoje = date.today()
        idade = hoje.year - data_nascimento.year
        if (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day):
            idade -= 1
        return idade
    except Exception as e:
        app.logger.error(f"Erro ao calcular idade: {e}")
        return 0

def formatar_telefone(telefone):
    """Formata o telefone para exibição"""
    if not telefone:
        return '-'
    numeros = re.sub(r'\D', '', telefone)
    if len(numeros) == 11:
        return f'({numeros[:2]}) {numeros[2:7]}-{numeros[7:]}'
    elif len(numeros) == 10:
        return f'({numeros[:2]}) {numeros[2:6]}-{numeros[6:]}'
    return telefone

def gerar_token_recuperacao(email):
    """Gera token para recuperação de senha"""
    return secrets.token_urlsafe(32)

# ==================== CSRF TOKEN ====================
@app.before_request
def gerar_csrf_token():
    """Gera token CSRF para cada sessão"""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)

# ==================== DECORATOR DE LOGIN MELHORADO ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        public_pages = ['login', 'cadastro', 'health_check', 'test_db', 'debug_env', 
                       'recuperar_senha', 'resetar_senha']
        
        if request.endpoint not in public_pages:
            if 'usuario_id' not in session:
                flash('Por favor, faça login para acessar o sistema.', 'warning')
                return redirect(url_for('login'))
            
            # Verificar tempo de sessão (opcional)
            if 'login_time' in session:
                login_time = datetime.fromisoformat(session['login_time'])
                if datetime.now() - login_time > timedelta(hours=2):
                    session.clear()
                    flash('Sessão expirada. Faça login novamente.', 'warning')
                    return redirect(url_for('login'))
            
            # Verificar CSRF em requisições POST
            if request.method == 'POST':
                csrf_token = request.form.get('csrf_token')
                session_csrf = session.get('csrf_token')
                
                if not csrf_token or not session_csrf or csrf_token != session_csrf:
                    app.logger.warning(f"Tentativa de CSRF detectada - IP: {request.remote_addr}")
                    flash('Token de segurança inválido. Tente novamente.', 'error')
                    return redirect(url_for('logout'))
        
        return f(*args, **kwargs)
    
    return decorated_function

# ==================== ROTAS DE DEBUG ====================

@app.route("/debug-env")
def debug_env():
    """Rota para debug - MOSTRA AS VARIÁVEIS DE AMBIENTE (use apenas temporariamente)"""
    env_vars = {
        "DATABASE_URL_existe": bool(os.environ.get('DATABASE_URL')),
        "FLASK_ENV": os.environ.get('FLASK_ENV', 'não configurado'),
        "SECRET_KEY_existe": bool(os.environ.get('SECRET_KEY')),
    }
    
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        masked_url = re.sub(r':([^@]+)@', ':****@', db_url)
        env_vars["DATABASE_URL_mascarada"] = masked_url
    else:
        env_vars["DATABASE_URL_mascarada"] = "Não configurada"
    
    return jsonify(env_vars)

@app.route("/test-db")
def test_db():
    """Rota para testar conexão com o banco"""
    results = {
        "status": "testando",
        "database_url_configurada": False,
        "testes": []
    }
    
    database_url = os.environ.get('DATABASE_URL')
    results["database_url_configurada"] = bool(database_url)
    
    if not database_url:
        results["status"] = "erro"
        results["mensagem"] = "DATABASE_URL não configurada"
        return jsonify(results), 500
    
    try:
        conn = psycopg2.connect(database_url + "?sslmode=require")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cursor.fetchall()]
        results["tabelas_encontradas"] = tables
        
        if 'candidato' in tables:
            cursor.execute("SELECT COUNT(*) FROM candidato")
            count = cursor.fetchone()[0]
            results["total_candidatos"] = count
        
        cursor.close()
        conn.close()
        
        results["status"] = "sucesso"
        results["mensagem"] = "✅ Conexão com banco OK!"
        
    except Exception as e:
        results["status"] = "erro"
        results["erro"] = str(e)
        results["tipo_erro"] = type(e).__name__
    
    return jsonify(results)

@app.route("/health")
def health_check():
    """Rota para verificar se o banco está funcionando"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return jsonify({
            "status": "healthy", 
            "database": "connected",
            "environment": os.environ.get('FLASK_ENV', 'development')
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy", 
            "error": str(e)
        }), 500

# ==================== ROTAS PÚBLICAS ====================

@app.route("/login", methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Máximo 5 tentativas por minuto
def login():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = sanitizar_input(request.form['email'])
        senha = request.form['senha']
        
        if not email or not senha:
            flash('❌ Preencha todos os campos!', 'error')
            return render_template("login.html", csrf_token=session.get('csrf_token', ''))
        
        try:
            conn = get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT id_candidato, nome_candidato, email_candidato, senha,
                       tentativas_login, bloqueado_ate
                FROM candidato 
                WHERE email_candidato = %s AND ativo = TRUE
            """, (email,))
            
            candidato = cursor.fetchone()
            
            if not candidato:
                app.logger.warning(f"Tentativa de login com email não cadastrado: {email} - IP: {request.remote_addr}")
                flash('❌ Email não cadastrado!', 'error')
                cursor.close()
                conn.close()
                return render_template("login.html", csrf_token=session.get('csrf_token', ''))
            
            # Verificar se usuário está bloqueado
            if candidato['bloqueado_ate'] and candidato['bloqueado_ate'] > datetime.now():
                tempo_restante = candidato['bloqueado_ate'] - datetime.now()
                minutos = int(tempo_restante.total_seconds() / 60)
                flash(f'❌ Conta bloqueada. Tente novamente em {minutos} minutos.', 'error')
                cursor.close()
                conn.close()
                return render_template("login.html", csrf_token=session.get('csrf_token', ''))
            
            # Verificar senha com bcrypt
            if verificar_senha(senha, candidato['senha']):
                # Resetar tentativas de login
                cursor.execute("""
                    UPDATE candidato 
                    SET tentativas_login = 0, bloqueado_ate = NULL, ultimo_login = CURRENT_TIMESTAMP
                    WHERE id_candidato = %s
                """, (candidato['id_candidato'],))
                
                conn.commit()
                
                # Criar sessão segura
                session.permanent = True
                session['usuario_id'] = candidato['id_candidato']
                session['usuario_nome'] = candidato['nome_candidato']
                session['usuario_email'] = candidato['email_candidato']
                session['logged_in'] = True
                session['login_time'] = datetime.now().isoformat()
                session['csrf_token'] = secrets.token_hex(32)
                
                cursor.close()
                conn.close()
                
                app.logger.info(f"Login bem-sucedido: {email} - IP: {request.remote_addr}")
                flash('✅ Login realizado com sucesso!', 'success')
                
                return redirect(url_for('index'))
            else:
                # Incrementar tentativas de login
                novas_tentativas = (candidato['tentativas_login'] or 0) + 1
                
                if novas_tentativas >= 5:
                    bloqueado_ate = datetime.now() + timedelta(minutes=15)
                    cursor.execute("""
                        UPDATE candidato 
                        SET tentativas_login = %s, bloqueado_ate = %s
                        WHERE id_candidato = %s
                    """, (novas_tentativas, bloqueado_ate, candidato['id_candidato']))
                    
                    flash('❌ Muitas tentativas. Conta bloqueada por 15 minutos.', 'error')
                    app.logger.warning(f"Conta bloqueada: {email} - IP: {request.remote_addr}")
                else:
                    cursor.execute("""
                        UPDATE candidato 
                        SET tentativas_login = %s
                        WHERE id_candidato = %s
                    """, (novas_tentativas, candidato['id_candidato']))
                    
                    flash(f'❌ Senha incorreta! Tentativa {novas_tentativas} de 5.', 'error')
                
                conn.commit()
                cursor.close()
                conn.close()
            
        except Exception as e:
            app.logger.error(f"Erro no login: {str(e)} - IP: {request.remote_addr}")
            flash('Erro interno. Tente novamente.', 'error')
    
    return render_template("login.html", csrf_token=session.get('csrf_token', ''))

@app.route("/cadastro", methods=['GET', 'POST'])
@limiter.limit("3 per minute")  # Máximo 3 cadastros por minuto
def cadastro():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    
    hoje = date.today()
    max_date = hoje.replace(year=hoje.year - 15).strftime('%Y-%m-%d')
    min_date = hoje.replace(year=hoje.year - 120).strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            # Validar token CSRF
            if request.form.get('csrf_token') != session.get('csrf_token'):
                app.logger.warning(f"Tentativa de CSRF no cadastro - IP: {request.remote_addr}")
                flash('❌ Token de segurança inválido!', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date, 
                                     csrf_token=session.get('csrf_token', ''))
            
            # Sanitizar inputs
            nome = sanitizar_input(request.form['nome'])
            email = sanitizar_input(request.form['email'])
            telefone = sanitizar_input(request.form.get('telefone', ''))
            data_nascimento_input = sanitizar_input(request.form['data_nascimento'])
            senha = request.form['senha']
            confirmar_senha = request.form['confirmar_senha']
            
            app.logger.info(f"Tentativa de cadastro: {email} - IP: {request.remote_addr}")
            
            # Validações
            if senha != confirmar_senha:
                flash('❌ As senhas não coincidem.', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            # Validar senha forte
            senha_valida, msg_senha = validar_senha_forte(senha)
            if not senha_valida:
                flash(f'❌ {msg_senha}', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            # Validar email seguro
            email_valido, msg_email = validar_email_seguro(email)
            if not email_valido:
                flash(f'❌ {msg_email}', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            data_nascimento = converter_data_br_para_iso(data_nascimento_input)
            
            if not validate_date(data_nascimento):
                flash(f'❌ Data de nascimento inválida! Use o formato DD/MM/AAAA.', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            idade = calcular_idade(data_nascimento)
            if idade < 15:
                flash(f'❌ Idade insuficiente: {idade} anos (mínimo: 15 anos)', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            # Conectar ao banco
            conn = get_connection()
            cursor = conn.cursor()
            
            # Verificar se email já existe
            cursor.execute("SELECT id_candidato FROM candidato WHERE email_candidato = %s", (email,))
            if cursor.fetchone():
                flash('❌ Este email já está cadastrado.', 'error')
                cursor.close()
                conn.close()
                return render_template("cadastro.html", max_date=max_date, min_date=min_date,
                                     csrf_token=session.get('csrf_token', ''))
            
            # Remover formatação do telefone
            telefone = re.sub(r'\D', '', telefone) if telefone else ''
            
            # Inserir novo usuário com hash bcrypt
            senha_hash = hash_senha(senha)
            
            cursor.execute("""
                INSERT INTO candidato 
                (nome_candidato, email_candidato, telefone_candidato, data_nascimento_c, senha, data_cadastro)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING id_candidato, nome_candidato, email_candidato
            """, (nome, email, telefone, data_nascimento, senha_hash))
            
            result = cursor.fetchone()
            user_id = result[0]
            user_nome = result[1]
            user_email = result[2]
            
            conn.commit()
            
            # Criar sessão
            session.permanent = True
            session['usuario_id'] = user_id
            session['usuario_nome'] = user_nome
            session['usuario_email'] = user_email
            session['logged_in'] = True
            session['login_time'] = datetime.now().isoformat()
            session['csrf_token'] = secrets.token_hex(32)
            
            cursor.close()
            conn.close()
            
            app.logger.info(f"Novo usuário cadastrado: {email} - ID: {user_id} - IP: {request.remote_addr}")
            flash(f'✅ Cadastro realizado com sucesso! Bem-vindo(a), {user_nome}!', 'success')
            return redirect(url_for('index'))
            
        except psycopg2.Error as e:
            app.logger.error(f"Erro PostgreSQL no cadastro: {str(e)} - IP: {request.remote_addr}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            flash('Erro no banco de dados. Tente novamente.', 'error')
            
        except Exception as e:
            app.logger.error(f"Erro geral no cadastro: {str(e)} - IP: {request.remote_addr}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            flash('Erro ao realizar cadastro. Tente novamente.', 'error')
    
    return render_template("cadastro.html", max_date=max_date, min_date=min_date, 
                          csrf_token=session.get('csrf_token', ''))

@app.route("/recuperar-senha", methods=['GET', 'POST'])
@limiter.limit("3 per hour")
def recuperar_senha():
    """Rota para solicitar recuperação de senha"""
    if request.method == 'POST':
        email = sanitizar_input(request.form['email'])
        
        if not validar_email(email):
            flash('❌ Email inválido!', 'error')
            return render_template("recuperar_senha.html")
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT id_candidato FROM candidato WHERE email_candidato = %s", (email,))
            usuario = cursor.fetchone()
            
            if usuario:
                # Gerar token de recuperação
                token = gerar_token_recuperacao(email)
                
                # Salvar token no banco (você precisará criar uma tabela para isso)
                cursor.execute("""
                    INSERT INTO recuperacao_senha (id_candidato, token, data_expiracao)
                    VALUES (%s, %s, %s)
                """, (usuario[0], token, datetime.now() + timedelta(hours=1)))
                
                conn.commit()
                
                # Aqui você enviaria o email com o link de recuperação
                # link = url_for('resetar_senha', token=token, _external=True)
                app.logger.info(f"Token de recuperação gerado para: {email}")
                
                flash('✅ Se o email existir, você receberá instruções para recuperar sua senha.', 'success')
            else:
                # Não revelar se o email existe ou não
                flash('✅ Se o email existir, você receberá instruções para recuperar sua senha.', 'success')
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            app.logger.error(f"Erro na recuperação de senha: {str(e)}")
            flash('Erro interno. Tente novamente.', 'error')
        
        return redirect(url_for('login'))
    
    return render_template("recuperar_senha.html")

@app.route("/resetar-senha/<token>", methods=['GET', 'POST'])
def resetar_senha(token):
    """Rota para resetar a senha com token"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Verificar se token é válido e não expirou
        cursor.execute("""
            SELECT id_candidato FROM recuperacao_senha 
            WHERE token = %s AND data_expiracao > CURRENT_TIMESTAMP AND usado = FALSE
        """, (token,))
        
        result = cursor.fetchone()
        
        if not result:
            flash('❌ Link de recuperação inválido ou expirado!', 'error')
            return redirect(url_for('login'))
        
        if request.method == 'POST':
            senha = request.form['senha']
            confirmar_senha = request.form['confirmar_senha']
            
            if senha != confirmar_senha:
                flash('❌ As senhas não coincidem!', 'error')
                return render_template("resetar_senha.html", token=token)
            
            senha_valida, msg = validar_senha_forte(senha)
            if not senha_valida:
                flash(f'❌ {msg}', 'error')
                return render_template("resetar_senha.html", token=token)
            
            # Atualizar senha
            senha_hash = hash_senha(senha)
            cursor.execute("""
                UPDATE candidato SET senha = %s WHERE id_candidato = %s
            """, (senha_hash, result[0]))
            
            # Marcar token como usado
            cursor.execute("""
                UPDATE recuperacao_senha SET usado = TRUE WHERE token = %s
            """, (token,))
            
            conn.commit()
            
            app.logger.info(f"Senha resetada para usuário ID: {result[0]}")
            flash('✅ Senha alterada com sucesso! Faça login com sua nova senha.', 'success')
            
            cursor.close()
            conn.close()
            
            return redirect(url_for('login'))
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        app.logger.error(f"Erro ao resetar senha: {str(e)}")
        flash('Erro interno. Tente novamente.', 'error')
        return redirect(url_for('login'))
    
    return render_template("resetar_senha.html", token=token)

@app.route("/api/verificar-idade", methods=['POST'])
def verificar_idade():
    try:
        data_nascimento_input = request.form.get('data_nascimento', '').strip()
        
        if not data_nascimento_input:
            return jsonify({'success': False, 'message': 'Informe uma data de nascimento'}), 400
        
        data_nascimento = converter_data_br_para_iso(data_nascimento_input)
        
        if not validate_date(data_nascimento):
            return jsonify({'success': False, 'message': 'Data de nascimento inválida! Use DD/MM/AAAA'}), 400
        
        idade = calcular_idade(data_nascimento)
        idade_minima = 15
        idade_valida = idade >= idade_minima
        
        return jsonify({
            'success': True,
            'idade': idade,
            'idade_valida': idade_valida,
            'mensagem': f"{'✅' if idade_valida else '❌'} Idade: {idade} anos",
            'idade_minima': idade_minima
        })
        
    except Exception as e:
        app.logger.error(f"Erro ao verificar idade: {e}")
        return jsonify({'success': False, 'message': 'Erro ao verificar idade'}), 500

@app.route("/logout")
def logout():
    app.logger.info(f"Logout: {session.get('usuario_email')} - IP: {request.remote_addr}")
    session.clear()
    flash('👋 Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

# ==================== ROTAS PROTEGIDAS ====================

@app.route("/")
def index():
    if 'usuario_id' in session:
        return render_template("index.html")  # USUÁRIO LOGADO → volta para esta página!
    return render_template("index_publico.html")# logado
    
@app.route("/questionario")
@login_required
def questionario():
    return render_template("questionario.html")

@app.route("/area")
@login_required
def area():
    return render_template("area.html")

@app.route("/informacoes")
@login_required
def informacoes():
    return render_template("informacoes.html")

# ==================== LISTAGEM DE USUÁRIOS ====================
@app.route("/listagem")
@login_required
def listar_usuarios():
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT 
                id_candidato,
                nome_candidato,
                email_candidato,
                telefone_candidato,
                TO_CHAR(data_nascimento_c, 'DD/MM/YYYY') as data_nascimento_formatada,
                data_nascimento_c,
                TO_CHAR(data_cadastro, 'DD/MM/YYYY HH24:MI') as data_cadastro_formatada,
                ativo,
                tentativas_login,
                TO_CHAR(bloqueado_ate, 'DD/MM/YYYY HH24:MI') as bloqueado_ate
            FROM candidato
            ORDER BY id_candidato DESC
        """

        cursor.execute(query)
        usuarios = cursor.fetchall()
        
        for user in usuarios:
            if user['telefone_candidato']:
                user['telefone_candidato'] = formatar_telefone(user['telefone_candidato'])
            else:
                user['telefone_candidato'] = '-'
        
        cursor.close()
        conn.close()
        
        return render_template("listagem.html", usuarios=usuarios)
        
    except Exception as e:
        app.logger.error(f"Erro ao listar usuários: {str(e)}")
        flash('Erro ao carregar listagem', 'error')
        return redirect(url_for('index'))

# ==================== ATUALIZAR USUÁRIO ====================
@app.route("/atualizar_usuario", methods=['POST'])
@login_required
def atualizar_usuario():
    try:
        # Validar CSRF
        if request.form.get('csrf_token') != session.get('csrf_token'):
            flash('❌ Token de segurança inválido!', 'error')
            return redirect(url_for('listar_usuarios'))
        
        conn = get_connection()
        cursor = conn.cursor()
        
        id_candidato = request.form['id_candidato']
        nome_candidato = sanitizar_input(request.form['nome_candidato'])
        email_candidato = sanitizar_input(request.form['email_candidato'])
        telefone_candidato = sanitizar_input(request.form.get('telefone_candidato', ''))
        data_nascimento_c = request.form['data_nascimento_c']
        senha = request.form.get('senha', '')
        
        # Validar email
        if not validar_email(email_candidato):
            flash('❌ Email inválido!', 'error')
            return redirect(url_for('listar_usuarios'))
        
        cursor.execute("SELECT id_candidato FROM candidato WHERE id_candidato = %s", (id_candidato,))
        if not cursor.fetchone():
            flash('❌ Usuário não encontrado!', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('listar_usuarios'))
        
        # Remover formatação do telefone
        telefone_candidato = re.sub(r'\D', '', telefone_candidato) if telefone_candidato else ''
        
        if senha.strip():
            # Validar senha forte se for alterada
            senha_valida, msg = validar_senha_forte(senha)
            if not senha_valida:
                flash(f'❌ {msg}', 'error')
                cursor.close()
                conn.close()
                return redirect(url_for('listar_usuarios'))
            
            senha_hash = hash_senha(senha)
            query = """
                UPDATE candidato 
                SET nome_candidato = %s, 
                    email_candidato = %s, 
                    telefone_candidato = %s,
                    data_nascimento_c = %s, 
                    senha = %s
                WHERE id_candidato = %s
            """
            cursor.execute(query, (nome_candidato, email_candidato, telefone_candidato, 
                                 data_nascimento_c, senha_hash, id_candidato))
        else:
            query = """
                UPDATE candidato 
                SET nome_candidato = %s, 
                    email_candidato = %s, 
                    telefone_candidato = %s,
                    data_nascimento_c = %s
                WHERE id_candidato = %s
            """
            cursor.execute(query, (nome_candidato, email_candidato, telefone_candidato, 
                                 data_nascimento_c, id_candidato))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f"Usuário atualizado: ID {id_candidato} - por: {session.get('usuario_email')}")
        flash('✅ Usuário atualizado com sucesso!', 'success')
        
    except Exception as e:
        app.logger.error(f"Erro ao atualizar: {str(e)}")
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        flash('❌ Erro ao atualizar usuário', 'error')
    
    return redirect(url_for('listar_usuarios'))

# ==================== EXCLUIR USUÁRIO ====================
@app.route("/excluir_usuario", methods=['POST'])
@login_required
def excluir_usuario():
    try:
        # Validar CSRF
        if request.form.get('csrf_token') != session.get('csrf_token'):
            flash('❌ Token de segurança inválido!', 'error')
            return redirect(url_for('listar_usuarios'))
        
        conn = get_connection()
        cursor = conn.cursor()
        
        id_candidato = request.form['id_candidato']
        
        cursor.execute("SELECT id_candidato FROM candidato WHERE id_candidato = %s", (id_candidato,))
        if not cursor.fetchone():
            flash('❌ Usuário não encontrado!', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('listar_usuarios'))
        
        if int(id_candidato) == session.get('usuario_id'):
            flash('❌ Você não pode excluir seu próprio usuário!', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('listar_usuarios'))
        
        # Soft delete
        query = "UPDATE candidato SET ativo = FALSE WHERE id_candidato = %s"
        cursor.execute(query, (id_candidato,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f"Usuário desativado: ID {id_candidato} - por: {session.get('usuario_email')}")
        flash('✅ Usuário desativado com sucesso!', 'success')
        
    except Exception as e:
        app.logger.error(f"Erro ao excluir: {str(e)}")
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        flash('❌ Erro ao excluir usuário', 'error')
    
    return redirect(url_for('listar_usuarios'))

# ==================== API DO QUESTIONÁRIO ====================
@app.route("/api/perguntas", methods=['GET'])
@login_required
def api_perguntas():
    try:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT q.n_pergunta, q.descricao 
            FROM questionario q 
            WHERE q.ativo = TRUE 
            ORDER BY q.ordem_exibicao, q.n_pergunta
        """
        cursor.execute(query)
        perguntas = cursor.fetchall()
        
        for pergunta in perguntas:
            cursor.execute("""
                SELECT 
                    n_resposta,
                    resposta_01 as text,
                    COALESCE(peso_informatica, 0) as informatica,
                    COALESCE(peso_web, 0) as web,
                    COALESCE(peso_manutencao, 0) as manutencao,
                    COALESCE(peso_dados, 0) as dados
                FROM respostas 
                WHERE n_pergunta = %s AND ativo = TRUE
                ORDER BY n_resposta
            """, (pergunta['n_pergunta'],))
            
            respostas = cursor.fetchall()
            
            letras = ['A', 'B', 'C']
            opcoes = []
            
            for i, resposta in enumerate(respostas):
                opcao = {
                    'id': letras[i],
                    'text': resposta['text']
                }
                
                if resposta['informatica'] > 0:
                    opcao['informatica'] = resposta['informatica']
                if resposta['web'] > 0:
                    opcao['web'] = resposta['web']
                if resposta['manutencao'] > 0:
                    opcao['manutencao'] = resposta['manutencao']
                if resposta['dados'] > 0:
                    opcao['dados'] = resposta['dados']
                
                opcoes.append(opcao)
            
            pergunta['opcoes'] = opcoes
        
        cursor.close()
        conn.close()
        
        return jsonify(perguntas)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar perguntas: {str(e)}")
        return jsonify({'error': 'Erro ao carregar perguntas'}), 500

# ==================== API SALVAR RESULTADO ====================
@app.route("/api/salvar-resultado", methods=['POST'])
@login_required
def salvar_resultado():
    try:
        data = request.json
        usuario_id = session.get('usuario_id')
        
        if not usuario_id:
            return jsonify({'error': 'Usuário não autenticado'}), 401
        
        # Validar dados recebidos
        campos_obrigatorios = ['informatica', 'web', 'manutencao', 'dados', 'curso_recomendado']
        for campo in campos_obrigatorios:
            if campo not in data:
                return jsonify({'error': f'Campo {campo} obrigatório'}), 400
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO resultados_questionario 
            (id_candidato, pontuacao_informatica, pontuacao_web, pontuacao_manutencao, pontuacao_dados, curso_recomendado)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            usuario_id,
            data.get('informatica', 0),
            data.get('web', 0),
            data.get('manutencao', 0),
            data.get('dados', 0),
            data['curso_recomendado']
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        app.logger.info(f"Resultado salvo - Usuário: {usuario_id} - Curso: {data['curso_recomendado']}")
        
        return jsonify({'success': True, 'message': 'Resultado registrado com sucesso!'})
        
    except Exception as e:
        app.logger.error(f"Erro ao salvar resultado: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return jsonify({'error': 'Erro ao salvar resultado'}), 500

# ==================== API VERIFICAR SESSÃO ====================
@app.route("/api/verificar-sessao")
def verificar_sessao():
    if 'usuario_id' in session and session.get('logged_in'):
        return jsonify({
            'logged_in': True, 
            'usuario': session['usuario_nome']
        })
    return jsonify({'logged_in': False}), 401

# ==================== API RESULTADOS DO USUÁRIO ====================
@app.route("/api/meus-resultados")
@login_required
def meus_resultados():
    try:
        usuario_id = session.get('usuario_id')
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                id_resultado,
                TO_CHAR(data_realizacao, 'DD/MM/YYYY HH24:MI') as data_realizacao,
                pontuacao_informatica,
                pontuacao_web,
                pontuacao_manutencao,
                pontuacao_dados,
                curso_recomendado
            FROM resultados_questionario
            WHERE id_candidato = %s
            ORDER BY data_realizacao DESC
        """, (usuario_id,))
        
        resultados = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return jsonify(resultados)
        
    except Exception as e:
        app.logger.error(f"Erro ao buscar resultados: {str(e)}")
        return jsonify({'error': 'Erro ao buscar resultados'}), 500

# ==================== INICIAR APLICAÇÃO ====================
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    
    app.logger.info(f"🚀 Iniciando app na porta {port}")
    app.logger.info(f"🔒 Modo debug: {debug}")
    app.logger.info(f"🔐 CSRF Protection: Ativado")
    app.logger.info(f"⏱️ Rate Limiting: Ativado")
    
    app.run(host='0.0.0.0', port=port, debug=debug)


