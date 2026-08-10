import streamlit as st
import bcrypt
import hmac
import hashlib
import base64
import re
import time
from datetime import date
import pandas as pd
from io import BytesIO
from openpyxl.chart import BarChart, Reference

from config.db_connection import query, fetch_one, fetch_all

st.set_page_config(
    page_title="Sistema de Presença Mikumite",
    page_icon="🙏",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ----------------------------------------------------------------------
# CSS
# - font-size 16px nos inputs evita o zoom automático do Safari/iOS ao
#   focar um campo (a causa mais comum de "dificuldade para digitar" no
#   celular: a página pula/dá zoom e o dropdown some da tela).
# - min-height 44px nos botões segue o tamanho mínimo de toque recomendado.
# ----------------------------------------------------------------------
st.markdown(
    """
    <style>
    input, textarea, select { font-size: 16px !important; }
    div[data-testid="stSelectbox"] input { font-size: 16px !important; }
    .stButton > button, .stFormSubmitButton > button {
        min-height: 44px;
        font-weight: 600;
    }
    div[data-baseweb="tab-list"] { gap: 0.5rem; }
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border-radius: 0.5rem;
        padding: 0.75rem 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------
# ESTADO DE SESSÃO
# ----------------------------------------------------------------------
if "user_logged" not in st.session_state:
    st.session_state.user_logged = None


# ----------------------------------------------------------------------
# LOGIN PERSISTENTE
# Sem isso, dar F5 na página derruba o login (cada refresh cria uma nova
# sessão do Streamlit). Guardamos um token assinado na URL (?tok=...)
# que carrega usuário + validade; ao recarregar, se o token ainda for
# válido, o login é restaurado. Ele "desliza" 30min a partir da última
# interação — não precisa de tabela nova no banco.
# ----------------------------------------------------------------------
SESSAO_TTL_SEGUNDOS = 30 * 60
_SESSION_SECRET = (
    st.secrets.get("session_secret")
    or (st.secrets.get("pass", "mikumite") + "::sessao-mikumite")
).encode("utf-8")


def _criar_token_sessao(user):
    validade = int(time.time()) + SESSAO_TTL_SEGUNDOS
    payload = f"{user}|{validade}"
    assinatura = hmac.new(_SESSION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")
    return f"{payload_b64}.{assinatura}"


def _validar_token_sessao(token):
    try:
        payload_b64, assinatura = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
        esperada = hmac.new(_SESSION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(assinatura, esperada):
            return None
        user, validade = payload.rsplit("|", 1)
        if int(validade) < int(time.time()):
            return None
        return user
    except Exception:
        return None


def _restaurar_sessao():
    if st.session_state.user_logged:
        return
    token = st.query_params.get("tok")
    if not token:
        return
    user = _validar_token_sessao(token)
    if user:
        st.session_state.user_logged = user
    else:
        st.query_params.pop("tok", None)


def _renovar_sessao():
    """Renova a validade do token (login desliza a cada interação),
    evitando reescrever a URL a cada rerun sem necessidade."""
    token = st.query_params.get("tok")
    precisa_renovar = True
    if token:
        try:
            payload_b64, _ = token.split(".", 1)
            payload = base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
            _, validade = payload.rsplit("|", 1)
            restante = int(validade) - int(time.time())
            precisa_renovar = restante < (SESSAO_TTL_SEGUNDOS - 300)
        except Exception:
            precisa_renovar = True
    if precisa_renovar:
        st.query_params["tok"] = _criar_token_sessao(st.session_state.user_logged)


def _encerrar_sessao():
    st.session_state.user_logged = None
    st.query_params.pop("tok", None)


# ----------------------------------------------------------------------
# SENHA (hash com bcrypt, com migração automática de senhas antigas
# gravadas em texto puro)
# ----------------------------------------------------------------------
def _hash_senha(senha_texto):
    return bcrypt.hashpw(senha_texto.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _parece_hash_bcrypt(valor):
    return isinstance(valor, str) and valor.startswith(("$2a$", "$2b$", "$2y$"))


def _autenticar(user, senha):
    resultado = fetch_one(
        "SELECT id_usuario, pass_admin FROM dbo.cadastro_admins WHERE user_admin = %s",
        (user,),
    )
    if not resultado:
        return False

    id_usuario, senha_armazenada = resultado

    if _parece_hash_bcrypt(senha_armazenada):
        return bcrypt.checkpw(senha.encode("utf-8"), senha_armazenada.encode("utf-8"))

    # Senha antiga em texto puro: valida e migra para hash silenciosamente.
    if senha_armazenada == senha:
        query(
            "UPDATE dbo.cadastro_admins SET pass_admin = %s WHERE id_usuario = %s",
            (_hash_senha(senha), id_usuario),
        )
        return True

    return False


def _validar_novo_admin(user, senha, confirmar_senha):
    """Regras de cadastro de administrador. Retorna a mensagem de erro,
    ou None se estiver tudo certo."""
    if not user or not senha or not confirmar_senha:
        return "Preencha todos os campos!"
    if len(user.strip()) < 3:
        return "O usuário deve ter pelo menos 3 caracteres."
    if senha != confirmar_senha:
        return "As senhas não coincidem."
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if not re.search(r"[A-Za-z]", senha) or not re.search(r"\d", senha):
        return "A senha deve conter letras e números."
    return None


# ----------------------------------------------------------------------
# DADOS DOS SELECTBOX (com cache curto para reduzir idas ao banco a
# cada interação — no mobile, cada round-trip extra é sentido como
# travamento)
# ----------------------------------------------------------------------
@st.cache_data(ttl=120)
def carregar_nomes():
    return sorted({m[0] for m in fetch_all("SELECT nome_mikumite FROM dbo.sistema_mikumite")})


@st.cache_data(ttl=120)
def carregar_convidantes():
    return sorted(
        {
            c[0]
            for c in fetch_all("SELECT DISTINCT nome_convidante FROM dbo.sistema_mikumite")
            if c[0]
        }
    )


@st.cache_data(ttl=120)
def carregar_nucleos():
    return sorted({n[0] for n in fetch_all("SELECT nome_nucleo FROM dbo.nucleos")})


def _limpar_cache_selects():
    carregar_nomes.clear()
    carregar_convidantes.clear()
    carregar_nucleos.clear()


@st.cache_data(ttl=300)
def carregar_resumo_nucleo_3_meses():
    return fetch_all(
        """
        SELECT nucleo, COUNT(*)
        FROM dbo.sistema_mikumite
        WHERE data_inclusao >= CURRENT_DATE - INTERVAL '3 months'
        GROUP BY nucleo
        ORDER BY nucleo
        """
    )


def _gerar_excel(df_periodo):
    """Gera o Excel com a listagem filtrada + uma aba de resumo com
    gráfico de presenças por núcleo dos últimos 3 meses (o gráfico fica
    só no Excel, não na tela)."""
    resumo = carregar_resumo_nucleo_3_meses()
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_periodo.to_excel(writer, index=False, sheet_name="Presenças")

        if resumo:
            df_resumo = pd.DataFrame(resumo, columns=["Núcleo", "Presenças"])
            df_resumo.to_excel(writer, index=False, sheet_name="Resumo por Núcleo")

            ws = writer.sheets["Resumo por Núcleo"]
            grafico = BarChart()
            grafico.title = "Presenças por núcleo — últimos 3 meses"
            grafico.x_axis.title = "Núcleo"
            grafico.y_axis.title = "Presenças"
            n = len(df_resumo)
            dados = Reference(ws, min_col=2, min_row=1, max_row=n + 1)
            categorias = Reference(ws, min_col=1, min_row=2, max_row=n + 1)
            grafico.add_data(dados, titles_from_data=True)
            grafico.set_categories(categorias)
            ws.add_chart(grafico, "D2")

    return buffer.getvalue()


# ----------------------------------------------------------------------
# TELA DE LOGIN
# ----------------------------------------------------------------------
def tela_login():
    st.markdown(
        "<h3 style='text-align:center;'>Cerimônia Mensal Dai Dojo São Paulo</h3>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;'>Acesso ao Sistema de presença de Mikumite</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    # O cadastro de novo administrador não fica mais aberto nesta tela
    # pública — qualquer pessoa não autenticada podia criar um acesso de
    # admin. Agora só é possível criar um novo admin de dentro da área
    # logada (aba "Admins"), por outro admin já autenticado.
    with st.form("form_login"):
        user = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar", use_container_width=True)

    if entrar:
        if not user or not senha:
            st.warning("Preencha todos os campos!")
        else:
            with st.spinner("Verificando credenciais..."):
                autenticado = _autenticar(user, senha)
            if autenticado:
                st.session_state.user_logged = user
                st.query_params["tok"] = _criar_token_sessao(user)
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos!")


# ----------------------------------------------------------------------
# TELA DE CADASTRO DE PRESENÇA
# ----------------------------------------------------------------------
def tela_cadastro():
    st.subheader("Incluir presença Mikumite")

    nomes = carregar_nomes()
    convs = carregar_convidantes()
    nucs = carregar_nucleos()

    # "gen" muda a cada cadastro salvo, forçando o Streamlit a recriar os
    # widgets do zero (chave nova) em vez de só confiar no clear_on_submit.
    # Isso corrige o bug em que, depois do 1º cadastro, a lista de opções
    # mudava (o nome recém-incluído passa a aparecer nela) e o combobox
    # "selecionar ou digitar" ficava com estado inconsistente, fazendo o
    # 2º cadastro acusar campos vazios mesmo preenchidos.
    if "form_gen" not in st.session_state:
        st.session_state.form_gen = 0
    gen = st.session_state.form_gen

    with st.form(f"form_cadastro_presenca_{gen}", clear_on_submit=True):
        nome = st.selectbox(
            "Mikumite",
            options=[""] + nomes,
            index=0,
            accept_new_options=True,
            key=f"nome_mikumite_{gen}",
        )
        convidante = st.selectbox(
            "Convidante",
            options=[""] + convs,
            index=0,
            accept_new_options=True,
            key=f"nome_convidante_{gen}",
        )
        # Núcleo é uma lista fechada (sempre os mesmos núcleos), por isso
        # aqui é só seleção, sem opção de digitar um novo.
        nucleo = st.selectbox(
            "Núcleo",
            options=[""] + nucs,
            index=0,
            key=f"nome_nucleo_{gen}",
        )

        salvar = st.form_submit_button("Salvar", use_container_width=True)

    if salvar:
        if not nome or not nucleo:
            st.warning("Atenção! Preencha os campos Mikumite e Núcleo.")
        else:
            sql = (
                "INSERT INTO dbo.sistema_mikumite "
                "(nome_mikumite, nome_convidante, nucleo, data_inclusao) "
                "VALUES (%s, %s, %s, CURRENT_DATE)"
            )
            with st.spinner("Salvando..."):
                sucesso = query(sql, (nome, convidante, nucleo))
            if sucesso:
                _limpar_cache_selects()
                st.session_state.form_gen += 1
                st.toast("Presença registrada!", icon="✅")
                st.session_state["_ultimo_cadastro_ok"] = nome
                st.rerun()
            else:
                st.error(
                    f"Erro: {st.session_state.get('_db_error', 'desconhecido')}"
                )

    if st.session_state.get("_ultimo_cadastro_ok"):
        st.success(
            f"Presença de **{st.session_state.pop('_ultimo_cadastro_ok')}** registrada com sucesso!"
        )


# ----------------------------------------------------------------------
# TELA DE LISTAGEM
# ----------------------------------------------------------------------
def tela_listagem():
    st.subheader("Listagem de presenças")

    col1, col2 = st.columns(2)
    with col1:
        data_inicio = st.date_input("De:", value=date.today())
    with col2:
        data_fim = st.date_input("Até:", value=date.today())

    busca = st.text_input(
        "Buscar por nome, convidante ou núcleo",
        placeholder="Digite para filtrar a lista abaixo...",
    )

    sql = """
        SELECT nome_mikumite, nome_convidante, nucleo, data_inclusao
        FROM dbo.sistema_mikumite
        WHERE data_inclusao BETWEEN %s AND %s
        ORDER BY data_inclusao DESC
    """
    clientes = fetch_all(sql, (str(data_inicio), str(data_fim)))

    total_hoje = fetch_one(
        "SELECT COUNT(*) FROM dbo.sistema_mikumite WHERE data_inclusao = CURRENT_DATE"
    )[0]

    df = pd.DataFrame(
        clientes,
        columns=["Nome Mikumite", "Convidante", "Núcleo", "Data Cadastro"],
    )

    if busca:
        filtro = df.apply(
            lambda linha: busca.lower() in " ".join(str(v) for v in linha).lower(),
            axis=1,
        )
        df_filtrado = df[filtro]
    else:
        df_filtrado = df

    col_m1, col_m2 = st.columns(2)
    col_m1.metric("Presentes hoje", total_hoje)
    col_m2.metric("No período filtrado", len(df_filtrado))

    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    if not df_filtrado.empty:
        st.download_button(
            "Exportar Excel",
            data=_gerar_excel(df_filtrado),
            file_name=f"relatorio_mikumite_{date.today().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            help="Inclui uma aba de resumo com gráfico de presenças por núcleo dos últimos 3 meses.",
        )
    else:
        st.caption("Não há dados para exportar nesse período.")


# ----------------------------------------------------------------------
# TELA DE ADMINISTRADORES (só acessível já logado)
# ----------------------------------------------------------------------
def tela_admins():
    st.subheader("Administradores")

    admins = fetch_all(
        "SELECT user_admin, data_inclusao FROM dbo.cadastro_admins ORDER BY data_inclusao"
    )
    st.caption(f"{len(admins)} administrador(es) cadastrado(s)")
    st.dataframe(
        pd.DataFrame(admins, columns=["Usuário", "Cadastrado em"]),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.markdown("##### Novo administrador")
    st.caption(
        "Usuário com pelo menos 3 caracteres. Senha com pelo menos 8 "
        "caracteres, contendo letras e números."
    )

    with st.form("form_novo_admin", clear_on_submit=True):
        novo_user = st.text_input("Novo usuário")
        nova_senha = st.text_input("Nova senha", type="password")
        confirmar_senha = st.text_input("Confirmar senha", type="password")
        cadastrar = st.form_submit_button(
            "Cadastrar administrador", use_container_width=True
        )

    if cadastrar:
        erro = _validar_novo_admin(novo_user, nova_senha, confirmar_senha)
        if erro:
            st.warning(erro)
        else:
            existente = fetch_one(
                "SELECT id_usuario FROM dbo.cadastro_admins WHERE user_admin = %s",
                (novo_user,),
            )
            if existente:
                st.error("Erro: Este usuário já existe!")
            else:
                with st.spinner("Cadastrando..."):
                    sucesso = query(
                        "INSERT INTO dbo.cadastro_admins "
                        "(user_admin, pass_admin, data_inclusao) "
                        "VALUES (%s, %s, CURRENT_DATE)",
                        (novo_user, _hash_senha(nova_senha)),
                    )
                if sucesso:
                    st.toast("Administrador cadastrado!", icon="✅")
                    st.success(f"Administrador **{novo_user}** cadastrado com sucesso!")
                else:
                    st.error(
                        f"Erro: {st.session_state.get('_db_error', 'desconhecido')}"
                    )


# ----------------------------------------------------------------------
# APP PRINCIPAL
# ----------------------------------------------------------------------
def main():
    _restaurar_sessao()

    if not st.session_state.user_logged:
        tela_login()
        return

    _renovar_sessao()

    with st.sidebar:
        st.write(f"Logado como **{st.session_state.user_logged}**")
        st.divider()
        if st.button("Sair", use_container_width=True):
            _encerrar_sessao()
            st.rerun()

    st.markdown(
        "<h4 style='margin-bottom:0;'>🙏 Sistema de presença Mikumite</h4>",
        unsafe_allow_html=True,
    )
    st.caption(f"Logado como **{st.session_state.user_logged}**")

    # Navegação sempre visível na tela principal — no celular a barra
    # lateral fica escondida atrás de uma setinha pequena no canto, o que
    # dificultava achar a opção "Cadastro" para incluir dados.
    if "nav_page" not in st.session_state:
        st.session_state.nav_page = "📋 Cadastro"

    st.segmented_control(
        "Navegação",
        options=["📋 Cadastro", "📊 Listagem", "👤 Admins"],
        key="nav_page",
        label_visibility="collapsed",
    )

    pagina_atual = st.session_state.nav_page or "📋 Cadastro"
    st.divider()

    if pagina_atual == "📋 Cadastro":
        tela_cadastro()
    elif pagina_atual == "📊 Listagem":
        tela_listagem()
    else:
        tela_admins()


if __name__ == "__main__":
    main()
