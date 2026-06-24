# VERSAO_FINAL_PRODUCAO_V18_FINAL
import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import gc
import os
import threading
import duckdb
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURAÇÃO DE DESIGN DA PÁGINA ---
st.set_page_config(
    page_title="Inteligência Territorial | DATASUS",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; text-align: center; margin-bottom: 15px;}
    .footer-text { text-align: center; color: #666; font-size: 14px; margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; }
    </style>
""", unsafe_allow_html=True)

# --- BASES CONSIDERADAS PESADAS ---
BASES_PESADAS = ["Internações (SIH)", "Notificações (SINAN)", "Cadastro Nacional de Estabelecimentos (CNES)"]

# --- TRAVA DE CONCORRÊNCIA GLOBAL ---
@st.cache_resource
def obter_trava_global():
    return threading.Lock()

trava_global = obter_trava_global()

# --- FUNÇÕES BÁSICAS (ANOS E MESES) ---
@st.cache_data
def listar_anos_disponiveis(sistema="GERAL"):
    ano_atual = datetime.now().year
    limites = {
        "Mortalidade (SIM)": (1979, 2024),
        "Nascimentos (SINASC)": (1994, 2020),
        "Notificações (SINAN)": (2007, 2026),
        "Internações (SIH)": (2008, 2026),
        "Cadastro Nacional de Estabelecimentos (CNES)": (2005, ano_atual),
    }
    ano_inicial, ano_final = limites.get(sistema, (1995, ano_atual - 1))
    return list(range(ano_final, ano_inicial - 1, -1))

def obter_colunas_municipio(sistema, grupo=None):
    if "SIH" in sistema:
        if grupo == "RD": return ["MUNIC_RES", "MUNIC_MOV", "GESTOR_COD"]
        elif grupo == "SP": return ["SP_MUNRES", "SP_MUNMOV", "SP_GESTOR"]
        else: return ["MUNIC_RES", "MUNIC_MOV", "SP_MUNRES", "SP_MUNMOV", "SP_GESTOR"]
    if "SIM" in sistema: return ["CODMUNRES"]
    if "SINASC" in sistema: return ["CODMUNRES", "CODMUNNASC"]
    if "SINAN" in sistema: return ["ID_MN_RESI", "ID_MUNICIP"]
    if "CNES" in sistema: return ["CODUFMUN"]
    return []

MESES_NOMES = [
    "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
    "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
    "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"
]

# --- PUXANDO DICIONÁRIOS DO GITHUB ---
@st.cache_data(show_spinner=False)
def carregar_dicionarios_github():
    URL_RAW_GITHUB = "https://raw.githubusercontent.com/lorenahlna/gestao_territorial/refs/heads/main/dicionarios.json"
    try:
        res = requests.get(URL_RAW_GITHUB, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.warning(f"⚠️ Aviso: Usando dicionários de contingência.")
        return {
            "CBO_ESPECIFICOS": {"2251": "Médicos clínicos", "2235": "Enfermeiros"},
            "CBO_SUBGRUPOS": {"01": "Forças Armadas", "11": "Dirigentes", "22": "Profissionais de Saúde"},
            "DICIONARIOS_VALORES": {"SIM": {"SEXO": {"1": "Masculino", "2": "Feminino"}}},
            "TRADUCAO_CABECALHOS": {"SIM": {"CAUSABAS": "Causa Básica (CID-10)"}}
        }

CONFIG_APP = carregar_dicionarios_github()

@st.cache_data(show_spinner=False)
def carregar_tabelas_complementares():
    tabelas = {"CBO": {}, "CID10": {}, "SIGTAP": {}}
    if os.path.exists("tabela_cid10_codigo_descricao.csv"):
        try:
            df_cid = pd.read_csv("tabela_cid10_codigo_descricao.csv", sep=";", dtype=str, encoding='utf-8', on_bad_lines='skip')
            if {"codigo_datasus", "descricao"}.issubset(df_cid.columns):
                df_cid["codigo_datasus"] = df_cid["codigo_datasus"].str.strip().str.upper()
                df_cid["descricao"] = df_cid["descricao"].str.strip()
                tabelas["CID10"] = dict(zip(df_cid["codigo_datasus"], df_cid["descricao"]))
            else:
                tabelas["CID10"] = dict(zip(df_cid.iloc[:, 0].str.strip().str.upper(), df_cid.iloc[:, 1].str.strip()))
        except: pass
            
    BASE_RAW_URL = "https://raw.githubusercontent.com/cartaproale/PySUS/main/"
    try:
        df_cbo = pd.read_csv(BASE_RAW_URL + "tabelas/cbo.csv", sep=";", dtype=str, encoding='utf-8')
        tabelas["CBO"] = dict(zip(df_cbo.iloc[:, 0], df_cbo.iloc[:, 1]))
    except: pass
    try:
        df_sigtap = pd.read_csv(BASE_RAW_URL + "Referencias/tb_procedimento.csv", sep=";", dtype=str, encoding='utf-8')
        tabelas["SIGTAP"] = dict(zip(df_sigtap.iloc[:, 0], df_sigtap.iloc[:, 1]))
    except: pass
    return tabelas

TABELAS_EXTERNAS = carregar_tabelas_complementares()

# --- 🛠️ CORREÇÃO CRÍTICA DE IMPORTS PYSUS 🛠️ ---
try:
    # A estrutura correta na versão 2.3.0 para as funções high-level
    from pysus.api._impl.databases import sim as api_sim, sih as api_sih, cnes as api_cnes, sinasc as api_sinasc, sinan as api_sinan
except ImportError:
    try:
        # Fallback para versões onde a exposição na raiz da API pode variar
        import pysus.api._impl.databases as db_impl
        api_sim = db_impl.sim; api_sih = db_impl.sih; api_cnes = db_impl.cnes; api_sinasc = db_impl.sinasc; api_sinan = db_impl.sinan
    except:
        api_sim = api_sih = api_cnes = api_sinasc = api_sinan = None

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]
ESTADOS_IBGE = {"AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29", "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21", "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25", "PR": "41", "PE": "26", "PI": "22", "RJ": "33", "RN": "24", "RS": "43", "RO": "11", "RR": "14", "SC": "42", "SP": "35", "SE": "28", "TO": "17"}

@st.cache_data
def buscar_municipios_por_uf(uf_sigla):
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_sigla}/municipios"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10).json()
        return {m['nome']: {"id7": str(m['id']), "id6": str(m['id'])[:6], "nome": m['nome'], "uf": uf_sigla} for m in res}
    except:
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620", "nome": "Belo Horizonte", "uf": "MG"}}

# --- TRATADORES DE DADOS ---
def normalizar_codigo(valor):
    if pd.isna(valor): return ""
    return str(valor).strip().replace(".0", "")

def extrair_mes_datasus(serie):
    s = (serie.astype(str)
         .str.replace(r"\.0$", "", regex=True)
         .str.replace("-", "", regex=False)
         .str.replace("/", "", regex=False)
         .str.strip())
    mes_aaaammdd = pd.to_datetime(s, format="%Y%m%d", errors="coerce").dt.month
    mes_ddmmaaaa = pd.to_datetime(s, format="%d%m%Y", errors="coerce").dt.month
    mes = mes_aaaammdd.fillna(mes_ddmmaaaa)
    return mes.astype("Int64")

def aplicar_filtros_imediato(df_t, sistema, nivel_terr, uf, id_datasus_alvo, mes_num, cols_alvo, dt_alvos):
    try:
        df_t = df_t.copy()
        df_t.columns = [str(c).upper().strip() for c in df_t.columns]
        
        col_filtro_real = next((c for c in df_t.columns if c in [x.upper() for x in cols_alvo]), None)
        dt_col_real = next((c for c in df_t.columns if c in dt_alvos), None)
        
        if nivel_terr == "Município" and not col_filtro_real:
            return pd.DataFrame() 

        if "SINAN" in sistema and nivel_terr in ["Estado", "Município"] and col_filtro_real:
            codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
            df_t.loc[:, col_filtro_real] = df_t[col_filtro_real].apply(normalizar_codigo)
            df_t = df_t[df_t[col_filtro_real].str.startswith(codigo_uf_ibge)].copy()
        
        if nivel_terr == "Município" and col_filtro_real:
            df_t.loc[:, col_filtro_real] = df_t[col_filtro_real].apply(normalizar_codigo)
            df_t = df_t[df_t[col_filtro_real].str.startswith(id_datasus_alvo)].copy()
        
        if mes_num is not None and dt_col_real:
            meses_extraidos = extrair_mes_datasus(df_t[dt_col_real])
            df_t = df_t[meses_extraidos == mes_num].copy()
        
        if "SINAN" in sistema and not df_t.empty and len(df_t) > 50000:
            df_t = df_t.head(50000).copy()
            
        return df_t
    except Exception as e:
        print(f"[ERRO FILTRO IMEDIATO] {e}")
        return pd.DataFrame()

def processar_retorno_pysus_duckdb(res, cols_alvo, id_alvo, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado="Amostra limitada de microdados"):
    if cols_alvo is None: cols_alvo = []
    arquivos_lidos = 0
    try:
        # Se já for DataFrame (o api_sih as_dataframe=True retorna isso)
        if isinstance(res, pd.DataFrame):
            arquivos_lidos = 1
            return aplicar_filtros_imediato(res, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo, dt_alvos), arquivos_lidos
        
        # Se for lista de caminhos
        if isinstance(res, list) and len(res) > 0:
            frames = []
            for r in res:
                caminho = str(r.path) if hasattr(r, "path") else str(r)
                if not caminho.upper().endswith(".PARQUET"): continue
                
                arquivos_lidos += 1
                caminho_sql = caminho.replace("'", "''")
                try:
                    cols_parquet = duckdb.query(f"DESCRIBE SELECT * FROM read_parquet('{caminho_sql}')").df()["column_name"].tolist()
                    col_filtro = next((c for c in cols_parquet if c.upper() in [x.upper() for x in cols_alvo]), None)
                    
                    if not col_filtro:
                        col_filtro = next((c for c in cols_parquet if c.upper() in ["MUNIC_RES", "SP_MUNRES", "CODUFMUN", "ID_MN_RESI"]), None)

                    if id_alvo and col_filtro and nivel_terr == "Município":
                        query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{id_alvo}%'"
                        frames.append(duckdb.query(query).df())
                    elif nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                        if col_filtro:
                            codigo_uf = ESTADOS_IBGE.get(uf, "")
                            where_uf = f"WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{codigo_uf}%'" if codigo_uf else ""
                            query = f"SELECT \"{col_filtro}\" AS CODIGO_MUNICIPIO, COUNT(*) AS TOTAL_REGISTROS FROM read_parquet('{caminho_sql}') {where_uf} GROUP BY \"{col_filtro}\""
                            frames.append(duckdb.query(query).df())
                        else:
                            frames.append(duckdb.query(f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT 50000").df())
                    else:
                        limite = 50000 if sistema in BASES_PESADAS else 500000
                        frames.append(duckdb.query(f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT {limite}").df())
                except: continue
            
            if frames: return pd.concat(frames, ignore_index=True), arquivos_lidos
            
    except Exception as e:
        print(f"[ERRO DUCKDB] {e}")
    return pd.DataFrame(), arquivos_lidos

def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, sih_grupo=None, cnes_grupo=None, nivel_terr="Estado", id_datasus_alvo="", tipo_resultado=""):
    if not api_sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada ou falha crítica de importação."] })
    
    partes_final = [] 
    meses_para_baixar = [mes_num] if mes_num else [1,2,3,4,5,6,7,8,9,10,11,12]
    cols_alvo = obter_colunas_municipio(sistema, sih_grupo if "SIH" in sistema else cnes_grupo)
    dt_alvos = ["DTOBITO", "DTNASC", "DT_NOTIFIC", "DT_INTER"]
    id_filtro = id_datasus_alvo if nivel_terr == "Município" else ""
    falhas = []

    for uf in ufs_lista:
        for m in meses_para_baixar:
            df_temp = pd.DataFrame()
            arquivos_lidos = 0
            try:
                if "SIH" in sistema:
                    # Uso da API simplificada com as_dataframe=True para maior estabilidade
                    res = api_sih(state=uf, year=int(ano), month=int(m), group=sih_grupo, as_dataframe=True)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
                
                elif "CNES" in sistema:
                    res = api_cnes(state=uf, year=int(ano), month=int(m), group=cnes_grupo, as_dataframe=True)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
                
                elif "SIM" in sistema:
                    res = api_sim(state=uf, year=int(ano), as_dataframe=True)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
                    if not mes_num: break # SIM não é mensal na API high-level
                
                elif "SINASC" in sistema:
                    res = api_sinasc(state=uf, year=int(ano), as_dataframe=True)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
                    if not mes_num: break
                
                elif "SINAN" in sistema:
                    res = api_sinan(disease=agravo, year=int(ano), as_dataframe=True)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
                    if not mes_num: break

                if not df_temp.empty:
                    df_temp = aplicar_filtros_imediato(df_temp, sistema, nivel_terr, uf, id_datasus_alvo, m if "SIH" in sistema or "CNES" in sistema else mes_num, cols_alvo, dt_alvos)
                    if not df_temp.empty:
                        partes_final.append(df_temp)
                
            except Exception as e:
                falhas.append(f"{uf} {m}: {e}")
                continue
        gc.collect()

    if not partes_final:
        return pd.DataFrame({"Erro": ["Nenhum registro encontrado para os filtros selecionados ou falha de conexão com o DATASUS."] })
    
    return pd.concat(partes_final, ignore_index=True)

# --- TRADUÇÕES E INTERFACE (Mantidos da versão original) ---
def decodificar_idade_datasus(valor):
    v_str = normalizar_codigo(valor)
    if not v_str: return "Não informado"
    try:
        if len(v_str) in [1, 2]: return f"{v_str} Ano(s)"
        prefixo = v_str[0]
        num = int(v_str[1:])
        if prefixo == '4': return f"{num} Ano(s)"
        if prefixo == '3': return f"{num} Mês(es)"
        if prefixo == '2': return f"{num} Dia(s)"
        return f"{v_str}"
    except: return v_str

def tratar_e_traduzir_df(df, sistema):
    df_t = df.copy()
    df_t.columns = [str(c).upper().strip() for c in df_t.columns]
    sigla = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES" if "CNES" in sistema else "SINAN"
    
    # Aplica decodificações básicas
    if "IDADE" in df_t.columns: df_t["IDADE"] = df_t["IDADE"].apply(decodificar_idade_datasus)
    
    # Tradução de cabeçalhos
    cabecalhos = CONFIG_APP.get("TRADUCAO_CABECALHOS", {}).get(sigla, {})
    # Injeção de cabeçalhos padrão SIH se não existirem no config
    if sigla == "SIH":
        cabecalhos.update({"SEXO": "Sexo Paciente", "VAL_TOT": "Valor Total AIH (R$)", "DIAG_PRINC": "Diagnóstico Principal (CID-10)", "PROC_REA": "Procedimento Realizado (SIGTAP)"})
    
    return df_t.rename(columns=cabecalhos)

# --- UI STREAMLIT ---
st.title("📊 Inteligência Territorial | Extração DATASUS")
st.sidebar.title("🧬 Filtros")

fonte = st.sidebar.selectbox("Fonte:", ["🏥 Saúde (DATASUS)"])
nivel_terr = st.sidebar.radio("Nível Territorial:", ["Estado", "Município"])
uf_sel = st.sidebar.selectbox("Estado:", sorted(UFS), index=UFS.index("MG"))

id_datasus_alvo = ""
nome_local = uf_sel
if nivel_terr == "Município":
    muns = buscar_municipios_por_uf(uf_sel)
    mun_nome = st.sidebar.selectbox("Município:", sorted(muns.keys()))
    id_datasus_alvo = muns[mun_nome]['id6']
    nome_local = mun_nome

sistema = st.sidebar.selectbox("Sistema:", ["Internações (SIH)", "Mortalidade (SIM)", "Nascimentos (SINASC)", "Cadastro Nacional de Estabelecimentos (CNES)", "Notificações (SINAN)"])

sih_grupo_sel = cnes_grupo_sel = agravo_sel = None
if "SIH" in sistema:
    sih_grupo_sel = st.sidebar.selectbox("Grupo SIH:", ["RD", "SP", "ER"])
elif "CNES" in sistema:
    cnes_grupo_sel = st.sidebar.selectbox("Grupo CNES:", ["ST", "PF", "LT", "EQ"])
elif "SINAN" in sistema:
    agravo_sel = st.sidebar.text_input("Código do Agravo (ex: DENG):", "DENG").upper()

ano_sel = st.sidebar.selectbox("Ano:", listar_anos_disponiveis(sistema))
nome_mes = st.sidebar.selectbox("Mês:", ["Todos os Meses"] + MESES_NOMES)
mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])

if st.sidebar.button("🔍 Consultar"):
    with st.spinner("Extraindo dados..."):
        df_bruto = buscar_datasus_v7(sistema, [uf_sel], ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo)
        
        if not df_bruto.empty and "Erro" not in df_bruto.columns:
            df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
            st.success(f"{len(df_bruto)} registros encontrados!")
            st.dataframe(df_tratado.head(100))
            st.download_button("📥 Baixar CSV", df_tratado.to_csv(index=False, sep=';'), f"dados_{nome_local}.csv")
        else:
            st.error(df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Erro desconhecido.")
