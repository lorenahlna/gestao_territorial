import streamlit as st
import pandas as pd
import requests
import io
import gc
from datetime import datetime

# Configuração Estilo SIDRA
st.set_page_config(page_title="Inteligência Territorial | DATASUS & MDS", page_icon="📊", layout="wide")

# CSS Estilo SIDRA
st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; margin-bottom: 10px; text-align: center; }
    </style>
""", unsafe_allow_html=True)

# --- METADADOS E TERRITÓRIO ---

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]

@st.cache_data
def buscar_municipios_por_uf(uf_sigla):
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_sigla}/municipios"
    try:
        res = requests.get(url, timeout=10).json()
        return {m['nome']: {"id7": str(m['id']), "id6": str(m['id'])[:6]} for m in res}
    except:
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc, sinan
except ImportError:
    sim = sih = cnes = sinasc = sinan = None

# --- DICIONÁRIOS E TRADUÇÃO (Requisitos v8) ---
DICIONARIOS = {
    "SIM": {"SEXO": {"1": "Masculino", "2": "Feminino"}, "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}},
    "SINASC": {"SEXO": {"1": "Masculino", "2": "Feminino"}, "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}},
    "SINAN": {"CS_SEXO": {"M": "Masculino", "F": "Feminino", "I": "Ignorado"}, "CS_RACA": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}}
}

def aplicar_dicionarios(df, sistema_key):
    df_new = df.copy()
    sigla = "SIM" if "SIM" in sistema_key else "SINASC" if "SINASC" in sistema_key else "SINAN" if "SINAN" in sistema_key else None
    if sigla and sigla in DICIONARIOS:
        for col, mapa in DICIONARIOS[sigla].items():
            if col in df_new.columns:
                df_new[f"{col}_DESC"] = df_new[col].astype(str).map(mapa).fillna("Não Informado")
    return df_new

# --- MOTOR DE BUSCA DATASUS ---

@st.cache_data
def buscar_datasus_v9(sistema, uf, ano, mun_id, nivel_terr, agravo=None):
    if not sim: return pd.DataFrame()
    try:
        # Chamada específica por sistema
        if "SIM" in sistema: res = sim(state=uf, year=ano)
        elif "SIH" in sistema: res = sih(state=uf, year=ano, month=1)
        elif "SINASC" in sistema: res = sinasc(state=uf, year=ano)
        elif "CNES" in sistema: res = cnes(state=uf, year=ano, month=1)
        elif "SINAN" in sistema: 
            # Correção SINAN: O PySUS exige o agravo em letras MAIÚSCULAS e sem acentos
            res = sinan(disease=agravo, state=uf, year=ano)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        
        if nivel_terr == "Município":
            col_map = {"SIM": "CODMUNRES", "SIH": "MUNIC_RES", "SINASC": "CODMUNRES", "CNES": "CODUFMUN", "SINAN": "ID_MN_RESI"}
            sigla = "SIM" if "SIM" in sistema else "SIH" if "SIH" in sistema else "SINASC" if "SINASC" in sistema else "CNES" if "CNES" in sistema else "SINAN"
            col = col_map.get(sigla)
            if col in df.columns:
                df = df[df[col].astype(str).str.startswith(str(mun_id)[:6])]
        
        return df
    except Exception as e:
        return pd.DataFrame({"Erro": [str(e)]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>Relatórios Oficiais v9</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Configurações")
    fonte = st.radio("Fonte:", ["🏥 DATASUS", "🏠 VIS DATA 3"])
    nivel_terr = st.radio("Território:", ["Estado", "Município"])
    uf_sel = st.selectbox("UF:", sorted(UFS), index=UFS.index("MG"))
    
    mun_id = ""
    nome_local = uf_sel
    if nivel_terr == "Município":
        muns = buscar_municipios_por_uf(uf_sel)
        nome_mun = st.selectbox("Município:", sorted(muns.keys()))
        mun_id = muns[nome_mun]['id7']
        nome_local = nome_mun

    if fonte == "🏥 DATASUS":
        sistema = st.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH-SP)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)", "Notificações (SINAN)"])
        agravo = None
        if "SINAN" in sistema:
            mapa_doencas = {"Dengue": "DENG", "Sifilis Adquirida": "SIFA", "Tuberculose": "TUBE", "Hanseníase": "HANS"}
            agravo = mapa_doencas[st.selectbox("Agravo:", list(mapa_doencas.keys()))]
        ano = st.number_input("Ano:", 1996, 2026, 2022)

if fonte == "🏥 DATASUS":
    if st.button("🔍 Gerar Relatório"):
        with st.spinner("Buscando dados..."):
            df = buscar_datasus_v9(sistema, uf_sel, ano, mun_id, nivel_terr, agravo)
            if not df.empty and "Erro" not in df.columns:
                df_tratado = aplicar_dicionarios(df, sistema)
                st.markdown(f'<div class="metric-card"><h2>{len(df)} Registros</h2><p>{sistema} - {nome_local} ({ano})</p></div>', unsafe_allow_html=True)
                t1, t2 = st.tabs(["Tratados", "Brutos"])
                with t1:
                    st.dataframe(df_tratado.head(1000))
                    st.download_button("Baixar Tratado", df_tratado.to_csv(index=False), "tratado.csv")
                with t2:
                    st.dataframe(df.head(1000))
                    st.download_button("Baixar Bruto", df.to_csv(index=False), "bruto.csv")
            else:
                st.error(df["Erro"].iloc[0] if not df.empty else "Nenhum dado encontrado.")

else:
    st.subheader(f"🏠 VIS DATA 3 - {nome_local}")
    if st.button("Consultar MDS"):
        url = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={mun_id if mun_id else '31'}"
        try:
            res = requests.get(url, timeout=15)
            tabelas = pd.read_html(io.StringIO(res.text))
            for i, t in enumerate(tabelas):
                with st.expander(f"Tabela {i+1}"):
                    st.table(t)
        except:
            st.error("Erro ao acessar MDS.")
