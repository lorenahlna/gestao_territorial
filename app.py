import streamlit as st
import pandas as pd
import requests
import io
from bs4 import BeautifulSoup

# Configuração da página estilo SIDRA
st.set_page_config(
    page_title="SIDRA + DATASUS | Central de Indicadores",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS Estilo SIDRA (Cores: Azul Escuro #003366, Cinza Claro #F8F9FA)
st.markdown("""
    <style>
    /* Estilo geral */
    .main { background-color: #f8f9fa; }
    
    /* Cabeçalho estilo SIDRA */
    .header-sidra {
        background-color: #003366;
        padding: 20px;
        color: white;
        border-radius: 5px;
        margin-bottom: 25px;
        text-align: center;
    }
    
    /* Sidebar customizada */
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #dee2e6;
    }
    
    /* Botões */
    .stButton>button {
        width: 100%;
        background-color: #003366;
        color: white;
        border-radius: 4px;
        border: none;
        padding: 10px;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #002244;
        color: #ffcc00;
    }
    
    /* Tabelas */
    .stDataFrame {
        border: 1px solid #dee2e6;
        border-radius: 5px;
    }
    
    /* Títulos */
    h1, h2, h3 { color: #003366; font-family: 'Open Sans', sans-serif; }
    
    /* Cards de métricas */
    .metric-card {
        background-color: white;
        padding: 15px;
        border-radius: 8px;
        border-left: 5px solid #003366;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

# Tenta importar PySUS
try:
    from pysus.api._impl.databases import sim, sih, cnes
except ImportError:
    sim = sih = cnes = None

# --- FUNÇÕES DE DADOS ---

@st.cache_data
def buscar_cadunico_robusto(municipio_ibge):
    """
    Busca dados do CadÚnico via SAGI/MDS com tratamento de erro.
    """
    # O SAGI às vezes exige o código de 7 dígitos para relatórios detalhados
    # Se tiver 6, tentamos buscar o 7º dígito via IBGE se necessário
    url = f"https://aplicacoes.cidadania.gov.br/ri/pbfcad/relatorio.php?ibge={municipio_ibge}"
    
    try:
        response = requests.get(url, timeout=20)
        if response.status_code == 200:
            # Força o uso do parser lxml para melhor compatibilidade
            tables = pd.read_html(io.StringIO(response.text), flavor='bs4')
            return tables
        return None
    except Exception as e:
        return f"Erro de conexão: {e}"

@st.cache_data
def buscar_datasus_premium(sistema, uf, ano, mun_id):
    if not sim: return pd.DataFrame()
    try:
        # Lógica inspirada no Hugo Fabrício: tratamento de tipos e colunas
        if sistema == "Mortalidade (SIM)": res = sim(state=uf, year=ano)
        elif sistema == "Internações (SIH)": res = sih(state=uf, year=ano, month=1)
        else: res = cnes(state=uf, year=ano, month=1)
        
        df = pd.read_parquet(res[0]) if isinstance(res, list) else res
        
        # Mapeamento de colunas de município
        col_map = {"Mortalidade (SIM)": "CODMUNRES", "Internações (SIH)": "MUNIC_RES", "Estabelecimentos (CNES)": "CODUFMUN"}
        col = col_map.get(sistema)
        
        if col in df.columns:
            df = df[df[col].astype(str).str.startswith(mun_id)]
            
        return df
    except:
        return pd.DataFrame()

# --- INTERFACE ---

# Banner Superior
st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>Integração Oficial DATASUS & MDS (VIS DATA 3)</p></div>', unsafe_allow_html=True)

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/b/ba/Flag_of_Brazil.svg/200px-Flag_of_Brazil.svg.png", width=100)
    st.title("Configurações")
    
    fonte = st.selectbox("Fonte de Dados:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])
    
    st.divider()
    
    # Filtros Comuns
    uf = st.selectbox("Estado (UF):", ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"], index=10)
    mun_id = st.text_input("Código IBGE (6 ou 7 dígitos):", value="310620")
    
    if fonte == "🏥 Saúde (DATASUS)":
        sistema = st.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Estabelecimentos (CNES)"])
        ano = st.slider("Ano de Referência:", 2018, 2024, 2022)
    
    st.divider()
    st.info("O código IBGE de 6 dígitos é o padrão para a maioria das buscas.")

# Conteúdo Principal
if fonte == "🏥 Saúde (DATASUS)":
    st.subheader(f"📊 {sistema} - {uf} ({ano})")
    
    if st.button("GERAR RELATÓRIO DE SAÚDE"):
        with st.spinner("Acessando servidores do DATASUS..."):
            df = buscar_datasus_premium(sistema, uf, ano, mun_id)
            if not df.empty:
                # Métricas de resumo estilo Dashboard
                c1, c2, c3 = st.columns(3)
                c1.metric("Total de Registros", len(df))
                c2.metric("Município Base", mun_id)
                c3.metric("Ano", ano)
                
                st.dataframe(df, use_container_width=True)
                st.download_button("📥 Exportar Dados (CSV)", df.to_csv(index=False), f"datasus_{mun_id}.csv")
            else:
                st.error("Nenhum dado encontrado. Verifique se o ano/estado está disponível no FTP do DATASUS.")

else:
    st.subheader(f"🏠 Indicadores Sociais - Município {mun_id}")
    st.warning("Os dados do VIS DATA 3 são extraídos em tempo real do portal SAGI/MDS.")
    
    if st.button("GERAR RELATÓRIO SOCIAL"):
        with st.spinner("Conectando ao VIS DATA 3..."):
            tabelas = buscar_cadunico_robusto(mun_id)
            
            if isinstance(tabelas, list) and len(tabelas) > 0:
                st.success(f"Foram encontradas {len(tabelas)} tabelas de indicadores.")
                
                # Exibição em abas internas para não poluir o visual
                tabs_internas = st.tabs([f"Tabela {i+1}" for i in range(len(tabelas))])
                for i, tab in enumerate(tabs_internas):
                    with tab:
                        st.table(tabelas[i])
            else:
                st.error("Não foi possível extrair os dados sociais.")
                st.markdown(f"""
                **Possíveis causas:**
                1. O código IBGE `{mun_id}` pode estar incorreto para esta base.
                2. O servidor do MDS está temporariamente fora do ar.
                3. Tente usar o código de 7 dígitos (adicione o dígito verificador).
                """)

# Rodapé
st.divider()
st.caption("Desenvolvido com base nas referências: Hugo Fabrício (GitHub) e Sistema SIDRA (IBGE).")
