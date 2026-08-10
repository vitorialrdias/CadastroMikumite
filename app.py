import streamlit as st
import bcrypt
from datetime import date
import pandas as pd
from io import BytesIO

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

    aba_login, aba_cadastro = st.tabs(["Entrar", "Cadastrar Administrador"])

    with aba_login:
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
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos!")

    with aba_cadastro:
        with st.form("form_cadastro_admin"):
            novo_user = st.text_input("Novo usuário")
            nova_senha = st.text_input("Nova senha", type="password")
            cadastrar = st.form_submit_button(
                "Cadastrar Administrador", use_container_width=True
            )

        if cadastrar:
            if not novo_user or not nova_senha:
                st.warning("Preencha todos os campos!")
            elif len(nova_senha) < 6:
                st.warning("A senha deve ter pelo menos 6 caracteres.")
            else:
                sql_verificar = (
                    "SELECT id_usuario FROM dbo.cadastro_admins WHERE user_admin = %s"
                )
                existente = fetch_one(sql_verificar, (novo_user,))
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
                        st.success(
                            "Administrador cadastrado com sucesso! Realize o login."
                        )
                    else:
                        st.error(
                            f"Erro: {st.session_state.get('_db_error', 'desconhecido')}"
                        )


# ----------------------------------------------------------------------
# TELA DE CADASTRO DE PRESENÇA
# ----------------------------------------------------------------------
def tela_cadastro():
    st.subheader("Incluir presença Mikumite")

    nomes = carregar_nomes()
    convs = carregar_convidantes()
    nucs = carregar_nucleos()

    with st.form("form_cadastro_presenca", clear_on_submit=True):
        # selectbox com opção de digitar é mais natural no mobile do que
        # autocomplete customizado; aceita texto livre clicando "+ digitar"
        nome = st.selectbox(
            "Mikumite",
            options=[""] + nomes,
            index=0,
            accept_new_options=True,
        )
        convidante = st.selectbox(
            "Convidante",
            options=[""] + convs,
            index=0,
            accept_new_options=True,
        )
        nucleo = st.selectbox(
            "Núcleo",
            options=[""] + nucs,
            index=0,
            accept_new_options=True,
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
                st.toast("Presença registrada!", icon="✅")
                st.success("Presença do Mikumite registrada com sucesso!")
            else:
                st.error(
                    f"Erro: {st.session_state.get('_db_error', 'desconhecido')}"
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

    if not df_filtrado.empty:
        st.bar_chart(df_filtrado["Núcleo"].value_counts())

    st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

    if not df_filtrado.empty:
        buffer = BytesIO()
        df_filtrado.to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            "Exportar Excel",
            data=buffer.getvalue(),
            file_name=f"relatorio_mikumite_{date.today().strftime('%Y-%m-%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.caption("Não há dados para exportar nesse período.")


# ----------------------------------------------------------------------
# APP PRINCIPAL
# ----------------------------------------------------------------------
def main():
    if not st.session_state.user_logged:
        tela_login()
        return

    with st.sidebar:
        st.write(f"Logado como **{st.session_state.user_logged}**")
        st.divider()
        if st.button("Sair", use_container_width=True):
            st.session_state.user_logged = None
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
        options=["📋 Cadastro", "📊 Listagem"],
        key="nav_page",
        label_visibility="collapsed",
    )

    pagina_atual = st.session_state.nav_page or "📋 Cadastro"
    st.divider()

    if pagina_atual == "📋 Cadastro":
        tela_cadastro()
    else:
        tela_listagem()


if __name__ == "__main__":
    main()
