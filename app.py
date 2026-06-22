import streamlit as st
import pandas as pd
import requests
import io
import gc
from datetime import datetime

# Configuração Estilo SIDRA
st.set_page_config(page_title="Gestão Territorial | Auditoria SUS & MDS", page_icon="📊", layout="wide")

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

# --- DICIONÁRIOS DE TRATAMENTO EXAUSTIVO ---

def decodificar_idade(valor):
    try:
        v = str(int(float(valor))).zfill(3)
        u, q = v[0], int(v[1:])
        if u == '1': return f"{q} Minutos"
        if u == '2': return f"{q} Horas"
        if u == '3': return f"{q} Meses"
        if u == '4': return f"{q} Anos"
        if u == '5': return f"{100+q} Anos"
        return f"{q} Anos"
    except: return "N/I"

DICIONARIOS = {
    "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado", "M": "Masculino", "F": "Feminino", "I": "Ignorado"},
    "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"},
    "ESTCIV": {"1": "Solteiro", "2": "Casado", "3": "Viúvo", "4": "Separado", "5": "União Estável", "9": "Ignorado"},
    "ESC": {"1": "Nenhuma", "2": "1 a 3 anos", "3": "4 a 7 anos", "4": "8 a 11 anos", "5": "12 anos+", "9": "Ignorado"},
    "LOCOCOR": {"1": "Hospital", "2": "Outro Estab.", "3": "Domicílio", "4": "Via Pública", "5": "Outros"},
    "PARTO": {"1": "Vaginal", "2": "Cesáreo", "9": "Ignorado"},
    "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla+", "9": "Ignorado"}
}

def aplicar_tratamento_final(df, sistema):
    df_new = df.copy()
    # 1. Idade
    for c in ["IDADE", "IDADEMAE", "NU_IDADE_N"]:
        if c in df_new.columns: df_new[f"{c}_TRATADA"] = df_new[c].apply(decodificar_idade)
    # 2. Dicionários
    for col_key, mapa in DICIONARIOS.items():
        for df_col in df_new.columns:
            if col_key in df_col:
                df_new[f"{df_col}_DESC"] = df_new[df_col].astype(str).map(mapa).fillna("Não Informado")
    return df_new

# --- MOTOR DE BUSCA COM FILTRO DE MEMÓRIA ---

@st.cache_data
def buscar_datasus_v12(sistema, uf, ano, mun_id, nivel_terr, agravo=None):
    if not sim: return pd.DataFrame({"Erro": ["PySUS não instalado"]})
    try:
        df_acumulado = pd.DataFrame()
        col_filtro = {"SIM": "CODMUNRES", "SIH": "MUNIC_RES", "SINASC": "CODMUNRES", "CNES": "CODUFMUN", "SINAN": "ID_MN_RESI"}
        sigla = "SIM" if "SIM" in sistema else "SIH" if "SIH" in sistema else "SINASC" if "SINASC" in sistema else "CNES" if "CNES" in sistema else "SINAN"
        target_col = col_filtro.get(sigla)
        
        # Coleta de arquivos (CNES e SIH por meses para evitar estouro)
        arquivos = []
        if "CNES" in sistema or "SIH" in sistema:
            for m in range(1, 13):
                try:
                    res = cnes(state=uf, year=ano, month=m) if "CNES" in sistema else sih(state=uf, year=ano, month=m)
                    if isinstance(res, list): arquivos.extend(res)
                    else: arquivos.append(res)
                except: continue
        else:
            if "SIM" in sistema: res = sim(state=uf, year=ano)
            elif "SINASC" in sistema: res = sinasc(state=uf, year=ano)
            elif "SINAN" in sistema: res = sinan(disease=agravo, state=uf, year=ano)
            arquivos = res if isinstance(res, list) else [res]

        # Processamento um a um com filtro imediato (SALVA A MEMÓRIA RAM)
        for arq in arquivos:
            try:
                df_temp = pd.read_parquet(arq)
                if nivel_terr == "Município" and target_col in df_temp.columns:
                    df_temp = df_temp[df_temp[target_col].astype(str).str.startswith(str(mun_id)[:6])]
                df_acumulado = pd.concat([df_acumulado, df_temp], ignore_index=True)
                del df_temp
                gc.collect()
            except: continue
            
        return df_acumulado
    except Exception as e:
        return pd.DataFrame({"Erro": [str(e)]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Gestão Territorial v12</h1><p>Auditoria Profissional de Dados Públicos</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Filtros")
    fonte = st.radio("Fonte:", ["🏥 DATASUS", "🏠 VIS DATA 3"])
    nivel_terr = st.radio("Território:", ["Estado", "Município"])
    uf_sel = st.selectbox("UF:", sorted(UFS), index=sorted(UFS).index("MG"))
    
    mun_id = ""
    nome_local = uf_sel
    if nivel_terr == "Município":
        muns = buscar_municipios_por_uf(uf_sel)
        nome_mun = st.selectbox("Município:", sorted(muns.keys()))
        mun_id = muns[nome_mun]['id7']
        nome_local = nome_mun

    if fonte == "🏥 DATASUS":
        sistema = st.selectbox("Base:", ["Mortalidade (SIM)", "Internações (SIH-SP)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)", "Notificações (SINAN)"])
        agravo = None
        if "SINAN" in sistema:
            mapa_doencas = {"Dengue": "DENG", "Sifilis": "SIFA", "Tuberculose": "TUBE", "Hanseníase": "HANS", "Chikungunya": "CHIK"}
            agravo = mapa_doencas[st.selectbox("Agravo:", sorted(list(mapa_doencas.keys())))]
        ano = st.number_input("Ano:", 1996, 2026, 2022)

if fonte == "🏥 DATASUS":
    if st.button("🚀 Gerar Auditoria"):
        with st.spinner("Filtrando e tratando dados em tempo real..."):
            df = buscar_datasus_v12(sistema, uf_sel, ano, mun_id, nivel_terr, agravo)
            if not df.empty and "Erro" not in df.columns:
                df_tratado = aplicar_tratamento_final(df, sistema)
                st.markdown(f'<div class="metric-card"><h2>{len(df)} Registros Encontrados</h2><p>{nome_local} ({ano})</p></div>', unsafe_allow_html=True)
                t1, t2 = st.tabs(["📋 Dados Tratados", "📂 Dados Brutos"])
                with t1:
                    st.dataframe(df_tratado.head(3000))
                    st.download_button("Baixar Tratado", df_tratado.to_csv(index=False), "tratado.csv")
                with t2:
                    st.dataframe(df.head(3000))
                    st.download_button("Baixar Bruto", df.to_csv(index=False), "bruto.csv")
            else:
                st.error("Nenhum registro encontrado para esta seleção.")
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
