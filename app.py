import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime

# Configuração Estilo SIDRA
st.set_page_config(page_title="Inteligência Territorial | DATASUS & MDS", page_icon="📊", layout="wide")

# CSS Estilo SIDRA
st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; font-weight: bold; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; margin-bottom: 10px; }
    .sidebar .sidebar-content { background-image: linear-gradient(#f8f9fa, #e9ecef); }
    </style>
""", unsafe_allow_html=True)

# --- CARREGAMENTO DE METADADOS ---

@st.cache_data
def get_municipios_base():
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    try:
        res = requests.get(url).json()
        df = pd.DataFrame([{
            "nome": m['nome'],
            "uf": m['microrregiao']['mesorregiao']['UF']['sigla'],
            "ibge7": str(m['id']),
            "datasus6": str(m['id'])[:6],
            "label": f"{m['nome']} - {m['microrregiao']['mesorregiao']['UF']['sigla']}"
        } for m in res])
        return df
    except:
        return pd.DataFrame([{"nome": "Belo Horizonte", "uf": "MG", "ibge7": "3106200", "datasus6": "310620", "label": "Belo Horizonte - MG"}])

# --- DICIONÁRIOS DE TRATAMENTO ---
DICIONARIOS = {
    "SIM": {
        "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "ESTCIV": {"1": "Solteiro", "2": "Casado", "3": "Viúvo", "4": "Separado", "5": "União Estável", "9": "Ignorado"},
        "LOCOCOR": {"1": "Hospital", "2": "Outro Estab.", "3": "Domicílio", "4": "Via Pública", "5": "Outros"},
        "CIRCOBITO": {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros"}
    },
    "SINASC": {
        "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "PARTO": {"1": "Vaginal", "2": "Cesáreo", "9": "Ignorado"},
        "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla+", "9": "Ignorado"}
    }
}

# --- FUNÇÕES DE BUSCA ---

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc
except ImportError:
    sim = sih = cnes = sinasc = None

def tratar_dados(df, sistema_key):
    if sistema_key in DICIONARIOS:
        dics = DICIONARIOS[sistema_key]
        for col, mapeamento in dics.items():
            if col in df.columns:
                df[f"{col}_DESC"] = df[col].astype(str).map(mapeamento).fillna("Não Informado")
    return df

@st.cache_data
def buscar_datasus_v8(sistema, uf, ano, mun_id, tipo_territorio):
    if not sim: return pd.DataFrame()
    try:
        if sistema == "SIM": res = sim(state=uf, year=ano)
        elif sistema == "SIH": res = sih(state=uf, year=ano, month=1)
        elif sistema == "SINASC": res = sinasc(state=uf, year=ano)
        else: res = cnes(state=uf, year=ano, month=1)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        
        if tipo_territorio == "Município":
            col_map = {"SIM": "CODMUNRES", "SIH": "MUNIC_RES", "SINASC": "CODMUNRES", "CNES": "CODUFMUN"}
            col = col_map.get(sistema)
            if col in df.columns:
                df = df[df[col].astype(str).str.startswith(str(mun_id)[:6])]
        return df
    except Exception as e:
        return pd.DataFrame({"Erro": [str(e)]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>Relatórios Oficiais de Saúde e Social</p></div>', unsafe_allow_html=True)

df_mun_base = get_municipios_base()

with st.sidebar:
    st.header("Configurações")
    fonte = st.radio("Fonte de Dados:", ["🏥 DATASUS", "🏠 VIS DATA 3"])
    
    st.divider()
    
    # Territorial
    territorio = st.selectbox("Nível Territorial:", ["Estado", "Município"])
    uf_sel = st.selectbox("UF:", sorted(df_mun_base['uf'].unique()), index=10) # MG default
    
    mun_sel_id = None
    if territorio == "Município":
        lista_mun_uf = df_mun_base[df_mun_base['uf'] == uf_sel]
        nome_mun = st.selectbox("Município:", lista_mun_uf['label'])
        mun_sel_id = lista_mun_uf[lista_mun_uf['label'] == nome_mun]['ibge7'].values[0]
        st.caption(f"Código IBGE: {mun_sel_id}")

    st.divider()
    
    if fonte == "🏥 DATASUS":
        sistema = st.selectbox("Base de Dados:", ["SIM", "SIH", "SINASC", "CNES"])
        ano = st.number_input("Ano:", 1996, 2026, 2022)
    
    st.divider()

# --- EXECUÇÃO ---

if fonte == "🏥 DATASUS":
    st.subheader(f"📊 Relatório {sistema} - {uf_sel} " + (f"({nome_mun})" if territorio == "Município" else ""))
    
    if st.button(f"Gerar Relatório {sistema}"):
        with st.spinner("Buscando dados..."):
            df_bruto = buscar_datasus_v8(sistema, uf_sel, ano, mun_sel_id, territorio)
            
            if not df_bruto.empty and "Erro" not in df_bruto.columns:
                df_tratado = tratar_dados(df_bruto.copy(), sistema)
                
                c1, c2 = st.columns(2)
                c1.markdown(f'<div class="metric-card"><h4>Registros Brutos</h4><h2>{len(df_bruto)}</h2></div>', unsafe_allow_html=True)
                
                st.tabs_dados = st.tabs(["📋 Dados Tratados", "📂 Dados Brutos"])
                
                with st.tabs_dados[0]:
                    st.dataframe(df_tratado.head(5000), width='stretch')
                    st.download_button("📥 Baixar Tratado (CSV)", df_tratado.to_csv(index=False), "tratado.csv")
                
                with st.tabs_dados[1]:
                    st.dataframe(df_bruto.head(5000), width='stretch')
                    st.download_button("📥 Baixar Bruto (CSV)", df_bruto.to_csv(index=False), "bruto.csv")
            else:
                st.error("Erro ou dados não disponíveis para este período/UF.")

else:
    st.subheader(f"🏠 Indicadores Sociais (VIS DATA 3) - {uf_sel}")
    if territorio == "Município":
        if st.button("Consultar MDS"):
            with st.spinner("Acessando SAGI/MDS..."):
                url = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={mun_sel_id}"
                try:
                    res = requests.get(url, timeout=15)
                    tabelas = pd.read_html(io.StringIO(res.text))
                    for i, t in enumerate(tabelas):
                        with st.expander(f"Tabela de Indicadores {i+1}"):
                            st.table(t)
                except:
                    st.error("Portal do MDS instável ou código não encontrado.")
    else:
        st.info("A consulta por Estado no VIS DATA 3 requer agregação manual ou acesso a painéis específicos. Utilize o nível 'Município' para dados detalhados.")

st.divider()
st.caption("Central de Inteligência Territorial | Desenvolvido conforme requisitos técnicos v8.")
