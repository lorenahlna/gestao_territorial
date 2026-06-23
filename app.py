import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import gc
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURAÇÃO DE DESIGN DA PÁGINA ---
st.set_page_config(
    page_title="Inteligência Territorial | SIDRA + DATASUS",
    page_icon="📊",
    layout="wide"
)

st.markdown("""
    <style>
    .header-sidra { background-color: #003366; padding: 20px; color: white; border-radius: 5px; text-align: center; margin-bottom: 20px; }
    .stButton>button { background-color: #003366; color: white; width: 100%; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; text-align: center;}
    .footer-text { text-align: center; color: #666; font-size: 14px; margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; }
    </style>
""", unsafe_allow_html=True)

# --- 1. PUXANDO O JSON DE CONFIGURAÇÕES (O SEU GITHUB) ---

@st.cache_data(show_spinner=False)
def carregar_dicionarios_github():
    URL_RAW_GITHUB = "https://raw.githubusercontent.com/lorenahlna/gestao_territorial/refs/heads/main/dicionarios.json"
    try:
        res = requests.get(URL_RAW_GITHUB, timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.warning("⚠️ Usando dicionários de contingência (Falha ao ler o JSON).")
        return {
            "CBO_ESPECIFICOS": {"2251": "Médicos clínicos", "2235": "Enfermeiros"},
            "CBO_SUBGRUPOS": {"01": "Forças Armadas", "11": "Dirigentes", "22": "Profissionais de Saúde"},
            "DICIONARIOS_VALORES": {"SIM": {"SEXO": {"1": "Masculino", "2": "Feminino", "M": "Masculino", "F": "Feminino"}}},
            "TRADUCAO_CABECALHOS": {"SIM": {"CAUSABAS": "Causa Básica (CID-10)"}}
        }

CONFIG_APP = carregar_dicionarios_github()

# --- 2. PUXANDO AS TABELAS PESADAS DO REPOSITÓRIO (CARTAPROALE) ---

@st.cache_data(show_spinner=False)
def carregar_tabelas_cartaproale():
    """Baixa dicionários pesados em CSV diretamente do repositório indicado"""
    BASE_RAW_URL = "https://raw.githubusercontent.com/cartaproale/PySUS/main/tabelas/"
    tabelas = {"CBO": {}, "CID10": {}}
    
    # 1. Tabela CBO (Profissões)
    try:
        # ⚠️ AJUSTE: Se o nome da tabela CBO for diferente no repo deles, altere o "cbo.csv" abaixo
        df_cbo = pd.read_csv(BASE_RAW_URL + "cbo.csv", sep=";", dtype=str, encoding='utf-8')
        # Cria o dicionário onde a Coluna 1 é a chave (Código) e a Coluna 2 é o valor (Descrição)
        tabelas["CBO"] = dict(zip(df_cbo.iloc[:, 0], df_cbo.iloc[:, 1]))
    except:
        pass
        
    # 2. Tabela CID-10 (Doenças)
    try:
        # ⚠️ AJUSTE: Se o nome da tabela CID for diferente, altere o "cid10.csv" abaixo
        df_cid = pd.read_csv(BASE_RAW_URL + "cid10.csv", sep=";", dtype=str, encoding='utf-8')
        tabelas["CID10"] = dict(zip(df_cid.iloc[:, 0], df_cid.iloc[:, 1]))
    except:
        pass
        
    return tabelas

TABELAS_CARTAPROALE = carregar_tabelas_cartaproale()

# --- FUNÇÕES DE METADADOS E TERRITÓRIO ---

UFS = ["AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"]

ESTADOS_IBGE = {
    "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29", "CE": "23", "DF": "53", "ES": "32",
    "GO": "52", "MA": "21", "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25", "PR": "41",
    "PE": "26", "PI": "22", "RJ": "33", "RN": "24", "RS": "43", "RO": "11", "RR": "14", "SC": "42",
    "SP": "35", "SE": "28", "TO": "17"
}

@st.cache_data
def buscar_municipios_por_uf(uf_sigla):
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_sigla}/municipios"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10).json()
        mun_dict = {}
        for m in res:
            nome = m['nome']
            id7 = str(m['id'])
            id6 = id7[:6] 
            mun_dict[nome] = {"id7": id7, "id6": id6, "nome": nome, "uf": uf_sigla}
        return mun_dict
    except:
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620", "nome": "Belo Horizonte", "uf": "MG"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc, sinan
except ImportError:
    sim = sih = cnes = sinasc = sinan = None

@st.cache_data
def listar_anos_disponiveis():
    return list(range(datetime.now().year, 1995, -1))

MESES_NOMES = [
    "Todos os Meses", "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
    "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
    "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"
]

# --- TRATADORES COM RECURSOS DO GITHUB INTEGRADOS ---

def decodificar_idade_datasus(valor):
    if pd.isna(valor) or str(valor).strip() == '': return "Não informado"
    try:
        valor_str = str(int(float(valor))).zfill(3)
        if len(valor_str) == 3:
            u, q = valor_str[0], int(valor_str[1:])
            if u == '1': return f"{q} Minuto(s)"
            elif u == '2': return f"{q} Hora(s)"
            elif u == '3': return f"{q} Mês(es)"
            elif u == '4': return f"{q} Ano(s)"
            elif u == '5': return f"{100 + q} Ano(s)"
            else: return f"{q} (Und. ñ identificada)"
        elif len(valor_str) == 2: return f"{int(valor_str)} Ano(s)"
        else: return str(valor)
    except: return "Erro na Leitura"

def decodificar_cbo_github(codigo, dict_cbo_repo):
    if pd.isna(codigo) or str(codigo).strip() in ['', 'None', 'nan', '999999', '000000']: 
        return "Não informado / Ignorado"
    
    cod_str = str(codigo).split('.')[0].zfill(6)
    
    # Plano A: Usa a tabela CSV gigante do repositório 'cartaproale'
    if dict_cbo_repo:
        if cod_str in dict_cbo_repo: return f"{cod_str} - {dict_cbo_repo[cod_str]}"
        if cod_str[:4] in dict_cbo_repo: return f"{cod_str} - {dict_cbo_repo[cod_str[:4]]}"
        if cod_str[:2] in dict_cbo_repo: return f"{cod_str} - {dict_cbo_repo[cod_str[:2]]}"
    
    # Plano B: Usa a tabela condensada em JSON do seu repositório
    cbo_especificos = CONFIG_APP.get("CBO_ESPECIFICOS", {})
    cbo_subgrupos = CONFIG_APP.get("CBO_SUBGRUPOS", {})
    
    if cod_str[:4] in cbo_especificos:
        return f"{cod_str} - {cbo_especificos[cod_str[:4]]}"
        
    prefixo_2 = cod_str[:2]
    grupo_nome = cbo_subgrupos.get(prefixo_2, "Ocupação geral/Não classificada")
    return f"{cod_str} - {grupo_nome}"

def decodificar_cid_github(codigo, dict_cid_repo):
    if pd.isna(codigo) or str(codigo).strip() in ['', 'None', 'nan']: 
        return "Não informado"
    
    cod_str = str(codigo).strip().upper()
    
    # Tenta cruzar com a tabela de Doenças do 'cartaproale'
    if dict_cid_repo:
        if cod_str in dict_cid_repo: return f"{cod_str} - {dict_cid_repo[cod_str]}"
        if cod_str[:3] in dict_cid_repo: return f"{cod_str} - {dict_cid_repo[cod_str[:3]]}"
        return f"{cod_str} - CID não mapeada no dicionário"
    
    # Se a tabela falhar em carregar, devolve a sigla original
    return cod_str

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES" if "CNES" in sistema else "SINAN"
    
    if sigla_sistema == "SIM" and "IDADE" in df_tratado.columns: df_tratado["IDADE"] = df_tratado["IDADE"].apply(decodificar_idade_datasus)
    if sigla_sistema == "SINASC" and "IDADEMAE" in df_tratado.columns: df_tratado["IDADEMAE"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus)
    if sigla_sistema == "SINAN" and "NU_IDADE_N" in df_tratado.columns: df_tratado["NU_IDADE_N"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus)

    # Aplicação do CBO Github
    dict_cbo = TABELAS_CARTAPROALE.get("CBO", {})
    if "OCUP" in df_tratado.columns: df_tratado["OCUP"] = df_tratado["OCUP"].apply(lambda x: decodificar_cbo_github(x, dict_cbo))
    if "OCUPMAE" in df_tratado.columns: df_tratado["OCUPMAE"] = df_tratado["OCUPMAE"].apply(lambda x: decodificar_cbo_github(x, dict_cbo))
    if "ID_OCUPA_N" in df_tratado.columns: df_tratado["ID_OCUPA_N"] = df_tratado["ID_OCUPA_N"].apply(lambda x: decodificar_cbo_github(x, dict_cbo))

    # Aplicação do CID-10 Github
    dict_cid = TABELAS_CARTAPROALE.get("CID10", {})
    colunas_doencas = ["CAUSABAS", "CAUSABAS_O", "DIAG_PRINC", "CODANOMAL"]
    for col in colunas_doencas:
        if col in df_tratado.columns:
            df_tratado[col] = df_tratado[col].apply(lambda x: decodificar_cid_github(x, dict_cid))

    dict_valores = CONFIG_APP.get("DICIONARIOS_VALORES", {}).get(sigla_sistema, {})
    for coluna, de_para in dict_valores.items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].astype(str).map(de_para).fillna("Ignorado/Outros")
            
    df_tratado = df_tratado.rename(columns=CONFIG_APP.get("TRADUCAO_CABECALHOS", {}).get(sigla_sistema, {}))
    return df_tratado

# --- MOTOR DATASUS COM RADAR DE COLUNAS E DETECTOR DE FALHAS ---

def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, sih_grupo=None, cnes_grupo=None, nivel_terr="Brasil", id_datasus_alvo=""):
    if not sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    
    df_final = pd.DataFrame()
    meses_para_baixar = [mes_num] if mes_num else list(range(1, 13))

    col_map_possiveis = {
        "Mortalidade (SIM)": ["CODMUNRES", "codmunres"], 
        "Internações (SIH)": ["MUNIC_RES", "munic_res", "SP_GESTOR", "sp_gestor", "SP_MUNIC", "sp_munic", "MUNIC_MOV", "munic_mov"],
        "Nascimentos (SINASC)": ["CODMUNRES", "codmunres"], 
        "Cadastro Nacional de Estabelecimentos (CNES)": ["CODUFMUN", "codufmun"], 
        "Notificações (SINAN)": ["ID_MN_RESI", "id_mn_resi", "ID_MUNICIP", "id_municip"]
    }
    cols_alvo = col_map_possiveis.get(sistema, [])

    dt_cols_map = {
        "Mortalidade (SIM)": ["DTOBITO", "dtobito"],
        "Nascimentos (SINASC)": ["DTNASC", "dtnasc"],
        "Notificações (SINAN)": ["DT_NOTIFIC", "dt_notific"]
    }
    dt_alvos = dt_cols_map.get(sistema, [])

    sinan_baixado = False
    falhas_conexao = 0
    sucessos_download = 0

    for uf in ufs_lista:
        try:
            resultados = []
            
            if "SIH" in sistema or "CNES" in sistema:
                for m in meses_para_baixar:
                    if "SIH" in sistema:
                        try:
                            res = sih(state=uf, year=ano, month=m, groups=[sih_grupo])
                        except:
                            try:
                                res = sih(state=uf, year=ano, month=m, group=sih_grupo)
                            except:
                                try:
                                    res = sih(state=uf, year=ano, month=m)
                                except:
                                    falhas_conexao += 1
                                    continue
                    elif "CNES" in sistema:
                        try:
                            res = cnes(state=uf, year=ano, month=m, groups=[cnes_grupo])
                        except:
                            try:
                                res = cnes(state=uf, year=ano, month=m, group=cnes_grupo)
                            except:
                                try:
                                    res = cnes(state=uf, year=ano, month=m)
                                except:
                                    falhas_conexao += 1
                                    continue
                    
                    if isinstance(res, list): 
                        resultados.extend(res)
                        sucessos_download += 1
                    elif res is not None: 
                        resultados.append(res)
                        sucessos_download += 1
            
            else:
                try:
                    if sistema == "Mortalidade (SIM)": res = sim(state=uf, year=ano)
                    elif sistema == "Nascimentos (SINASC)": res = sinasc(state=uf, year=ano)
                    elif sistema == "Notificações (SINAN)":
                        if sinan_baixado and nivel_terr == "Brasil":
                            continue 
                        try:
                            res = sinan(disease=agravo, year=ano) 
                        except TypeError:
                            res = sinan(disease=agravo, state=uf, year=ano)
                        sinan_baixado = True
                    
                    if isinstance(res, list): 
                        resultados.extend(res)
                        sucessos_download += 1
                    elif res is not None: 
                        resultados.append(res)
                        sucessos_download += 1
                except:
                    falhas_conexao += 1
                    continue
            
            for r in resultados:
                try:
                    if isinstance(r, pd.DataFrame): df_temp = r.copy()
                    elif hasattr(r, 'to_pandas'): df_temp = r.to_pandas()
                    elif isinstance(r, str): df_temp = pd.read_parquet(r)
                    else: continue
                    
                    col_filtro_real = None
                    for c in df_temp.columns:
                        if str(c).upper() in [x.upper() for x in cols_alvo]:
                            col_filtro_real = c
                            break

                    dt_col_real = None
                    for c in df_temp.columns:
                        if str(c).upper() in [x.upper() for x in dt_alvos]:
                            dt_col_real = c
                            break
                    
                    if sistema == "Notificações (SINAN)" and nivel_terr in ["Estado", "Município"] and col_filtro_real:
                        codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
                        df_temp = df_temp[df_temp[col_filtro_real].astype(str).str.startswith(codigo_uf_ibge)]
                    
                    if nivel_terr == "Município" and col_filtro_real:
                        df_temp[col_filtro_real] = df_temp[col_filtro_real].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        df_temp = df_temp[df_temp[col_filtro_real].str.startswith(id_datasus_alvo)]
                    
                    if mes_num is not None and dt_col_real:
                        mes_str = str(mes_num).zfill(2)
                        if sistema in ["Mortalidade (SIM)", "Nascimentos (SINASC)"]:
                            df_temp[dt_col_real] = df_temp[dt_col_real].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(8)
                            df_temp = df_temp[df_temp[dt_col_real].str[2:4] == mes_str]
                        elif sistema == "Notificações (SINAN)":
                            dt_notific_limpa = df_temp[dt_col_real].astype(str).str.replace("-", "").str.replace(r'\.0$', '', regex=True)
                            df_temp = df_temp[dt_notific_limpa.str[4:6] == mes_str]
                    
                    if not df_temp.empty:
                        df_final = pd.concat([df_final, df_temp], ignore_index=True)
                    
                    del df_temp
                    gc.collect()
                    
                except Exception as e:
                    continue
                
            del resultados
            gc.collect()
                
        except Exception: continue
            
    if df_final.empty:
        if sucessos_download == 0 and falhas_conexao > 0:
            return pd.DataFrame({"Erro": ["🛑 FALHA DE CONEXÃO: O servidor do FTP do DATASUS recusou o download ou os arquivos não existem para esse grupo/período."]})
        else:
            return pd.DataFrame({"Erro": ["⚠️ FALTA DE DADOS: O download foi realizado com sucesso, mas a tabela ficou vazia. Não existem registros para este agravo no Município/Estado/Mês selecionado."]})
    
    return df_final.drop_duplicates()

# --- INTERFACE PRINCIPAL ---

st.sidebar.title("🧬 Navegação e Filtros")

aba_ativa = st.sidebar.radio(
    "Navegar para:",
    ["📋 Guia Principal (Extração)", "📚 Dicionários e Citações"]
)

if aba_ativa == "📋 Guia Principal (Extração)":

    st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3</p></div>', unsafe_allow_html=True)

    fonte = st.sidebar.radio("Base de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])
    nivel_terr = st.sidebar.radio("Nível Territorial:", ["Brasil", "Estado", "Município"])

    ufs_selecionadas = UFS
    id_ibge_alvo = "1" 
    id_datasus_alvo = ""

    if nivel_terr == "Estado":
        uf_sel = st.sidebar.selectbox("Selecione o Estado:", sorted(UFS))
        ufs_selecionadas = [uf_sel]
        id_ibge_alvo = ESTADOS_IBGE[uf_sel]
        nome_local = uf_sel
    elif nivel_terr == "Município":
        uf_sel = st.sidebar.selectbox("Filtrar Estado:", sorted(UFS), index=UFS.index("MG"))
        muns_estado = buscar_municipios_por_uf(uf_sel)
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
            "Internações (SIH)", 
            "Nascimentos (SINASC)", 
            "Cadastro Nacional de Estabelecimentos (CNES)", 
            "Notificações (SINAN)"
        ])
        
        agravo_sel = None
        sih_grupo_sel = None
        cnes_grupo_sel = None
        
        if sistema == "Notificações (SINAN)":
            mapa_doencas = {
                "Acidente de trabalho": "ACGR",
                "Acidente de trabalho com material biológico": "ACBI",
                "AIDS em adultos": "AIDA",
                "AIDS em crianças": "AIDC",
                "Câncer Relacionado ao Trabalho": "CANC",
                "Chikungunya": "CHIK",
                "Dengue": "DENG",
                "Doença de Chagas": "CHAG",
                "Hepatites Virais": "HEPA",
                "HIV em adultos": "HIVA",
                "HIV em crianças": "HIVC",
                "HIV em crianças expostas": "HIVE",
                "Leptospirose": "LEPT",
                "Meningite": "MENI",
                "Perda Auditiva por Ruído (Trabalho)": "PAIR",
                "Raiva Humana": "RAIV",
                "Sífilis Adquirida": "SIFA",
                "Sífilis Congênita": "SIFC",
                "Sífilis em Gestante": "SIFG",
                "Transtornos Mentais (Trabalho)": "MENT",
                "Tuberculose": "TUBE",
                "Varicela": "VARI",
                "Violência doméstica, sexual e/ou outras": "VIOL",
                "Zika Vírus": "ZIKA"
            }
            nome_agravo = st.sidebar.selectbox("Doença/Agravo:", sorted(list(mapa_doencas.keys())))
            agravo_sel = mapa_doencas[nome_agravo]
            
        elif sistema == "Internações (SIH)":
            mapa_sih = {
                "RD - Registros de Internações (Padrão)": "RD",
                "SP - Serviços Profissionais": "SP",
                "ER - Emergência Referenciada": "ER",
                "CM - Cirurgias Ambulatoriais": "CM"
            }
            nome_sih = st.sidebar.selectbox("Grupo de Dados (SIH):", list(mapa_sih.keys()))
            sih_grupo_sel = mapa_sih[nome_sih]
            
        elif sistema == "Cadastro Nacional de Estabelecimentos (CNES)":
            mapa_cnes = {
                "ST - Estabelecimentos": "ST",
                "PF - Profissionais": "PF",
                "SR - Serviços": "SR",
                "HB - Habilitações": "HB",
                "IN - Incentivos": "IN",
                "EP - Estabelecimento por Procedimento": "EP",
                "EQ - Equipamentos": "EQ",
                "LT - Leitos": "LT",
                "DC - Dados Complementares": "DC"
            }
            nome_cnes = st.sidebar.selectbox("Grupo de Dados (CNES):", list(mapa_cnes.keys()))
            cnes_grupo_sel = mapa_cnes[nome_cnes]
        
        ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis())
        
        nome_mes = st.sidebar.selectbox("Mês de Competência/Ocorrência (Opcional):", MESES_NOMES)
        mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])
        
        if st.button(f"🔍 Consultar Base"):
            with st.spinner(f"Baixando e filtrando dados para {nome_local}... Isso pode demorar bastante dependendo da base escolhida."):
                df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, sih_grupo_sel, cnes_grupo_sel, nivel_terr, id_datasus_alvo)
                
                if not df_bruto.empty and "Erro" not in df_bruto.columns:
                    
                    df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                    
                    if sistema == "Notificações (SINAN)":
                        sistema_titulo = f"SINAN ({nome_agravo})"
                    elif sistema == "Internações (SIH)":
                        sistema_titulo = f"SIH ({sih_grupo_sel})"
                    elif sistema == "Cadastro Nacional de Estabelecimentos (CNES)":
                        sistema_titulo = f"CNES ({cnes_grupo_sel})"
                    else:
                        sistema_titulo = sistema.split(" (")[0]
                    
                    st.markdown(f'<div class="metric-card"><h2>{len(df_bruto)} Registros Encontrados</h2><p>{sistema_titulo} - {nome_local} ({ano_sel})</p></div>', unsafe_allow_html=True)
                    st.info("💡 Apenas as primeiras 100 linhas são exibidas abaixo. Use os botões para exportar a base completa.")
                    
                    tab1, tab2 = st.tabs(["✅ Planilha Tratada (Visualização Amigável)", "⚙️ Planilha Bruta (Códigos Originais)"])
                    
                    with tab1:
                        st.dataframe(df_tratado.head(100), use_container_width=True)
                        st.download_button("📥 Baixar Tabela TRATADA Completa (CSV)", df_tratado.to_csv(index=False, sep=';', decimal=','), f"tratado_{sistema_titulo}_{nome_local}.csv", "text/csv", use_container_width=True)

                    with tab2:
                        st.dataframe(df_bruto.head(100), use_container_width=True)
                        st.download_button("📥 Baixar Tabela BRUTA Completa (CSV)", df_bruto.to_csv(index=False, sep=';', decimal=','), f"bruto_{sistema_titulo}_{nome_local}.csv", "text/csv", use_container_width=True)
                else:
                    mensagem_erro = df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Sem dados."
                    if "FALHA DE CONEXÃO" in mensagem_erro:
                        st.error(mensagem_erro)
                    else:
                        st.warning(mensagem_erro)

    else:
        st.subheader(f"🏠 Indicadores Sociais - {nome_local}")
        if st.button("🔍 Extrair Tabelas MDS"):
            with st.spinner("Ultrapassando protocolos do servidor federal..."):
                url_mds = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={id_ibge_alvo}"
                try:
                    res = requests.get(url_mds, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
                    tabelas = pd.read_html(io.StringIO(res.text))
                    if not tabelas: st.warning("Nenhum dado social retornado.")
                    else:
                        for i, t in enumerate(tabelas):
                            st.write(f"**Tabela {i+1}**")
                            st.dataframe(t, use_container_width=True)
                            st.download_button(f"📥 Baixar Tabela {i+1}", t.to_csv(index=False, sep=';'), f"mds_tabela_{i+1}_{id_ibge_alvo}.csv", "text/csv", key=f"btn_{i}")
                except:
                    st.error("O servidor do Ministério encontra-se fora do ar ou bloqueou a conexão. Tente mais tarde.")

    st.markdown("""
        <div class="footer-text">
            <b>Fontes de Dados:</b> Ministério da Saúde (DATASUS) | IBGE | Ministério da Cidadania (VIS DATA 3)<br>
            <i>Sistema construído com arquitetura PySUS e Dicionários Desacoplados. Otimizado com Garbage Collector (Limpeza de RAM ativa).</i>
        </div>
    """, unsafe_allow_html=True)

# 🌟 ABA DE DICIONÁRIOS E CITAÇÕES
elif aba_ativa == "📚 Dicionários e Citações":
    st.title("📚 Dicionários de Dados e Normas de Citação")
    st.markdown("---")
    
    st.header("1. Dicionários de Dados (Variáveis)")
    st.write("Abaixo estão os resumos das principais variáveis que o sistema traduz automaticamente na **Planilha Tratada** com base nos Manuais Oficiais do Ministério da Saúde:")
    
    with st.expander("💀 SIM (Sistema de Informações sobre Mortalidade)"):
        st.markdown("""
        * **ESTCIV (Estado Civil):** 1-Solteiro | 2-Casado | 3-Viúvo | 4-Separado/Divorciado | 5-União estável | 9-Ignorado
        * **ESC2010 (Escolaridade):** 0-Sem escolaridade | 1-Fundamental I | 2-Fundamental II | 3-Médio | 4-Superior incompleto | 5-Superior completo | 9-Ignorado
        * **OCUP (Ocupação):** Traduzido automaticamente pelos dicionários externos (CBO-2002).
        * **CAUSABAS (Causa Básica):** Traduzido automaticamente pelo dicionário CID-10 integrado via Github.
        * **TIPOBITO:** 1-Fetal | 2-Não fetal
        * **CIRCOBITO (Circunstância):** 1-Acidente | 2-Suicídio | 3-Homicídio | 4-Outros
        * **LOCOCOR (Local de Ocorrência):** 1-hospital | 2-outros estabelecimentos de saúde | 3-domicílio | 4-via pública | 5-outros | 6-aldeia indigena | 9-ignorado
        """)
        
    with st.expander("👶 SINASC (Sistema de Informações sobre Nascidos Vivos)"):
        st.markdown("""
        * **ESTCIVMAE (Estado Civil da Mãe):** 1-Solteira | 2-Casada | 3-Viúva | 4-Separada/Divorciada | 5-União Consensual | 9-Ignorado
        * **ESCMAE2010 (Escolaridade da Mãe):** 0-Sem escolaridade | 1-Fundamental I | 2-Fundamental II | 3-Médio | 4-Superior incompleto | 5-Superior completo | 9-Ignorado
        * **GRAVIDEZ:** 1-Única | 2-Dupla | 3-Tripla ou mais | 9-Ignorada
        * **PARTO:** 1-Vaginal | 2-Cesáreo | 9-Ignorado
        * **PESO:** Peso ao nascer em gramas
        """)

    with st.expander("🩺 SINAN (Sistema de Informação de Agravos de Notificação)"):
        st.markdown("""
        * **CS_ESCOL_N (Escolaridade):** 00-Sem instrução | 01-Fundamental I | 02-Fundamental II | 03-Médio | 04-Superior | 05-Não se aplica | 09-Ignorado
        * **CS_EST_CIV (Estado Civil):** 1-Solteiro | 2-Casado | 3-Viúvo | 4-Separado/Divorciado | 9-Ignorado
        * **EVOLUCAO (Evolução do Caso):** 1-Cura | 2-Óbito pelo agravo | 3-Óbito por outras causas | 9-Ignorado
        * **st_transmissao_vertical (Transmissão Vertical):** 1-Sim | 2-Não foi transmissão vertical | 9-Ignorado
        * **tp_sexual (Transmissão Sexual):** 1-Relações sexuais com Homens | 2-Relações sexuais com Mulheres | 3-Relações sexuais com homens e mulheres | 4-Não foi transmissão sexual | 9-Ignorado
        """)
        
    with st.expander("📂 Dicionários Externos Integrados (Repositório PySUS)"):
        st.markdown("""
        O sistema implementa uma engenharia de dados desacoplada, consultando os dicionários mestre diretamente da documentação oficial acessível validada do projeto PySUS no GitHub.

        **1. CBO-2002 (Classificação Brasileira de Ocupações):**
        * Realiza o mapeamento oficial cruzando a coluna original do DATASUS com o arquivo `cbo.csv` hospedado remotamente.

        **2. CID-10 (Classificação Internacional de Doenças):**
        * Extrai o significado clínico exato dos códigos presentes nas Autorizações de Internação Hospitalar (SIH) e Declarações de Óbito (SIM) via leitura paralela do `cid10.csv`.
        """)
        
    st.markdown("---")
    st.header("2. Como citar os dados (Padrão ABNT)")
    st.info("Sempre que utilizar dados extraídos deste sistema em relatórios, TCCs ou artigos científicos, você deve referenciar a fonte primária governamental.")
    
    st.markdown("**Para dados do Ministério da Saúde (SIM, SINASC, SIH, SINAN, CNES):**")
    st.code("BRASIL. Ministério da Saúde. Departamento de Informática do SUS – DATASUS. Microdados de Saúde. Brasília, DF. Disponível em: <http://datasus.saude.gov.br/>. Acesso em: [Data de hoje].", language="text")

    st.markdown("**Para dados de Vulnerabilidade Social (VIS DATA 3 / CadÚnico):**")
    st.code("BRASIL. Ministério da Cidadania. Matriz de Informação Social (VIS DATA 3). Secretaria de Avaliação e Gestão da Informação. Brasília, DF. Disponível em: <https://aplicacoes.cidadania.gov.br/>. Acesso em: [Data de hoje].", language="text")

    st.markdown("**Para utilizar a API de extração Python (PySUS):**")
    st.code("ROCHA, F. A. C. et al. PySUS: ferramenta em linguagem Python para extração e tabulação de dados em saúde. Rio de Janeiro, RJ. Disponível em: <https://github.com/AlertaDengue/PySUS>. Acesso em: [Data de hoje].", language="text")
