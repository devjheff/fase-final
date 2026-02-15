from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import hashlib
import re
import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave_fallback_somente_desenvolvimento_12345')

# ==================== CONFIGURAÇÃO DO BANCO ====================
def get_connection():
    """Obtém conexão com o banco de dados usando DATABASE_URL do ambiente"""
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        # Para Neon, precisamos garantir que o SSL está habilitado
        if 'sslmode' not in database_url:
            if '?' in database_url:
                database_url += '&sslmode=require'
            else:
                database_url += '?sslmode=require'
        return psycopg2.connect(database_url)
    else:
        # Fallback para desenvolvimento local
        DB_CONFIG = {
            'host': os.environ.get('DB_HOST', 'localhost'),
            'database': os.environ.get('DB_NAME', 'postgres'),
            'user': os.environ.get('DB_USER', 'postgres'),
            'password': os.environ.get('DB_PASSWORD', '5353'),
            'port': os.environ.get('DB_PORT', '5432')
        }
        return psycopg2.connect(**DB_CONFIG)

# ==================== FUNÇÕES UTILITÁRIAS ====================
def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_date(date_string):
    try:
        datetime.strptime(date_string, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def calcular_idade(data_nascimento_str):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, '%Y-%m-%d').date()
        hoje = date.today()
        idade = hoje.year - data_nascimento.year
        if (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day):
            idade -= 1
        return idade
    except Exception as e:
        print(f"Erro ao calcular idade: {e}")
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

# ==================== DECORATOR DE LOGIN ====================
def login_required(f):
    def decorated_function(*args, **kwargs):
        public_pages = ['login', 'cadastro', 'health_check', 'setup_database']
        
        if request.endpoint not in public_pages:
            if 'usuario_id' not in session:
                flash('Por favor, faça login para acessar o sistema.', 'warning')
                return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    
    decorated_function.__name__ = f.__name__
    return decorated_function

# ==================== ROTAS PÚBLICAS ====================

@app.route("/login", methods=['GET', 'POST'])
def login():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form['email']
        senha = request.form['senha']
        
        try:
            conn = get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT id_candidato, nome_candidato, email_candidato, senha
                FROM candidato 
                WHERE email_candidato = %s AND ativo = TRUE
            """, (email,))
            
            candidato = cursor.fetchone()
            
            if not candidato:
                flash('❌ Email não cadastrado!', 'error')
                cursor.close()
                conn.close()
                return redirect(url_for('login'))
            
            if candidato and candidato['senha'] == hash_senha(senha):
                session['usuario_id'] = candidato['id_candidato']
                session['usuario_nome'] = candidato['nome_candidato']
                session['usuario_email'] = candidato['email_candidato']
                session['logged_in'] = True
                
                # Atualizar último login
                cursor.execute("""
                    UPDATE candidato SET ultimo_login = CURRENT_TIMESTAMP 
                    WHERE id_candidato = %s
                """, (candidato['id_candidato'],))
                conn.commit()
                
                cursor.close()
                conn.close()
                
                flash('✅ Login realizado com sucesso!', 'success')
                return redirect(url_for('index'))
            else:
                flash('❌ Senha incorreta!', 'error')
                
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Erro no login: {str(e)}")
            flash('Erro ao fazer login. Tente novamente.', 'error')
    
    return render_template("login.html")

@app.route("/cadastro", methods=['GET', 'POST'])
def cadastro():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    
    hoje = date.today()
    max_date = hoje.replace(year=hoje.year - 15)
    min_date = hoje.replace(year=hoje.year - 120)
    
    if request.method == 'POST':
        nome = request.form['nome']
        email = request.form['email']
        telefone = request.form.get('telefone', '')
        data_nascimento = request.form['data_nascimento']
        senha = request.form['senha']
        confirmar_senha = request.form['confirmar_senha']
        
        if senha != confirmar_senha:
            flash('❌ As senhas não coincidem.', 'error')
            return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
        
        if not validate_email(email):
            flash('❌ Formato de email inválido!', 'error')
            return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
        
        if not validate_date(data_nascimento):
            flash('❌ Data de nascimento inválida!', 'error')
            return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
        
        idade = calcular_idade(data_nascimento)
        if idade < 15:
            flash(f'❌ Idade insuficiente: {idade} anos (mínimo: 15 anos)', 'error')
            return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
        
        if len(senha) < 6:
            flash('❌ A senha deve ter no mínimo 6 caracteres!', 'error')
            return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT id_candidato FROM candidato WHERE email_candidato = %s", (email,))
            if cursor.fetchone():
                flash('❌ Este email já está cadastrado.', 'error')
                cursor.close()
                conn.close()
                return render_template("cadastro.html", max_date=max_date.strftime('%Y-%m-%d'), min_date=min_date.strftime('%Y-%m-%d'))
            
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
            
            session['usuario_id'] = user_id
            session['usuario_nome'] = user_nome
            session['usuario_email'] = user_email
            session['logged_in'] = True
            
            cursor.close()
            conn.close()
            
            flash(f'✅ Cadastro realizado com sucesso! Bem-vindo(a), {user_nome}!', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            print(f"Erro no cadastro: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            flash('Erro ao realizar cadastro. Tente novamente.', 'error')
    
    return render_template("cadastro.html", 
                         max_date=max_date.strftime('%Y-%m-%d'),
                         min_date=min_date.strftime('%Y-%m-%d'))

@app.route("/api/verificar-idade", methods=['POST'])
def verificar_idade():
    try:
        data_nascimento = request.form.get('data_nascimento', '').strip()
        
        if not data_nascimento:
            return jsonify({'success': False, 'message': 'Informe uma data de nascimento'}), 400
        
        if not validate_date(data_nascimento):
            return jsonify({'success': False, 'message': 'Data de nascimento inválida!'}), 400
        
        idade = calcular_idade(data_nascimento)
        idade_minima = 15
        idade_valida = idade >= idade_minima
        
        if idade_valida:
            mensagem = f"✅ Idade válida: {idade} anos"
        else:
            mensagem = f"❌ Idade insuficiente: {idade} anos (mínimo: {idade_minima} anos)"
        
        return jsonify({
            'success': True,
            'idade': idade,
            'idade_valida': idade_valida,
            'mensagem': mensagem,
            'idade_minima': idade_minima
        })
        
    except Exception as e:
        print(f"Erro ao verificar idade: {e}")
        return jsonify({'success': False, 'message': 'Erro ao verificar idade'}), 500

@app.route("/logout")
def logout():
    session.clear()
    flash('👋 Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

# ==================== ROTAS DE VERIFICAÇÃO ====================

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

@app.route("/setup-db")
def setup_database():
    """Rota para criar as tabelas (apenas em desenvolvimento)"""
    # Proteção para não executar em produção
    if os.environ.get('FLASK_ENV') == 'production':
        # Verificar se é uma requisição local ou com chave secreta
        if request.remote_addr != '127.0.0.1' and request.args.get('key') != os.environ.get('SETUP_KEY', 'setup123'):
            return jsonify({"error": "Acesso negado"}), 403
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Criar tabela candidato se não existir
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidato (
                id_candidato SERIAL PRIMARY KEY,
                nome_candidato VARCHAR(100) NOT NULL,
                email_candidato VARCHAR(100) NOT NULL UNIQUE,
                telefone_candidato VARCHAR(20),
                data_nascimento_c DATE NOT NULL,
                senha VARCHAR(64) NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultimo_login TIMESTAMP,
                ativo BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Criar tabela questionario se não existir
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questionario (
                n_pergunta INTEGER PRIMARY KEY,
                descricao TEXT NOT NULL,
                ativo BOOLEAN DEFAULT TRUE,
                ordem_exibicao INTEGER,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Criar tabela respostas se não existir
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS respostas (
                id_resposta SERIAL PRIMARY KEY,
                n_pergunta INTEGER NOT NULL,
                n_resposta INTEGER NOT NULL,
                resposta_01 VARCHAR(255) NOT NULL,
                peso_informatica INTEGER DEFAULT 0,
                peso_web INTEGER DEFAULT 0,
                peso_manutencao INTEGER DEFAULT 0,
                peso_dados INTEGER DEFAULT 0,
                ativo BOOLEAN DEFAULT TRUE,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (n_pergunta) REFERENCES questionario(n_pergunta) ON DELETE CASCADE,
                UNIQUE(n_pergunta, n_resposta)
            )
        """)
        
        # Criar tabela resultados_questionario se não existir
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resultados_questionario (
                id_resultado SERIAL PRIMARY KEY,
                id_candidato INTEGER NOT NULL,
                data_realizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pontuacao_informatica INTEGER DEFAULT 0,
                pontuacao_web INTEGER DEFAULT 0,
                pontuacao_manutencao INTEGER DEFAULT 0,
                pontuacao_dados INTEGER DEFAULT 0,
                curso_recomendado VARCHAR(50),
                FOREIGN KEY (id_candidato) REFERENCES candidato(id_candidato) ON DELETE CASCADE
            )
        """)
        
        # Verificar se já existem perguntas cadastradas
        cursor.execute("SELECT COUNT(*) FROM questionario")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Inserir perguntas do questionário
            perguntas = [
                (1, 'Como você se sente ao resolver problemas complexos?', 1),
                (2, 'Qual dessas atividades você mais gosta?', 2),
                (3, 'Em um trabalho em equipe, você prefere:', 3),
                (4, 'O que você acha mais interessante?', 4),
                (5, 'Qual área da tecnologia mais te chama atenção?', 5),
                (6, 'Como você lida com prazos apertados?', 6),
                (7, 'Você prefere trabalhar:', 7),
                (8, 'Qual dessas habilidades você mais se identifica?', 8),
                (9, 'O que te motiva a aprender algo novo?', 9),
                (10, 'Como você reage a mudanças tecnológicas?', 10)
            ]
            
            for pergunta in perguntas:
                cursor.execute(
                    "INSERT INTO questionario (n_pergunta, descricao, ordem_exibicao) VALUES (%s, %s, %s)",
                    pergunta
                )
            
            # Inserir respostas
            respostas = [
                # Pergunta 1
                (1, 1, 'Gosto de analisar cada detalhe e encontrar a solução lógica', 3, 2, 4, 3),
                (1, 2, 'Busco soluções criativas e inovadoras', 2, 4, 2, 3),
                (1, 3, 'Prefiro seguir um método testado e aprovado', 3, 2, 4, 2),
                # Pergunta 2
                (2, 1, 'Criar sites e aplicações web', 2, 5, 1, 2),
                (2, 2, 'Trabalhar com banco de dados e relatórios', 3, 2, 2, 5),
                (2, 3, 'Resolver problemas de hardware e software', 4, 1, 5, 1),
                # Pergunta 3
                (3, 1, 'Coordenar e organizar as tarefas do grupo', 3, 3, 3, 3),
                (3, 2, 'Contribuir com ideias e soluções criativas', 2, 5, 2, 3),
                (3, 3, 'Executar as tarefas com precisão', 4, 2, 5, 3),
                # Pergunta 4
                (4, 1, 'Entender como os computadores funcionam internamente', 5, 1, 4, 2),
                (4, 2, 'Criar interfaces bonitas e funcionais', 2, 5, 1, 2),
                (4, 3, 'Analisar padrões e tendências em dados', 3, 2, 2, 5),
                # Pergunta 5
                (5, 1, 'Desenvolvimento de software', 5, 3, 2, 2),
                (5, 2, 'Design e experiência do usuário', 1, 5, 1, 1),
                (5, 3, 'Infraestrutura e redes', 3, 1, 5, 2),
                # Pergunta 6
                (6, 1, 'Planejo cuidadosamente cada etapa', 4, 3, 4, 3),
                (6, 2, 'Trabalho de forma intensa e focada', 3, 4, 3, 3),
                (6, 3, 'Peço ajuda e delego quando necessário', 2, 3, 2, 3),
                # Pergunta 7
                (7, 1, 'Sozinho, no meu próprio ritmo', 4, 3, 4, 4),
                (7, 2, 'Em equipe, colaborando com outros', 2, 4, 2, 3),
                (7, 3, 'Híbrido, alternando conforme necessidade', 3, 3, 3, 3),
                # Pergunta 8
                (8, 1, 'Raciocínio lógico e matemático', 5, 2, 3, 4),
                (8, 2, 'Criatividade e comunicação visual', 1, 5, 1, 2),
                (8, 3, 'Atenção aos detalhes e organização', 3, 2, 5, 4),
                # Pergunta 9
                (9, 1, 'Resolver problemas do dia a dia', 4, 3, 5, 3),
                (9, 2, 'Criar coisas novas e inovadoras', 3, 5, 2, 3),
                (9, 3, 'Entender como as coisas funcionam', 5, 2, 4, 4),
                # Pergunta 10
                (10, 1, 'Fico animado e busco aprender imediatamente', 3, 5, 2, 3),
                (10, 2, 'Analiso os prós e contras primeiro', 4, 2, 4, 4),
                (10, 3, 'Prefiro esperar para ver se é confiável', 3, 1, 4, 2)
            ]
            
            for resposta in respostas:
                cursor.execute("""
                    INSERT INTO respostas 
                    (n_pergunta, n_resposta, resposta_01, peso_informatica, peso_web, peso_manutencao, peso_dados) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, resposta)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            "success": True, 
            "message": "Tabelas criadas/verificadas com sucesso!",
            "environment": os.environ.get('FLASK_ENV', 'development')
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== ROTAS PROTEGIDAS ====================

@app.route("/")
@login_required
def index():
    return render_template("index.html")

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
                senha,
                TO_CHAR(data_cadastro, 'DD/MM/YYYY HH24:MI') as data_cadastro_formatada,
                ativo
            FROM candidato
            ORDER BY id_candidato DESC
        """

        cursor.execute(query)
        usuarios = cursor.fetchall()
        
        # Formatar telefones
        for user in usuarios:
            if user['telefone_candidato']:
                user['telefone_candidato'] = formatar_telefone(user['telefone_candidato'])
            else:
                user['telefone_candidato'] = '-'
        
        cursor.close()
        conn.close()
        
        return render_template("listagem.html", usuarios=usuarios)
        
    except Exception as e:
        print(f"❌ Erro ao listar usuários: {str(e)}")
        flash(f'Erro ao carregar listagem: {str(e)}', 'error')
        return redirect(url_for('index'))

# ==================== ATUALIZAR USUÁRIO ====================
@app.route("/atualizar_usuario", methods=['POST'])
@login_required
def atualizar_usuario():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        id_candidato = request.form['id_candidato']
        nome_candidato = request.form['nome_candidato']
        email_candidato = request.form['email_candidato']
        telefone_candidato = request.form.get('telefone_candidato', '')
        data_nascimento_c = request.form['data_nascimento_c']
        senha = request.form.get('senha', '')
        
        cursor.execute("SELECT id_candidato FROM candidato WHERE id_candidato = %s", (id_candidato,))
        if not cursor.fetchone():
            flash('❌ Usuário não encontrado!', 'error')
            cursor.close()
            conn.close()
            return redirect(url_for('listar_usuarios'))
        
        # Remover formatação do telefone antes de salvar
        telefone_candidato = re.sub(r'\D', '', telefone_candidato) if telefone_candidato else ''
        
        if senha.strip():
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
        
        flash('✅ Usuário atualizado com sucesso!', 'success')
        
    except Exception as e:
        print(f"❌ Erro ao atualizar: {str(e)}")
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        flash(f'❌ Erro ao atualizar usuário: {str(e)}', 'error')
    
    return redirect(url_for('listar_usuarios'))

# ==================== EXCLUIR USUÁRIO ====================
@app.route("/excluir_usuario", methods=['POST'])
@login_required
def excluir_usuario():
    try:
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
        
        # Soft delete - apenas marcar como inativo
        query = "UPDATE candidato SET ativo = FALSE WHERE id_candidato = %s"
        cursor.execute(query, (id_candidato,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('✅ Usuário desativado com sucesso!', 'success')
        
    except Exception as e:
        print(f"❌ Erro ao excluir: {str(e)}")
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        flash(f'❌ Erro ao excluir usuário: {str(e)}', 'error')
    
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
        print(f"Erro ao buscar perguntas: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ==================== API SALVAR RESULTADO ====================
@app.route("/api/salvar-resultado", methods=['POST'])
@login_required
def salvar_resultado():
    try:
        data = request.json
        usuario_id = session.get('usuario_id')
        
        if not usuario_id:
            return jsonify({'error': 'Usuário não autenticado'}), 401
        
        # Salvar resultado no banco
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
        
        print(f"✅ Resultado salvo - Usuário: {usuario_id}")
        print(f"   Curso: {data['curso_recomendado']}")
        
        return jsonify({'success': True, 'message': 'Resultado registrado com sucesso!'})
        
    except Exception as e:
        print(f"Erro ao salvar resultado: {str(e)}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return jsonify({'error': str(e)}), 500

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
        print(f"Erro ao buscar resultados: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)
