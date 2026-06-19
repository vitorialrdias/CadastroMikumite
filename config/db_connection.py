import streamlit as st
import psycopg2


@st.cache_resource
def get_connection():
    """
    Cria (e reaproveita) a conexão com o PostgreSQL.
    As credenciais vêm de st.secrets, configuradas em:
    - Local: arquivo .streamlit/secrets.toml
    - Streamlit Cloud: aba "Secrets" nas configurações do app
    """
    conn = psycopg2.connect(
        dbname=st.secrets["db_name"],
        user=st.secrets["user"],
        password=st.secrets["pass"],
        host=st.secrets["host"],
        port=st.secrets["port"],
    )
    return conn


def query(sql, params=None):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
        return True

    except Exception as e:
        st.session_state["_db_error"] = str(e)
        return False


def fetch_one(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetch_all(sql, params=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()