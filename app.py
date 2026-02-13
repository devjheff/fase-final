from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import hashlib
import re

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui_super_secreta_12345'

# CONFIGURAÇÃO DO BANCO
DB_CONFIG = {
    'host': 'localhost',
    'database': 'postgres',
    'user': 'postgres',
    'password': '5353',
    'port': '5432'
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

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
        public_pages = ['login', 'cadastro']
        
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
                WHERE email_candidato = %s
            """, (email,))
            
            candidato = cursor.fetchone()
            
            if not candidato:
                flash('❌ Email não cadastrado!', 'error')
                return redirect(url_for('login'))
            
            if candidato and candidato['senha'] == hash_senha(senha):
                session['usuario_id'] = candidato['id_candidato']
                session['usuario_nome'] = candidato['nome_candidato']
                session['usuario_email'] = candidato['email_candidato']
                session['logged_in'] = True
                
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
                (nome_candidato, email_candidato, telefone_candidato, data_nascimento_c, senha)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id_candidato, nome_candidato, email_candidato
            """, (nome, email, telefone, data_nascimento, senha_hash))
            
            user_id, user_nome, user_email = cursor.fetchone()
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
# APENAS OS CAMPOS SOLICITADOS: id, nome, email, nascimento, telefone, senha
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
                senha
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
            return redirect(url_for('listar_usuarios'))
        
        if int(id_candidato) == session.get('usuario_id'):
            flash('❌ Você não pode excluir seu próprio usuário!', 'error')
            return redirect(url_for('listar_usuarios'))
        
        query = "DELETE FROM candidato WHERE id_candidato = %s"
        cursor.execute(query, (id_candidato,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('✅ Usuário excluído com sucesso!', 'success')
        
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
            ORDER BY q.n_pergunta
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
                WHERE n_pergunta = %s 
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
        
        print(f"✅ Resultado salvo - Usuário: {usuario_id}")
        print(f"   Curso: {data['curso_recomendado']}")
        
        return jsonify({'success': True, 'message': 'Resultado registrado com sucesso!'})
        
    except Exception as e:
        print(f"Erro ao salvar resultado: {str(e)}")
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

if __name__ == "__main__":
    app.run(debug=True, port=5000)