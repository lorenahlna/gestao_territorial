import streamlit as st
import pandas as pd
import requests
import io
import urllib3
import gc
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    ano_atual = datetime.now().year
    return list(range(ano_atual, 1995, -1))

MESES_NOMES = [
    "Todos os Meses", "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
    "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
    "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"
]

# --- TRATAMENTO DATASUS ---

def decodificar_idade_datasus(valor):
    if pd.isna(valor) or str(valor).strip() == '': return "Não informado"
    try:
        valor_str = str(int(float(valor))).zfill(3)
        if len(valor_str) == 3:
            unidade, quantidade = valor_str[0], int(valor_str[1:])
            if unidade == '1': return f"{quantidade} Minuto(s)"
            elif unidade == '2': return f"{quantidade} Hora(s)"
            elif unidade == '3': return f"{quantidade} Mês(es)"
            elif unidade == '4': return f"{quantidade} Ano(s)"
            elif unidade == '5': return f"{100 + quantidade} Ano(s)"
            else: return f"{quantidade} (Unidade não identificada)"
        elif len(valor_str) == 2: return f"{int(valor_str)} Ano(s)"
        else: return str(valor)
    except: return "Erro na Leitura"

DICIONARIOS_VALORES = {
    "SIM": {"ACIDTRAB": {"1": "Sim", "2": "Não"}, "CIRCOBITO": {"1": "Acidente", "2": "Suicídio", "3": "Homicídio", "4": "Outros"}, "LOCOCOR": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio", "4": "Via pública"}, "NECROPSIA": {"1": "Sim", "2": "Não"}, "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}, "SEXO": {"1": "Masculino", "2": "Feminino"}, "TIPOBITO": {"1": "Não fetal", "2": "Fetal"}},
    "SINASC": {"ESTCIVMAE": {"1": "Solteira", "2": "Casada", "3": "Viúva", "4": "Separada/Divorciada", "5": "União Consensual", "9": "Ignorado"}, "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla ou mais", "9": "Ignorado"}, "IDANOMAL": {"1": "Sim", "2": "Não", "9": "Ignorado"}, "LOCNASC": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio"}, "PARTO": {"1": "Vaginal/Normal", "2": "Cesáreo", "9": "Ignorado"}, "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"}, "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"}},
    "SINAN": {"CS_SEXO": {"M": "Masculino", "F": "Feminino", "I": "Ignorado"}, "CS_RACA": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"}, "EVOLUCAO": {"1": "Cura", "2": "Óbito pelo agravo", "3": "Óbito por outras causas", "9": "Ignorado"}}
}

TRADUCAO_CABECALHOS = {
    "SIM": {"IDADE": "Idade Formatada", "ACIDTRAB": "Acidente de Trabalho", "CAUSABAS": "Causa Básica (CID-10)", "CIRCOBITO": "Circunstância do Óbito", "CODESTAB": "Código CNES (Óbito)", "CODMUNOCOR": "Município Ocorrência", "CODMUNRES": "Município Residência", "DTNASC": "Data de Nascimento", "DTOBITO": "Data do Óbito", "LOCOCOR": "Local de Ocorrência", "NECROPSIA": "Necropsia", "OCUP": "Ocupação (CBO)", "RACACOR": "Raça/Cor", "SEXO": "Sexo", "TIPOBITO": "Tipo de Óbito"},
    "SIH": {"SP_AA": "Ano Competência", "SP_CNES": "Código Hospital (CNES)", "SP_DTINTER": "Data Internação", "SP_DTSAIDA": "Data Saída/Alta", "SP_NAIH": "Número AIH", "SP_PROCREA": "Procedimento Realizado", "SP_QTD_ATO": "Quantidade do Ato", "SP_UF": "UF Internação", "SP_VALATO": "Valor Pago (R$)"},
    "SINASC": {"IDADEMAE": "Idade da Mãe (Anos)", "APGAR1": "Apgar 1º Minuto", "APGAR5": "Apgar 5º Minuto", "CODANOMAL": "CID Anomalia", "CODESTAB": "Código Maternidade (CNES)", "CONSULTAS": "Consultas Pré-Natal", "DTNASC": "Data Nascimento", "ESTCIVMAE": "Estado Civil Mãe", "GESTACAO": "Semanas Gestação", "GRAVIDEZ": "Tipo Gravidez", "IDANOMAL": "Anomalia Congênita", "LOCNASC": "Local Nascimento", "PARTO": "Tipo Parto", "PESO": "Peso (g)", "RACACOR": "Raça/Cor Bebê", "SEXO": "Sexo Bebê"},
    "SINAN": {"DT_NOTIFIC": "Data de Notificação", "DT_SIN_PRI": "Data Primeiros Sintomas", "ID_MUNICIP": "Município Notificação (IBGE)", "ID_MN_RESI": "Município Residência (IBGE)", "NU_IDADE_N": "Idade Formatada", "CS_SEXO": "Sexo", "CS_RACA": "Raça/Cor", "CLASSI_FIN": "Classificação Final", "EVOLUCAO": "Evolução do Caso"}
}

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES" if "CNES" in sistema else "SINAN"
    
    if sigla_sistema == "SIM" and "IDADE" in df_tratado.columns: df_tratado["IDADE"] = df_tratado["IDADE"].apply(decodificar_idade_datasus)
    if sigla_sistema == "SINASC" and "IDADEMAE" in df_tratado.columns: df_tratado["IDADEMAE"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus)
    if sigla_sistema == "SINAN" and "NU_IDADE_N" in df_tratado.columns: df_tratado["NU_IDADE_N"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus)

    dict_valores = DICIONARIOS_VALORES.get(sigla_sistema, {})
    for coluna, de_para in dict_valores.items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].astype(str).map(de_para).fillna("Ignorado/Outros")
            
    df_tratado = df_tratado.rename(columns=TRADUCAO_CABECALHOS.get(sigla_sistema, {}))
    return df_tratado

# --- MOTOR DATASUS COM OTIMIZADOR DE MEMÓRIA (ANTI-QUEDAS) ---

def buscar_datasus_v7(sistema, ufs_lista, ano, mes_num=None, agravo=None, nivel_terr="Brasil", id_datasus_alvo=""):
    if not sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    
    if "Internações (SIH" in sistema or sistema == "Estabelecimentos (CNES)":
        if mes_num is None:
            return pd.DataFrame({"Erro": ["🚨 TRAVA DE SEGURANÇA: As bases do SIH e CNES são gigantescas. Para evitar que o servidor trave por falta de memória RAM, por favor, selecione um 'Mês de Competência' específico na barra lateral em vez de 'Todos os Meses'."]})

    df_final = pd.DataFrame()
    meses_para_baixar = [mes_num] if mes_num else list(range(1, 13))

    # MAPEAMENTO CORRIGIDO BASEADO NA DOCUMENTAÇÃO DO PYSUS
    col_map = {
        "Mortalidade (SIM)": "CODMUNRES", 
        "Internações (SIH-RD) - Registros de Internações": "MUNIC_RES", 
        "Internações (SIH-SP) - Serviços Profissionais": "SP_GESTOR", 
        "Internações (SIH-ER) - Emergência Referenciada": "MUNIC_RES",
        "Internações (SIH-CM) - Cirurgias Ambulatoriais": "MUNIC_RES",
        "Nascimentos (SINASC)": "CODMUNRES", 
        "Estabelecimentos (CNES)": "CODUFMUN", 
        "Notificações (SINAN)": "ID_MN_RESI"
    }
    col_filtro = col_map.get(sistema)

    sinan_baixado = False

    for uf in ufs_lista:
        try:
            resultados = []
            
            # Baixa os caminhos dos arquivos do FTP
            if "Internações (SIH" in sistema or sistema == "Estabelecimentos (CNES)":
                for m in meses_para_baixar:
                    try:
                        if "SIH" in sistema:
                            # Corta a string "Internações (SIH-XX) - ..." para pegar apenas as 2 letras do grupo (RD, SP, ER ou CM)
                            sih_group = sistema.split("(SIH-")[1][:2] 
                            res = sih(state=uf, year=ano, month=m, group=sih_group)
                        else:
                            res = cnes(state=uf, year=ano, month=m)
                            
                        if isinstance(res, list): resultados.extend(res)
                        elif res is not None: resultados.append(res)
                    except: continue
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
                    
                    if isinstance(res, list): resultados.extend(res)
                    elif res is not None: resultados.append(res)
                except: continue
            
            # Lê cada arquivo um por um e FILTRA IMEDIATAMENTE
            for r in resultados:
                try:
                    if isinstance(r, pd.DataFrame): df_temp = r.copy()
                    elif hasattr(r, 'to_pandas'): df_temp = r.to_pandas()
                    elif isinstance(r, str): df_temp = pd.read_parquet(r)
                    else: continue
                    
                    if sistema == "Notificações (SINAN)" and nivel_terr in ["Estado", "Município"] and col_filtro in df_temp.columns:
                        codigo_uf_ibge = ESTADOS_IBGE.get(uf, "")
                        df_temp = df_temp[df_temp[col_filtro].astype(str).str.startswith(codigo_uf_ibge)]
                    
                    if nivel_terr == "Município" and col_filtro and col_filtro in df_temp.columns:
                        df_temp[col_filtro] = df_temp[col_filtro].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                        df_temp = df_temp[df_temp[col_filtro].str.startswith(id_datasus_alvo)]
                    
                    if mes_num is not None and sistema in ["Mortalidade (SIM)", "Nascimentos (SINASC)", "Notificações (SINAN)"]:
                        mes_str = str(mes_num).zfill(2)
                        if sistema == "Mortalidade (SIM)" and "DTOBITO" in df_temp.columns:
                            df_temp["DTOBITO"] = df_temp["DTOBITO"].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(8)
                            df_temp = df_temp[df_temp["DTOBITO"].str[2:4] == mes_str]
                        elif sistema == "Nascimentos (SINASC)" and "DTNASC" in df_temp.columns:
                            df_temp["DTNASC"] = df_temp["DTNASC"].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(8)
                            df_temp = df_temp[df_temp["DTNASC"].str[2:4] == mes_str]
                        elif sistema == "Notificações (SINAN)" and "DT_NOTIFIC" in df_temp.columns:
                            dt_notific_limpa = df_temp["DT_NOTIFIC"].astype(str).str.replace("-", "").str.replace(r'\.0$', '', regex=True)
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
        return pd.DataFrame({"Erro": ["O Datasus não retornou dados. Verifique a existência de registros ou se os filtros inseridos são válidos no DATASUS."] })
    
    return df_final.drop_duplicates()

# --- INTERFACE ---

st.markdown('<div class="header-sidra"><h1>Central de Inteligência Territorial</h1><p>SIDRA + DATASUS + VIS DATA 3</p></div>', unsafe_allow_html=True)

st.sidebar.title("Filtros de Pesquisa")

fonte = st.sidebar.radio("Base de Informação:", ["🏥 Saúde (DATASUS)", "🏠 Social (VIS DATA 3)"])
nivel_terr = st.sidebar.radio("Nível Territorial:", ["Brasil", "Estado", "Município"])

ufs_selecionadas = UFS
id_ibge_alvo = "1" 

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
    id_datasus_alvo = ""

if fonte == "🏥 Saúde (DATASUS)":
    # 🌟 MENU ATUALIZADO COM OS 4 BLOCOS DO SIH CONFORME A DOCUMENTAÇÃO
    sistema = st.sidebar.selectbox("Sistema:", [
        "Mortalidade (SIM)", 
        "Internações (SIH-RD) - Registros de Internações", 
        "Internações (SIH-SP) - Serviços Profissionais",
        "Internações (SIH-ER) - Emergência Referenciada",
        "Internações (SIH-CM) - Cirurgias Ambulatoriais",
        "Nascimentos (SINASC)", 
        "Estabelecimentos (CNES)", 
        "Notificações (SINAN)"
    ])
    
    agravo_sel = None
    if sistema == "Notificações (SINAN)":
        mapa_doencas = {"AIDS": "AIDS", "Câncer Relacionado ao Trabalho": "CANC", "Chikungunya": "CHIK", "Dengue": "DENG", "Doença de Chagas": "CHAG", "Leptospirose": "LEPT", "Meningite": "MENI", "Perda Auditiva por Ruído (Trabalho)": "PAIR", "Raiva Humana": "RAIV", "Sífilis Adquirida": "SIFA", "Sífilis Congênita": "SIFC", "Sífilis em Gestante": "SIFG", "Transtornos Mentais (Trabalho)": "MENT", "Tuberculose": "TUBE", "Varicela": "VARI", "Zika Vírus": "ZIKA"}
        nome_agravo = st.sidebar.selectbox("Doença/Agravo:", sorted(list(mapa_doencas.keys())))
        agravo_sel = mapa_doencas[nome_agravo]
    
    ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis())
    
    nome_mes = st.sidebar.selectbox("Mês de Competência/Ocorrência (Opcional):", MESES_NOMES)
    mes_sel = None if nome_mes == "Todos os Meses" else int(nome_mes.split(" - ")[0])
    
    if st.button(f"🔍 Consultar Base"):
        with st.spinner(f"Baixando e filtrando dados para {nome_local}... Isso pode demorar se a base estadual for muito grande."):
            df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel, nivel_terr, id_datasus_alvo)
            
            if not df_bruto.empty and "Erro" not in df_bruto.columns:
                
                df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                agravo_titulo = f" ({nome_agravo})" if agravo_sel else ""
                
                sistema_titulo = sistema.split(" - ")[0] if "SIH" in sistema
