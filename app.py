import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import io

# Tenta importar o PySUS
try:
    from pysus.api._impl.databases import sim, sih, cnes
except ImportError:
    sim = sih = cnes = None

st.set_page_config(page_title="DataSUS + VIS DATA 3", layout="wide")

# --- FUNÇÕES DE BUSCA ---

@st.cache_data
def buscar_cadunico_sagi(municipio_ibge):
    """
    Busca dados de cobertura do Cadastro Único via SAGI/RI.
    """
    # URL do relatório de informações do município
    url = f"https://aplicacoes.cidadania.gov.br/ri/pbfcad/relatorio.php?ibge={municipio_ibge}"
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            # O SAGI retorna tabelas HTML formatadas
            tables = pd.read_html(io.StringIO(response.text))
            return tables
        return []
    except:
        return []

@st.cache_data
def buscar_datasus(sistema, uf, ano, mun_id):
    if not sim: return pd.DataFrame()
    try:
        if sistema == "SIM": res = sim(state=uf, year=ano)
        elif sistema == "SIH": res = sih(state=uf, year=ano, month=1)
        else: res = cnes(state=uf, year=ano, month=1)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        col = "CODMUNRES" if sistema == "SIM" else ("MUNIC_RES" if sistema == "SIH" else "CODUFMUN")
        return df[df[col].astype(str).str.startswith(mun_id)]
    except:
        return pd.DataFrame()

# --- INTERFACE ---

st.title("📊 Central de Dados Sociais e Saúde")

aba = st.tabs(["🏥 DATASUS", "🏠 VIS DATA 3 (CadÚnico)"])

with aba[0]:
    st.header("Dados de Saúde (DATASUS)")
    col1, col2, col3 = st.columns(3)
    sis = col1.selectbox("Sistema", ["SIM", "SIH", "CNES"])
    uf = col2.selectbox("UF", ["MG", "SP", "RJ", "BA", "PR"]) # Simplificado
    ano = col3.number_input("Ano", 2020, 2024, 2022)
    mun = st.text_input("IBGE (6 dígitos)", "310620", key="mun_health")
    
    if st.button("Buscar Saúde"):
        df_h = buscar_datasus(sis, uf, ano, mun)
        st.dataframe(df_h)

with aba[1]:
    st.header("Dados Sociais (VIS DATA 3 / SAGI)")
    st.info("Esta busca acessa o Relatório de Informações do MDS para o município selecionado.")
    mun_soc = st.text_input("IBGE (6 dígitos)", "310620", key="mun_soc")
    
    if st.button("Buscar Dados Sociais"):
        with st.spinner("Acessando base do MDS..."):
            tabelas = buscar_cadunico_sagi(mun_soc)
            if tabelas:
                for i, t in enumerate(tabelas):
                    with st.expander(f"Tabela de Indicadores {i+1}"):
                        st.table(t)
            else:
                st.error("Não foi possível encontrar dados para este município no VIS DATA 3.")
                st.markdown("""
                **Dica:** Verifique se o código IBGE está correto. 
                Alguns dados do MDS exigem que o código tenha os 7 dígitos ou apenas os 6 iniciais.
                """)
