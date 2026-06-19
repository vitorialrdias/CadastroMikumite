import streamlit as st
from datetime import date
import pandas as pd
from io import BytesIO

from config.db_connection import query, fetch_one, fetch_all

st.set_page_config(
    page_title="Sistema de Presença Mikumite",
    page_icon="🙏",
    layout="centered",
)

# ----------------------------------------------------------------------
# ESTADO DE SESSÃO
# ----------------------------------------------------------------------
if "user_logged" not in st.session_state:
    st.session_state.user_logged = None

if "page" not in st.session_state:
    st.session_state.page = "cadastro"


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
                sql = (
                    "SELECT id_usuario FROM dbo.cadastro_admins "
                    "WHERE user_admin = %s AND pass_admin = %s"
                )
                resultado = fetch_one(sql, (user, senha))
                if resultado:
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
            else:
                sql_verificar = (
                    "SELECT id_usuario FROM dbo.cadastro_admins WHERE user_admin = %s"
                )
                existente = fetch_one(sql_verificar, (novo_user,))
                if existente:
                    st.error("Erro: Este usuário já existe!")
                else:
                    sucesso = query(
                        "INSERT INTO dbo.cadastro_admins "
                        "(user_admin, pass_admin, data_inclusao) "
                        "VALUES (%s, %s, CURRENT_DATE)",
                        (novo_user, nova_senha),
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

    nomes = [m[0] for m in fetch_all("SELECT nome_mikumite FROM dbo.sistema_mikumite")]
    convs = [
        c[0]
        for c in fetch_all(
            "SELECT DISTINCT nome_convidante FROM dbo.sistema_mikumite"
        )
    ]
    nucs = [n[0] for n in fetch_all("SELECT nome_nucleo FROM dbo.nucleos")]

    with st.form("form_cadastro_presenca", clear_on_submit=True):
        # selectbox com opção de digitar é mais natural no mobile do que
        # autocomplete customizado; aceita texto livre clicando "+ digitar"
        nome = st.selectbox(
            "Mikumite",
            options=[""] + sorted(set(nomes)),
            index=0,
            accept_new_options=True,
        )
        convidante = st.selectbox(
            "Convidante",
            options=[""] + sorted(set(convs)),
            index=0,
            accept_new_options=True,
        )
        nucleo = st.selectbox(
            "Núcleo",
            options=[""] + sorted(set(nucs)),
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
            sucesso = query(sql, (nome, convidante, nucleo))
            if sucesso:
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

    if st.button("Filtrar", use_container_width=True):
        st.session_state["_filtrar"] = True

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
    st.info(f"Total de Mikumites presentes na data atual: **{total_hoje}**")

    df = pd.DataFrame(
        clientes,
        columns=["Nome Mikumite", "Convidante", "Núcleo", "Data Cadastro"],
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        buffer = BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
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
        if st.button("📋 Cadastro", use_container_width=True):
            st.session_state.page = "cadastro"
        if st.button("📊 Listagem", use_container_width=True):
            st.session_state.page = "listagem"
        st.divider()
        if st.button("Sair", use_container_width=True):
            st.session_state.user_logged = None
            st.rerun()

    st.title("Sistema de presença Mikumite")

    if st.session_state.page == "cadastro":
        tela_cadastro()
    else:
        tela_listagem()


if __name__ == "__main__":
    main()
