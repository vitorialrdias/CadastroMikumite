import streamlit as st
import psycopg2

@st.cache_resource
def get_connection():
    """Cria a conexão inicial."""
    return psycopg2.connect(
        dbname=st.secrets["db_name"],
        user=st.secrets["user"],
        password=st.secrets["pass"],
        host=st.secrets["host"],
        port=st.secrets["port"],
    )

def ensure_connection():
    """Verifica se a conexão está viva, se não, reconecta."""
    conn = get_connection()
    try:
        # Tenta realizar um ping no banco para ver se a conexão ainda responde
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        # Se falhar, forçamos o cache a ser limpo e criamos uma nova
        get_connection.clear()
        conn = get_connection()
    return conn

def query(sql, params=None):
    try:
        conn = ensure_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Erro no banco: {e}")
        return False

def fetch_one(sql, params=None):
    conn = ensure_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()

def fetch_all(sql, params=None):
    conn = ensure_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()