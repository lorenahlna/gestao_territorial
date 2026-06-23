import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import gc
from datetime import datetime
import os

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

# --- FUNÇÕES BÁSICAS (ANOS E MESES) ---
@st.cache_data
def listar_anos_disponiveis(sistema="GERAL"):
    ano_atual = datetime.now().year
    limites = {
        "Mortalidade (SIM)": (1979, ano_atual - 1),
        "Nascimentos (SINASC)": (1994, 2020),
        "Notificações (SINAN)": (2007, ano_atual - 1),
        "Internações (SIH)": (2008, ano_atual),
        "Cadastro Nacional de Estabelecimentos (CNES)": (2005, ano_atual),
    }
    ano_inicial, ano_final = limites.get(sistema, (1995, ano_atual - 1))
    return list(range(ano_final, ano_inicial - 1, -1))

MESES_NOMES = [
    "Todos os Meses", "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
    "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
    "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"
]

# --- 1. PUXANDO O JSON DE CONFIGURAÇÕES (GITHUB) ---
@st.cache_data(show_spinner=False)
def carregar_dicionarios_github():
    URL_RAW_GITHUB = "https://raw.githubusercontent.com/lorenahlna/gestao_territorial/refs/heads/main/dicionarios.json"
    try:
        res = requests.get(URL_RAW_GITHUB, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.warning(f"⚠️ Aviso: Usando dicionários de contingência (Falha ao ler JSON: {e}).")
        return {
            "CBO_ESPECIFICOS": {"2251": "Médicos clínicos", "2235": "Enfermeiros"},
            "CBO_SUBGRUPOS": {"01": "Forças Armadas", "11": "Dirigentes", "22": "Profissionais de Saúde"},
            "DICIONARIOS_VALORES": {"SIM": {"SEXO": {"1": "Masculino", "2": "Feminino"}}},
            "TRADUCAO_CABECALHOS": {"SIM": {"CAUSABAS": "Causa Básica (CID-10)"}}
        }

CONFIG_APP = carregar_dicionarios_github()

# --- 2. INTEGRAÇÃO DOS DICIONÁRIOS PESADOS (CSV LOCAL E GITHUB) ---
@st.cache_data(show_spinner=False)
def carregar_tabelas_complementares():
    tabelas = {"CBO": {}, "CID10": {}, "SIGTAP": {}}
    
    if os.path.exists("tabela_cid10_codigo_descricao.csv"):
        try:
            df_cid = pd.read_csv("tabela_cid10_codigo_descricao.csv", sep=";", dtype=str, encoding='utf-8', on_bad_lines='skip')
            # Tratamento robusto das colunas
            if {"codigo_datasus", "descricao"}.issubset(df_cid.columns):
                df_cid["codigo_datasus"] = df_cid["codigo_datasus"].str.strip().str.upper()
                df_cid["descricao"] = df_cid["descricao"].str.strip()
                tabelas["CID10"] = dict(zip(df_cid["codigo_datasus"], df_cid["descricao"]))
            else:
                tabelas["CID10"] = dict(zip(df_cid.iloc[:, 0].str.strip().str.upper(), df_cid.iloc[:, 1].str.strip()))
        except Exception as e:
            st.sidebar.warning(f"Erro ao ler CID local: {e}")
            
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

# --- BLINDAGEM DE VARIÁVEIS DO PYSUS ---
try:
    from pysus.api._impl.databases import sim as api_sim, sih as api_sih, cnes as api_cnes, sinasc as api_sinasc, sinan as api_sinan
except ImportError:
    api_sim = api_sih = api_cnes = api_sinasc = api_sinan = None

# --- FUNÇÕES DE METADADOS E TERRITÓRIO ---
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

# --- TRATADORES DE DADOS (COM NORMALIZAÇÃO DE CÓDIGOS) ---

def normalizar_codigo(valor):
    if pd.isna(valor): return ""
    return str(valor).strip().replace(".0", "")

def extrair_mes_datasus(serie):
    s = (serie.astype(str)
         .str.replace(r"\.0$", "", regex=True)
         .str.replace("-", "", regex=False)
         .str.replace("/", "", regex=False)
         .str.strip())
    
    datas_aaaammdd = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    mes = datas_aaaammdd.dt.month
    
    faltantes = mes.isna()
    if faltantes.any():
        datas_ddmmaaaa = pd.to_datetime(s[faltantes], format="%d%m%Y", errors="coerce")
        mes.loc[faltantes] = datas_ddmmaaaa.dt.month
    return mes.astype("Int64")

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
    if dict_cbo:
        if cod_str in dict_cbo: return f"{cod_str} - {dict_cbo[cod_str]}"
        if cod_str[:4] in dict_cbo: return f"{cod_str} - {dict_cbo[cod_str[:4]]}"
        
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
    if dict_sigtap and cod in dict_sigtap:
        return f"{cod} - {dict_sigtap[cod]}"
    return cod

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    
    # Força TODAS as colunas para MAIÚSCULAS
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

    if "IDADE" in df_tratado.columns: df_tratado["IDADE"] = df_tratado["IDADE"].apply(decodificar_idade_datasus)
    if "IDADEMAE" in df_tratado.columns: 
        df_tratado["IDADEMAE"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus)
        df_tratado["GRUPO_IDADE_MAE"] = df_tratado["IDADEMAE"].apply(agrupar_idade_mae)
    if "NU_IDADE_N" in df_tratado.columns: df_tratado["NU_IDADE_N"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus)

    for c_cbo in ["OCUP", "OCUPMAE", "CODOCUPMAE", "ID_OCUPA_N"]:
        if c_cbo in df_tratado.columns: df_tratado[c_cbo] = df_tratado[c_cbo].apply(decodificar_cbo)

    dict_cid = TABELAS_EXTERNAS.get("CID10", {})
    for col in ["CAUSABAS", "DIAG_PRINC", "DIAG_SECUN", "ID_AGRAVO"]:
        if col in df_tratado.columns: df_tratado[col] = df_tratado[col].apply(lambda x: decodificar_cid(x, dict_cid))

    dict_sigtap = TABELAS_EXTERNAS.get("SIGTAP", {})
    for col in ["PROC_REA", "PROC_SOLIC"]:
        if col in df_tratado.columns: df_tratado[col] = df_tratado[col].apply(lambda x: decodificar_sigtap(x, dict_sigtap))

    # Aplicação de Dicionários com Normalização de Código (Resolve o bug do "1.0")
    for coluna, de_para in dic_dinamico.get(sigla_sistema, {}).items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].apply(normalizar_codigo).map(de_para).fillna("Ignorado/Outros")
            
    cabecalhos = CONFIG_APP.get("TRADUCAO_CABECALHOS", {})
    if "SIH" not in cabecalhos: cabecalhos["SIH"] = {}
    cabecalhos["SIH"].update({"SEXO": "Sexo Paciente", "MORTE": "Desfecho (Alta/Óbito)", "VAL_TOT": "Valor Total AIH (R$)", "VAL_UTI": "Valor UTI (R$)", "DIAG_PRINC": "Diagnóstico Principal (CID-10)", "PROC_REA": "Procedimento Realizado (SIGTAP)"})
    if "SINASC" not in cabecalhos: cabecalhos["SINASC"] = {}
    cabecalhos["SINASC"].update({"GRUPO_IDADE_MAE": "Faixa Etária da Mãe", "ESCMAE": "Escolaridade Mãe (Anos)", "ESCMAE2010": "Escolaridade Mãe (2010)", "CODOCUPMAE": "Ocupação/Profissão Mãe (CBO)", "RACACORMAE": "Raça/Cor da Mãe"})
    
    df_tratado = df_tratado.rename(columns=cabecalhos.get(sigla_sistema, {}))
    return df_tratado

# --- MOTOR DATASUS SEGURO E BLINDADO ---

def processar_retorno_pysus(res):
    """Garante o retorno consistente de um DataFrame válido"""
    if isinstance(res, pd.DataFrame): return res
    if hasattr(res, 'to_pandas'): return res.to_pandas()
    if isinstance(res, str) and res.endswith('.parquet'): return pd.read_parquet(res)
    if isinstance(res, list) and len(res) > 0:
        frames = [r.to_pandas() for r in res if hasattr(r, 'to_pandas')]
        if frames: return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()

def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, sih_grupo=None, cnes_grupo=None, nivel_terr="Brasil", id_datasus_alvo=""):
    if not api_sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    
    df_final = pd.DataFrame()
    meses_para_baixar = [mes_num] if mes_num else list(range(1, 13))

    cols_alvo = obter_colunas_municipio(sistema, sih_grupo)
    dt_alvos = ["DTOBITO", "DTNASC", "DT_NOTIFIC"]

    sinan_baixado = False
    falhas = []
    sucessos_download = 0

    for uf in ufs_lista:
        resultados = []
        
        if "SIH" in sistema or "CNES" in sistema:
            for m in meses_para_baixar:
                df_temp = pd.DataFrame()
                try:
                    if "SIH" in sistema:
                        try:
                            res = api_sih(state=uf, year=ano, month=m, group=sih_grupo, as_dataframe=True)
                        except TypeError:
                            res = api_sih(state=uf, year=ano, month=m, group=sih_grupo)
                        df_temp = processar_retorno_pysus(res)
                    elif "CNES" in sistema:
                        res = api_cnes(state=uf, year=ano, month=m, group=cnes_grupo)
                        df_temp = processar_retorno_pysus(res)
                except Exception as e:
                    falhas.append(f"{sistema} ({sih_grupo or cnes_grupo}) | {uf} {ano}/{m:02d}: {e}")
                    continue

                if not df_temp.empty:
                    resultados.append(df_temp)
                    sucessos_download += 1
                else:
                    falhas.append(f"{sistema} VAZIO | {uf} {ano}/{m:02d}")
                    
        else:
            df_temp = pd.DataFrame()
            try:
                if "SIM" in sistema: 
                    res = api_sim(state=uf, year=ano)
                    df_temp = processar_retorno_pysus(res)
                elif "SINASC" in sistema: 
                    res = api_sinasc(state=uf, year=ano)
                    df_temp = processar_retorno_pysus(res)
                elif "SINAN" in sistema:
                    if not (sinan_baixado and nivel_terr == "Brasil"):
                        try: res = api_sinan(disease=agravo, year=ano) 
                        except TypeError: res = api_sinan(disease=agravo, state=uf, year=ano)
                        df_temp = processar_retorno_pysus(res)
                        sinan_baixado = True
            except Exception as e:
                falhas.append(f"{sistema} | {uf} {ano}: {e}")
                continue

            if not df_temp.empty:
                resultados.append(df_temp)
                sucessos_download += 1
            else:
                falhas.append(f"{sistema} VAZIO | {uf} {ano}")
        
        for df_t in resultados:
            try:
                df_t.columns = [str(c).upper().strip() for c in df_t.columns]
                col_filtro_real = next((c for c in df_t.columns if c in [x.upper() for x in cols_alvo]), None)
                dt_col_real = next((c for c in df_t.columns if c in dt_alvos), None)
                
                if "SINAN" in sistema and nivel_terr in ["Estado", "Município"] and col_filtro_real:
                    codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
                    df_t = df_t[df_t[col_filtro_real].astype(str).str.startswith(codigo_uf_ibge)]
                
                if nivel_terr == "Município" and col_filtro_real:
                    df_t[col_filtro_real] = df_t[col_filtro_real].apply(normalizar_codigo)
                    df_t = df_t[df_t[col_filtro_real].str.startswith(id_datasus_alvo)]
                
                if mes_num is not None and dt_col_real:
                    meses_extraidos = extrair_mes_datasus(df_t[dt_col_real])
                    df_t = df_t[meses_extraidos == mes_num]
                
                if not df_t.empty: df_final = pd.concat([df_final, df_t], ignore_index=True)
                
                del df_t
                gc.collect()
            except Exception as e:
                falhas.append(f"Erro no Filtro | {uf}: {e}")
                continue
            
        del resultados
        gc.collect()
            
    if df_final.empty:
        if sucessos_download == 0 and len(falhas) > 0:
            return pd.DataFrame({"Erro": [f"🛑 FALHA DE CONEXÃO ou ARQUIVO INEXISTENTE. O DATASUS não retornou dados para este período.\nDetalhes: {falhas[0]}"]})
        else:
            return pd.DataFrame({"Erro": ["⚠️ FALTA DE DADOS: O download foi realizado, mas a tabela está vazia após a aplicação dos filtros geográficos/temporais."]})
    
    return df_final

# --- INTERFACE PRINCIPAL ---

st.sidebar.title("🧬 Navegação e Filtros")
aba_ativa = st.sidebar.radio("Navegar para:", ["📋 Guia Principal (Extração)", "📚 Dicionários e Citações"])

if aba_ativa == "📋 Guia Principal (Extração)":

    st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>DATASUS conectado | SIDRA e VIS DATA 3 em desenvolvimento</p></div>', unsafe_allow_html=True)

    fonte = st.sidebar.radio("Base de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3 - Indisponível)"])
    
    if "VIS DATA 3" in fonte:
        st.warning("VIS DATA 3 ainda não está conectado nesta versão.")
        st.stop()
        
    nivel_terr = st.sidebar.radio("Nível Territorial:", ["Brasil", "Estado", "Município"])

    ufs_selecionadas = UFS; id_ibge_alvo = "1"; id_datasus_alvo = ""

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
    else: nome_local = "Brasil"

    if fonte == "🏥 Saúde (DATASUS)":
        sistema = st.sidebar.selectbox("Sistema:", ["Mortalidade (SIM)", "Internações (SIH)", "Nascimentos (SINASC)", "Cadastro Nacional de Estabelecimentos (CNES)", "Notificações (SINAN)"])
        
        agravo_sel = sih_grupo_sel = cnes_grupo_sel = None
        
        if "SINAN" in sistema:
            mapa_doencas = {"Acidente de trabalho": "ACGR", "Acidente de trabalho com material biológico": "ACBI", "AIDS em adultos": "AIDA", "AIDS em crianças": "AIDC", "Câncer Relacionado ao Trabalho": "CANC", "Chikungunya": "CHIK", "Dengue": "DENG", "Doença de Chagas": "CHAG", "Hepatites Virais": "HEPA", "HIV em adultos": "HIVA", "HIV em crianças": "HIVC", "HIV em crianças expostas": "HIVE", "Leptospirose": "LEPT", "Meningite": "MENI", "Perda Auditiva por Ruído (Trabalho)": "PAIR", "Raiva Humana": "RAIV", "Sífilis Adquirida": "SIFA", "Sífilis Congênita": "SIFC", "Sífilis em Gestante": "SIFG", "Transtornos Mentais (Trabalho)": "MENT", "Tuberculose": "TUBE", "Varicela": "VARC", "Violência doméstica/sexual": "VIOL", "Zika Vírus": "ZIKA"}
            nome_agravo = st.sidebar.selectbox("Doença/Agravo:", sorted(list(mapa_doencas.keys())))
            agravo_sel = mapa_doencas[nome_agravo]
        elif "SIH" in sistema:
            mapa_sih = {"RD - Registros de Internações (Padrão)": "RD", "SP - Serviços Profissionais": "SP", "ER - Emergência Referenciada": "ER", "CM - Cirurgias Ambulatoriais": "CM"}
            sih_grupo_sel = mapa_sih[st.sidebar.selectbox("Grupo de Dados (SIH):", list(mapa_sih.keys()))]
        elif "CNES" in sistema:
            mapa_cnes = {"ST - Estabelecimentos": "ST", "PF - Profissionais": "PF", "SR - Serviços": "SR", "HB - Habilitações": "HB", "IN - Incentivos": "IN", "EP - Estabelecimento por Procedimento": "EP", "EQ - Equipamentos": "EQ", "LT - Leitos": "LT", "DC - Dados Complementares": "DC"}
            cnes_grupo_sel = mapa_cnes[st.sidebar.selectbox("Grupo de Dados (CNES):", list(mapa_cnes.keys()))]
        
        ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis(sistema))
        
        if "SINASC" in sistema and ano_sel >= 2021:
            st.sidebar.warning("⚠️ **Aviso de Migração Governamental:** Os microdados de Nascidos Vivos após 2020 foram movidos para o Portal de Dados Abertos. A conexão nativa (FTP) pode falhar.")
            
        nome_mes = st.sidebar.selectbox("Mês de Competência/Ocorrência (Opcional):", MESES_NOMES)
        mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])
        
        if st.button(f"🔍 Consultar Base"):
            with st.spinner(f"Processando requisição para {nome_local}... Isso pode demorar dependendo do tamanho do arquivo original."):
                df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo)
                
                if not df_bruto.empty and "Erro" not in df_bruto.columns:
                    df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                    
                    sistema_titulo = f"SINAN ({nome_agravo})" if "SINAN" in sistema else f"SIH ({sih_grupo_sel})" if "SIH" in sistema else f"CNES ({cnes_grupo_sel})" if "CNES" in sistema else sistema.split(" (")[0]
                    
                    st.markdown(f'<div class="metric-card"><h2>{len(df_bruto)} Registros Encontrados</h2><p>{sistema_titulo} - {nome_local} ({ano_sel})</p></div>', unsafe_allow_html=True)
                    
                    tab1, tab2, tab3 = st.tabs(["✅ Planilha Tratada", "⚙️ Planilha Bruta", "📈 Painel de Análises (Dashboards)"])
                    
                    with tab1:
                        st.dataframe(df_tratado.head(100), use_container_width=True)
                        st.download_button("📥 Baixar Tabela TRATADA (CSV)", df_tratado.to_csv(index=False, sep=';', decimal=','), f"tratado_{sistema_titulo}_{nome_local}.csv", "text/csv")
                    with tab2:
                        st.dataframe(df_bruto.head(100), use_container_width=True)
                        st.download_button("📥 Baixar Tabela BRUTA (CSV)", df_bruto.to_csv(index=False, sep=';', decimal=','), f"bruto_{sistema_titulo}_{nome_local}.csv", "text/csv")
                        
                    with tab3:
                        st.subheader(f"📊 Painel Analítico: {sistema_titulo}")
                        
                        if "SIH" in sistema:
                            c1, c2, c3 = st.columns(3)
                            for c_val in ["Valor Total AIH (R$)", "Valor UTI (R$)"]:
                                if c_val in df_tratado.columns:
                                    df_tratado[f"Num_{c_val}"] = pd.to_numeric(df_tratado[c_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
                            
                            soma_tot = df_tratado["Num_Valor Total AIH (R$)"].sum() if "Num_Valor Total AIH (R$)" in df_tratado.columns else 0
                            soma_uti = df_tratado["Num_Valor UTI (R$)"].sum() if "Num_Valor UTI (R$)" in df_tratado.columns else 0
                            
                            c1.metric("💰 Custo Total Pago (AIH)", f"R$ {soma_tot:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                            c2.metric("🏥 Custo em UTI", f"R$ {soma_uti:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
                            
                            c_sexo, c_morte = st.columns(2)
                            with c_sexo:
                                col_sexo = next((c for c in df_tratado.columns if "Sexo Paciente" in c), None)
                                if col_sexo:
                                    st.write(f"**Distribuição por Sexo**")
                                    st.bar_chart(df_tratado[col_sexo].value_counts())
                            with c_morte:
                                if "Desfecho (Alta/Óbito)" in df_tratado.columns:
                                    st.write("**Desfecho da Internação**")
                                    st.bar_chart(df_tratado["Desfecho (Alta/Óbito)"].value_counts())
                            
                            c_a, c_b = st.columns(2)
                            if "Procedimento Realizado (SIGTAP)" in df_tratado.columns:
                                with c_a:
                                    st.write("**Top 10 Procedimentos Realizados**")
                                    st.bar_chart(df_tratado["Procedimento Realizado (SIGTAP)"].value_counts().head(10))
                            if "Diagnóstico Principal (CID-10)" in df_tratado.columns:
                                with c_b:
                                    st.write("**Top 10 Causas de Internação (CID-10)**")
                                    st.bar_chart(df_tratado["Diagnóstico Principal (CID-10)"].value_counts().head(10))
                                
                        elif "SINASC" in sistema:
                            st.write("### Perfil da Mãe")
                            c1, c2 = st.columns(2)
                            with c1:
                                if "Faixa Etária da Mãe" in df_tratado.columns:
                                    st.write("**Idade das Mães no Parto**")
                                    st.bar_chart(df_tratado["Faixa Etária da Mãe"].value_counts().sort_index())
                            with c2:
                                col_esc = next((c for c in df_tratado.columns if "Escolaridade Mãe (2010)" in c or "Escolaridade Mãe" in c), None)
                                if col_esc:
                                    st.write(f"**{col_esc}**")
                                    st.bar_chart(df_tratado[col_esc].value_counts())
                                    
                            if "Ocupação/Profissão Mãe (CBO)" in df_tratado.columns:
                                st.write("**Top 10 Ocupações das Mães**")
                                st.bar_chart(df_tratado["Ocupação/Profissão Mãe (CBO)"].value_counts().head(10))
                                
                            st.write("---")
                            st.write("### Perfil do Nascido Vivo")
                            c3, c4, c5 = st.columns(3)
                            with c3:
                                col_sexo = next((c for c in df_tratado.columns if "Sexo Bebê" in c), None)
                                if col_sexo:
                                    st.write("**Sexo do Bebê**")
                                    st.bar_chart(df_tratado[col_sexo].value_counts())
                            with c4:
                                col_cor_bebe = next((c for c in df_tratado.columns if "Raça/Cor Bebê" in c), None)
                                if col_cor_bebe:
                                    st.write("**Raça/Cor do Bebê**")
                                    st.bar_chart(df_tratado[col_cor_bebe].value_counts())
                            with c5:
                                col_cor_mae = next((c for c in df_tratado.columns if "Raça/Cor da Mãe" in c), None)
                                if col_cor_mae:
                                    st.write("**Raça/Cor da Mãe**")
                                    st.bar_chart(df_tratado[col_cor_mae].value_counts())
                                
                        elif "CNES" in sistema:
                            st.write("📈 *O Painel Gráfico prioriza bases clínicas e epidemiológicas. Explore a lista bruta de recursos do CNES na aba de Planilha.*")
                            
                        elif "SIM" in sistema:
                            c1, c2 = st.columns(2)
                            col_sexo = next((c for c in df_tratado.columns if "Sexo" in c), None)
                            if col_sexo:
                                with c1:
                                    st.write(f"**Distribuição por {col_sexo}**")
                                    st.bar_chart(df_tratado[col_sexo].value_counts())
                            col_raca = next((c for c in df_tratado.columns if "Raça" in c), None)
                            if col_raca:
                                with c2:
                                    st.write(f"**Distribuição por {col_raca}**")
                                    st.bar_chart(df_tratado[col_raca].value_counts())
                            
                            c3, c4 = st.columns(2)
                            with c3:
                                col_circ = next((c for c in df_tratado.columns if "Circunstância do Óbito" in c), None)
                                if col_circ:
                                    st.write(f"**Circunstância do Óbito**")
                                    st.bar_chart(df_tratado[col_circ].value_counts())
                            with c4:
                                col_doenca = next((c for c in df_tratado.columns if "Causa Básica (CID-10)" in c), None)
                                if col_doenca:
                                    st.write(f"**Top 10 Causas de Mortalidade ({col_doenca})**")
                                    st.bar_chart(df_tratado[col_doenca].value_counts().head(10))
                        else:
                            c1, c2 = st.columns(2)
                            col_sexo = next((c for c in df_tratado.columns if "Sexo" in c), None)
                            if col_sexo:
                                with c1:
                                    st.write(f"**Distribuição por {col_sexo}**")
                                    st.bar_chart(df_tratado[col_sexo].value_counts())
                            col_raca = next((c for c in df_tratado.columns if "Raça" in c), None)
                            if col_raca:
                                with c2:
                                    st.write(f"**Distribuição por {col_raca}**")
                                    st.bar_chart(df_tratado[col_raca].value_counts())
                else:
                    msg = df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Sem dados disponíveis."
                    st.error(msg)

    st.markdown("""
        <div class="footer-text">
            <b>Fontes de Dados:</b> Ministério da Saúde (DATASUS) | IBGE<br>
            <i>Sistema construído com arquitetura PySUS e Dicionários Desacoplados. Otimizado com Garbage Collector (Limpeza de RAM ativa).</i>
        </div>
    """, unsafe_allow_html=True)

# 🌟 ABA DE DICIONÁRIOS E CITAÇÕES
elif aba_ativa == "📚 Dicionários e Citações":
    st.title("📚 Dicionários e Metadados")
    st.markdown("Consulte os Manuais Oficiais para entender a Planilha Tratada:")
    
    with st.expander("🏥 CNES (Cadastro Nacional de Estabelecimentos de Saúde)"):
        st.markdown("""
        O CNES é desdobrado em várias tabelas. As principais utilizadas no cruzamento e mapeamento são:
        * **Tabela ST (Estabelecimentos):** Contém os dados básicos de cada estabelecimento de saúde ativo no Brasil (localização, natureza jurídica, tipo de unidade). A chave `CNES` liga com SIH e SIA.
        * **Tabela PF (Profissionais):** Relação de profissionais vinculados, com código `CBO` e carga horária.
        * **Tabela EQ (Equipamentos):** Lista de equipamentos médicos vinculados ao estabelecimento.
        """)

    with st.expander("🛏️ SIH (Sistema de Informações Hospitalares)"):
        st.markdown("""
        * **Resumo:** Dados de internações hospitalares pelo SUS. A tabela do tipo RD (AIH Reduzida) contém o resumo clínico e financeiro da internação.
        * **DIAG_PRINC / DIAG_SECUN:** Diagnósticos registrados em formato CID-10, passíveis de mapeamento automático.
        * **PROC_REA / PROC_SOLIC:** Procedimentos realizados e solicitados. Cruzados automaticamente com a tabela SIGTAP.
        * **CGC_HOSP:** Identificação do hospital que pode ser relacionada ao Cadastro Nacional de Estabelecimentos (CNES).
        """)

    with st.expander("💀 SIM (Sistema de Informações sobre Mortalidade)"):
        st.markdown("""
        * **Resumo:** Registros de óbitos com campos demográficos e causas de morte codificadas por CID-10.
        * **CAUSABAS:** A causa básica do óbito (CID-10), crucial para análises de mortalidade.
        * **ESTCIV (Estado Civil):** 1-Solteiro | 2-Casado | 3-Viúvo | 4-Separado | 5-União estável | 9-Ignorado.
        * **ESC (Escolaridade em Anos):** Traduzido pelo sistema para o formato 2010 (Sem escolaridade, Fundamental I/II, Médio, Superior).
        * **OCUP (Ocupação):** Ramo de atividade, mapeado através do CBO-2002.
        * **TIPOBITO:** 1-Fetal | 2-Não fetal.
        * **CIRCOBITO:** 1-Acidente | 2-Suicídio | 3-Homicídio | 4-Outros.
        """)
        
    with st.expander("👶 SINASC (Sistema de Informações sobre Nascidos Vivos)"):
        st.markdown("""
        * **Resumo:** Dados sobre os recém-nascidos, perfil demográfico das mães e características do parto no Brasil.
        * **ESTCIVMAE (Estado Civil da Mãe):** 1-Solteira | 2-Casada | 3-Viúva | 4-Separada | 5-União Consensual | 9-Ignorado.
        * **ESCMAE (Escolaridade da Mãe):** O sistema categoriza em ciclos de ensino.
        * **GRAVIDEZ:** 1-Única | 2-Dupla | 3-Tripla ou mais.
        * **PARTO:** 1-Vaginal | 2-Cesáreo.
        * **PESO:** Peso do nascido vivo em gramas.
        """)

    with st.expander("🩺 SINAN (Sistema de Informação de Agravos de Notificação)"):
        st.markdown("""
        * **CS_ESCOL_N (Escolaridade):** 00-Sem instrução | 01-Fundamental I | 02-Fundamental II | 03-Médio | 04-Superior | 05-Não se aplica | 09-Ignorado.
        * **CS_EST_CIV (Estado Civil):** 1-Solteiro | 2-Casado | 3-Viúvo | 4-Separado/Divorciado | 9-Ignorado.
        * **CS_SEXO:** M-Masculino | F-Feminino | I-Ignorado.
        * **CS_RACA:** 1-Branca | 2-Preta | 3-Amarela | 4-Parda | 5-Indígena | 9-Ignorado.
        """)
        
    st.info("Sempre cite as fontes originais: BRASIL. Ministério da Saúde. DATASUS.")
