import streamlit as st
import pandas as pd
import requests
import io
from datetime import datetime

# Configuração da página
st.set_page_config(
    page_title="Inteligência Territorial | SIDRA + DATASUS",
    page_icon="📊",
    layout="wide"
)

# CSS Estilo
st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; }
    </style>
""", unsafe_allow_html=True)

# --- FUNÇÕES DE METADADOS E TERRITÓRIO ---

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]

ESTADOS_IBGE = {
    "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29", "CE": "23", "DF": "53", "ES": "32",
    "GO": "52", "MA": "21", "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25", "PR": "41",
    "PE": "26", "PI": "22", "RJ": "33", "RN": "24", "RS": "43", "RO": "11", "RR": "14", "SC": "42",
    "SP": "35", "SE": "28", "TO": "17"
}

@st.cache_data
def buscar_municipios():
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    try:
        res = requests.get(url, timeout=10).json()
        mun_dict = {}
        for m in res:
            uf = m['microrregiao']['mesorregiao']['UF']['sigla']
            nome = m['nome']
            id7 = str(m['id'])
            id6 = id7[:6] # Padrão DATASUS
            mun_dict[f"{nome} - {uf}"] = {"id7": id7, "id6": id6, "uf": uf, "nome": nome}
        return mun_dict
    except:
        # Fallback de segurança com BH corrigida
        return {"Belo Horizonte - MG": {"id7": "3106200", "id6": "310620", "uf": "MG", "nome": "Belo Horizonte"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc
except ImportError:
    sim = sih = cnes = sinasc = None

@st.cache_data
def listar_anos_disponiveis():
    ano_atual = datetime.now().year
    return list(range(ano_atual, 1995, -1))

MESES = {
    "01 - Janeiro": 1, "02 - Fevereiro": 2, "03 - Março": 3, "04 - Abril": 4,
    "05 - Maio": 5, "06 - Junho": 6, "07 - Julho": 7, "08 - Agosto": 8,
    "09 - Setembro": 9, "10 - Outubro": 10, "11 - Novembro": 11, "12 - Dezembro": 12
}

# --- DICIONÁRIOS DE TRATAMENTO ---

DICIONARIOS = {
    "SIM": {
        "ACIDTRAB": {"1": "Sim", "2": "Não"},
        "CIRCOBITO": {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros"},
        "LOCOCOR": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio", "4": "Via pública"},
        "NECROPSIA": {"1": "Sim", "2": "Não"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "SEXO": {"1": "Masculino", "2": "Feminino"},
        "TIPOBITO": {"1": "Não fetal", "2": "Fetal"}
    },
    "SINASC": {
        "ESTCIVMAE": {"1": "Solteira", "2": "Casada", "3": "Viúva", "4": "Separada/Divorciada", "5": "União Consensual"},
        "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla ou mais"},
        "IDANOMAL": {"1": "Sim", "2": "Não", "9": "Ignorado"},
        "LOCNASC": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio"},
        "PARTO": {"1": "Vaginal/Normal", "2": "Cesáreo"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "SEXO": {"1": "Masculino", "2": "Feminino"}
    }
}

def aplicar_dicionarios(df, sistema):
    df_tratado = df.copy()
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES"
    
    dict_sistema = DICIONARIOS.get(sigla_sistema, {})
    
    # Aplica as traduções criando colunas novas com o sufixo _DESC
    for coluna, de_para in dict_sistema.items():
        if coluna in df_tratado.columns:
            # Mantém a original e cria a nova
            df_tratado[f"{coluna}_DESC"] = df_tratado[coluna].astype(str).map(de_para).fillna("Não informado/Ignorado")
            
    return df_tratado

# --- CONECTORES DE DADOS ---

@st.cache_data
def buscar_datasus_v7(sistema, ufs_lista, ano, mes=None):
    if not sim: return pd.DataFrame({"Erro": ["PySUS não instalado/disponível."]})
    
    df_final = pd.DataFrame()
    for uf in ufs_lista:
        try:
            if sistema == "Mortalidade (SIM)":
                res = sim(state=uf, year=ano)
            elif sistema == "Internações (SIH-SP)":
                res = sih(state=uf, year=ano, month=mes)
            elif sistema == "Nascimentos (SINASC)":
                res = sinasc(state=uf, year=ano)
            else: # CNES
                res = cnes(state=uf, year=ano, month=mes)
            
            # Alguns retornos do PySUS são listas de arquivos
            if isinstance(res, list) and len(res) > 0:
                df_uf = pd.read_parquet(res[0])
            elif not isinstance(res, list) and res is not None:
                df_uf = pd.read_parquet(res)
            else:
                continue
                
            df_final = pd.concat([df_final, df_uf], ignore_index=True)
            
        except Exception as e:
            continue
            
    if df_final.empty:
        return pd.DataFrame({"Erro": [f"Dados ainda não disponíveis para o período e região selecionados."]})
    return df_final

def baixar_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    return output.getvalue()

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3</p></div>', unsafe_allow_html=True)

# 1. Filtros Principais (Sidebar)
st.sidebar.title("Filtros de Pesquisa")

fonte = st.sidebar.radio("Base de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])
nivel_terr = st.sidebar.radio("Nível Territorial:", ["Brasil", "Estado", "Município"])

municipios_dict = buscar_municipios()

ufs_selecionadas = UFS
id_ibge_alvo = "1" # Código IBGE Brasil

if nivel_terr == "Estado":
    uf_sel = st.sidebar.selectbox("Selecione o Estado:", sorted(UFS))
    ufs_selecionadas = [uf_sel]
    id_ibge_alvo = ESTADOS_IBGE[uf_sel]
    nome_local = uf_sel
elif nivel_terr == "Município":
    uf_sel = st.sidebar.selectbox("Filtrar Estado:", sorted(UFS), index=UFS.index("MG"))
    muns_estado = {k: v for k, v in municipios_dict.items() if v['uf'] == uf_sel}
    
    mun_nome = st.sidebar.selectbox("Selecione o Município:", sorted(muns_estado.keys()))
    dados_mun = muns_estado[mun_nome]
    
    ufs_selecionadas = [uf_sel]
    id_ibge_alvo = dados_mun['id7']
    id_datasus_alvo = dados_mun['id6']
    nome_local = mun_nome
else:
    nome_local = "Brasil"


if fonte == "🏥 Saúde (DATASUS)":
    sistema = st.sidebar.selectbox("Sistema:", [
        "Mortalidade (SIM)", 
        "Internações (SIH-SP)", 
        "Nascimentos (SINASC)", 
        "Estabelecimentos (CNES)"
    ])
    
    ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis())
    
    mes_sel = None
    if sistema in ["Internações (SIH-SP)", "Estabelecimentos (CNES)"]:
        nome_mes = st.sidebar.selectbox("Mês de Competência:", list(MESES.keys()))
        mes_sel = MESES[nome_mes]
    
    if st.button(f"Consultar {sistema}"):
        if nivel_terr == "Brasil":
            st.warning("⚠️ Consultar o Brasil inteiro no DATASUS em tempo real pode demorar. Processando...")
            
        with st.spinner(f"Baixando base de {ano_sel}..."):
            df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel)
            
            if not df_bruto.empty and "Erro" not in df_bruto.columns:
                
                # Filtro Municipal se aplicável
                if nivel_terr == "Município":
                    col_map = {
                        "Mortalidade (SIM)": "CODMUNRES", 
                        "Internações (SIH-SP)": "SP_GESTOR", # No SIH-SP geralmente usamos o gestor ou hospital
                        "Nascimentos (SINASC)": "CODMUNRES", 
                        "Estabelecimentos (CNES)": "CODUFMUN"
                    }
                    coluna_filtro = col_map.get(sistema)
                    if coluna_filtro in df_bruto.columns:
                        df_bruto = df_bruto[df_bruto[coluna_filtro].astype(str).str.startswith(id_datasus_alvo)]
                
                df_tratado = aplicar_dicionarios(df_bruto, sistema)
                
                st.subheader(f"📊 {sistema} - {nome_local} ({ano_sel})")
                st.markdown(f'<div class="metric-card"><h4>Registros Encontrados</h4><h2>{len(df_bruto)}</h2></div>', unsafe_allow_html=True)
                
                tab1, tab2 = st.tabs(["📋 Dados Tratados (Recomendado)", "⚙️ Dados Brutos (Originais)"])
                
                with tab1:
                    st.dataframe(df_tratado, width='stretch', height=400)
                    col1, col2 = st.columns(2)
                    col1.download_button("📥 Baixar Tratado (CSV)", df_tratado.to_csv(index=False, sep=';', decimal=','), f"tratado_{sistema}.csv", "text/csv")
                    col2.download_button("📥 Baixar Tratado (Excel)", baixar_excel(df_tratado), f"tratado_{sistema}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                
                with tab2:
                    st.dataframe(df_bruto, width='stretch', height=400)
                    col3, col4 = st.columns(2)
                    col3.download_button("📥 Baixar Bruto (CSV)", df_bruto.to_csv(index=False, sep=';', decimal=','), f"bruto_{sistema}.csv", "text/csv")
                    col4.download_button("📥 Baixar Bruto (Excel)", baixar_excel(df_bruto), f"bruto_{sistema}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            else:
                msg = df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Dados não localizados para este período."
                st.error(msg)

else:
    # Lógica VIS DATA 3 (MDS)
    st.subheader(f"🏠 Indicadores Sociais - {nome_local}")
    st.info("A base do VIS DATA 3 extrai indicadores sociais diretos do Ministério do Desenvolvimento Social.")
    
    if st.button("Consultar MDS"):
        with st.spinner("Conectando ao VIS DATA 3..."):
            # A API do MDS recebe o código IBGE (2 dígitos estado, 7 dígitos município)
            url_mds = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={id_ibge_alvo}"
            
            try:
                res = requests.get(url_mds, timeout=20)
                tabelas = pd.read_html(io.StringIO(res.text))
                
                if len(tabelas) == 0:
                    st.warning("Nenhuma tabela encontrada nesta consulta.")
                else:
                    for i, t in enumerate(tabelas):
                        with st.expander(f"Tabela {i+1}", expanded=(i==0)):
                            st.dataframe(t)
                            
                            # Opção de baixar tabelas do MDS
                            st.download_button(
                                f"📥 Baixar Tabela {i+1} (CSV)", 
                                t.to_csv(index=False, sep=';'), 
                                f"mds_tab{i+1}_{id_ibge_alvo}.csv", 
                                key=f"mds_btn_{i}"
                            )
            except Exception as e:
                st.error("Falha ao conectar com o MDS. Verifique a disponibilidade do serviço federal.")

st.divider()
st.caption("Dados atualizados conforme disponibilidade nos servidores oficiais (FTP DATASUS / SAGI MDS). A ferramenta preserva os microdados originais e expande os metadados.")
