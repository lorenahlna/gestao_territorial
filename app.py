# VERSAO_FINAL_SIH_POLIMORFICO_HOMOLOGADA_V12
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

try:
    from pysus.api._impl.databases import sim as api_sim, sih as api_sih, cnes as api_cnes, sinasc as api_sinasc, sinan as api_sinan
except ImportError:
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

def decodificar_idade_datasus(valor):
    v_str = normalizar_codigo(valor)
    if not v_str: return "Não informado"
    try:
        if len(v_str) in [1, 2]: return f"{v_str} Ano(s)"
        if len(v_str) >= 3:
            u, q = v_str[0], int(v_str[1:])
            if u == '1': return f"{q} Minuto(s)"
            elif u == '2': return f"{q} Hora(s)"
            elif u == '3': return f"{q} Mês(es)"
            elif u == '4': return f"{q} Ano(s)"
            elif u == '5': return f"{100 + q} Ano(s)"
            else: return f"{q} (Idade ñ ident.)"
    except: return str(valor)

def agrupar_idade_mae(idade_str):
    if "Ano(s)" not in str(idade_str): return "Ignorado"
    try:
        idade = int(idade_str.replace(" Ano(s)", ""))
        if idade < 15: return "< 15 anos"
        elif 15 <= idade <= 19: return "15 a 19 anos"
        elif 20 <= idade <= 29: return "20 a 29 anos"
        elif 30 <= idade <= 39: return "30 a 39 anos"
        else: return "40 anos ou mais"
    except: return "Ignorado"

def decodificar_cbo(codigo):
    cod_str = normalizar_codigo(codigo).zfill(6)
    if cod_str in ['', '000000', '999999']: return "Não informado"
    dict_cbo = TABELAS_EXTERNAS.get("CBO", {})
    if dict_cbo and cod_str in dict_cbo: return f"{cod_str} - {dict_cbo[cod_str]}"
    if dict_cbo and cod_str[:4] in dict_cbo: return f"{cod_str} - {dict_cbo[cod_str[:4]]}"
    cbo_esp = CONFIG_APP.get("CBO_ESPECIFICOS", {})
    if cod_str[:4] in cbo_esp: return f"{cod_str} - {cbo_esp[cod_str[:4]]}"
    return f"{cod_str} - {CONFIG_APP.get('CBO_SUBGRUPOS', {}).get(cod_str[:2], 'Outros')}"

def decodificar_cid(codigo, dict_cid):
    cod_str = normalizar_codigo(codigo).upper()
    if not cod_str: return "Não informado"
    if dict_cid:
        if cod_str in dict_cid: return f"{cod_str} - {dict_cid[cod_str]}"
        if cod_str[:3] in dict_cid: return f"{cod_str} - {dict_cid[cod_str[:3]]}"
    return cod_str

def decodificar_sigtap(codigo, dict_sigtap):
    cod = normalizar_codigo(codigo).zfill(10)
    if not cod or cod == '0000000000': return "Não informado"
    if dict_sigtap and cod in dict_sigtap: return f"{cod} - {dict_sigtap[cod]}"
    return cod

def aplicar_filtros_imediato(df_t, sistema, nivel_terr, uf, id_datasus_alvo, mes_num, cols_alvo, dt_alvos):
    try:
        df_t = df_t.copy()
        df_t.columns = [str(c).upper().strip() for c in df_t.columns]
        
        col_filtro_real = next((c for c in df_t.columns if c in [x.upper() for x in cols_alvo]), None)
        dt_col_real = next((c for c in df_t.columns if c in dt_alvos), None)
        
        if nivel_terr == "Município" and not col_filtro_real:
            print(f"[ALERTA CRÍTICO] Coluna municipal esperada {cols_alvo} NÃO ENCONTRADA no arquivo: {list(df_t.columns)}")
            return pd.DataFrame() 

        if "SINAN" in sistema and nivel_terr in ["Estado", "Município"] and col_filtro_real:
            codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
            df_t.loc[:, col_filtro_real] = df_t[col_filtro_real].apply(normalizar_codigo)
            df_t = df_t[df_t[col_filtro_real].str.startswith(codigo_uf_ibge)].copy()
        
        if nivel_terr == "Município" and col_filtro_real:
            df_t.loc[:, col_filtro_real] = df_t[col_filtro_real].apply(normalizar_codigo)
            df_t = df_t[df_t[col_filtro_real].str.startswith(id_datasus_alvo)].copy()
        
        if sistema not in ["Internações (SIH)", "Cadastro Nacional de Estabelecimentos (CNES)"]:
            if mes_num is not None and dt_col_real:
                meses_extraidos = extrair_mes_datasus(df_t[dt_col_real])
                df_t = df_t[meses_extraidos == mes_num].copy()
        
        if "SINAN" in sistema and not df_t.empty and len(df_t) > 50000:
            df_t = df_t.head(50000).copy()
            
        return df_t
    except Exception as e:
        print(f"[ERRO FILTRO IMEDIATO] {e}")
        return pd.DataFrame()

def leitura_segura_parquet(caminho, limite=50000):
    try:
        caminho_sql = str(caminho).replace("'", "''")
        query = f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT {limite}"
        return duckdb.query(query).df()
    except Exception as e:
        print(f"[ERRO LEITURA SEGURA] {repr(e)}")
        return pd.DataFrame()

def normalizar_lista_arquivos_pysus(res):
    if res is None: return []
    if isinstance(res, pd.DataFrame): return res
    if isinstance(res, str): return [res]
    if isinstance(res, list):
        caminhos = []
        for item in res:
            if isinstance(item, str): caminhos.append(item)
            elif hasattr(item, "__fspath__"): caminhos.append(os.fspath(item))
            elif hasattr(item, "path"): caminhos.append(str(item.path))
            else: caminhos.append(str(item))
        return caminhos
    if hasattr(res, "__fspath__"): return [os.fspath(res)]
    if hasattr(res, "path"): return [str(res.path)]
    return [str(res)]

def filtrar_arquivos_sih_exatos(arquivos, uf, ano, mes, grupo):
    if isinstance(arquivos, pd.DataFrame): return arquivos
    ano2 = str(ano)[-2:]
    mes2 = f"{int(mes):02d}" if mes is not None else ""
    prefixo_exato = f"{grupo}{uf}{ano2}{mes2}".upper()
    
    selecionados = []
    for caminho in arquivos:
        nome = os.path.basename(str(caminho)).upper()
        if nome.startswith(prefixo_exato): 
            selecionados.append(caminho)
        elif grupo.upper() in nome and uf.upper() in nome and ano2 in nome:
            selecionados.append(caminho)
            
    if not selecionados and arquivos:
        return arquivos
    return selecionados

# --- MOTOR SEMÂNTICO E CONSULTAS DUCKDB ---
def processar_retorno_pysus_duckdb(res, cols_alvo, id_alvo, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado="Amostra limitada de microdados", prefixo_esperado=None):
    if cols_alvo is None: cols_alvo = []
    arquivos_lidos = 0
    try:
        if isinstance(res, pd.DataFrame):
            arquivos_lidos = 1
            return aplicar_filtros_imediato(res, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo, dt_alvos), arquivos_lidos
        if hasattr(res, "to_pandas"):
            arquivos_lidos = 1
            return aplicar_filtros_imediato(res.to_pandas(), sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo, dt_alvos), arquivos_lidos

        if isinstance(res, str): res = [res]
        if isinstance(res, list) and len(res) > 0:
            frames = []
            for r in res:
                if isinstance(r, pd.DataFrame):
                    arquivos_lidos += 1
                    df_r = aplicar_filtros_imediato(r, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo, dt_alvos)
                    if not df_r.empty: frames.append(df_r)
                    continue

                caminho = os.fspath(r) if hasattr(r, "__fspath__") else str(r)
                if not caminho.endswith(".parquet"): continue

                nome_arquivo = os.path.basename(caminho).upper()
                if prefixo_esperado:
                    prefixo = str(prefixo_esperado).upper()
                    if not nome_arquivo.startswith(prefixo):
                        grupo_essencial = prefixo[:2]
                        if not (grupo_essencial in nome_arquivo and uf.upper() in nome_arquivo):
                            continue

                arquivos_lidos += 1
                caminho_sql = caminho.replace("'", "''")

                try:
                    cols_parquet = duckdb.query(f"DESCRIBE SELECT * FROM read_parquet('{caminho_sql}')").df()["column_name"].tolist()
                    cols_alvo_upper = [x.upper() for x in cols_alvo]
                    col_filtro = next((c for c in cols_parquet if c.upper() in cols_alvo_upper), None)

                    if id_alvo and col_filtro and nivel_terr == "Município":
                        id_sql = str(id_alvo).replace("'", "''")
                        query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{id_sql}%'"
                        df = duckdb.query(query).df()
                        frames.append(df)

                    elif nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                        col_mun_res = next((c for c in cols_parquet if c.upper() in ["MUNIC_RES", "SP_MUNRES", "ID_MN_RESI", "ID_MUNICIP", "CODUFMUN"]), None)
                        if col_mun_res:
                            codigo_uf = ESTADOS_IBGE.get(uf, "")
                            where_uf = f"WHERE CAST(\"{col_mun_res}\" AS VARCHAR) LIKE '{codigo_uf}%'" if "SINAN" in sistema and codigo_uf else ""
                            query = f"SELECT \"{col_mun_res}\" AS CODIGO_MUNICIPIO, COUNT(*) AS TOTAL_REGISTROS FROM read_parquet('{caminho_sql}') {where_uf} GROUP BY \"{col_mun_res}\" ORDER BY TOTAL_REGISTROS DESC"
                            df = duckdb.query(query).df()
                            frames.append(df)
                        else:
                            frames.append(leitura_segura_parquet(caminho, limite=50000))
                    else:
                        limite_linhas = 50000 if sistema in BASES_PESADAS else 500000
                        codigo_uf = ESTADOS_IBGE.get(uf, "")
                        if "SINAN" in sistema and nivel_terr == "Estado" and col_filtro and codigo_uf:
                            query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{codigo_uf}%' LIMIT {limite_linhas}"
                        else:
                            query = f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT {limite_linhas}"
                        df = duckdb.query(query).df()
                        frames.append(df)
                except Exception as e:
                    frames.append(leitura_segura_parquet(caminho, limite=50000))
            if frames: return pd.concat(frames, ignore_index=True), arquivos_lidos
    except Exception as e:
        print(f"[ERRO OPERACIONAL DUCKDB] {repr(e)}")
    return pd.DataFrame(), arquivos_lidos

def gerar_metricas_cnes(df, grupo):
    df = df.copy()
    df.columns = [str(c).upper().strip() for c in df.columns]
    metricas = {
        "grupo": grupo,
        "registros": len(df),
        "estabelecimentos_unicos": df["CNES"].nunique() if "CNES" in df.columns else None
    }
    if grupo == "ST":
        metricas["principal_label"] = "Estabelecimentos unicos"
        metricas["principal_value"] = metricas["estabelecimentos_unicos"] or len(df)
    elif grupo == "PF":  
        metricas["principal_label"] = "Vinculos profissionais"
        metricas["principal_value"] = len(df)
    elif grupo in ["SR", "HB", "IN", "EP", "DC"]:
        labels = {"SR": "Servicos especializados", "HB": "Habilitacoes", "IN": "Incentivos", "EP": "Equipes cadastradas", "DC": "Registros complementares"}
        metricas["principal_label"] = labels[grupo]
        metricas["principal_value"] = len(df)
    elif grupo == "EQ":
        for col in ["QT_EXIST", "QT_USO", "QT_SUS", "QT_NSUS"]:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)         
        metricas["principal_label"] = "Equipamentos existentes"
        metricas["principal_value"] = int(df["QT_EXIST"].sum()) if "QT_EXIST" in df.columns else len(df)
    elif grupo == "LT":
        for col in ["QT_EXIST", "QT_SUS", "QT_NSUS", "QT_CONTR"]:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)              
        metricas["principal_label"] = "Leitos existentes"
        metricas["principal_value"] = int(df["QT_EXIST"].sum()) if "QT_EXIST" in df.columns else len(df)
    return metricas

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    df_tratado.columns = [str(c).upper().strip() for c in df_tratado.columns]
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES" if "CNES" in sistema else "SINAN"
    
    dic_dinamico = CONFIG_APP.get("DICIONARIOS_VALORES", {})
    if "SIH" not in dic_dinamico: dic_dinamico["SIH"] = {}
    dic_dinamico["SIH"].update({"SEXO": {"1": "Masculino", "3": "Feminino"}, "MORTE": {"0": "Alta", "1": "Óbito"}})
    
    if "SINASC" not in dic_dinamico: dic_dinamico["SINASC"] = {}
    dic_dinamico["SINASC"].update({
        "ESCMAE": {"1": "Nenhuma", "2": "1 a 3 anos", "3": "4 a 7 anos", "4": "8 a 11 anos", "5": "12 anos e mais", "9": "Ignorado"},
        "ESCMAE2010": {"0": "Sem escolaridade", "1": "Fundamental I", "2": "Fundamental II", "3": "Médio", "4": "Superior incompleto", "5": "Superior completo", "9": "Ignorado"},
        "RACACORMAE": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"}
    })

    if "IDADE" in df_tratado.columns: df_tratado.loc[:, "IDADE"] = df_tratado["IDADE"].apply(decodificar_idade_datasus)
    if "IDADEMAE" in df_tratado.columns: 
        df_tratado.loc[:, "IDADEMAE"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus)
        df_tratado.loc[:, "GRUPO_IDADE_MAE"] = df_tratado["IDADEMAE"].apply(agrupar_idade_mae)
    if "NU_IDADE_N" in df_tratado.columns: df_tratado.loc[:, "NU_IDADE_N"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus)

    for c_vbo in ["OCUP", "OCUPMAE", "CODOCUPMAE", "ID_OCUPA_N"]:
        if c_vbo in df_tratado.columns: df_tratado.loc[:, c_vbo] = df_tratado[c_vbo].apply(decodificar_cbo)

    dict_cid = TABELAS_EXTERNAS.get("CID10", {})
    for col in ["CAUSABAS", "DIAG_PRINC", "DIAG_SECUN", "ID_AGRAVO"]:
        if col in df_tratado.columns: df_tratado.loc[:, col] = df_tratado[col].apply(lambda x: decodificar_cid(x, dict_cid))

    dict_sigtap = TABELAS_EXTERNAS.get("SIGTAP", {})
    for col in ["PROC_REA", "PROC_SOLIC"]:
        if col in df_tratado.columns: df_tratado.loc[:, col] = df_tratado[col].apply(lambda x: decodificar_sigtap(x, dict_sigtap))

    for coluna, de_para in dic_dinamico.get(sigla_sistema, {}).items():
        if coluna in df_tratado.columns:
            df_tratado.loc[:, coluna] = df_tratado[coluna].apply(normalizar_codigo).map(de_para).fillna("Ignorado/Outros")
            
    cabecalhos = CONFIG_APP.get("TRADUCAO_CABECALHOS", {})
    if "SIH" not in cabecalhos: cabecalhos["SIH"] = {}
    cabecalhos["SIH"].update({"SEXO": "Sexo Paciente", "MORTE": "Desfecho (Alta/Óbito)", "VAL_TOT": "Valor Total AIH (R$)", "VAL_UTI": "Valor UTI (R$)", "DIAG_PRINC": "Diagnóstico Principal (CID-10)", "PROC_REA": "Procedimento Realizado (SIGTAP)"})
    if "SINASC" not in cabecalhos: cabecalhos["SINASC"] = {}
    cabecalhos["SINASC"].update({"GRUPO_IDADE_MAE": "Faixa Etária da Mãe", "ESCMAE": "Escolaridade Mãe (Anos)", "ESCMAE2010": "Escolaridade Mãe (2010)", "CODOCUPMAE": "Ocupação/Profissão Mãe (CBO)", "RACACORMAE": "Raça/Cor da Mãe"})
    
    df_tratado = df_tratado.rename(columns=cabecalhos.get(sigla_sistema, {}))
    return df_tratado

# 🌟 CORREÇÃO CRÍTICA: TRATAMENTO POLIMÓRFICO COMPLETO DA COOPERAÇÃO ENTRE APIS DO SIH NO PYSUS
def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, sih_grupo=None, cnes_grupo=None, nivel_terr="Estado", id_datasus_alvo="", tipo_resultado=""):
    if not api_sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    partes_final = [] 
    meses_para_baixar = [mes_num] if mes_num else [None]
    cols_alvo = obter_colunas_municipio(sistema, sih_grupo)
    dt_alvos = ["DTOBITO", "DTNASC", "DT_NOTIFIC", "DT_INTER"]
    falhas = []
    sucessos_download = 0
    id_filtro = id_datasus_alvo if nivel_terr == "Município" else ""

    for uf in ufs_lista:
        if "SIH" in sistema or "CNES" in sistema:
            for m in meses_para_baixar:
                df_temp = pd.DataFrame()
                arquivos_lidos = 0
                try:
                    if "SIH" in sistema:
                        prefixo_token = f"{sih_grupo}{uf}{str(ano)[-2:]}{int(m):02d}" if m else f"{sih_grupo}{uf}{str(ano)[-2:]}"
                        prefixo_token = prefixo_token.upper()
                        
                        res = None
                        # Estratégia 1: Tenta primeiro a API impl estruturada via impl se disponível
                        try:
                            if api_sih:
                                res = api_sih(state=uf, year=int(ano), month=int(m) if m else 0, group=sih_grupo)
                        except Exception as e_api:
                            print(f"[SIH API_SIH EXCEÇÃO] {repr(e_api)}")
                            
                        # Estratégia 2: Fallback Robusto — Chamada posicional pura (download(uf, ano, mes, grupo))
                        if res is None or (isinstance(res, list) and len(res) == 0):
                            try:
                                from pysus.online_data.SIH import download as download_sih_posicional
                                res = download_sih_posicional(uf, int(ano), int(m) if m else 0, sih_grupo)
                            except Exception as e_pos:
                                print(f"[SIH POSICIONAL EXCEÇÃO] {repr(e_pos)}")
                                # Margem cega: Última tentativa nomeada caso a instalação inverta assinaturas
                                try:
                                    from pysus.online_data.SIH import download as download_sih_nomeado
                                    res = download_sih_nomeado(state=uf, year=int(ano), month=int(m) if m else 0, group=sih_grupo)
                                except: pass
                        
                        # Tratamento polimórfico dos formatos de retorno antes de acionar DuckDB
                        if res is not None:
                            if hasattr(res, "to_dataframe"):
                                try: res = res.to_dataframe()
                                except: pass
                            elif hasattr(res, "to_pandas"):
                                try: res = res.to_pandas()
                                except: pass

                        # Encaminha o objeto normalizado (seja DataFrame ou lista de caminhos)
                        if isinstance(res, pd.DataFrame):
                            df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(
                                res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado, prefixo_esperado=prefixo_token
                            )
                        else:
                            arquivos_norm = normalizar_lista_arquivos_pysus(res)
                            arquivos_norm = filtrar_arquivos_sih_exatos(arquivos_norm, uf, ano, m, sih_grupo)
                            df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(
                                arquivos_norm, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado, prefixo_esperado=prefixo_token
                            )
                        
                    elif "CNES" in sistema:
                        prefixo_token = f"{cnes_grupo}{uf}{str(ano)[-2:]}{int(m):02d}".upper()
                        try: res = api_cnes(state=uf, year=ano, month=m, group=cnes_grupo)
                        except: res = None
                        df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado, prefixo_esperado=prefixo_token)
                except Exception as e:
                    falhas.append(f"Erro {sistema} | {uf} {ano}/{m}: {e}")
                    continue

                if not df_temp.empty:
                    df_temp = aplicar_filtros_imediato(df_temp, sistema, nivel_terr, uf, id_datasus_alvo, m, cols_alvo, dt_alvos)
                    if not df_temp.empty:
                        partes_final.append(df_temp)
                        sucessos_download += 1
                    else: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO FINAL | {uf} {ano}")
                else:
                    if arquivos_lidos > 0: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO TERRITORIAL | {uf} {ano}")
                    else: falhas.append(f"{sistema} FALHA DE DOWNLOAD OU ARQUIVO INEXISTENTE | {uf} {ano}")
        else:
            df_temp = pd.DataFrame()
            arquivos_lidos = 0
            try:
                if "SIM" in sistema: 
                    res = api_sim(state=uf, year=ano)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado)
                elif "SINASC" in sistema: 
                    res = api_sinasc(state=uf, year=ano)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado)
                elif "SINAN" in sistema:
                    try:
                        from pysus.online_data.SINAN import download as download_sinan
                        res = download_sinan(disease=agravo, years=[ano], states=[uf])
                    except:
                        try: res = api_sinan(disease=agravo, year=ano)
                        except: res = api_sinan(disease=agravo, state=uf, year=ano)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado)
            except Exception as e:
                falhas.append(f"Download Error {sistema} | {uf} {ano}: {e}")
                continue

            if not df_temp.empty:
                df_temp = aplicar_filtros_imediato(df_temp, sistema, nivel_terr, uf, id_datasus_alvo, mes_num, cols_alvo, dt_alvos)
                if not df_temp.empty:
                    partes_final.append(df_temp)
                    sucessos_download += 1
                else: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO FINAL | {uf} {ano}")
            else:
                if arquivos_lidos > 0: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO TERRITORIAL | {uf} {ano}")
                else: falhas.append(f"{sistema} FALHA DE DOWNLOAD OU ARQUIVO INEXISTENTE | {uf} {ano}")
        gc.collect()
            
    if not partes_final:
        if any("SEM REGISTROS" in f for f in falhas):
            return pd.DataFrame({"Erro": ["A base foi baixada corretamente, mas não há registros para o território, período ou agravo selecionados."] })
        else:
            return pd.DataFrame({"Erro": ["Falha de conexão ou arquivo inexistente no DATASUS para os filtros selecionados."] })
    return pd.concat(partes_final, ignore_index=True)

# --- INTERFACE PRINCIPAL ---
st.sidebar.title("🧬 Navegação e Filtros")
aba_ativa = st.sidebar.radio("Navegar para:", ["📋 Guia Principal (Extração)", "📚 Dicionários e Citações"])

if aba_ativa == "📋 Guia Principal (Extração)":
    st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>DATASUS conectado via DuckDB | SIDRA e VIS DATA 3 em desenvolvimento</p></div>', unsafe_allow_html=True)
    fonte = st.sidebar.radio("Base de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3 - Indisponível)"])
    if "VIS DATA 3" in fonte:
        st.warning("VIS DATA 3 ainda não está conectado nesta versão.")
        st.stop()
        
    nivel_terr = st.sidebar.radio("Nível Territorial:", ["Estado", "Município"])
    ufs_selecionadas = []; id_ibge_alvo = "1"; id_datasus_alvo = ""
    ufs_ordenadas = sorted(UFS)

    if nivel_terr == "Estado":
        uf_sel = st.sidebar.selectbox("Selecione o Estado:", ufs_ordenadas, index=ufs_ordenadas.index("MG"))
        ufs_selecionadas = [uf_sel]; id_ibge_alvo = ESTADOS_IBGE[uf_sel]; nome_local = uf_sel
    elif nivel_terr == "Município":
        uf_sel = st.sidebar.selectbox("Filtrar Estado:", ufs_ordenadas, index=ufs_ordenadas.index("MG"))
        muns_estado = buscar_municipios_por_uf(uf_sel)
        mun_nome = st.sidebar.selectbox("Selecione o Município:", sorted(muns_estado.keys()))
        dados_mun = muns_estado[mun_nome]
        ufs_selecionadas = [uf_sel]; id_ibge_alvo = dados_mun['id7']; id_datasus_alvo = dados_mun['id6']; nome_local = mun_nome

    if fonte == "🏥 Saúde (DATASUS)":
        sistema = st.sidebar.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Nascimentos (SINASC)", "Cadastro Nacional de Estabelecimentos (CNES)", "Notificações (SINAN)"])
        
        if nivel_terr == "Estado" and sistema in BASES_PESADAS:
            tipo_resultado = st.sidebar.radio("Tipo de resultado estadual:", ["Resumo agregado", "Amostra limitada de microdados"])
        else:
            tipo_resultado = "Microdados filtrados"

        agravo_sel = sih_grupo_sel = cnes_grupo_sel = None
        
        if "SINAN" in sistema:
            mapa_doencas = {"Acidente de trabalho": "ACGR", "Acidente de trabalho com material biológico": "ACBI", "AIDS em adultos": "AIDA", "AIDS em crianças": "AIDC", "Câncer Relacionado ao Trabalho": "CANC", "Chikungunya": "CHIK", "Dengue": "DENG", "Doença de Chagas": "CHAG", "Hepatites Virais": "HEPA", "HIV em adultos": "HIVA", "HIV em crianças": "HIVC", "HIV em crianças expostas": "HIVE", "Leptospirose": "LEPT", "Meningite": "MENI", "Perda Auditiva por Ruído (Trabalho)": "PAIR", "Raiva Humana": "RAIV", "Sífilis Adquirida": "SIFA", "Sífilis Congênita": "SIFC", "Sífilis em Gestante": "SIFG", "Transtornos Mentais (Trabalho)": "MENT", "Tuberculose": "TUBE", "Varicela": "VARC", "Violência doméstica/sexual": "VIOL", "Zika Vírus": "ZIKA"}
            nome_agravo = st.sidebar.selectbox("Doença/Agravo:", sorted(list(mapa_doencas.keys())))
            agravo_sel = mapa_doencas[nome_agravo]
        elif "SIH" in sistema:
            mapa_sih = {
                "RD - Registros de Internações / AIH Reduzida (padrão)": "RD",
                "SP - Serviços Profissionais (não representa nº de internações)": "SP",
                "ER - Emergência Referenciada (experimental)": "ER",
                "CM - Cirurgias Ambulatoriais (não habilitado para consulta UF/mês nesta versão)": "CM"
            }
            sih_grupo_sel = mapa_sih[st.sidebar.selectbox("Grupo de Dados (SIH):", list(mapa_sih.keys()))]
            if sih_grupo_sel != "RD":
                st.sidebar.warning("Este grupo do SIH não deve ser interpretado como número de internações. O app processará somente arquivos com o prefixo exato do grupo, UF, ano e mês selecionados.")
            if sih_grupo_sel == "CM":
                st.sidebar.warning("O grupo CM foi mantido na interface, mas não será processado como consulta mensal por UF/município nesta versão.")
        elif "CNES" in sistema:
            mapa_cnes = {
                "ST - Estabelecimentos": "ST",
                "PF - Vínculos Profissionais": "PF",
                "SR - Serviços Especializados": "SR",
                "HB - Habilitações": "HB",
                "IN - Incentivos": "IN",
                "EP - Equipes": "EP",
                "EQ - Equipamentos": "EQ",
                "LT - Leitos": "LT",
                "DC - Dados Complementares": "DC"
            }
            cnes_grupo_sel = mapa_cnes[st.sidebar.selectbox("Grupo de Dados (CNES):", list(mapa_cnes.keys()))]
        
        ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis(sistema))
        if "SINASC" in sistema and ano_sel >= 2021:
            st.sidebar.warning("⚠️ **Aviso de Migração:** Os microdados de Nascidos Vivos após 2020 foram movidos para o Portal de Dados Abertos.")
            
        nome_mes = st.sidebar.selectbox("Mês de Competência/Ocorrência:", ["Todos os Meses"] + MESES_NOMES, index=1)
        mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])
        
        with st.sidebar.form("form_consulta"):
            submit_button = st.form_submit_button("🔍 Consultar Base")

        if submit_button:
            is_dengue = (sistema == "Notificações (SINAN)" and agravo_sel == "DENG")
            if mes_sel is None and (sistema in ["Internações (SIH)", "Cadastro Nacional de Estabelecimentos (CNES)"] or is_dengue):
                st.error("Para SIH, CNES e SINAN (Dengue), selecione um mês específico. A opção 'Todos os Meses' foi liberada para os outros agravos leves do SINAN, mas permanece bloqueada nessas bases massivas para evitar estouro de RAM.")
                st.stop()
                
            if sistema == "Internações (SIH)" and sih_grupo_sel == "CM":
                st.error("O grupo SIH/CM não está disponível de forma confiável para consulta mensal por UF/município nesta versão. Use RD para internações ou SP para serviços profissionais.")
                st.stop()

            if trava_global.locked():
                st.error("🛑 Há outra extração complexa em andamento neste servidor. Por segurança de memória do Streamlit Cloud, aguarde 10 segundos e clique novamente.")
                st.stop()
                
            with trava_global:
                with st.spinner(f"Processando via DuckDB para {nome_local}..."):
                    df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo, tipo_resultado)
                    
                    if not df_bruto.empty and "Erro" not in df_bruto.columns:
                        if nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                            df_tratado = df_bruto.copy()
                            df_tratado.columns = ["CÓDIGO_MUNICÍPIO_RESIDENTE", "TOTAL_DE_REGISTROS"]
                            sistema_titulo = f"Resumo Agregado — {sistema}"
                        else:
                            df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                            sistema_titulo = f"SINAN ({nome_agravo})" if "SINAN" in sistema else f"SIH ({sih_grupo_sel})" if "SIH" in sistema else f"CNES ({cnes_grupo_sel})" if "CNES" in sistema else sistema.split(" (")[0]
                        
                        periodo_label = f"{mes_sel:02d}/{ano_sel}" if mes_sel else f"{ano_sel}"
                        card_text = f"<h2>{len(df_bruto)} Registros Processados</h2>"
                        if "CNES" in sistema:
                            m_cnes = gerar_metricas_cnes(df_bruto, cnes_grupo_sel)
                            if cnes_grupo_sel == "ST": card_text = f"<h2>{m_cnes['principal_value']} estabelecimentos únicos | {len(df_bruto)} registros processados</h2>"
                            elif cnes_grupo_sel == "PF": card_text = f"<h2>{m_cnes['principal_value']} vínculos profissionais processados</h2>"
                            elif cnes_grupo_sel == "EQ": card_text = f"<h2>{m_cnes['principal_value']} equipamentos existentes | {len(df_bruto)} registros de equipamentos</h2>"
                            elif cnes_grupo_sel == "LT": card_text = f"<h2>{m_cnes['principal_value']} leitos existentes | {len(df_bruto)} registros LT</h2>"
                            else: card_text = f"<h2>{len(df_bruto)} {m_cnes['principal_label'].lower()} processados</h2>"
                        elif "SIH" in sistema:
                            if sih_grupo_sel == "RD": card_text = f"<h2>{len(df_bruto)} AIHs / registros de internação processados</h2>"
                            elif sih_grupo_sel == "SP": card_text = f"<h2>{len(df_bruto)} registros de serviços profissionais processados</h2>"
                            elif sih_grupo_sel == "ER": card_text = f"<h2>{len(df_bruto)} registros técnicos processados, com aviso metodológico</h2>"

                        st.markdown(f'<div class="metric-card">{card_text}<p>{sistema_titulo} - {nome_local} ({periodo_label})</p></div>', unsafe_allow_html=True)
                        
                        if nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Amostra limitada de microdados":
                            st.warning("Consulta estadual em base pesada. Para preservar o funcionamento do app, a visualização foi limitada a uma amostra de 50.000 registros. Para microdados completos, utilize filtro municipal ou exportação específica.")
                        if "SINAN" in sistema and len(df_tratado) >= 50000:
                            st.warning("⚠️ O limite de visualização de 50.000 linhas foi acionado por segurança de RAM. Por favor, baixe o CSV para acessar a base completa.")
                        
                        tab1, tab2, tab3 = st.tabs(["✅ Planilha Tratada", "⚙️ Planilha Bruta", "📈 Painel de Análises (Dashboards)"])
                        with tab1:
                            st.dataframe(df_tratado.head(100), width="stretch")
                            st.download_button("📥 Baixar Tabela TRATADA (CSV)", df_tratado.to_csv(index=False, sep=';', decimal=','), f"tratado_{sistema_titulo}_{nome_local}.csv", "text/csv")
                        with tab2:
                            st.dataframe(df_bruto.head(100), width="stretch")
                            st.download_button("📥 Baixar Tabela BRUTA (CSV)", df_bruto.to_csv(index=False, sep=';', decimal=','), f"bruto_{sistema_titulo}_{nome_local}.csv", "text/csv")
                            
                        with tab3:
                            if (nivel_terr == "Estado" and sistema in BASES_PESADAS) or ("SINAN" in sistema and len(df_tratado) >= 50000):
                                st.info("📊 Gráficos suspensos para consultas agregadas ou massivas de nível Estadual. Altere para o nível territorial 'Município' para visualizar os painéis analíticos.")
                            else:
                                st.subheader(f"📊 Painel Analítico: {sistema_titulo}")
                                if "SIH" in sistema:
                                    c1, c2, c3 = st.columns(3)
                                    for c_val in ["Valor Total AIH (R$)", "Valor UTI (R$)"]:
                                        if c_val in df_tratado.columns:
                                            df_tratado.loc[:, f"Num_{c_val}"] = pd.to_numeric(df_tratado[c_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
                                    soma_tot = df_tratado["Num_Valor Total AIH (R$)"].sum() if "Num_Valor Total AIH (R$)" in df_tratado.columns else 0
                                    soma_uti = df_tratado["Num_Valor UTI (R$)"].sum() if "Num_Valor UTI (R$)" in df_tratado.columns else 0
                                    c1.metric("💰 Custo Total Pago (AIH)", f"R$ {soma_tot:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                                    c2.metric("🏥 Custo em UTI", f"R$ {soma_uti:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                                    
                                    c_sexo, c_morte = st.columns(2)
                                    with c_sexo:
                                        col_sexo = next((c for c in df_tratado.columns if "Sexo Paciente" in c), None)
                                        if col_sexo: st.bar_chart(df_tratado[col_sexo].value_counts())
                                    with c_morte:
                                        if "Desfecho (Alta/Óbito)" in df_tratado.columns: st.bar_chart(df_tratado["Desfecho (Alta/Óbito)"].value_counts())
                                    
                                    c_a, c_b = st.columns(2)
                                    if "Procedimento Realizado (SIGTAP)" in df_tratado.columns:
                                        with c_a: st.bar_chart(df_tratado["Procedimento Realizado (SIGTAP)"].value_counts().head(10))
                                    if "Diagnóstico Principal (CID-10)" in df_tratado.columns:
                                        with c_b: st.bar_chart(df_tratado["Diagnóstico Principal (CID-10)"].value_counts().head(10))
                                        
                                elif "SINASC" in sistema:
                                    st.write("### Perfil da Mãe")
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        if "Faixa Etária da Mãe" in df_tratado.columns: st.bar_chart(df_tratado["Faixa Etária da Mãe"].value_counts().sort_index())
                                    with c2:
                                        if "Escolaridade Mãe (2010)" in df_tratado.columns: st.bar_chart(df_tratado["Escolaridade Mãe (2010)"].value_counts())
                                    if "Ocupação/Profissão Mãe (CBO)" in df_tratado.columns: st.bar_chart(df_tratado["Ocupação/Profissão Mãe (CBO)"].value_counts().head(10))
                                    
                                    st.write("---")
                                    st.write("### Perfil do Nascido Vivo")
                                    c3, c4, c5 = st.columns(3)
                                    with c3:
                                        col_sexo = next((c for c in df_tratado.columns if "Sexo Bebê" in c), None)
                                        if col_sexo: st.bar_chart(df_tratado[col_sexo].value_counts())
                                    with c4:
                                        col_cor_bebe = next((c for c in df_tratado.columns if "Raça/Cor Bebê" in c), None)
                                        if col_cor_bebe: st.bar_chart(df_tratado[col_cor_bebe].value_counts())
                                    with c5:
                                        col_cor_mae = next((c for c in df_tratado.columns if "Raça/Cor da Mãe" in c), None)
                                        if col_cor_mae: st.bar_chart(df_tratado[col_cor_mae].value_counts())
                                        
                                elif "CNES" in sistema:
                                    st.write("📈 *O Painel Gráfico prioriza bases clínicas e epidemiológicas.*")
                                elif "SIM" in sistema:
                                    c1, c2 = st.columns(2)
                                    col_sexo = next((c for c in df_tratado.columns if "Sexo" in c), None)
                                    if col_sexo: st.bar_chart(df_tratado[col_sexo].value_counts())
                                    col_raca = next((c for c in df_tratado.columns if "Raça" in c), None)
                                    if col_raca: st.bar_chart(df_tratado[col_raca].value_counts())
                                    
                                    c3, c4 = st.columns(2)
                                    with c3:
                                        col_circ = next((c for c in df_tratado.columns if "Circunstância do Óbito" in c), None)
                                        if col_circ: st.bar_chart(df_tratado[col_circ].value_counts())
                                    with c4:
                                        col_doenca = next((c for c in df_tratado.columns if "Causa Básica (CID-10)" in c), None)
                                        if col_doenca: st.bar_chart(df_tratado[col_doenca].value_counts().head(10))
                    else:
                        msg = df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Sem dados disponíveis."
                        if "território, período ou agravo" in msg:
                            st.info("ℹ️ A consulta foi executada com sucesso, mas não foram encontrados registros de notificações para o agravo, território e período selecionados.")
                        else: st.error(msg)

# --- ABA DE DICIONÁRIOS E CITAÇÕES ---
elif aba_ativa == "📚 Dicionários e Citações":
    st.title("📚 Dicionários de Dados e Linhas do Tempo do DATASUS")
    st.markdown("---")
    st.header("1. Dicionários de Dados (Variáveis)")
    
    with st.expander("🏥 CNES (Cadastro Nacional de Estabelecimentos de Saúde)"):
        st.markdown("""
        O CNES deve ser tratado estritamente como um cadastro de capacidade instalada de unidades federativas[cite: 25, 27].
        * **ST - Estabelecimentos:** Apresenta dados cadastrais básicos de unidades[cite: 29]. A contagem única pelo método `CNES.nunique()` reflete o quantitativo real de estabelecimentos unificados[cite: 29].
        * **PF - Vínculos Profissionais:** Registra contratos profissional-estabelecimento[cite: 29]. Representa o volume de vínculos ativos, não indivíduos físicos isolados[cite: 29].
        * **SR - Serviços Especializados:** Cadastro técnico de serviços de saúde. Não deve ser interpretado como indicador de atendimentos efetuados[cite: 29].
        * **HB / IN:** Habilitações de alta complexidade e incentivos financeiros regulamentados[cite: 29]. Não espelham valores líquidos repassados sem colunas de faturamento explícitas[cite: 29].
        * **EP - Equipes:** Cadastro nominal de Equipes de Saúde da Família e correlatas (nomenclatura corrigida do PySUS)[cite: 29].
        * **EQ / LT - Equipamentos e Leitos:** Linhas de tabelas quantitativas[cite: 29]. **Atenção:** A função `len(df)` monitora apenas o controle operacional das linhas[cite: 14, 29]. O total de itens instalados deve ser calculado pela consolidação da soma da coluna quantitativa `QT_EXIST`[cite: 29].
        """)

    with st.expander("🛏️ SIH (Sistema de Informações Hospitalares)"):
        st.markdown("""
        O SIH atua como o sistema de registro de produção e faturamento hospitalar[cite: 25, 44]. Os grupos disponíveis possuem naturezas completamente distintas[cite: 13, 44]:
        * **Grupo RD (AIH Reduzida):** É a tabela padrão-ouro para análise epidemiológica de internações no país[cite: 10, 46]. Cada linha representa uma internação de paciente que ocupou leito hospitalar[cite: 46].
        * **Grupo SP (Serviços Profissionais):** Registra atos e procedimentos efetuados pelos profissionais de saúde vinculados ao faturamento hospitalar[cite: 46, 47]. Um único paciente pode gerar dezenas de linhas neste grupo[cite: 47]. **Nunca utilize a contagem de linhas do grupo SP como métrica de internações**, sob risco de erro metodológico grave de superestimação[cite: 11, 47].
        * **Grupo ER (Emergência Referenciada):** Grupo técnico contendo fluxos específicos e dados de rejeições hospitalares com erros operacionais, mantido sob caráter de análise experimental[cite: 12, 46].
        * **Grupo CM (Cirurgias Ambulatoriais):** Fluxo não geral que agrupa cirurgias de curtíssima permanência[cite: 46]. Devido ao limbo de faturamento, hospitais preferem reportar esses procedimentos no **SIA (Sistema Ambulatorial)**. Logo, possui subnotificação endêmica e está desativado para o fluxo mensal comum por UF nesta versão[cite: 46, 58].
        """)

    with st.expander("💀 SIM (Sistema de Informações sobre Mortalidade)"):
        st.markdown("""
        * **Resumo:** Registros de óbitos com campos demográficos e causas de morte codificadas por CID-10[cite: 622, 634].
        * **CAUSABAS:** A causa básica do óbito (CID-10), crucial para análises de mortalidade[cite: 622, 635].
        """)
        
    with st.expander("👶 SINASC (Sistema de Informações sobre Nascidos Vivos)"):
        st.markdown("""
        * **Resumo:** Dados sobre os recém-nascidos, perfil demográfico das mães e características do parto no Brasil[cite: 627, 639].
        """)

    with st.expander("🔬 SINAN (Sistema de Informação de Agravos de Notificação)"):
        st.markdown("""
        * **Resumo:** Cadastro nacional de notificações de doenças compulsórias[cite: 624]. Monitora perfis epidemiológicos a partir de notificações estaduais[cite: 624].
        """)

    st.markdown("---")
    st.header("2. ⚠️ Notas Técnicas e Limitações do DATASUS")
    with st.expander("⏳ Atraso de Digitação e Consolidação (Lag)"):
        st.markdown("""
        Os dados de saúde pública no Brasil sofrem um atraso natural entre a ocorrência e a disponibilidade no sistema:
        * **SIH (Internações):** É o sistema mais ágil (focado em faturamento). Atraso médio de **2 a 3 meses**.
        * **SINAN (Agravos):** Varia por doença. Epidemias são rápidas, mas agravos crônicos podem levar até **6 meses** para chegar ao servidor federal.
        """)
        
    st.markdown("---")
    st.header("3. Como citar os dados (Padrão ABNT)")
    st.code("BRASIL. Ministério da Saúde. Departamento de Informática do SUS – DATASUS. Microdados de Saúde. Brasília, DF. Disponível em: <http://datasus.saude.gov.br/>. Acesso em: [2026].")
