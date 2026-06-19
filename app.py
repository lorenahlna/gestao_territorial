import streamlit as st
import pandas as pd
import requests
import io
from bs4 import BeautifulSoup

# Configuração da página estilo SIDRA
st.set_page_config(
    page_title="Central de Inteligência Territorial | SIDRA + DATASUS",
    page_icon="📊",
    layout="wide"
)

# CSS Estilo SIDRA
st.markdown("""
    <style>
    .header-sidra {
        background-color: #003366;
        padding: 20px;
        color: white;
        border-radius: 5px;
        margin-bottom: 25px;
        text-align: center;
    }
    .stButton>button {
        background-color: #003366;
        color: white;
        font-weight: bold;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #003366;
    }
    </style>
""", unsafe_allow_html=True)

# --- DICIONÁRIOS DE TRATAMENTO (Inspirado no Hugo Fabrício) ---
DICIONARIOS = {
    "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
    "RACACOR": {"01": "Branca", "02": "Preta", "03": "Amarela", "04": "Parda", "05": "Indígena", "99": "Ignorado"},
    "ESC": {"1": "Nenhuma", "2": "1 a 3 anos", "3": "4 a 7 anos", "4": "8 a 11 anos", "5": "12 anos ou mais", "9": "Ignorado"}
}

# --- FUNÇÕES DE DADOS ---

@st.cache_data
def buscar_municipios():
    """Busca lista de municípios do IBGE para o seletor."""
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    try:
        res = requests.get(url).json()
        return {m['nome']: m['id'] for m in res}
    except:
        return {"Belo Horizonte": "310620"}

@st.cache_data
def buscar_mds_v3(municipio_id):
    """
    Nova tentativa de extração do MDS (SAGI RIv3).
    Se o endpoint direto falhar, usamos uma alternativa de dados abertos.
    """
    # Endpoint alternativo (Data3 Explorer)
    url = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={municipio_id}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            tables = pd.read_html(io.StringIO(response.text))
            return tables
        return None
    except:
        return None

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc
except ImportError:
    sim = sih = cnes = sinasc = None

@st.cache_data
def buscar_datasus_tratado(sistema, uf, ano, mun_id):
    if not sim: return pd.DataFrame()
    try:
        mun_id_6 = str(mun_id)[:6]
        if sistema == "Mortalidade (SIM)": res = sim(state=uf, year=ano)
        elif sistema == "Internações (SIH)": res = sih(state=uf, year=ano, month=1)
        elif sistema == "Nascimentos (SINASC)": res = sinasc(state=uf, year=ano)
        else: res = cnes(state=uf, year=ano, month=1)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        
        # Filtro
        col_map = {"Mortalidade (SIM)": "CODMUNRES", "Internações (SIH)": "MUNIC_RES", 
                   "Nascimentos (SINASC)": "CODMUNRES", "Estabelecimentos (CNES)": "CODUFMUN"}
        col = col_map.get(sistema)
        if col in df.columns:
            df = df[df[col].astype(str).str.startswith(mun_id_6)]
        
        # --- TRATAMENTO DOS DADOS ---
        for campo, de_para in DICIONARIOS.items():
            if campo in df.columns:
                df[campo] = df[campo].astype(str).map(de_para).fillna(df[campo])
        
        return df
    except Exception as e:
        return pd.DataFrame({"Erro": [str(e)]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3</p></div>', unsafe_allow_html=True)

# Busca de Município por Nome
municipios_dict = buscar_municipios()
nome_mun = st.selectbox("Selecione o Município:", sorted(municipios_dict.keys()), index=sorted(municipios_dict.keys()).index("Belo Horizonte") if "Belo Horizonte" in municipios_dict else 0)
id_mun = municipios_dict[nome_mun]
uf_sigla = nome_mun.split("-")[-1].strip() if "-" in nome_mun else "MG" # Simplificação

st.sidebar.title("Configurações de Busca")
fonte = st.sidebar.radio("Fonte de Dados:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])

if fonte == "🏥 Saúde (DATASUS)":
    sistema = st.sidebar.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)"])
    ano = st.sidebar.slider("Ano:", 2018, 2024, 2022)
    
    if st.button(f"Consultar {sistema}"):
        with st.spinner("Buscando e tratando dados..."):
            # Extraímos a UF do município selecionado (exemplo simplificado, ideal seria mapear)
            uf_target = "MG" # Default para teste, pode ser melhorado
            df = buscar_datasus_tratado(sistema, uf_target, ano, id_mun)
            
            if not df.empty and "Erro" not in df.columns:
                st.subheader(f"📊 Resultados: {nome_mun} ({ano})")
                
                # Resumo Executivo
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f'<div class="metric-card"><h4>Total de Ocorrências</h4><h2>{len(df)}</h2></div>', unsafe_allow_html=True)
                
                st.divider()
                st.write("### Tabela de Dados Tratados")
                st.dataframe(df, use_container_width=True)
                st.download_button("📥 Baixar Dados Tratados", df.to_csv(index=False), "dados_tratados.csv")
            else:
                st.error("Dados não encontrados para esta combinação de Ano/UF.")

else:
    st.subheader(f"🏠 Indicadores Sociais - {nome_mun}")
    if st.button("Consultar VIS DATA 3"):
        with st.spinner("Acessando base do MDS..."):
            tabelas = buscar_mds_v3(id_mun)
            if tabelas:
                st.success(f"Encontradas {len(tabelas)} tabelas de indicadores.")
                for i, tab in enumerate(tabelas):
                    with st.expander(f"Indicadores Grupo {i+1}"):
                        st.table(tab)
            else:
                st.error("O portal do MDS está instável ou o código IBGE não retornou dados.")
                st.info("Dica: O MDS utiliza o código de 7 dígitos. O sistema tentou buscar para o ID: " + str(id_mun))

st.divider()
st.caption("Dados oficiais processados via PySUS e APIs Governamentais.")
