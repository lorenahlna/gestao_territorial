# VERSAO_FINAL_PRODUCAO_CORRIGIDA_V17_FIXED_SIH
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
    from pysus.api import sim as api_sim, sih as api_sih, cnes as api_cnes, sinasc as api_sinasc, sinan as api_sinan
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
    if not arquivos: return []
    
    ano2 = str(ano)[-2:]
    mes2 = f"{int(mes):02d}" if mes is not None else ""
    
    # Prefixos possíveis para o grupo solicitado
    # Às vezes o DATASUS usa RD ou RJ para internações, SP para serviços profissionais
    prefixo_exato = f"{grupo}{uf}{ano2}{mes2}".upper()
    
    selecionados = []
    for caminho in arquivos:
        nome = os.path.basename(str(caminho)).upper()
        # Se o nome do arquivo contém o grupo, UF e ano, aceitamos (mes pode variar no nome do arquivo físico)
        if (grupo.upper() in nome or (grupo.upper() == "RD" and "RJ" in nome)) and uf.upper() in nome and ano2 in nome:
            selecionados.append(caminho)
            
    if not selecionados:
        # Se não filtramos nada, retornamos a lista original para o DuckDB tentar ler
        return arquivos
        
    return selecionados

def processar_retorno_pysus_duckdb(res, cols_alvo, id_alvo, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado="Amostra limitada de microdados", prefixo_esperado=None):
    if cols_alvo is None: cols_alvo = []
    arquivos_lidos = 0
    try:
        if isinstance(res, pd.DataFrame):
            arquivos_lidos = 1
            return aplicar_filtros_imediato(res, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo, dt_alvos), arquivos_lidos
        
        arquivos = normalizar_lista_arquivos_pysus(res)
        if not arquivos: return pd.DataFrame(), 0

        frames = []
        for caminho in arquivos:
            if not str(caminho).upper().endswith(".PARQUET"): continue
            
            arquivos_lidos += 1
            caminho_sql = str(caminho).replace("'", "''")

            try:
                # Descobrir colunas do arquivo
                cols_parquet = duckdb.query(f"DESCRIBE SELECT * FROM read_parquet('{caminho_sql}')").df()["column_name"].tolist()
                cols_parquet_upper = [c.upper() for c in cols_parquet]
                
                # Identificar coluna de filtro municipal/estadual
                col_filtro = next((c for c in cols_parquet if c.upper() in [x.upper() for x in cols_alvo]), None)
                
                # Se não achou a coluna alvo, tenta colunas genéricas de município
                if not col_filtro:
                    col_filtro = next((c for c in cols_parquet if c.upper() in ["MUNIC_RES", "SP_MUNRES", "CODUFMUN", "ID_MN_RESI", "CODMUNRES"]), None)

                if id_alvo and col_filtro and nivel_terr == "Município":
                    id_sql = str(id_alvo).replace("'", "''")
                    query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{id_sql}%'"
                    df = duckdb.query(query).df()
                    frames.append(df)
                elif nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                    if col_filtro:
                        codigo_uf = ESTADOS_IBGE.get(uf, "")
                        where_uf = f"WHERE CAST(\"{col_filtro}\" AS VARCHAR) LIKE '{codigo_uf}%'" if codigo_uf else ""
                        query = f"SELECT \"{col_filtro}\" AS CODIGO_MUNICIPIO, COUNT(*) AS TOTAL_REGISTROS FROM read_parquet('{caminho_sql}') {where_uf} GROUP BY \"{col_filtro}\""
                        df = duckdb.query(query).df()
                        frames.append(df)
                    else:
                        frames.append(leitura_segura_parquet(caminho, limite=50000))
                else:
                    limite = 50000 if sistema in BASES_PESADAS else 500000
                    query = f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT {limite}"
                    df = duckdb.query(query).df()
                    frames.append(df)
            except Exception as e:
                print(f"[DUCKDB ERRO] {caminho}: {e}")
                frames.append(leitura_segura_parquet(caminho))

        if frames:
            return pd.concat(frames, ignore_index=True), arquivos_lidos
    except Exception as e:
        print(f"[ERRO OPERACIONAL DUCKDB] {e}")
    return pd.DataFrame(), arquivos_lidos

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
                        # Tenta baixar usando a API do PySUS
                        try:
                            # O PySUS às vezes falha se passar month=None, então usamos 0 ou lista
                            res = api_sih(state=uf, year=int(ano), month=int(m) if m else [1,2,3,4,5,6,7,8,9,10,11,12], group=sih_grupo)
                        except:
                            res = None
                        
                        # Se falhou ou voltou vazio, tenta sem o grupo (padrão RD)
                        if not res and sih_grupo == "RD":
                            try: res = api_sih(state=uf, year=int(ano), month=int(m) if m else 1)
                            except: res = None

                        # Filtragem de arquivos físicos se necessário
                        arquivos_norm = filtrar_arquivos_sih_exatos(res, uf, ano, m, sih_grupo)
                        
                        df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(
                            arquivos_norm, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado
                        )
                        
                    elif "CNES" in sistema:
                        try: res = api_cnes(state=uf, year=ano, month=m, group=cnes_grupo)
                        except: res = None
                        df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado)
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
            # Outros sistemas (SIM, SINASC, SINAN)
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
        if prefixo == '1': return f"{num} Hora(s)"
        if prefixo == '0': return f"{num} Minuto(s)"
        return f"{v_str} (Codificado)"
    except: return v_str

def agrupar_idade_mae(idade_str):
    try:
        idade = int(idade_str.split(' ')[0])
        if idade < 15: return "1. < 15 anos"
        if idade < 20: return "2. 15-19 anos"
        if idade < 30: return "3. 20-29 anos"
        if idade < 40: return "4. 30-39 anos"
        return "5. 40+ anos"
    except: return "6. Ignorado"

def decodificar_cbo(cod):
    cod = normalizar_codigo(cod)
    if not cod: return "Não informado"
    return TABELAS_EXTERNAS["CBO"].get(cod, cod)

def decodificar_cid(cod, dic):
    cod = str(cod).upper().strip()
    if not cod: return "Não informado"
    return f"{cod} - {dic.get(cod, 'Descrição não encontrada')}"

def decodificar_sigtap(cod, dic):
    cod = normalizar_codigo(cod)
    if not cod: return "Não informado"
    return f"{cod} - {dic.get(cod, 'Procedimento não encontrado')}"

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

# --- INTERFACE PRINCIPAL ---
st.sidebar.title("🧬 Navegação e Filtros")
aba_ativa = st.sidebar.radio("Navegar para:", ["📋 Guia Principal (Extração)", "📚 Dicionários e Citações"])

if aba_ativa == "📋 Guia Principal (Extração)":
    st.title("📊 Inteligência Territorial | Extração de Dados SUS")
    st.markdown("---")
    
    st.sidebar.header("⚙️ Configurações da Extração")
    fonte = st.sidebar.selectbox("Fonte de Dados:", ["🏥 Saúde (DATASUS)"])
    
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
                "ER - Emergência Referenciada (experimental)": "ER"
            }
            sih_grupo_sel = mapa_sih[st.sidebar.selectbox("Grupo de Dados (SIH):", list(mapa_sih.keys()))]
        elif "CNES" in sistema:
            mapa_cnes = {"ST": "ST", "PF": "PF", "SR": "SR", "HB": "HB", "IN": "IN", "EP": "EP", "EQ": "EQ", "LT": "LT", "DC": "DC"}
            cnes_grupo_sel = st.sidebar.selectbox("Grupo de Dados (CNES):", list(mapa_cnes.keys()))
        
        ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis(sistema))
        nome_mes = st.sidebar.selectbox("Mês de Competência/Ocorrência:", ["Todos os Meses"] + MESES_NOMES, index=1)
        mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])
        
        with st.sidebar.form("form_consulta"):
            submit_button = st.form_submit_button("🔍 Consultar Base")

        if submit_button:
            with trava_global:
                with st.spinner(f"Processando via DuckDB para {nome_local}..."):
                    df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo, tipo_resultado)
                    
                    if not df_bruto.empty and "Erro" not in df_bruto.columns:
                        df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                        st.success(f"Sucesso! {len(df_bruto)} registros processados.")
                        
                        tab1, tab2 = st.tabs(["✅ Planilha Tratada", "⚙️ Planilha Bruta"])
                        with tab1:
                            st.dataframe(df_tratado.head(100))
                            st.download_button("📥 Baixar CSV", df_tratado.to_csv(index=False, sep=';'), f"tratado_{nome_local}.csv")
                        with tab2:
                            st.dataframe(df_bruto.head(100))
                    else:
                        st.error(df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Nenhum dado encontrado.")

elif aba_ativa == "📚 Dicionários e Citações":
    st.title("📚 Dicionários de Dados e Normas de Citação")
    st.info("Consulte os dicionários oficiais do DATASUS para entender as variáveis.")
