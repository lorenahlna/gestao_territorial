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
        if not res: return {"Belo Horizonte": {"id7": "3106200", "id6": "310620"}}
        return {m['nome']: {"id7": str(m['id']), "id6": str(m['id'])[:6]} for m in res}
    except:
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc, sinan
except ImportError:
    sim = sih = cnes = sinasc = sinan = None

# --- DICIONÁRIOS E TRADUÇÃO ---
DICIONARIOS = {
    "SIM": {
        "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"},
        "LOCOCOR": {"1": "Hospital", "2": "Outro Estab.", "3": "Domicílio", "4": "Via Pública", "5": "Outros"},
        "CIRCOBITO": {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros", "9": "Ignorado"}
    },
    "SINASC": {
        "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"},
        "PARTO": {"1": "Vaginal", "2": "Cesáreo", "9": "Ignorado"}
    },
    "SINAN": {
        "CS_SEXO": {"M": "Masculino", "F": "Feminino", "I": "Ignorado"},
        "CS_RACA": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"}
    }
}

def aplicar_dicionarios_v10(df, sistema_key):
    df_new = df.copy()
    # Identifica o sistema
    sigla = None
    for s in ["SIM", "SINASC", "SINAN"]:
        if s in sistema_key:
            sigla = s
            break
            
    if sigla and sigla in DICIONARIOS:
        for col, mapa in DICIONARIOS[sigla].items():
            if col in df_new.columns:
                df_new[f"{col}_DESC"] = df_new[col].astype(str).map(mapa).fillna("Não Informado")
    return df_new

# --- MOTOR DE BUSCA DATASUS ---

@st.cache_data
def buscar_datasus_v10(sistema, uf, ano, mun_id, nivel_terr, agravo=None):
    if not sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    try:
        res = None
        if "SIM" in sistema: res = sim(state=uf, year=ano)
        elif "SIH" in sistema: res = sih(state=uf, year=ano, month=1)
        elif "SINASC" in sistema: res = sinasc(state=uf, year=ano)
        elif "CNES" in sistema: res = cnes(state=uf, year=ano, month=1)
        elif "SINAN" in sistema: 
            # O PySUS exige o código do agravo (ex: DENG)
            if not agravo: return pd.DataFrame({"Erro": ["Selecione um agravo para o SINAN."]})
            res = sinan(disease=agravo, state=uf, year=ano)
        
        if res is None: return pd.DataFrame()
        
        # O PySUS pode retornar uma lista de arquivos ou um DataFrame
        df = pd.read_parquet(res[0]) if isinstance(res, list) and len(res) > 0 else res
        
        if isinstance(df, list) and len(df) == 0: return pd.DataFrame()
        if not isinstance(df, pd.DataFrame): return pd.DataFrame()

        # Filtro de Município
        if nivel_terr == "Município":
            col_map = {"SIM": "CODMUNRES", "SIH": "MUNIC_RES", "SINASC": "CODMUNRES", "CNES": "CODUFMUN", "SINAN": "ID_MN_RESI"}
            # Pega a sigla correta
            sigla_f = None
            for s in col_map.keys():
                if s in sistema: sigla_f = s; break
            
            col = col_map.get(sigla_f)
            if col and col in df.columns:
                df = df[df[col].astype(str).str.startswith(str(mun_id)[:6])]
        
        return df
    except Exception as e:
        return pd.DataFrame({"Erro": [f"Erro na conexão ou dados não disponíveis: {str(e)}"]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3 (v10)</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Configurações")
    fonte = st.radio("Fonte de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])
    nivel_terr = st.radio("Nível Territorial:", ["Estado", "Município"])
    
    # Seleção de UF Segura
    uf_lista_ordenada = sorted(UFS)
    try:
        idx_mg = uf_lista_ordenada.index("MG")
    except:
        idx_mg = 0
    uf_sel = st.selectbox("Selecione a UF:", uf_lista_ordenada, index=idx_mg)
    
    mun_id = ""
    nome_local = uf_sel
    if nivel_terr == "Município":
        muns = buscar_municipios_por_uf(uf_sel)
        nome_mun = st.selectbox("Selecione o Município:", sorted(muns.keys()))
        mun_id = muns[nome_mun]['id7']
        nome_local = nome_mun

    if fonte == "🏥 Saúde (DATASUS)":
        sistema = st.selectbox("Sistema de Saúde:", ["Mortalidade (SIM)", "Internações (SIH-SP)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)", "Notificações (SINAN)"])
        agravo = None
        if "SINAN" in sistema:
            mapa_doencas = {
                "Dengue": "DENG", "Sifilis Adquirida": "SIFA", "Tuberculose": "TUBE", 
                "Hanseníase": "HANS", "Leptospirose": "LEPT", "Meningite": "MENI",
                "Raiva Humana": "RAIV", "Zika Vírus": "ZIKA", "Chikungunya": "CHIK"
            }
            nome_agravo = st.selectbox("Agravo/Doença:", sorted(list(mapa_doencas.keys())))
            agravo = mapa_doencas[nome_agravo]
            
        ano = st.number_input("Ano de Referência:", 1996, 2026, 2022)

# --- EXECUÇÃO ---

if fonte == "🏥 Saúde (DATASUS)":
    if st.button("🔍 Gerar Relatório Territorial"):
        with st.spinner(f"Consultando base {sistema} para {nome_local}..."):
            df = buscar_datasus_v10(sistema, uf_sel, ano, mun_id, nivel_terr, agravo)
            
            if not df.empty and "Erro" not in df.columns:
                df_tratado = aplicar_dicionarios_v10(df, sistema)
                
                st.markdown(f'<div class="metric-card"><h2>{len(df)} Registros Encontrados</h2><p>{sistema} - {nome_local} ({ano})</p></div>', unsafe_allow_html=True)
                
                tab1, tab2 = st.tabs(["📋 Dados Tratados (v8)", "📂 Dados Brutos"])
                with tab1:
                    st.dataframe(df_tratado.head(1000), width='stretch')
                    st.download_button("📥 Baixar CSV Tratado", df_tratado.to_csv(index=False), f"tratado_{nome_local}.csv")
                with tab2:
                    st.dataframe(df.head(1000), width='stretch')
                    st.download_button("📥 Baixar CSV Bruto", df.to_csv(index=False), f"bruto_{nome_local}.csv")
            else:
                msg_erro = df["Erro"].iloc[0] if not df.empty else "Nenhum registro encontrado para esta seleção."
                st.error(msg_erro)
                st.info("Dica: Verifique se o ano e o estado selecionados já possuem dados consolidados no servidor do DATASUS.")

else:
    st.subheader(f"🏠 Indicadores Sociais (VIS DATA 3) - {nome_local}")
    if st.button("Consultar MDS"):
        # Usa código de 7 dígitos para município ou 2 dígitos para estado
        id_busca = mun_id if nivel_terr == "Município" else str(idx_mg + 1) # Simplificação para UF
        url = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={id_busca}"
        try:
            res = requests.get(url, timeout=15)
            tabelas = pd.read_html(io.StringIO(res.text))
            for i, t in enumerate(tabelas):
                with st.expander(f"Tabela de Indicadores {i+1}"):
                    st.table(t)
        except:
            st.error("Erro ao acessar o portal do MDS. O servidor pode estar instável.")

st.divider()
st.caption("Inteligência Territorial | Desenvolvido com PySUS e APIs Oficiais do Governo Federal.")
