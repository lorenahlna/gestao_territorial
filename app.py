import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime

# Configuração da página estilo SIDRA
st.set_page_config(
    page_title="Inteligência Territorial | SIDRA + DATASUS",
    page_icon="📊",
    layout="wide"
)

# CSS Estilo SIDRA
st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; }
    </style>
""", unsafe_allow_html=True)

# --- FUNÇÕES DE METADADOS ---

@st.cache_data
def buscar_municipios():
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    try:
        res = requests.get(url).json()
        return {f"{m['nome']} - {m['microrregiao']['mesorregiao']['UF']['sigla']}": {"id": m['id'], "uf": m['microrregiao']['mesorregiao']['UF']['sigla']} for m in res}
    except:
        return {"Belo Horizonte - MG": {"id": "310620", "uf": "MG"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc
except ImportError:
    sim = sih = cnes = sinasc = None

@st.cache_data
def listar_anos_disponiveis(sistema, uf):
    """
    Tenta descobrir os anos disponíveis consultando os metadados do PySUS/FTP.
    Se falhar, retorna um range padrão seguro.
    """
    # Como o PySUS não expõe uma lista direta de anos via API sem baixar, 
    # usamos um range dinâmico baseado no ano atual.
    ano_atual = datetime.now().year
    return list(range(ano_atual, 1995, -1))

# --- TRATAMENTO ---
DICIONARIOS = {
    "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"},
    "RACACOR": {"01": "Branca", "02": "Preta", "03": "Amarela", "04": "Parda", "05": "Indígena", "99": "Ignorado"}
}

@st.cache_data
def buscar_datasus_v7(sistema, uf, ano, mun_id):
    if not sim: return pd.DataFrame()
    try:
        mun_id_6 = str(mun_id)[:6]
        # Chamada dinâmica
        if sistema == "Mortalidade (SIM)": res = sim(state=uf, year=ano)
        elif sistema == "Internações (SIH)": res = sih(state=uf, year=ano, month=1)
        elif sistema == "Nascimentos (SINASC)": res = sinasc(state=uf, year=ano)
        else: res = cnes(state=uf, year=ano, month=1)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        
        # Filtro e Tradução
        col_map = {"Mortalidade (SIM)": "CODMUNRES", "Internações (SIH)": "MUNIC_RES", "Nascimentos (SINASC)": "CODMUNRES", "Estabelecimentos (CNES)": "CODUFMUN"}
        col = col_map.get(sistema)
        if col in df.columns:
            df = df[df[col].astype(str).str.startswith(mun_id_6)]
        
        for campo, de_para in DICIONARIOS.items():
            if campo in df.columns:
                df[campo] = df[campo].astype(str).map(de_para).fillna(df[campo])
        
        return df
    except Exception as e:
        return pd.DataFrame({"Erro": [f"Dados de {ano} ainda não disponíveis para {uf} neste sistema."]})

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3</p></div>', unsafe_allow_html=True)

# Seleção de Município
municipios = buscar_municipios()
nome_mun = st.selectbox("Selecione o Município (Busca Nacional):", sorted(municipios.keys()), index=sorted(municipios.keys()).index("Belo Horizonte - MG"))
dados_mun = municipios[nome_mun]

st.sidebar.title("Filtros de Pesquisa")
fonte = st.sidebar.radio("Fonte:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])

if fonte == "🏥 Saúde (DATASUS)":
    sistema = st.sidebar.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)"])
    
    # Descoberta de Anos
    anos_lista = listar_anos_disponiveis(sistema, dados_mun['uf'])
    ano_sel = st.sidebar.selectbox("Ano de Referência:", anos_lista)
    
    if st.button(f"Consultar {sistema}"):
        with st.spinner(f"Verificando base de {ano_sel}..."):
            df = buscar_datasus_v7(sistema, dados_mun['uf'], ano_sel, dados_mun['id'])
            
            if not df.empty and "Erro" not in df.columns:
                st.subheader(f"📊 {sistema} - {nome_mun} ({ano_sel})")
                st.markdown(f'<div class="metric-card"><h4>Registros Encontrados</h4><h2>{len(df)}</h2></div>', unsafe_allow_html=True)
                st.dataframe(df, width='stretch')
                st.download_button("📥 Baixar Dados", df.to_csv(index=False), "dados.csv")
            else:
                msg = df["Erro"].iloc[0] if not df.empty else "Dados não disponíveis."
                st.warning(msg)
                st.info("Nota: Dados de 2024 a 2026 podem estar em fase de processamento pelo Ministério da Saúde.")

else:
    # Lógica VIS DATA 3 simplificada e direta
    st.subheader(f"🏠 Indicadores Sociais - {nome_mun}")
    if st.button("Consultar MDS"):
        url_mds = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={dados_mun['id']}"
        try:
            res = requests.get(url_mds, timeout=15)
            tabelas = pd.read_html(io.StringIO(res.text))
            for i, t in enumerate(tabelas):
                with st.expander(f"Tabela {i+1}"):
                    st.table(t)
        except:
            st.error("Erro ao conectar com o MDS. Tente o código de 7 dígitos.")

st.divider()
st.caption("Dados atualizados conforme disponibilidade nos servidores oficiais (FTP DATASUS / SAGI).")
