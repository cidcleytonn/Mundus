import json
import os
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, flash
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_session import Session
import psycopg2
from psycopg2.extras import RealDictCursor
import time
import unicodedata
from werkzeug.security import generate_password_hash, check_password_hash
import string
import random

app = Flask(__name__)
# Chave secreta para sessões e segurança
app.secret_key = os.environ.get('SECRET_KEY', 'chave_super_secreta_do_geoquiz_cidy')

socketio = SocketIO(app, cors_allowed_origins="*")

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configuração da Base de Dados Híbrida
DB_CONFIG = {
    "host": os.environ.get('DB_HOST', 'localhost'),
    "database": os.environ.get('DB_NAME', 'geogames_db'),
    "user": os.environ.get('DB_USER', 'postgres'),
    "password": os.environ.get('DB_PASSWORD', 'cidcleytonnvive')
}

DATABASE_URL = os.environ.get('DATABASE_URL')

def pegar_conexao():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return psycopg2.connect(**DB_CONFIG)

# --- FUNÇÕES DE BASE DE DADOS ---

def pegar_todos_paises_embaralhados(regiao, incluir_territorios):
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    condicao = "" if incluir_territorios else "WHERE soberano = TRUE "
    if regiao == 'sul': query = f"SELECT nome, codigo_iso, '' as apelidos FROM paises_america_sul {condicao}ORDER BY RANDOM();"
    elif regiao == 'norte_central': query = f"SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_america_nc {condicao}ORDER BY RANDOM();"
    elif regiao == 'europa': query = f"SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_europa {condicao}ORDER BY RANDOM();"
    elif regiao == 'africa': query = f"SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_africa {condicao}ORDER BY RANDOM();"
    elif regiao == 'asia': query = f"SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_asia {condicao}ORDER BY RANDOM();"
    elif regiao == 'oceania': query = f"SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_oceania {condicao}ORDER BY RANDOM();"
    else: 
        condicao_mundo = "" if incluir_territorios else "WHERE soberano = TRUE"
        query = f"""
            SELECT * FROM (
                SELECT nome, codigo_iso, '' as apelidos FROM paises_america_sul {condicao_mundo}
                UNION ALL SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_america_nc {condicao_mundo}
                UNION ALL SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_europa {condicao_mundo}
                UNION ALL SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_africa {condicao_mundo}
                UNION ALL SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_asia {condicao_mundo}
                UNION ALL SELECT nome, codigo_iso, COALESCE(apelidos, '') FROM paises_oceania {condicao_mundo}
            ) AS mundo_todo ORDER BY RANDOM();
        """
    cursor.execute(query)
    paises = cursor.fetchall()
    cursor.close()
    conexao.close()
    return [{"nome": p[0], "iso": p[1], "apelidos": p[2]} for p in paises]

def pegar_paises_trunfo():
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    query = """
        SELECT * FROM (
            SELECT nome, codigo_iso, populacao FROM paises_america_sul WHERE populacao > 0
            UNION ALL SELECT nome, codigo_iso, populacao FROM paises_america_nc WHERE populacao > 0
            UNION ALL SELECT nome, codigo_iso, populacao FROM paises_europa WHERE populacao > 0
            UNION ALL SELECT nome, codigo_iso, populacao FROM paises_africa WHERE populacao > 0
            UNION ALL SELECT nome, codigo_iso, populacao FROM paises_asia WHERE populacao > 0
            UNION ALL SELECT nome, codigo_iso, populacao FROM paises_oceania WHERE populacao > 0
        ) AS mundo_trunfo ORDER BY RANDOM();
    """
    cursor.execute(query)
    paises = cursor.fetchall()
    cursor.close()
    conexao.close()
    return [{"nome": p[0], "iso": p[1], "populacao": p[2]} for p in paises]

def pegar_estados_brasil():
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("SELECT sigla, nome, imagem_url, cultura FROM estados_brasil ORDER BY RANDOM();")
    estados = cursor.fetchall()
    cursor.close()
    conexao.close()
    return [{"sigla": e[0], "nome": e[1], "img": f"/static/estados/{e[0]}.jpg", "cultura": e[3]} for e in estados]

def pegar_perguntas_quiz(limite=5):
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("SELECT id, pergunta, opcao_a, opcao_b, opcao_c, opcao_d, resposta_correta, curiosidade FROM quiz_perguntas ORDER BY RANDOM() LIMIT %s;", (limite,))
    perguntas = cursor.fetchall()
    cursor.close()
    conexao.close()
    return [{"id": p[0], "pergunta": p[1], "A": p[2], "B": p[3], "C": p[4], "D": p[5], "correta": p[6], "curiosidade": p[7]} for p in perguntas]

def salvar_estatisticas_bd(nome, regiao, acertos, total, tempo_total, historico):
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("INSERT INTO ranking_partidas (nome_jogador, modo_jogo, acertos, total_paises, tempo_total) VALUES (%s, %s, %s, %s, %s)", (nome, regiao, acertos, total, tempo_total))
    for item in historico:
        iso = item['iso']
        nome_pais = item['pais']
        acertou = 1 if item['acertou'] else 0
        tempo = item['tempo'] if item['acertou'] else 0
        cursor.execute("""
            INSERT INTO stats_paises (codigo_iso, nome_pais, regiao, vezes_sorteado, vezes_acertado, tempo_total_acertos)
            VALUES (%s, %s, %s, 1, %s, %s)
            ON CONFLICT (codigo_iso) DO UPDATE SET
                vezes_sorteado = stats_paises.vezes_sorteado + 1, vezes_acertado = stats_paises.vezes_acertado + EXCLUDED.vezes_acertado, tempo_total_acertos = stats_paises.tempo_total_acertos + EXCLUDED.tempo_total_acertos;
        """, (iso, nome_pais, regiao, acertou, tempo))
    conexao.commit()
    cursor.close()
    conexao.close()

def obter_ranking_por_regiao(regiao):
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("SELECT nome_jogador, acertos, tempo_total FROM ranking_partidas WHERE modo_jogo = %s ORDER BY acertos DESC, tempo_total ASC LIMIT 10;", (regiao,))
    ranking = cursor.fetchall()
    cursor.close()
    conexao.close()
    return ranking

def obter_estatisticas_regiao(regiao):
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("SELECT nome_pais, vezes_sorteado, vezes_acertado, ROUND((vezes_acertado::numeric / vezes_sorteado) * 100, 1) as taxa_acerto, CASE WHEN vezes_acertado > 0 THEN ROUND((tempo_total_acertos::numeric / vezes_acertado), 2) ELSE 0 END as tempo_medio FROM stats_paises WHERE regiao = %s AND vezes_sorteado > 0 ORDER BY taxa_acerto DESC, tempo_medio ASC;", (regiao,))
    stats = cursor.fetchall()
    cursor.close()
    conexao.close()
    return stats

def normalizar_texto(texto):
    if not texto: return ""
    texto = texto.strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


# --- SISTEMA DE CONQUISTAS ---

def verificar_conquistas(username, dados_partida):
    conexao = pegar_conexao()
    cursor = conexao.cursor(cursor_factory=RealDictCursor)
    novas_conquistas = []
    
    try:
        cursor.execute("SELECT COUNT(*) as total FROM ranking_partidas WHERE nome_jogador = %s", (username,))
        total_partidas = cursor.fetchone()['total']

        cursor.execute("""
            SELECT * FROM conquistas 
            WHERE id NOT IN (SELECT conquista_id FROM conquistas_usuario WHERE username = %s)
        """, (username,))
        pendentes = cursor.fetchall()

        for c in pendentes:
            ganhou = False
            if c['requisito_tipo'] == 'partidas' and total_partidas >= c['requisito_valor']:
                ganhou = True
            elif c['requisito_tipo'] == 'precisao_100' and dados_partida['acertos'] == dados_partida['total'] and dados_partida['total'] > 0:
                ganhou = True
            elif c['requisito_tipo'] == 'acertos_brasil' and dados_partida['regiao'] == 'brasil_cultural' and dados_partida['acertos'] >= c['requisito_valor']:
                ganhou = True

            if ganhou:
                cursor.execute("INSERT INTO conquistas_usuario (username, conquista_id) VALUES (%s, %s)", (username, c['id']))
                novas_conquistas.append({'nome': c['nome'], 'icone': c['icone']})

        conexao.commit()
    except Exception as e:
        print(f"Erro conquistas: {e}")
    finally:
        cursor.close()
        conexao.close()
    return novas_conquistas

# --- MEMÓRIA DO MULTIPLAYER ---
salas_ativas = {}

def gerar_codigo_sala():
    while True:
        codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if codigo not in salas_ativas:
            return codigo

@app.route('/criar_sala', methods=['POST'])
def criar_sala():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    codigo = gerar_codigo_sala()
    salas_ativas[codigo] = {
        'anfitriao': session['usuario_logado'],
        'jogadores': [], 
        'estado': 'esperando' 
    }
    return redirect(url_for('sala_espera', codigo=codigo))

@app.route('/entrar_sala', methods=['POST'])
def entrar_sala():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    codigo = (request.form.get('codigo_sala') or '').upper()
    if codigo in salas_ativas and salas_ativas[codigo]['estado'] == 'esperando':
        return redirect(url_for('sala_espera', codigo=codigo))
    else:
        return render_template('quiz_lobby.html', erro="Código de sala inválido ou a partida já começou!")

@app.route('/sala/<codigo>')
def sala_espera(codigo):
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    if codigo not in salas_ativas: return "Esta sala não existe!", 404
    nome_jogador = session['usuario_logado']
    sala = salas_ativas[codigo]
    eh_anfitriao = (sala['anfitriao'] == nome_jogador)
    return render_template('sala_espera.html', codigo=codigo, nome_jogador=nome_jogador, eh_anfitriao=eh_anfitriao)


# --- EVENTOS EM TEMPO REAL (WEBSOCKETS) ---

@socketio.on('conectar_na_sala')
def on_join(dados):
    nome = dados['nome']
    codigo = dados['codigo']
    if codigo not in salas_ativas: return 
    join_room(codigo)
    if nome not in salas_ativas[codigo]['jogadores']:
        salas_ativas[codigo]['jogadores'].append(nome)
    emit('atualizar_jogadores', {'jogadores': salas_ativas[codigo]['jogadores']}, to=codigo)

@socketio.on('iniciar_jogo')
def iniciar_jogo(dados):
    codigo = dados['codigo']
    if codigo in salas_ativas and salas_ativas[codigo]['anfitriao'] == dados['nome']:
        sala = salas_ativas[codigo]
        sala['estado'] = 'jogando'
        sala['perguntas'] = pegar_perguntas_quiz(5) 
        sala['rodada_atual'] = 0
        sala['pontuacoes'] = {jogador: 0 for jogador in sala['jogadores']} 
        emit('redirecionar_jogo', {'url': f'/arena/{codigo}'}, to=codigo)

@app.route('/arena/<codigo>')
def arena_multi(codigo):
    if 'usuario_logado' not in session or codigo not in salas_ativas:
        return redirect(url_for('inicio'))
    eh_anfitriao = (salas_ativas[codigo]['anfitriao'] == session['usuario_logado'])
    return render_template('quiz_multi.html', codigo=codigo, nome_jogador=session['usuario_logado'], eh_anfitriao=eh_anfitriao)

@socketio.on('entrar_arena')
def entrar_arena(dados):
    codigo = dados['codigo']
    if codigo not in salas_ativas: return
    join_room(codigo)
    if salas_ativas[codigo]['anfitriao'] == dados['nome']:
        socketio.sleep(1) 
        enviar_pergunta_multi(codigo)

def enviar_pergunta_multi(codigo):
    sala = salas_ativas[codigo]
    if sala['rodada_atual'] < len(sala['perguntas']):
        pergunta = sala['perguntas'][sala['rodada_atual']]
        sala['respostas_rodada'] = 0
        sala['tempo_inicio'] = time.time() 
        dados_pergunta = {
            'pergunta': pergunta['pergunta'],
            'A': pergunta['A'], 'B': pergunta['B'], 'C': pergunta['C'], 'D': pergunta['D'],
            'rodada': sala['rodada_atual'] + 1,
            'total': len(sala['perguntas'])
        }
        emit('nova_pergunta', dados_pergunta, to=codigo)
    else:
        ranking = sorted(sala['pontuacoes'].items(), key=lambda x: x[1], reverse=True)
        emit('fim_de_jogo', {'ranking': ranking}, to=codigo)

@socketio.on('enviar_resposta')
def receber_resposta(dados):
    codigo = dados['codigo']
    nome = dados['nome']
    resposta = dados['resposta']
    sala = salas_ativas.get(codigo)
    if not sala: return
    pergunta_atual = sala['perguntas'][sala['rodada_atual']]
    tempo_gasto = time.time() - sala['tempo_inicio']
    if resposta == pergunta_atual['correta']:
        pontos = max(0, int(((15 - tempo_gasto) / 15.0) * 1000))
        sala['pontuacoes'][nome] = sala['pontuacoes'].get(nome, 0) + pontos
    sala['respostas_rodada'] += 1
    if sala['respostas_rodada'] >= len(sala['jogadores']):
        ranking = sorted(sala['pontuacoes'].items(), key=lambda x: x[1], reverse=True)
        resultado = {
            'correta_letra': pergunta_atual['correta'],
            'correta_texto': pergunta_atual[pergunta_atual['correta']],
            'curiosidade': pergunta_atual['curiosidade'],
            'ranking': ranking
        }
        emit('resultado_rodada', resultado, to=codigo)

@socketio.on('pedir_proxima')
def pedir_proxima(dados):
    codigo = dados['codigo']
    if codigo in salas_ativas and salas_ativas[codigo]['anfitriao'] == dados['nome']:
        salas_ativas[codigo]['rodada_atual'] += 1
        enviar_pergunta_multi(codigo)

# --- ROTAS DE AUTENTICAÇÃO ---

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    senha_digitada = request.form.get('password')
    conexao = pegar_conexao()
    cursor = conexao.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
    usuario = cursor.fetchone()
    cursor.close()
    conexao.close()
    if usuario and check_password_hash(usuario['senha_hash'], senha_digitada):
        session['usuario_logado'] = username
        session['avatar_url'] = usuario.get('avatar_url', 'agente01.svg')
        session['cor_pele'] = usuario.get('cor_pele', '#F9B17B')
        session['cor_cabelo'] = usuario.get('cor_cabelo', '#4a2e1b')
        session['cor_roupa'] = usuario.get('cor_roupa', '#2d3748')
        session['cor_extra'] = usuario.get('cor_extra', '#00BFFF')
        return redirect(url_for('inicio'))
    else:
        return render_template('inicio.html', erro="Credenciais incorretas.", nome_jogador=None)

@app.route('/registro', methods=['POST'])
def registro():
    username = request.form.get('new_username')
    senha = request.form.get('new_password')
    avatar_url = request.form.get('avatar_url', 'agente01.svg')
    cor_pele = request.form.get('avatar_pele', '#F9B17B')
    cor_cabelo = request.form.get('avatar_cabelo', '#4a2e1b')
    cor_roupa = request.form.get('avatar_roupa', '#2d3748')
    cor_extra = request.form.get('avatar_extra', '#00BFFF')
    senha_segura = generate_password_hash(senha)
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    try:
        cursor.execute("""
            INSERT INTO usuarios (username, senha_hash, avatar_url, cor_pele, cor_cabelo, cor_roupa, cor_extra) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (username, senha_segura, avatar_url, cor_pele, cor_cabelo, cor_roupa, cor_extra))
        conexao.commit()
        session['usuario_logado'] = username
        session['avatar_url'] = avatar_url
        session['cor_pele'] = cor_pele
        session['cor_cabelo'] = cor_cabelo
        session['cor_roupa'] = cor_roupa
        session['cor_extra'] = cor_extra
        return redirect(url_for('inicio'))
    except psycopg2.errors.UniqueViolation:
        conexao.rollback()
        return render_template('inicio.html', erro_registro="Nome já em uso. Escolha outro.", nome_jogador=None)
    finally:
        cursor.close()
        conexao.close()

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('inicio'))

# --- ROTAS DO SISTEMA PRINCIPAL ---

@app.route('/')
def inicio():
    nome = session.get('usuario_logado')
    return render_template('inicio.html', nome_jogador=nome)

@app.route('/perfil/<username>')
def perfil_usuario(username):
    conexao = pegar_conexao()
    cursor = conexao.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT c.*, 
               CASE WHEN cu.id IS NOT NULL THEN TRUE ELSE FALSE END as desbloqueada,
               cu.data_desbloqueio
        FROM conquistas c
        LEFT JOIN conquistas_usuario cu ON c.id = cu.conquista_id AND cu.username = %s
        ORDER BY c.id ASC
    """, (username,))
    conquistas = cursor.fetchall()
    cursor.close()
    conexao.close()
    return render_template('perfil.html', username=username, conquistas=conquistas)

@app.route('/iniciar_partida', methods=['POST'])
def iniciar_partida():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    modo_jogo = request.form.get('modo_jogo')
    if modo_jogo == 'trunfo':
        session['paises_trunfo'] = pegar_paises_trunfo()
        return redirect(url_for('trunfo'))
    elif modo_jogo == 'brasil_cultural':
        session['estados_jogo'] = pegar_estados_brasil()
        session['total_paises'] = len(session['estados_jogo'])
        session['rodada'] = 1
        session['acertos'] = 0
        session['tempos'] = []
        session['historico'] = [] 
        session['tempo_inicio_jogo'] = time.time()
        session['inicio_pergunta'] = time.time()
        session['nome_regiao'] = 'brasil_cultural'
        return redirect(url_for('jogo_brasil'))
    regiao = request.form.get('regiao')
    incluir_territorios = request.form.get('incluir_territorios') == 'sim'
    session['nome_regiao'] = regiao 
    session['paises_jogo'] = pegar_todos_paises_embaralhados(regiao, incluir_territorios)
    session['total_paises'] = len(session['paises_jogo'])
    session['rodada'] = 1
    session['acertos'] = 0
    session['tempos'] = []
    session['historico'] = [] 
    session['tempo_inicio_jogo'] = time.time()
    session['inicio_pergunta'] = time.time()
    return redirect(url_for('jogo'))

@app.route('/jogo_brasil', methods=['GET', 'POST'])
def jogo_brasil():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    if 'estados_jogo' not in session: return redirect(url_for('inicio'))
    mensagem = ""
    indice_atual = session['rodada'] - 1
    estado_atual = session['estados_jogo'][indice_atual]
    sigla_atual = estado_atual['sigla']
    if request.method == 'POST':
        tempo_decorrido = round(time.time() - session.get('inicio_pergunta', time.time()), 2)
        estado_clicado = request.form.get('estado_clicado') 
        acertou = (estado_clicado == sigla_atual)
        if acertou:
            mensagem = f"CORRETO: {estado_atual['nome']} em {tempo_decorrido}s!"
            session['acertos'] += 1
            session['tempos'].append(tempo_decorrido)
        else:
            estado_errado_nome = "Nenhum"
            if estado_clicado:
                conexao = pegar_conexao()
                cursor = conexao.cursor()
                cursor.execute("SELECT nome FROM estados_brasil WHERE sigla = %s", (estado_clicado,))
                res = cursor.fetchone()
                if res: estado_errado_nome = res[0]
                cursor.close()
                conexao.close()
            mensagem = f"INCORRETO: Clicaste em {estado_errado_nome}. O correto era {estado_atual['nome']}."
        session['historico'].append({'pais': estado_atual['nome'], 'iso': sigla_atual, 'acertou': acertou, 'chute': estado_clicado, 'tempo': tempo_decorrido})
        session['rodada'] += 1
        if session['rodada'] > session['total_paises']:
            session['tempo_total_jogo'] = round(time.time() - session['tempo_inicio_jogo'], 2)
            salvar_estatisticas_bd(session.get('usuario_logado'), session.get('nome_regiao'), session.get('acertos'), session.get('total_paises'), session['tempo_total_jogo'], session.get('historico'))
            return redirect(url_for('resultado_brasil'))
        session['inicio_pergunta'] = time.time()
        indice_atual = session['rodada'] - 1
        estado_atual = session['estados_jogo'][indice_atual]
    historico_json = json.dumps(session.get('historico', []))
    return render_template('brasil_game.html', estado=estado_atual, mensagem=mensagem, rodada=session['rodada'], max_rodadas=session['total_paises'], historico=session.get('historico', []), historico_js=historico_json, tempo_inicio=session['tempo_inicio_jogo'])

@app.route('/quiz_lobby')
def quiz_lobby():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    return render_template('quiz_lobby.html')

@app.route('/iniciar_partida_solo')
def iniciar_partida_solo():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    session['quiz_perguntas'] = pegar_perguntas_quiz(5) 
    session['quiz_rodada'] = 1
    session['quiz_pontuacao'] = 0
    return redirect(url_for('jogo_quiz_solo'))

@app.route('/jogo_quiz_solo', methods=['GET', 'POST'])
def jogo_quiz_solo():
    if 'usuario_logado' not in session or 'quiz_perguntas' not in session: return redirect(url_for('inicio'))
    indice = session['quiz_rodada'] - 1
    if indice >= len(session['quiz_perguntas']): return redirect(url_for('inicio')) 
    pergunta_atual = session['quiz_perguntas'][indice]
    if request.method == 'POST':
        if 'avancar' in request.form:
            session['quiz_rodada'] += 1
            return redirect(url_for('jogo_quiz_solo'))
        resposta_dada = request.form.get('resposta')
        tempo_restante = float(request.form.get('tempo_restante', 0))
        acertou = (resposta_dada == pergunta_atual['correta'])
        pontos_ganhos = int((tempo_restante / 15.0) * 1000) if acertou else 0
        session['quiz_pontuacao'] += pontos_ganhos
        feedback = {"acertou": acertou, "pontos": pontos_ganhos, "correta_letra": pergunta_atual['correta'], "correta_texto": pergunta_atual[pergunta_atual['correta']], "curiosidade": pergunta_atual['curiosidade']}
        return render_template('quiz_solo.html', pergunta=pergunta_atual, rodada=session['quiz_rodada'], total=len(session['quiz_perguntas']), pontuacao=session['quiz_pontuacao'], feedback=feedback)
    return render_template('quiz_solo.html', pergunta=pergunta_atual, rodada=session['quiz_rodada'], total=len(session['quiz_perguntas']), pontuacao=session['quiz_pontuacao'], feedback=None)

@app.route('/resultado_brasil')
def resultado_brasil():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    acertos = session.get('acertos', 0)
    total_paises = session.get('total_paises', 0)
    tempo_total = session.get('tempo_total_jogo', 0)
    tempos = session.get('tempos', [])
    tempo_medio = round(sum(tempos) / len(tempos), 2) if tempos else 0
    
    dados = {'acertos': acertos, 'total': total_paises, 'tempo': tempo_total, 'regiao': 'brasil_cultural'}
    novas = verificar_conquistas(session['usuario_logado'], dados)
    
    ranking_bruto = obter_ranking_por_regiao('brasil_cultural')
    top_global = [{"nome": r[0], "acertos": r[1], "tempo": r[2]} for r in ranking_bruto]
    
    conexao = pegar_conexao()
    cursor = conexao.cursor()
    cursor.execute("SELECT sigla, nome, cultura FROM estados_brasil;")
    dados_estados = {linha[0]: {"nome": linha[1], "cultura": linha[2]} for linha in cursor.fetchall()}
    cursor.close()
    conexao.close()

    return render_template('resultado_brasil.html', nome_jogador=session.get('usuario_logado'), acertos=acertos, max_rodadas=total_paises, tempo_medio=tempo_medio, tempo_total=tempo_total, historico_js=json.dumps(session.get('historico', [])), estados_js=json.dumps(dados_estados), top_global=top_global, novas_conquistas=novas)

@app.route('/trunfo')
def trunfo():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    if 'paises_trunfo' not in session or len(session['paises_trunfo']) < 2: return redirect(url_for('inicio'))
    paises_js = json.dumps(session['paises_trunfo'])
    return render_template('trunfo.html', nome_jogador=session['usuario_logado'], paises_js=paises_js)

@app.route('/jogo', methods=['GET', 'POST'])
def jogo():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    if 'paises_jogo' not in session: return redirect(url_for('inicio'))
    mensagem = ""
    indice_atual = session['rodada'] - 1
    if indice_atual >= len(session['paises_jogo']): return redirect(url_for('resultado'))
    pais_atual = session['paises_jogo'][indice_atual]
    if request.method == 'POST':
        is_ajax = request.is_json
        dados = request.get_json() if is_ajax else request.form
        chute_original = dados.get('resposta', '')
        nome_original = dados.get('pais_correto', '')
        apelidos_raw = dados.get('apelidos_corretos', '')
        tempo_decorrido = round(time.time() - session.get('inicio_pergunta', time.time()), 2)
        resposta_usuario = normalizar_texto(chute_original)
        resposta_certa = normalizar_texto(nome_original)
        lista_apelidos = [normalizar_texto(a) for a in apelidos_raw.split(',')] if apelidos_raw else []
        acertou = (resposta_usuario == resposta_certa) or (resposta_usuario in lista_apelidos)
        if acertou:
            mensagem = f"CORRETO: {nome_original} em {tempo_decorrido}s!"
            session['acertos'] += 1
            session['tempos'].append(tempo_decorrido)
        else:
            mensagem = f"INCORRETO: Era {nome_original}."
        iso_anterior = pais_atual['iso']
        session['historico'].append({'pais': nome_original, 'iso': iso_anterior, 'acertou': acertou, 'chute': chute_original, 'tempo': tempo_decorrido})
        session['rodada'] += 1
        if session['rodada'] > session['total_paises']:
            session['tempo_total_jogo'] = round(time.time() - session['tempo_inicio_jogo'], 2)
            salvar_estatisticas_bd(session.get('usuario_logado'), session.get('nome_regiao'), session.get('acertos'), session.get('total_paises'), session['tempo_total_jogo'], session.get('historico'))
            if is_ajax: return jsonify({"fim_jogo": True, "redirect_url": url_for('resultado')})
            return redirect(url_for('resultado'))
        session['inicio_pergunta'] = time.time()
        pais_atual = session['paises_jogo'][session['rodada'] - 1]
        if is_ajax: return jsonify({"fim_jogo": False, "mensagem": mensagem, "acertou": acertou, "iso_anterior": iso_anterior, "url_bandeira": f"https://flagcdn.com/w320/{pais_atual['iso'].lower()}.png", "nome_pais": pais_atual['nome'], "apelidos_pais": pais_atual['apelidos'], "rodada": session['rodada'], "max_rodadas": session['total_paises'], "acertos": session['acertos']})
    return render_template('index.html', url_bandeira=f"https://flagcdn.com/w320/{pais_atual['iso'].lower()}.png", nome_pais=pais_atual['nome'], apelidos_pais=pais_atual['apelidos'], mensagem=mensagem, rodada=session['rodada'], max_rodadas=session['total_paises'], acertos=session['acertos'], tempo_inicio=session['tempo_inicio_jogo'], regiao=session.get('nome_regiao'), historico=session.get('historico', []), historico_js=json.dumps(session.get('historico', [])))

@app.route('/desistir')
def desistir():
    if 'tempo_inicio_jogo' in session:
        session['tempo_total_jogo'] = round(time.time() - session['tempo_inicio_jogo'], 2)
        salvar_estatisticas_bd(session.get('usuario_logado'), session.get('nome_regiao'), session.get('acertos'), session.get('total_paises'), session['tempo_total_jogo'], session.get('historico'))
    if session.get('nome_regiao') == 'brasil_cultural': return redirect(url_for('resultado_brasil'))
    return redirect(url_for('resultado'))

@app.route('/resultado')
def resultado():
    if 'usuario_logado' not in session: return redirect(url_for('inicio'))
    acertos = session.get('acertos', 0)
    total_paises = session.get('total_paises', 0)
    tempo_total = session.get('tempo_total_jogo', 0)
    tempos = session.get('tempos', [])
    tempo_medio = round(sum(tempos) / len(tempos), 2) if tempos else 0
    regiao_jogada = session.get('nome_regiao', 'sul')
    
    dados = {'acertos': acertos, 'total': total_paises, 'tempo': tempo_total, 'regiao': regiao_jogada}
    novas = verificar_conquistas(session['usuario_logado'], dados)
    
    return render_template('resultado.html', nome_jogador=session.get('usuario_logado'), regiao_jogada=regiao_jogada.upper(), acertos=acertos, max_rodadas=total_paises, tempo_medio=tempo_medio, tempo_total=tempo_total, historico=session.get('historico', []), ranking=obter_ranking_por_regiao(regiao_jogada), stats_regiao=obter_estatisticas_regiao(regiao_jogada), novas_conquistas=novas)

@app.route('/sobre')
def sobre():
    return render_template('sobre.html', nome_jogador=session.get('usuario_logado'))

@app.route('/termos')
def termos():
    return render_template('termos.html', nome_jogador=session.get('usuario_logado'))

@app.route('/keep-alive')
def keep_alive():
    return "Acordado!", 200

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', debug=True)
