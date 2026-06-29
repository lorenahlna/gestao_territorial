# VERSAO_FINAL_PRODUCAO_SUPER_DASHBOARD_V33_CORRIGIDO_FINAL
import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import gc
import os
import shutil
import time
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
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; text-align: center; margin-bottom: 15px; box-shadow: 2px 2px 5px rgba(0,0,0,0.05);}
    .footer-text { text-align: center; color: #666; font-size: 14px; margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; }
    </style>
""", unsafe_allow_html=True)

BASES_PESADAS = ["Internações (SIH)", "Notificações (SINAN)", "Cadastro Nacional de Estabelecimentos (CNES)", "Mortalidade (SIM)"]

@st.cache_resource
def obter_trava_global():
    return threading.Lock()

trava_global = obter_trava_global()

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

def obter_colunas_territoriais(sistema, grupo=None):
    if "SIH" in sistema:
        if grupo == "SP": return {"res": ["SP_MUNRES", "MUNIC_RES", "MUN_RES"], "oco": ["SP_MUNIC", "SP_MUNMOV", "SP_GESTOR", "MUNIC_MOV", "GESTOR_COD"]}
        return {"res": ["MUNIC_RES"], "oco": ["MUNIC_MOV", "GESTOR_COD"]}
    if "SIM" in sistema:
        return {"res": ["CODMUNRES", "MUNIC_RES"], "oco": ["CODMUNOCO", "CODMUNOCOR", "CODMUNCART", "MUNIC_OCO", "MUNIC_MOV"]}
    if "SINASC" in sistema:
        return {"res": ["CODMUNRES", "MUNIC_RES"], "oco": ["CODMUNNASC", "CODMUNESTAB", "COMUNESTAB", "MUNIC_MOV"]}
    if "SINAN" in sistema:
        return {"res": ["ID_MN_RESI"], "oco": ["ID_MUNICIP"]}
    if "CNES" in sistema:
        return {"res": ["CODUFMUN"], "oco": ["CODUFMUN"]}
    return {"res": [], "oco": []}

MESES_NOMES = ["01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril", "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto", "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"]

@st.cache_data(show_spinner=False)
def carregar_dicionarios_github():
    URL_RAW_GITHUB = "https://raw.githubusercontent.com/lorenahlna/gestao_territorial/refs/heads/main/dicionarios.json"
    try:
        res = requests.get(URL_RAW_GITHUB, timeout=10).json()
        return res
    except Exception as e:
        return {
            "CBO_ESPECIFICOS": {"2251": "Médicos clínicos", "2235": "Enfermeiros"},
            "CBO_SUBGRUPOS": {"01": "Forças Armadas", "11": "Dirigentes", "22": "Profissionais de Saúde"}
        }

CONFIG_APP = carregar_dicionarios_github()

@st.cache_data(show_spinner=False)
def carregar_tabelas_complementares():
    tabelas = {"CBO": {}, "CID10": {}, "SIGTAP": {}}
    if os.path.exists("tabela_cid10_codigo_descricao.csv"):
        try:
            df_cid = pd.read_csv("tabela_cid10_codigo_descricao.csv", sep=";", dtype=str, encoding='utf-8', on_bad_lines='skip')
            if {"codigo_datasus", "descricao"}.issubset(df_cid.columns):
                tabelas["CID10"] = dict(zip(df_cid["codigo_datasus"].str.strip().str.upper(), df_cid["descricao"].str.strip()))
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
    from pysus import sim as api_sim_direct
    from pysus.api._impl.databases import sim as api_sim, sih as api_sih, cnes as api_cnes, sinasc as api_sinasc, sinan as api_sinan
except ImportError:
    api_sim_direct = api_sim = api_sih = api_cnes = api_sinasc = api_sinan = None

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

def limpar_cache_pysus_sih():
    caminhos_cache = [
        os.path.expanduser("~/pysus/downloads/ducklake/sih"),
        os.path.expanduser("~/pysus/downloads/sih"),
        os.path.expanduser("~/pysus/sih"),
        os.path.expanduser("~/PySUS/sih")
    ]
    for caminho in caminhos_cache:
        if os.path.exists(caminho):
            try: shutil.rmtree(caminho)
            except: pass

def normalizar_codigo(valor):
    if pd.isna(valor): return ""
    return str(valor).strip().replace(".0", "")

def decodificar_idade_datasus_anos(v):
    try:
        v = str(v).replace(".0", "").strip()
        if not v or not v.isdigit(): return -1
        if len(v) <= 2: return int(v)
        prefixo, valor = v[0], int(v[1:])
        if prefixo == '4': return valor
        if prefixo == '5': return 100 + valor
        if prefixo in ['1', '2', '3', '0']: return 0 
        return int(v) 
    except: return -1

def agrupar_faixa_etaria(idade):
    if idade < 0: return "Ignorado"
    if idade < 15: return "0 a 14 anos"
    if idade < 20: return "15 a 19 anos"
    if idade < 40: return "20 a 39 anos"
    if idade < 60: return "40 a 59 anos"
    return "60 anos ou mais"

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

def decodificar_tp_unid(codigo):
    dic_unid = {
        "01": "Posto de Saúde", "02": "Centro de Saúde / Unidade Básica", "04": "Policlínica",
        "05": "Hospital Geral", "07": "Hospital Hospitalizado", "15": "Unidade Mista",
        "20": "Pronto Socorro Geral", "21": "Pronto Socorro Especializado", "22": "Consultório Isolado",
        "32": "Unidade Móvel Fluvial", "36": "Clínica / Centro de Especialidade",
        "39": "Unidade de Apoio Diagnose e Terapia — SADT Isolado", "40": "Unidade Móvel Terrestre",
        "42": "Unidade Móvel de Nível Pré-Hospitalar na Área de Urgência", "43": "Farmácia",
        "50": "Unidade de Vigilância em Saúde", "60": "Cooperativa ou Empresa de Cessão de Trabalhadores na Saúde",
        "61": "Centro de Parto Normal — Isolado", "62": "Hospital/Dia — Isolado",
        "67": "Laboratório Central de Saúde Pública — LACEN", "68": "Central de Gestão em Saúde",
        "69": "Centro de Atenção Hemoterápica e/ou Hematológica", "70": "Centro de Atenção Psicossocial — CAPS",
        "71": "Centro de Apoio à Saúde da Família", "72": "Unidade de Atenção à Saúde Indígena",
        "73": "Pronto Atendimento", "74": "Polo Academia da Saúde", "75": "Telessaúde",
        "76": "Central de Regulação Médica das Urgências", "77": "Serviço de Atenção Domiciliar Isolado — Home Care",
        "78": "Unidade de Atenção em Regime Residencial", "79": "Oficina Ortopédica",
        "80": "Laboratório de Saúde Pública", "81": "Central de Regulação do Acesso",
        "82": "Central de Notificação, Captação e Distribuição de Órgãos Estadual",
        "83": "Polo de Prevenção de Doenças e Agravos e Promoção da Saúde",
        "84": "Central de Abastecimento", "85": "Centro de Imunização"
    }
    cod_str = str(codigo).strip().zfill(2)
    return dic_unid.get(cod_str, f"{cod_str} - Ignorado/Outros")

def aplicar_filtros_imediato(df_t, sistema, nivel_terr, uf, id_datasus_alvo, mes_num, cols_alvo_dict, dt_alvos, grupo=None):
    try:
        df_t = df_t.copy()
        df_t.columns = [str(c).upper().strip() for c in df_t.columns]
        
        if "SIM" in sistema and "TIPOBITO" in df_t.columns:
            df_t["TIPOBITO_STR"] = df_t["TIPOBITO"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
            df_t = df_t[df_t["TIPOBITO_STR"].isin(["1", "2"]) | df_t["TIPOBITO_STR"].isna() | (df_t["TIPOBITO_STR"] == "NAN")].copy()
            df_t = df_t.drop(columns=["TIPOBITO_STR"])

        cols_res = [x.upper() for x in cols_alvo_dict.get("res", [])]
        cols_oco = [x.upper() for x in cols_alvo_dict.get("oco", [])]
        
        col_filtro_res = next((c for c in df_t.columns if c in cols_res), None)
        col_filtro_oco = next((c for c in df_t.columns if c in cols_oco), None)
        dt_col_real = next((c for c in df_t.columns if c in dt_alvos), None)
        
        if nivel_terr == "Município" and not col_filtro_res and not col_filtro_oco:
            if grupo == "ER" or "ER" in sistema: return df_t
            return pd.DataFrame() 

        if "SINAN" in sistema and nivel_terr in ["Estado", "Município"]:
            col_estado = col_filtro_oco or col_filtro_res
            if col_estado:
                codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
                df_t.loc[:, col_estado] = df_t[col_estado].apply(normalizar_codigo)
                df_t = df_t[df_t[col_estado].str.startswith(codigo_uf_ibge)].copy()
        
        if nivel_terr == "Município":
            mask_res = pd.Series([False] * len(df_t), index=df_t.index)
            mask_oco = pd.Series([False] * len(df_t), index=df_t.index)
            
            if col_filtro_res:
                mask_res = df_t[col_filtro_res].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])
            if col_filtro_oco:
                mask_oco = df_t[col_filtro_oco].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])
                
            df_t = df_t[mask_res | mask_oco].copy()
        
        if sistema not in ["Internações (SIH)", "Cadastro Nacional de Estabelecimentos (CNES)"]:
            if mes_num is not None and dt_col_real:
                s = (df_t[dt_col_real].astype(str).str.replace(r"\.0$", "", regex=True).str.replace("-", "", regex=False).str.strip())
                mes_aaaammdd = pd.to_datetime(s, format="%Y%m%d", errors="coerce").dt.month
                mes_ddmmaaaa = pd.to_datetime(s, format="%d%m%Y", errors="coerce").dt.month
                meses_extraidos = mes_aaaammdd.fillna(mes_ddmmaaaa)
                df_t = df_t[meses_extraidos == mes_num].copy()
            
        return df_t
    except Exception as e:
        return pd.DataFrame()

def leitura_segura_parquet(caminho, limite=50000):
    try:
        caminho_sql = str(caminho).replace("'", "''")
        query = f"SELECT * FROM read_parquet('{caminho_sql}') LIMIT {limite}"
        return duckdb.query(query).df()
    except Exception as e:
        return pd.DataFrame()

# ===================================================================
# MÓDULO SIM COM FTP DIRETO E FALLBACKS (CORREÇÃO PARA RJ/SP)
# ===================================================================
def baixar_sim_ftp(uf, ano, grupo="DO"):
    try:
        from pysus.ftp.databases.sim import SIM
        motor = SIM()
        motor.load()
        arquivos = motor.get_files(state=uf, year=str(ano)[-2:], group=grupo)
        if not arquivos:
            return None
        caminhos = motor.download(arquivos)
        return caminhos
    except Exception as e:
        st.warning(f"FTP SIM {grupo} falhou para {uf}/{ano}: {e}")
        return None

def baixar_sim_online(uf, ano, grupo="DO"):
    try:
        from pysus.online_data.SIM import download as download_sim
        res = download_sim(uf, int(ano), group=grupo)
        return res
    except:
        pass
    try:
        if grupo == "DO":
            res = api_sim(state=uf, year=int(ano))
        else:
            res = api_sim(state=uf, year=int(ano), group=grupo)
        return res
    except:
        return None

def processar_sim_uf(uf, ano, nivel_terr, id_filtro, mes_num, cols_alvo_dict, dt_alvos, tipo_resultado):
    df_geral = pd.DataFrame()
    df_fetal = pd.DataFrame()
    mensagens = []

    st.info(f"⬇️ Baixando SIM/DO para {uf}/{ano}...")
    caminhos_ftp = baixar_sim_ftp(uf, ano, "DO")
    if caminhos_ftp:
        mensagens.append(f"FTP DO: {len(caminhos_ftp)} arquivos baixados.")
        df_geral, _ = processar_retorno_pysus_duckdb(
            caminhos_ftp, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
        )
    else:
        st.info(f"Tentando online_data para DO...")
        res_geral = baixar_sim_online(uf, ano, "DO")
        if res_geral is not None:
            mensagens.append("Online DO obtido.")
            df_geral, _ = processar_retorno_pysus_duckdb(
                res_geral, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
            )
        else:
            mensagens.append("❌ DO não disponível.")

    st.info(f"⬇️ Baixando SIM/DOFET para {uf}/{ano}...")
    caminhos_ftp_fetal = baixar_sim_ftp(uf, ano, "DOFET")
    if caminhos_ftp_fetal:
        mensagens.append(f"FTP DOFET: {len(caminhos_ftp_fetal)} arquivos baixados.")
        df_fetal, _ = processar_retorno_pysus_duckdb(
            caminhos_ftp_fetal, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
        )
    else:
        st.info(f"Tentando online_data para DOFET...")
        res_fetal = baixar_sim_online(uf, ano, "DOFET")
        if res_fetal is not None:
            mensagens.append("Online DOFET obtido.")
            df_fetal, _ = processar_retorno_pysus_duckdb(
                res_fetal, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
            )
        else:
            mensagens.append("❌ DOFET não disponível.")

    df_combined = pd.DataFrame()
    if not df_geral.empty:
        df_combined = pd.concat([df_combined, df_geral], ignore_index=True)
    if not df_fetal.empty:
        if "TIPOBITO" not in df_fetal.columns:
            df_fetal["TIPOBITO"] = 1
        df_combined = pd.concat([df_combined, df_fetal], ignore_index=True)

    if df_combined.empty:
        mensagens.append("⚠️ Nenhum dado do SIM obtido para esta UF/ano.")
    else:
        mensagens.append(f"✅ Total combinado: {len(df_combined)} registros.")

    return df_combined, mensagens

# ===================================================================
# FUNÇÃO PRINCIPAL DE BUSCA (MODIFICADA PARA USAR O NOVO MÓDULO SIM)
# ===================================================================
def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, sih_grupo=None, cnes_grupo=None, nivel_terr="Estado", id_datasus_alvo="", tipo_resultado="Amostra limitada de microdados"):
    if not api_sim and not api_sim_direct: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    partes_final = [] 
    meses_para_baixar = [mes_num] if mes_num else [None]
    cols_alvo_dict = obter_colunas_territoriais(sistema, sih_grupo)
    dt_alvos = ["DTOBITO", "DTNASC", "DT_NOTIFIC", "DT_INTER"]
    falhas = []
    sucessos_download = 0
    id_filtro = id_datasus_alvo if nivel_terr == "Município" else ""

    for uf in ufs_lista:
        if "SIH" in sistema:
            if sih_grupo == "CM":
                st.error("O grupo SIH/CM exige rotina própria via pysus.ftp.databases.sih.SIH e não será processado no fluxo mensal UF/município desta versão.")
                st.stop()
                
            for m in meses_para_baixar:
                df_temp = pd.DataFrame()
                prefixo_token = f"{sih_grupo}{uf}{str(ano)[-2:]}{int(m):02d}" if m else f"{sih_grupo}{uf}{str(ano)[-2:]}"
                prefixo_token = prefixo_token.upper()

                limpar_cache_pysus_sih()

                res = None
                try: res = baixar_sih_motor_raiz(uf, ano, m, sih_grupo)
                except Exception: pass
                if not res: res = baixar_sih_validado(uf, ano, m, sih_grupo)
                if not res: res = baixar_sih_fallback_api(uf, ano, m, sih_grupo)

                if res is None:
                    falhas.append(f"SIH SEM REGISTROS OU ARQUIVO NÃO PUBLICADO PELO DATASUS | {uf} {ano}/{m}")
                    continue

                arquivos_norm = normalizar_lista_arquivos_pysus(res)

                if isinstance(arquivos_norm, pd.DataFrame):
                    df_temp = aplicar_filtros_imediato(arquivos_norm, sistema, nivel_terr, uf, id_filtro, m, cols_alvo_dict, dt_alvos, grupo=sih_grupo)
                else:
                    arquivos_norm = filtrar_arquivos_sih_exatos(arquivos_norm, uf, ano, m, sih_grupo)
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(
                        arquivos_norm, cols_alvo_dict, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado, prefixo_esperado=prefixo_token
                    )
                
                if not df_temp.empty:
                    partes_final.append(df_temp)
                    sucessos_download += 1
                else:
                    falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO TERRITORIAL | {uf} {ano}")
            continue

        if "CNES" in sistema:
            for m in meses_para_baixar:
                df_temp = pd.DataFrame()
                arquivos_lidos = 0
                try:
                    prefixo_token = f"{cnes_grupo}{uf}{str(ano)[-2:]}{int(m):02d}".upper()
                    try: res = api_cnes(state=uf, year=ano, month=m, group=cnes_grupo)
                    except: res = None
                    df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo_dict, id_filtro, sistema, nivel_terr, uf, m, dt_alvos, tipo_resultado, prefixo_esperado=prefixo_token)
                except Exception as e:
                    falhas.append(f"Erro {sistema} | {uf} {ano}/{m}: {e}")
                    continue

                if not df_temp.empty:
                    df_temp = aplicar_filtros_imediato(df_temp, sistema, nivel_terr, uf, id_datasus_alvo, m, cols_alvo_dict, dt_alvos)
                    if not df_temp.empty:
                        partes_final.append(df_temp)
                        sucessos_download += 1
                    else: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO FINAL | {uf} {ano}")
                else:
                    if arquivos_lidos > 0: falhas.append(f"{sistema} SEM REGISTROS APÓS FILTRO TERRITORIAL | {uf} {ano}")
                    else: falhas.append(f"{sistema} FALHA DE DOWNLOAD OU ARQUIVO INEXISTENTE | {uf} {ano}")
            continue

        # ====== MORTALIDADE (SIM) – USANDO NOVO MÓDULO ======
        if "SIM" in sistema:
            df_temp = pd.DataFrame()
            try:
              def processar_sim_uf(uf, ano, nivel_terr, id_filtro, mes_num, cols_alvo_dict, dt_alvos, tipo_resultado):
    df_geral = pd.DataFrame()
    df_fetal = pd.DataFrame()
    mensagens = []

    # Tenta o método online_data (mais compatível)
    try:
        from pysus.online_data.SIM import download as download_sim
        res_geral = download_sim(uf, int(ano), group="DO")
        if res_geral is not None:
            mensagens.append("Online DO obtido.")
            df_geral, _ = processar_retorno_pysus_duckdb(
                res_geral, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
            )
        else:
            mensagens.append("❌ DO não disponível via online.")
    except Exception as e:
        mensagens.append(f"Erro no DO online: {e}")

    try:
        res_fetal = download_sim(uf, int(ano), group="DOFET")
        if res_fetal is not None:
            mensagens.append("Online DOFET obtido.")
            df_fetal, _ = processar_retorno_pysus_duckdb(
                res_fetal, cols_alvo_dict, id_filtro, "Mortalidade (SIM)", nivel_terr, uf, mes_num, dt_alvos, tipo_resultado
            )
        else:
            mensagens.append("❌ DOFET não disponível via online.")
    except Exception as e:
        mensagens.append(f"Erro no DOFET online: {e}")

    df_combined = pd.DataFrame()
    if not df_geral.empty:
        df_combined = pd.concat([df_combined, df_geral], ignore_index=True)
    if not df_fetal.empty:
        if "TIPOBITO" not in df_fetal.columns:
            df_fetal["TIPOBITO"] = 1
        df_combined = pd.concat([df_combined, df_fetal], ignore_index=True)

    if df_combined.empty:
        mensagens.append("⚠️ Nenhum dado do SIM obtido.")
    else:
        mensagens.append(f"✅ Total combinado: {len(df_combined)} registros.")

    return df_combined, mensagens
    
        # ====== OUTROS SISTEMAS (SINASC, SINAN) ======
        df_temp = pd.DataFrame()
        arquivos_lidos = 0
        try:
            if "SINASC" in sistema: 
                res = api_sinasc(state=uf, year=ano)
                df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo_dict, id_filtro, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado)
            elif "SINAN" in sistema:
                try:
                    from pysus.online_data.SINAN import download as download_sinan
                    res = download_sinan(disease=agravo, years=[ano], states=[uf])
                except:
                    try: res = api_sinan(disease=agravo, year=ano)
                    except: res = api_sinan(disease=agravo, state=uf, year=ano)
                df_temp, arquivos_lidos = processar_retorno_pysus_duckdb(res, cols_alvo_dict, id_filtro, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado)
        except Exception as e:
            falhas.append(f"Download Error {sistema} | {uf} {ano}: {e}")
            continue

        if not df_temp.empty:
            df_temp = aplicar_filtros_imediato(df_temp, sistema, nivel_terr, uf, id_datasus_alvo, mes_num, cols_alvo_dict, dt_alvos)
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
            return pd.DataFrame({"Erro": ["A base foi processada, mas não há registros para o território, período ou agravo selecionados. O Datasus pode não ter publicado esses dados ainda."] })
        else:
            return pd.DataFrame({"Erro": ["Falha de conexão ou arquivo inexistente no DATASUS para os filtros selecionados."] })
    return pd.concat(partes_final, ignore_index=True)

# Funções auxiliares para SIH
def baixar_sih_motor_raiz(uf, ano, mes, grupo):
    try:
        from pysus.ftp.databases.sih import SIH
        motor_sih = SIH()
        motor_sih.load()
        ano_str = str(ano)[-2:]
        mes_str = f"{int(mes):02d}" if mes else ""
        arquivos_esperados = motor_sih.get_files(dis_group=grupo, uf=uf, year=ano_str, month=mes_str)
        if not arquivos_esperados: return None
        return motor_sih.download(arquivos_esperados)
    except Exception as e: return None

def baixar_sih_validado(uf, ano, mes, grupo):
    max_retries = 3
    for tentativa in range(max_retries):
        try:
            from pysus.online_data.SIH import download
            obj = download(uf, int(ano), int(mes), grupo)
            if hasattr(obj, "to_dataframe"): return obj.to_dataframe()
            if hasattr(obj, "to_pandas"): return obj.to_pandas()
            if isinstance(obj, pd.DataFrame): return obj
            return obj
        except Exception as e:
            if "RemoteProtocolError" in str(e) or "connection" in str(e).lower():
                limpar_cache_pysus_sih()
                time.sleep(2)
                continue
            break 
    return None

def baixar_sih_fallback_api(uf, ano, mes, grupo):
    res = None
    tentativas_assinatura = [
        {"state": uf, "year": int(ano), "month": int(mes), "groups": [grupo]},
        {"state": uf, "year": int(ano), "month": int(mes), "group": grupo},
        {"state": uf, "year": int(ano), "month": int(mes)}
    ]
    for param in tentativas_assinatura:
        max_retries = 3
        for tentativa in range(max_retries):
            try:
                res = api_sih(**param)
                if res is not None: return res
            except Exception as e:
                if "RemoteProtocolError" in str(e) or "connection" in str(e).lower():
                    limpar_cache_pysus_sih()
                    time.sleep(2)
                    continue
                break 
    return res

def normalizar_lista_arquivos_pysus(res):
    if res is None: return []
    if isinstance(res, pd.DataFrame): return res
    if hasattr(res, "to_dataframe"): 
        try: return res.to_dataframe()
        except: pass
    if hasattr(res, "to_pandas"): 
        try: return res.to_pandas()
        except: pass
    if isinstance(res, str): return [res]
    if isinstance(res, list):
        caminhos = []
        frames = []
        for item in res:
            if isinstance(item, pd.DataFrame): frames.append(item)
            elif hasattr(item, "to_dataframe"): 
                try: frames.append(item.to_dataframe())
                except: pass
            elif hasattr(item, "to_pandas"): 
                try: frames.append(item.to_pandas())
                except: pass
            elif isinstance(item, str): caminhos.append(item)
            elif hasattr(item, "__fspath__"): caminhos.append(os.fspath(item))
            elif hasattr(item, "path"): caminhos.append(str(item.path))
            else: caminhos.append(str(item))
        if frames: return pd.concat(frames, ignore_index=True)
        return caminhos
    if hasattr(res, "__fspath__"): return [os.fspath(res)]
    if hasattr(res, "path"): return [str(res.path)]
    return [str(res)]

def filtrar_arquivos_sih_exatos(arquivos, uf, ano, mes, grupo):
    if isinstance(arquivos, pd.DataFrame): return arquivos
    ano2 = str(ano)[-2:]
    mes2 = f"{int(mes):02d}" if mes is not None else ""
    prefixo_exato = f"{grupo.upper()}{uf.upper()}{ano2}{mes2}"
    
    selecionados = []
    outros_grupos = {"RD", "SP", "ER", "CM", "RJ", "CH"} - {grupo.upper()}
    
    for caminho in arquivos:
        nome = os.path.basename(str(caminho)).upper()
        if grupo.upper() == "RD":
            if any(nome.startswith(g) for g in ["SP", "ER", "CM", "RJ", "CH"]): continue
            if uf.upper() in nome: selecionados.append(caminho)
        else:
            if nome.startswith(prefixo_exato) or (grupo.upper() in nome and uf.upper() in nome):
                selecionados.append(caminho)
                
    if not selecionados and arquivos:
        return arquivos
    return selecionados

def processar_retorno_pysus_duckdb(res, cols_alvo_dict, id_alvo, sistema, nivel_terr, uf, mes_num, dt_alvos, tipo_resultado="Amostra limitada de microdados", prefixo_esperado=None):
    arquivos_lidos = 0
    try:
        if isinstance(res, pd.DataFrame):
            arquivos_lidos = 1
            return aplicar_filtros_imediato(res, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo_dict, dt_alvos, group=prefixo_esperado[:2] if prefixo_esperado else None), arquivos_lidos

        if isinstance(res, str): res = [res]
        if isinstance(res, list) and len(res) > 0:
            frames = []
            for r in res:
                if isinstance(r, pd.DataFrame):
                    arquivos_lidos += 1
                    df_r = aplicar_filtros_imediato(r, sistema, nivel_terr, uf, id_alvo, mes_num, cols_alvo_dict, dt_alvos)
                    if not df_r.empty: frames.append(df_r)
                    continue

                caminho = os.fspath(r) if hasattr(r, "__fspath__") else str(r)
                if not caminho.endswith(".parquet"): continue

                nome_arquivo = os.path.basename(caminho).upper()
                
                if prefixo_esperado and sistema == "Internações (SIH)":
                    prefixo = str(prefixo_esperado).upper()
                    grupo_solicitado = prefixo[:2]
                    outros_grupos = {"RD", "SP", "ER", "CM", "RJ", "CH"} - {grupo_solicitado}
                    if any(nome_arquivo.startswith(g) for g in outros_grupos): continue
                    if uf.upper() not in nome_arquivo: continue

                arquivos_lidos += 1
                caminho_sql = caminho.replace("'", "''")

                try:
                    cols_parquet = duckdb.query(f"DESCRIBE SELECT * FROM read_parquet('{caminho_sql}')").df()["column_name"].tolist()
                    cols_upper = [c.upper() for c in cols_parquet]
                    cols_res = [x.upper() for x in cols_alvo_dict.get("res", [])]
                    cols_oco = [x.upper() for x in cols_alvo_dict.get("oco", [])]
                    
                    col_filtro_res = next((c for c in cols_parquet if c.upper() in cols_res), None)
                    col_filtro_oco = next((c for c in cols_parquet if c.upper() in cols_oco), None)

                    if id_alvo and nivel_terr == "Município":
                        id_sql = str(id_alvo).replace("'", "''")[:6]
                        where_clauses = []
                        if col_filtro_res: where_clauses.append(f"CAST(\"{col_filtro_res}\" AS VARCHAR) LIKE '{id_sql}%'")
                        if col_filtro_oco: where_clauses.append(f"CAST(\"{col_filtro_oco}\" AS VARCHAR) LIKE '{id_sql}%'")
                        
                        if where_clauses:
                            where_str = " OR ".join(where_clauses)
                            if "SIM" in sistema and "TIPOBITO" in cols_upper:
                                col_tb = cols_parquet[cols_upper.index("TIPOBITO")]
                                query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE ({where_str}) AND (TRY_CAST(TRY_CAST(\"{col_tb}\" AS DOUBLE) AS INT) IN (1, 2) OR \"{col_tb}\" IS NULL)"
                            else:
                                query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE {where_str}"
                            df = duckdb.query(query).df()
                            frames.append(df)
                        elif prefixo_esperado and "ER" in prefixo_esperado:
                            query = f"SELECT * FROM read_parquet('{caminho_sql}')"
                            df = duckdb.query(query).df()
                            frames.append(df)
                            
                    elif nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                        col_mun_agreg = col_filtro_oco or col_filtro_res
                        if not col_mun_agreg:
                            col_mun_agreg = next((c for c in cols_parquet if c.upper() in ["MUNIC_RES", "SP_MUNRES", "ID_MN_RESI", "ID_MUNICIP", "CODUFMUN"]), None)
                            
                        if col_mun_agreg:
                            codigo_uf = ESTADOS_IBGE.get(uf, "")
                            where_uf = f"WHERE CAST(\"{col_mun_agreg}\" AS VARCHAR) LIKE '{codigo_uf}%'" if "SINAN" in sistema and codigo_uf else ""
                            query = f"SELECT \"{col_mun_agreg}\" AS CODIGO_MUNICIPIO, COUNT(*) AS TOTAL_REGISTROS FROM read_parquet('{caminho_sql}') {where_uf} GROUP BY \"{col_mun_agreg}\" ORDER BY TOTAL_REGISTROS DESC"
                            df = duckdb.query(query).df()
                            frames.append(df)
                        else:
                            frames.append(leitura_segura_parquet(caminho, limite=50000))
                    else:
                        codigo_uf = ESTADOS_IBGE.get(uf, "")
                        col_estado = col_filtro_oco or col_filtro_res
                        if "SINAN" in sistema and nivel_terr == "Estado" and col_estado and codigo_uf:
                            query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE CAST(\"{col_estado}\" AS VARCHAR) LIKE '{codigo_uf}%' LIMIT 150000"
                        elif "SIM" in sistema and "TIPOBITO" in cols_upper:
                            col_tb = cols_parquet[cols_upper.index("TIPOBITO")]
                            query = f"SELECT * FROM read_parquet('{caminho_sql}') WHERE TRY_CAST(TRY_CAST(\"{col_tb}\" AS DOUBLE) AS INT) IN (1, 2) OR \"{col_tb}\" IS NULL"
                        else:
                            query = f"SELECT * FROM read_parquet('{caminho_sql}')" 
                        df = duckdb.query(query).df()
                        frames.append(df)
                except Exception as e:
                    frames.append(leitura_segura_parquet(caminho, limite=50000))
            if frames: return pd.concat(frames, ignore_index=True), arquivos_lidos
    except Exception as e:
        pass
    return pd.DataFrame(), arquivos_lidos

def gerar_metricas_cnes(df, grupo):
    df = df.copy()
    df.columns = [str(c).upper().strip() for c in df.columns]
    metricas = {"grupo": grupo, "registros": len(df), "estabelecimentos_unicos": df["CNES"].nunique() if "CNES" in df.columns else None}
    if grupo == "ST":
        metricas["principal_label"] = "Estabelecimentos unicos"
        metricas["principal_value"] = metricas["estabelecimentos_unicos"] if metricas["estabelecimentos_unicos"] else len(df)
    elif grupo == "PF":  
        metricas["principal_label"] = "Vinculos profissionais"
        metricas["principal_value"] = len(df)
    elif grupo in ["SR", "HB", "IN", "EP", "DC"]:
        metricas["principal_label"] = "Registros"
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
    else:
        metricas["principal_label"] = "Registros processados"
        metricas["principal_value"] = len(df)
    return metricas

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    df_tratado.columns = [str(c).upper().strip() for c in df_tratado.columns]
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES" if "CNES" in sistema else "SINAN"
    
    dic_dinamico = dict(CONFIG_APP.get("DICIONARIOS_VALORES", {}))
    dic_sih = dict(dic_dinamico.get("SIH", {}))
    dic_sih.update({"SEXO": {"1": "Masculino", "3": "Feminino"}, "MORTE": {"0": "Alta", "1": "Óbito"}})
    dic_dinamico["SIH"] = dic_sih
    
    dic_sinasc = dict(dic_dinamico.get("SINASC", {}))
    dic_sinasc.update({
        "ESCMAE": {"1": "Nenhuma", "2": "1 a 3 anos", "3": "4 a 7 anos", "4": "8 a 11 anos", "5": "12 anos e mais", "9": "Ignorado"},
        "ESCMAE2010": {"0": "Sem escolaridade", "1": "Fundamental I", "2": "Fundamental II", "3": "Médio", "4": "Superior incompleto", "5": "Superior completo", "9": "Ignorado"},
        "RACACORMAE": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"}
    })
    dic_dinamico["SINASC"] = dic_sinasc

    if "NU_IDADE_N" in df_tratado.columns: 
        df_tratado["Idade (Anos)"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus_anos)
        df_tratado["Faixa Etária"] = df_tratado["Idade (Anos)"].apply(agrupar_faixa_etaria)
    elif "IDADE" in df_tratado.columns:
        df_tratado["Idade (Anos)"] = df_tratado["IDADE"].apply(decodificar_idade_datasus_anos)
        df_tratado["Faixa Etária"] = df_tratado["Idade (Anos)"].apply(agrupar_faixa_etaria)
        
    if "IDADEMAE" in df_tratado.columns: 
        df_tratado["Idade Mãe (Anos)"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus_anos)
        df_tratado["Faixa Etária da Mãe"] = df_tratado["Idade Mãe (Anos)"].apply(agrupar_faixa_etaria)

    if "TP_SEXUAL" in df_tratado.columns:
        dic_sexual = {"1": "Com Homens", "2": "Com Mulheres", "3": "Ambos", "4": "Não sexual", "9": "Ignorado"}
        df_tratado["Transmissão (Sexual)"] = df_tratado["TP_SEXUAL"].astype(str).str.replace('.0','', regex=False).map(dic_sexual).fillna("Ignorado")
        
    if "NOBAIINF" in df_tratado.columns: df_tratado["Bairro Provável Infecção"] = df_tratado["NOBAIINF"]
    elif "NM_BAIRRO" in df_tratado.columns: df_tratado["Bairro Provável Infecção"] = df_tratado["NM_BAIRRO"]

    if "FANTASIA" in df_tratado.columns: df_tratado["Nome Unidade"] = df_tratado["FANTASIA"]
    if "NO_FANTASIA" in df_tratado.columns: df_tratado["Nome Unidade"] = df_tratado["NO_FANTASIA"]
    
    col_sus = next((c for c in df_tratado.columns if c in ["VINC_SUS", "ATENDE_SUS", "CONVENIO_SUS"]), None)
    if col_sus: 
        df_tratado["Atende SUS?"] = df_tratado[col_sus].astype(str).str.replace('.0','', regex=False).map({"1": "Sim", "0": "Não", "S": "Sim", "N": "Não"}).fillna("Não Informado")

    if "TP_UNID" in df_tratado.columns:
        df_tratado["Tipo de Estabelecimento"] = df_tratado["TP_UNID"].apply(decodificar_tp_unid)

    dic_circ = {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros", "9": "Ignorado"}
    col_circ = next((c for c in df_tratado.columns if c in ["CIRCOBITO"]), None)
    if col_circ:
        df_tratado["Circunstância do Óbito"] = df_tratado[col_circ].astype(str).str.replace(".0", "", regex=False).map(dic_circ).fillna("Natural/Outra")
        
    dic_lococor = {"1": "Hospital", "2": "Outro estab. saúde", "3": "Domicílio", "4": "Via Pública", "5": "Outros", "9": "Ignorado"}
    col_loc = next((c for c in df_tratado.columns if c in ["LOCOCOR"]), None)
    if col_loc:
        df_tratado["Local de Ocorrência"] = df_tratado[col_loc].astype(str).str.replace(".0", "", regex=False).map(dic_lococor).fillna("Ignorado/Outros")

    for c_vbo in ["OCUP", "OCUPMAE", "CODOCUPMAE", "ID_OCUPA_N", "COD_CBO"]:
        if c_vbo in df_tratado.columns: df_tratado[c_vbo] = df_tratado[c_vbo].apply(decodificar_cbo)

    dict_cid = TABELAS_EXTERNAS.get("CID10", {})
    for col in ["CAUSABAS", "DIAG_PRINC", "DIAG_SECUN", "ID_AGRAVO"]:
        if col in df_tratado.columns: df_tratado[col] = df_tratado[col].apply(lambda x: decodificar_cid(x, dict_cid))

    dict_sigtap = TABELAS_EXTERNAS.get("SIGTAP", {})
    for col in ["PROC_REA", "PROC_SOLIC"]:
        if col in df_tratado.columns: df_tratado[col] = df_tratado[col].apply(lambda x: decodificar_sigtap(x, dict_sigtap))

    for coluna, de_para in dic_dinamico.get(sigla_sistema, {}).items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].apply(normalizar_codigo).map(de_para).fillna("Ignorado/Outros")
            
    cabecalhos = dict(CONFIG_APP.get("TRADUCAO_CABECALHOS", {}))
    cab_sih = dict(cabecalhos.get("SIH", {}))
    cab_sih.update({"SEXO": "Sexo Paciente", "MORTE": "Desfecho (Alta/Óbito)", "VAL_TOT": "Valor Total AIH (R$)", "VAL_UTI": "Valor UTI (R$)", "DIAG_PRINC": "Diagnóstico Principal (CID-10)", "PROC_REA": "Procedimento Realizado (SIGTAP)"})
    cabecalhos["SIH"] = cab_sih
    
    cab_sinasc = dict(cabecalhos.get("SINASC", {}))
    cab_sinasc.update({"ESCMAE": "Escolaridade Mãe (Anos)", "ESCMAE2010": "Escolaridade Mãe (2010)", "CODOCUPMAE": "Ocupação/Profissão Mãe (CBO)", "RACACORMAE": "Raça/Cor da Mãe"})
    cabecalhos["SINASC"] = cab_sinasc
    
    df_tratado = df_tratado.rename(columns=cabecalhos.get(sigla_sistema, {}))
    df_tratado = df_tratado.loc[:, ~df_tratado.columns.duplicated()]
    return df_tratado

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

    uf_sel = st.sidebar.selectbox("Selecione o Estado:", ufs_ordenadas, index=ufs_ordenadas.index("MG"))
    muns_estado = buscar_municipios_por_uf(uf_sel)
    mapa_ibge = {dados['id6']: nome for nome, dados in muns_estado.items()}
    for nome, dados in muns_estado.items(): mapa_ibge[dados['id7']] = nome

    if nivel_terr == "Estado":
        ufs_selecionadas = [uf_sel]; id_ibge_alvo = ESTADOS_IBGE[uf_sel]; nome_local = uf_sel
    elif nivel_terr == "Município":
        mun_nome = st.sidebar.selectbox("Selecione o Município:", sorted(muns_estado.keys()))
        dados_mun = muns_estado[mun_nome]
        ufs_selecionadas = [uf_sel]; id_ibge_alvo = dados_mun['id7']; id_datasus_alvo = dados_mun['id6']; nome_local = mun_nome

    if fonte == "🏥 Saúde (DATASUS)":
        sistema = st.sidebar.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Nascimentos (SINASC)", "Cadastro Nacional de Estabelecimentos (CNES)", "Notificações (SINAN)"])
        
        if nivel_terr == "Estado" and sistema in BASES_PESADAS:
            tipo_resultado = st.sidebar.radio("Tipo de resultado estadual:", ["Resumo agregado", "Amostra limitada de microdados"])
        else:
            tipo_resultado = "Microdados filtrados"

        agravo_sel = sih_grupo_sel = cnes_grupo_sel = nome_agravo = None
        
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

            if trava_global.locked():
                st.error("🛑 Há outra extração complexa em andamento neste servidor. Por segurança de memória do Streamlit Cloud, aguarde 10 segundos e clique novamente.")
                st.stop()
                
            with trava_global:
                with st.spinner(f"Processando via DuckDB para {nome_local}..."):
                    df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo, tipo_resultado)
                    
                    if not df_bruto.empty and "Erro" not in df_bruto.columns:
                        if nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Resumo agregado":
                            df_tratado = df_bruto.copy()
                            df_tratado.columns = ["CÓDIGO_MUNICÍPIO", "TOTAL_DE_REGISTROS"]
                            sistema_titulo = f"Resumo Agregado — {sistema}"
                        else:
                            df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                            sistema_titulo = f"SINAN ({nome_agravo})" if "SINAN" in sistema else f"SIH ({sih_grupo_sel})" if "SIH" in sistema else f"CNES ({cnes_grupo_sel})" if "CNES" in sistema else sistema.split(" (")[0]
                        
                        periodo_label = f"{mes_sel:02d}/{ano_sel}" if mes_sel else f"{ano_sel}"
                        
                        if nivel_terr == "Município" and "CNES" not in sistema:
                            cols_dict = obter_colunas_territoriais(sistema, sih_grupo_sel)
                            sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "SINAN"
                            cab_sistema = CONFIG_APP.get("TRADUCAO_CABECALHOS", {}).get(sigla_sistema, {})
                            
                            cols_res_candidatas = set(cols_dict.get("res", []))
                            cols_oco_candidatas = set(cols_dict.get("oco", []))

                            for orig in list(cols_res_candidatas):
                                if orig in cab_sistema:
                                    cols_res_candidatas.add(cab_sistema[orig])
                            for orig in list(cols_oco_candidatas):
                                if orig in cab_sistema:
                                    cols_oco_candidatas.add(cab_sistema[orig])

                            cols_res_existentes = [c for c in cols_res_candidatas if c in df_tratado.columns]
                            cols_oco_existentes = [c for c in cols_oco_candidatas if c in df_tratado.columns]

                            mask_res = pd.Series([False] * len(df_tratado), index=df_tratado.index)
                            for col in cols_res_existentes:
                                mask_res |= df_tratado[col].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])

                            mask_oco = pd.Series([False] * len(df_tratado), index=df_tratado.index)
                            for col in cols_oco_existentes:
                                mask_oco |= df_tratado[col].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])

                            mask_oco_fallback = pd.Series([False] * len(df_tratado), index=df_tratado.index)
                            for col_oco in cols_oco_existentes:
                                vazia = df_tratado[col_oco].isna() | (df_tratado[col_oco].astype(str).str.strip() == "")
                                mask_oco_fallback |= (vazia & mask_res)

                            mask_oco = mask_oco | mask_oco_fallback
                            
                            if cols_oco_existentes and cols_res_existentes:
                                vol_oco = mask_oco.sum()
                                vol_res = mask_res.sum()
                                vol_ambos = (mask_oco & mask_res).sum()
                                vol_oco_fora = (mask_oco & ~mask_res).sum()
                                vol_res_fora = (mask_res & ~mask_oco).sum()
                                
                                col_res_principal = cols_res_existentes[0]
                                col_oco_principal = cols_oco_existentes[0]
                                
                                def classificar_relacao(row):
                                    r = str(row[col_res_principal]).startswith(id_datasus_alvo[:6])
                                    o = str(row[col_oco_principal]).startswith(id_datasus_alvo[:6])
                                    if r and o: return f"Morador ocorrido em {nome_local}"
                                    if o and not r: return f"Pessoa de fora ocorrida em {nome_local} (Importado)"
                                    if r and not o: return f"Morador de {nome_local} ocorrido em outra cidade (Exportado)"
                                    return "Outros"
                                df_tratado["Classificação_Migração"] = df_tratado.apply(classificar_relacao, axis=1)

                                st.markdown(f"### 📊 Visão Geral: {sistema_titulo} - {nome_local} ({periodo_label})")
                                
                                # ===== CORREÇÃO DOS CARDS PARA SIM =====
                                if "SIM" in sistema and "TIPOBITO" in df_tratado.columns:
                                    df_tratado["TB_CLEAN"] = df_tratado["TIPOBITO"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
                                    
                                    oco_geral = (mask_oco & (df_tratado["TB_CLEAN"] == "2")).sum()
                                    oco_fetal = (mask_oco & (df_tratado["TB_CLEAN"] == "1")).sum()
                                    res_geral = (mask_res & (df_tratado["TB_CLEAN"] == "2")).sum()
                                    res_fetal = (mask_res & (df_tratado["TB_CLEAN"] == "1")).sum()
                                    
                                    oco_total = oco_geral + oco_fetal
                                    res_total = res_geral + res_fetal

                                    c1, c2 = st.columns(2)
                                    c1.markdown(f'<div class="metric-card" style="border-left: 5px solid #007bff;"><h4>🏥 OCORRÊNCIA TOTAL</h4><h2 style="color:#007bff; margin:0;">{oco_total:,}</h2><p>Óbitos (fetais + não fetais) na cidade</p></div>', unsafe_allow_html=True)
                                    c2.markdown(f'<div class="metric-card" style="border-left: 5px solid #28a745;"><h4>🏠 RESIDÊNCIA TOTAL</h4><h2 style="color:#28a745; margin:0;">{res_total:,}</h2><p>Moradores (fetais + não fetais) falecidos</p></div>', unsafe_allow_html=True)
                                    
                                    df_tratado = df_tratado.drop(columns=["TB_CLEAN"])
                                elif "SIH" in sistema:
                                    for c_val in ["Valor Total AIH (R$)", "Valor UTI (R$)"]:
                                        if c_val in df_tratado.columns:
                                            df_tratado[f"Num_{c_val}"] = pd.to_numeric(df_tratado[c_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
                                    custo_oco = df_tratado.loc[mask_oco, "Num_Valor Total AIH (R$)"].sum() if "Num_Valor Total AIH (R$)" in df_tratado.columns else 0
                                    custo_res = df_tratado.loc[mask_res, "Num_Valor Total AIH (R$)"].sum() if "Num_Valor Total AIH (R$)" in df_tratado.columns else 0
                                    def f_br(val): return f"R$ {val:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                                    
                                    c1, c2, c3, c4 = st.columns(4)
                                    c1.markdown(f'<div class="metric-card" style="border-left: 5px solid #007bff;"><h4>🏥 ATENDIDOS NA CIDADE</h4><h2 style="color:#007bff; margin:0;">{vol_oco:,}</h2><p>Hospitais locais</p></div>', unsafe_allow_html=True)
                                    c2.markdown(f'<div class="metric-card" style="border-left: 5px solid #007bff;"><h4>💰 CUSTO OCORRÊNCIA</h4><h2 style="color:#007bff; margin:0;">{f_br(custo_oco)}</h2><p>Entrou nos Hospitais</p></div>', unsafe_allow_html=True)
                                    c3.markdown(f'<div class="metric-card" style="border-left: 5px solid #28a745;"><h4>🏠 MORADORES AFETADOS</h4><h2 style="color:#28a745; margin:0;">{vol_res:,}</h2><p>População local</p></div>', unsafe_allow_html=True)
                                    c4.markdown(f'<div class="metric-card" style="border-left: 5px solid #28a745;"><h4>💰 CUSTO RESIDÊNCIA</h4><h2 style="color:#28a745; margin:0;">{f_br(custo_res)}</h2><p>Gasto com Moradores</p></div>', unsafe_allow_html=True)
                                else:
                                    txt_oco = "NASCIMENTOS NA CIDADE" if "SINASC" in sistema else "NOTIFICADOS NA CIDADE" if "SINAN" in sistema else "ATENDIDOS NA CIDADE"
                                    txt_res = "MÃES RESIDENTES" if "SINASC" in sistema else "MORADORES AFETADOS"
                                    txt_oco_desc = "Partos na cidade" if "SINASC" in sistema else "Ocorrência registrada" if "SINAN" in sistema else "Hospitais locais"
                                    txt_res_desc = "Bebês de moradores" if "SINASC" in sistema else "População local"
                                    
                                    c1, c2 = st.columns(2)
                                    c1.markdown(f'<div class="metric-card" style="border-left: 5px solid #007bff;"><h4>🏥 {txt_oco}</h4><h2 style="color:#007bff; margin:0;">{vol_oco:,}</h2><p>{txt_oco_desc}</p></div>', unsafe_allow_html=True)
                                    c2.markdown(f'<div class="metric-card" style="border-left: 5px solid #28a745;"><h4>🏠 {txt_res}</h4><h2 style="color:#28a745; margin:0;">{vol_res:,}</h2><p>{txt_res_desc}</p></div>', unsafe_allow_html=True)
                                
                                st.markdown("---")
                                st.markdown("### 🗺️ Raio-X do Fluxo Geográfico (Migração de Pacientes/Eventos)")
                                col_mig1, col_mig2 = st.columns(2)
                                with col_mig1:
                                    st.markdown(f"**🏥 Eventos ocorridos em {nome_local} ({vol_oco}):**")
                                    st.write(f"- 🏠 **{vol_ambos}** referem-se a moradores da própria cidade.")
                                    st.write(f"- 🚑 **{vol_oco_fora}** vieram/são de fora. **De onde eles vieram?**")
                                    if vol_oco_fora > 0:
                                        df_in = df_tratado[mask_oco & ~mask_res].copy()
                                        df_in['Origem'] = df_in[col_res_principal].astype(str).str[:6].map(mapa_ibge).fillna("Outro Estado / Desconhecido")
                                        st.bar_chart(df_in['Origem'].value_counts().head(10), color="#007bff")
                                    else:
                                        st.info("Nenhuma ocorrência de pessoa de fora registrada na cidade.")
                                        
                                with col_mig2:
                                    st.markdown(f"**🏠 Moradores de {nome_local} na base ({vol_res}):**")
                                    st.write(f"- 🏥 **{vol_ambos}** permaneceram e foram assistidos na própria cidade.")
                                    st.write(f"- 🚑 **{vol_res_fora}** viajaram/ocorreram fora. **Para onde eles foram?**")
                                    if vol_res_fora > 0:
                                        df_out = df_tratado[mask_res & ~mask_oco].copy()
                                        df_out['Destino'] = df_out[col_oco_principal].astype(str).str[:6].map(mapa_ibge).fillna("Outro Estado / Desconhecido")
                                        st.bar_chart(df_out['Destino'].value_counts().head(10), color="#28a745")
                                    else:
                                        st.info("Nenhum morador precisou sair da cidade (Não há evasão).")

                            elif cols_oco_existentes and not cols_res_existentes:
                                st.warning("⚠️ **Aviso Técnico:** Este arquivo não informou a residência dos pacientes, apenas o local de ocorrência. O mapa de migração foi desabilitado para esta extração.")
                                mask_oco = pd.Series([False] * len(df_tratado), index=df_tratado.index)
                                for col in cols_oco_existentes:
                                    mask_oco |= df_tratado[col].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])
                                vol_oco = mask_oco.sum()
                                txt_oco = "ÓBITOS NA CIDADE" if "SIM" in sistema else "NASCIMENTOS NA CIDADE" if "SINASC" in sistema else "NOTIFICADOS NA CIDADE" if "SINAN" in sistema else "ATENDIDOS NA CIDADE"
                                st.markdown(f'<div class="metric-card" style="border-left: 5px solid #007bff;"><h4>🏥 {txt_oco}</h4><h2 style="color:#007bff; margin:0;">{vol_oco:,}</h2><p>Ocorrência / Produção Local</p></div>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<div class="metric-card"><h2>{len(df_bruto)} Registros Processados</h2><p>{sistema_titulo} - {nome_local} ({periodo_label})</p></div>', unsafe_allow_html=True)

                        else:
                            card_text = f"<h2>{len(df_bruto)} Registros Processados</h2>"
                            if "CNES" in sistema:
                                m_cnes = gerar_metricas_cnes(df_bruto, cnes_grupo_sel)
                                if cnes_grupo_sel == "ST": card_text = f"<h2>{m_cnes['principal_value']} Estabelecimentos Únicos</h2>"
                                elif cnes_grupo_sel == "PF": card_text = f"<h2>{m_cnes['principal_value']} Vínculos Profissionais</h2>"
                                elif cnes_grupo_sel == "EQ": card_text = f"<h2>{m_cnes['principal_value']} Equipamentos Existentes</h2>"
                                elif cnes_grupo_sel == "LT": card_text = f"<h2>{m_cnes['principal_value']} Leitos Existentes</h2>"
                                else: card_text = f"<h2>{len(df_bruto)} {m_cnes['principal_label'].lower()} processados</h2>"
                            st.markdown(f'<div class="metric-card">{card_text}<p>{sistema_titulo} - {nome_local} ({periodo_label})</p></div>', unsafe_allow_html=True)
                        
                        if nivel_terr == "Estado" and sistema in BASES_PESADAS and tipo_resultado == "Amostra limitada de microdados":
                            st.warning("Consulta estadual em base pesada. Para preservar o funcionamento do app, a visualização foi limitada a uma amostra de 50.000 registros. Para microdados completos, utilize filtro municipal ou exportação específica.")
                        
                        tab1, tab2, tab3 = st.tabs(["✅ Planilha Tratada", "⚙️ Planilha Bruta", "📈 Painel de Hospitais e Clínicas" if "CNES" in sistema else "📈 Painel Analítico"])
                        
                        with tab1:
                            st.dataframe(df_tratado, width="stretch")
                            st.download_button("📥 Baixar Tabela TRATADA Completa (CSV)", df_tratado.to_csv(index=False, sep=';', decimal=','), f"tratado_{sistema_titulo}_{nome_local}.csv", "text/csv")
                        with tab2:
                            st.dataframe(df_bruto, width="stretch")
                            st.download_button("📥 Baixar Tabela BRUTA Completa (CSV)", df_bruto.to_csv(index=False, sep=';', decimal=','), f"bruto_{sistema_titulo}_{nome_local}.csv", "text/csv")
                            
                        with tab3:
                            if (nivel_terr == "Estado" and sistema in BASES_PESADAS) or ("SINAN" in sistema and nivel_terr == "Estado" and len(df_tratado) >= 50000):
                                st.info("📊 Gráficos suspensos para consultas agregadas ou massivas de nível Estadual. Altere para o nível territorial 'Município' para visualizar os painéis analíticos.")
                            else:
                                df_dash = df_tratado.copy()
                                
                                if nivel_terr == "Município" and "CNES" not in sistema:
                                    if "SIH" in sistema:
                                        if cols_oco_existentes:
                                            st.info("🏥 **Lente Hospitalar/Ocorrência:** Os perfis clínicos e de custos abaixo focam nos **ATENDIDOS NA CIDADE**, mostrando a real produção dos hospitais locais.")
                                            col_oco_dash = cols_oco_existentes[0]
                                            df_dash = df_tratado[df_tratado[col_oco_dash].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])]
                                    else:
                                        if cols_res_existentes:
                                            st.info("🏠 **Lente Epidemiológica/Residência:** O painel abaixo foca exclusivamente na saúde dos **MORADORES DESTA CIDADE**, para facilitar o planejamento municipal e vacinal.")
                                            col_res_dash = cols_res_existentes[0]
                                            df_dash = df_tratado[df_tratado[col_res_dash].fillna("").astype(str).str.startswith(id_datasus_alvo[:6])]
                                
                                if "CNES" not in sistema:
                                    st.subheader(f"Perfil Demográfico/Clínico: {sistema_titulo}")
                                    
                                if "SIH" in sistema:
                                    c_faixa, c_sexo, c_morte = st.columns(3)
                                    with c_faixa:
                                        if "Faixa Etária" in df_dash.columns: st.bar_chart(df_dash["Faixa Etária"].value_counts().sort_index())
                                    with c_sexo:
                                        col_sexo = next((c for c in df_dash.columns if "Sexo Paciente" in c), None)
                                        if col_sexo: st.bar_chart(df_dash[col_sexo].value_counts())
                                    with c_morte:
                                        if "Desfecho (Alta/Óbito)" in df_dash.columns: st.bar_chart(df_dash["Desfecho (Alta/Óbito)"].value_counts())
                                    
                                    c_a, c_b = st.columns(2)
                                    if "Procedimento Realizado (SIGTAP)" in df_dash.columns:
                                        with c_a: st.bar_chart(df_dash["Procedimento Realizado (SIGTAP)"].value_counts().head(10))
                                    if "Diagnóstico Principal (CID-10)" in df_dash.columns:
                                        with c_b: st.bar_chart(df_dash["Diagnóstico Principal (CID-10)"].value_counts().head(10))
                                        
                                elif "SINASC" in sistema:
                                    c1, c2, c3 = st.columns(3)
                                    with c1:
                                        if "Faixa Etária da Mãe" in df_dash.columns: st.bar_chart(df_dash["Faixa Etária da Mãe"].value_counts().sort_index())
                                    with c2:
                                        if "Escolaridade Mãe (2010)" in df_dash.columns: st.bar_chart(df_dash["Escolaridade Mãe (2010)"].value_counts())
                                    with c3:
                                        col_cor_mae = next((c for c in df_dash.columns if "Raça/Cor da Mãe" in c), None)
                                        if col_cor_mae: st.bar_chart(df_dash[col_cor_mae].value_counts())

                                    c4, c5 = st.columns(2)
                                    with c4:
                                        if "Ocupação/Profissão Mãe (CBO)" in df_dash.columns: st.bar_chart(df_dash["Ocupação/Profissão Mãe (CBO)"].value_counts().head(10))
                                    with c5:
                                        col_sexo = next((c for c in df_dash.columns if "Sexo Bebê" in c), None)
                                        if col_sexo: st.bar_chart(df_dash[col_sexo].value_counts())
                                        
                                elif "CNES" in sistema:
                                    st.write("### 🏥 Estrutura e Capacidade Instalada")
                                    if cnes_grupo_sel == "ST":
                                        c1, c2 = st.columns([1, 2])
                                        with c1:
                                            st.write("**Tipos de Estabelecimentos (Top 10)**")
                                            if "Tipo de Estabelecimento" in df_dash.columns: st.bar_chart(df_dash["Tipo de Estabelecimento"].value_counts().head(10))
                                            st.write("**Atende ao SUS?**")
                                            if "Atende SUS?" in df_dash.columns: st.bar_chart(df_dash["Atende SUS?"].value_counts())
                                        with c2:
                                            st.write("**Top 15 Maiores Estabelecimentos da Cidade**")
                                            st.caption("🔍 Consulte os detalhes pelo código CNES em: https://cnes.datasus.gov.br/pages/estabelecimentos/consulta.jsp")
                                            if "Nome Unidade" in df_dash.columns:
                                                st.dataframe(df_dash[["CNES", "Nome Unidade", "Atende SUS?", "Tipo de Estabelecimento"]].head(15), use_container_width=True)
                                            else:
                                                st.dataframe(df_dash[["CNES"]].head(15), use_container_width=True)
                                    elif cnes_grupo_sel == "LT":
                                        c1, c2 = st.columns(2)
                                        with c1:
                                            st.write("**Volume Físico de Leitos na Cidade**")
                                            if "QT_SUS" in df_dash.columns and "QT_NSUS" in df_dash.columns:
                                                df_dash["QT_SUS"] = pd.to_numeric(df_dash["QT_SUS"], errors='coerce').fillna(0)
                                                df_dash["QT_NSUS"] = pd.to_numeric(df_dash["QT_NSUS"], errors='coerce').fillna(0)
                                                soma_sus = df_dash["QT_SUS"].sum()
                                                soma_nsus = df_dash["QT_NSUS"].sum()
                                                df_plot = pd.DataFrame({"Quantidade Física": [soma_sus, soma_nsus]}, index=["Leitos dedicados ao SUS", "Leitos Privados (Não SUS)"])
                                                st.bar_chart(df_plot)
                                        with c2:
                                            st.write("**Leitos de UTI vs Comuns**")
                                            st.info("Acesse a aba 'Planilha Tratada' para visualizar a quantidade física exata e detalhada por especialidade médica.")
                                    else:
                                        st.write("📈 *O Painel Gráfico prioriza as bases ST (Estabelecimentos) e LT (Leitos).*")

                                elif "SINAN" in sistema:
                                    c1, c2, c3 = st.columns(3)
                                    with c1:
                                        if "Faixa Etária" in df_dash.columns: st.bar_chart(df_dash["Faixa Etária"].value_counts().sort_index())
                                    with c2:
                                        col_sexo = next((c for c in df_dash.columns if "Sexo" in c), None)
                                        if col_sexo: st.bar_chart(df_dash[col_sexo].value_counts())
                                    with c3:
                                        col_raca = next((c for c in df_dash.columns if "Raça" in c), None)
                                        if col_raca: st.bar_chart(df_dash[col_raca].value_counts())
                                        
                                    if "Transmissão (Sexual)" in df_dash.columns:
                                        st.write("### Modo de Transmissão (AIDS/ISTs)")
                                        st.bar_chart(df_dash["Transmissão (Sexual)"].value_counts())
                                        
                                    if "Bairro Provável Infecção" in df_dash.columns:
                                        st.write("### Bairros de Infecção (Top 10)")
                                        st.bar_chart(df_dash["Bairro Provável Infecção"].value_counts().head(10))
                                        
                                elif "SIM" in sistema:
                                    c1, c2, c3 = st.columns(3)
                                    with c1:
                                        if "Faixa Etária" in df_dash.columns: st.bar_chart(df_dash["Faixa Etária"].value_counts().sort_index())
                                    with c2:
                                        col_sexo = next((c for c in df_dash.columns if "Sexo" in c), None)
                                        if col_sexo: st.bar_chart(df_dash[col_sexo].value_counts())
                                    with c3:
                                        col_raca = next((c for c in df_dash.columns if "Raça" in c), None)
                                        if col_raca: st.bar_chart(df_dash[col_raca].value_counts())
                                    
                                    st.write("---")
                                    c_a, c_b = st.columns(2)
                                    with c_a:
                                        st.write("### Causa Básica do Óbito")
                                        col_doenca = next((c for c in df_dash.columns if "Causa Básica (CID-10)" in c), None)
                                        if col_doenca: st.bar_chart(df_dash[col_doenca].value_counts().head(10))
                                    with c_b:
                                        if "Local de Ocorrência" in df_dash.columns: 
                                            st.write("### Local do Óbito")
                                            st.bar_chart(df_dash["Local de Ocorrência"].value_counts())
                                        
                                    if "Circunstância do Óbito" in df_dash.columns:
                                        st.write("---")
                                        st.write("### Circunstância do Óbito (Não Naturais)")
                                        st.bar_chart(df_dash["Circunstância do Óbito"].value_counts())
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
    with st.expander("🏥 CNES (Cadastro Nacional de Estabelecimentos de Saúde)"): st.markdown("...")
    with st.expander("🛏️ SIH (Sistema de Informações Hospitalares)"): st.markdown("...")
    with st.expander("💀 SIM (Sistema de Informações sobre Mortalidade)"): st.markdown("...")
    with st.expander("👶 SINASC (Sistema de Informações sobre Nascidos Vivos)"): st.markdown("...")
    with st.expander("🔬 SINAN (Sistema de Informação de Agravos de Notificação)"): st.markdown("...")
