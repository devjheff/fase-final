from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import hashlib
import re
import os

# REMOVIDO: from dotenv import load_dotenv
# REMOVIDO: load_dotenv() - Não usar no Render!

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave_fallback_somente_desenvolvimento_12345')

# ==================== CONFIGURAÇÃO DO BANCO COM DEBUG ====================
def get_connection():
    """Obtém conexão com o banco de dados usando DATABASE_URL do ambiente"""
    
    # PEGAR A DATABASE_URL DIRETO DAS VARIÁVEIS DE AMBIENTE
    database_url = os.environ.get('DATABASE_URL')
    
    if not database_url:
        error_msg = "❌ ERRO: DATABASE_URL não configurada nas variáveis de ambiente!"
        print(error_msg)
        print("📋 Variáveis encontradas:", list(os.environ.keys()))
        raise Exception(error_msg)
    
    try:
        # Garantir SSL para Neon
        if 'sslmode' not in database_url:
            if '?' in database_url:
                database_url += '&sslmode=require'
            else:
                database_url += '?sslmode=require'
        
        print("🔄 Tentando conectar ao Neon...")
        conn = psycopg2.connect(database_url)
        print("✅ Conexão estabelecida com sucesso!")
        return conn
        
    except Exception as e:
        print(f"❌ Erro de conexão: {str(e)}")
        print("🔍 Dica: Verifique se o IP do Render está liberado no Neon")
        raise

# ==================== FUNÇÕES UTILITÁRIAS ====================
def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

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
        # Remove espaços em branco
        data_br = data_br.strip()
        # Verifica se está no formato DD/MM/YYYY
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
        public_pages = ['login', 'cadastro', 'health_check', 'test_db', 'debug_env']
        
        if request.endpoint not in public_pages:
            if 'usuario_id' not in session:
                flash('Por favor, faça login para acessar o sistema.', 'warning')
                return redirect(url_for('login'))
        
        return f(*args, **kwargs)
    
    decorated_function.__name__ = f.__name__
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
    
    # MOSTRA PARTE DA DATABASE_URL (escondendo senha)
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        # Esconde a senha por segurança
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
    
    # Teste 1: Verificar se DATABASE_URL existe
    database_url = os.environ.get('DATABASE_URL')
    results["database_url_configurada"] = bool(database_url)
    
    if not database_url:
        results["status"] = "erro"
        results["mensagem"] = "DATABASE_URL não configurada"
        return jsonify(results), 500
    
    try:
        # Teste 2: Conectar ao banco
        conn = psycopg2.connect(database_url + "?sslmode=require")
        cursor = conn.cursor()
        
        # Teste 3: Listar tabelas
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cursor.fetchall()]
        results["tabelas_encontradas"] = tables
        
        # Teste 4: Contar registros
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
                
                # Atualizar último login (se a coluna existir)
                try:
                    cursor.execute("""
                        UPDATE candidato SET ultimo_login = CURRENT_TIMESTAMP 
                        WHERE id_candidato = %s
                    """, (candidato['id_candidato'],))
                    conn.commit()
                except:
                    # Coluna pode não existir, ignorar
                    pass
                
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
            flash(f'Erro ao fazer login: {str(e)}', 'error')
    
    return render_template("login.html")

@app.route("/cadastro", methods=['GET', 'POST'])
def cadastro():
    if 'usuario_id' in session:
        return redirect(url_for('index'))
    
    hoje = date.today()
    max_date = hoje.replace(year=hoje.year - 15).strftime('%Y-%m-%d')
    min_date = hoje.replace(year=hoje.year - 120).strftime('%Y-%m-%d')
    
    if request.method == 'POST':
        try:
            # Pegar dados do formulário
            nome = request.form['nome']
            email = request.form['email']
            telefone = request.form.get('telefone', '')
            data_nascimento_input = request.form['data_nascimento']
            senha = request.form['senha']
            confirmar_senha = request.form['confirmar_senha']
            
            print(f"📝 Dados recebidos: nome={nome}, email={email}, data={data_nascimento_input}")
            
            # CONVERTER DATA DO FORMATO BR PARA ISO
            data_nascimento = converter_data_br_para_iso(data_nascimento_input)
            print(f"🔄 Data convertida: {data_nascimento_input} -> {data_nascimento}")
            
            # Validações
            if senha != confirmar_senha:
                flash('❌ As senhas não coincidem.', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            if not validate_email(email):
                flash('❌ Formato de email inválido!', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            if not validate_date(data_nascimento):
                flash(f'❌ Data de nascimento inválida! Use o formato DD/MM/AAAA. Recebido: {data_nascimento_input}', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            idade = calcular_idade(data_nascimento)
            if idade < 15:
                flash(f'❌ Idade insuficiente: {idade} anos (mínimo: 15 anos)', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            if len(senha) < 6:
                flash('❌ A senha deve ter no mínimo 6 caracteres!', 'error')
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            # Conectar ao banco
            conn = get_connection()
            cursor = conn.cursor()
            
            # Verificar se email já existe
            cursor.execute("SELECT id_candidato FROM candidato WHERE email_candidato = %s", (email,))
            if cursor.fetchone():
                flash('❌ Este email já está cadastrado.', 'error')
                cursor.close()
                conn.close()
                return render_template("cadastro.html", max_date=max_date, min_date=min_date)
            
            # Inserir novo usuário
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
            session['usuario_id'] = user_id
            session['usuario_nome'] = user_nome
            session['usuario_email'] = user_email
            session['logged_in'] = True
            
            cursor.close()
            conn.close()
            
            flash(f'✅ Cadastro realizado com sucesso! Bem-vindo(a), {user_nome}!', 'success')
            return redirect(url_for('index'))
            
        except psycopg2.Error as e:
            print(f"❌ Erro PostgreSQL no cadastro: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            flash(f'Erro no banco de dados: {str(e)}', 'error')
            
        except Exception as e:
            print(f"❌ Erro geral no cadastro: {str(e)}")
            print(f"Tipo do erro: {type(e).__name__}")
            if 'conn' in locals():
                conn.rollback()
                conn.close()
            flash(f'Erro ao realizar cadastro: {str(e)}', 'error')
    
    return render_template("cadastro.html", max_date=max_date, min_date=min_date)

@app.route("/api/verificar-idade", methods=['POST'])
def verificar_idade():
    try:
        data_nascimento_input = request.form.get('data_nascimento', '').strip()
        
        if not data_nascimento_input:
            return jsonify({'success': False, 'message': 'Informe uma data de nascimento'}), 400
        
        # Converter data do formato BR para ISO
        data_nascimento = converter_data_br_para_iso(data_nascimento_input)
        
        if not validate_date(data_nascimento):
            return jsonify({'success': False, 'message': 'Data de nascimento inválida! Use DD/MM/AAAA'}), 400
        
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
        return jsonify({'success': False, 'message': f'Erro ao verificar idade: {str(e)}'}), 500

@app.route("/logout")
def logout():
    session.clear()
    flash('👋 Você foi desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

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
    print(f"🚀 Iniciando app na porta {port}")
    app.run(host='0.0.0.0', port=port, debug=debug)
