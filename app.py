import streamlit as st
import pandas as pd
import requests
import io
import urllib3
from datetime import datetime

# Desativa avisos de segurança SSL para APIs governamentais instáveis
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        st.error(f"Erro ao acessar API do IBGE para a UF {uf_sigla}.")
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620", "nome": "Belo Horizonte", "uf": "MG"}}

try:
    from pysus.api._impl.databases import sim, sih, cnes, sinasc, sinan
except ImportError:
    sim = sih = cnes = sinasc = sinan = None

@st.cache_data
def listar_anos_disponiveis():
    ano_atual = datetime.now().year
    return list(range(ano_atual, 1995, -1))

MESES = {
    "01 - Janeiro": 1, "02 - Fevereiro": 2, "03 - Março": 3, "04 - Abril": 4,
    "05 - Maio": 5, "06 - Junho": 6, "07 - Julho": 7, "08 - Agosto": 8,
    "09 - Setembro": 9, "10 - Outubro": 10, "11 - Novembro": 11, "12 - Dezembro": 12
}

# --- FUNÇÃO DE TRATAMENTO DE IDADE (METODOLOGIA DATASUS) ---

def decodificar_idade_datasus(valor):
    if pd.isna(valor) or str(valor).strip() == '':
        return "Não informado"
    try:
        valor_str = str(int(float(valor))).zfill(3)
        if len(valor_str) == 3:
            unidade = valor_str[0]
            quantidade = int(valor_str[1:])
            
            if unidade == '1': return f"{quantidade} Minuto(s)"
            elif unidade == '2': return f"{quantidade} Hora(s)"
            elif unidade == '3': return f"{quantidade} Mês(es)"
            elif unidade == '4': return f"{quantidade} Ano(s)"
            elif unidade == '5': return f"{100 + quantidade} Ano(s)"
            else: return f"{quantidade} (Unidade não identificada)"
        elif len(valor_str) == 2:
            return f"{int(valor_str)} Ano(s)"
        else:
            return str(valor)
    except:
        return "Erro na Leitura"

# --- DICIONÁRIOS E TRADUÇÃO DE CABEÇALHOS APRIMORADOS ---

DICIONARIOS_VALORES = {
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
        "ESTCIVMAE": {"1": "Solteira", "2": "Casada", "3": "Viúva", "4": "Separada/Divorciada", "5": "União Consensual", "9": "Ignorado"},
        "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla ou mais", "9": "Ignorado"},
        "IDANOMAL": {"1": "Sim", "2": "Não", "9": "Ignorado"},
        "LOCNASC": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio"},
        "PARTO": {"1": "Vaginal/Normal", "2": "Cesáreo", "9": "Ignorado"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "SEXO": {"1": "Masculino", "2": "Feminino", "0": "Ignorado"}
    },
    "SINAN": {
        "CS_SEXO": {"M": "Masculino", "F": "Feminino", "I": "Ignorado"},
        "CS_RACA": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena", "9": "Ignorado"},
        "CS_GESTANT": {"1": "1º Trimestre", "2": "2º Trimestre", "3": "3º Trimestre", "4": "Idade Gestacional Ignorada", "5": "Não", "6": "Não se aplica", "9": "Ignorado"},
        "EVOLUCAO": {"1": "Cura", "2": "Óbito pelo agravo", "3": "Óbito por outras causas", "9": "Ignorado"},
        "CRITERIO": {"1": "Laboratorial", "2": "Clínico-Epidemiológico", "3": "Clínico"}
    }
}

TRADUCAO_CABECALHOS = {
    "SIM": {
        "IDADE": "Idade Formatada", "ACIDTRAB": "Acidente de Trabalho", "CAUSABAS": "Causa Básica (CID-10)",
        "CIRCOBITO": "Circunstância do Óbito", "CODESTAB": "Código CNES (Óbito)", "CODMUNOCOR": "Município Ocorrência",
        "CODMUNRES": "Município Residência", "DTNASC": "Data de Nascimento", "DTOBITO": "Data do Óbito",
        "LOCOCOR": "Local de Ocorrência", "NECROPSIA": "Necropsia", "OCUP": "Ocupação (CBO)",
        "RACACOR": "Raça/Cor", "SEXO": "Sexo", "TIPOBITO": "Tipo de Óbito"
    },
    "SIH": {
        "SP_AA": "Ano Competência", "SP_CNES": "Código Hospital (CNES)", "SP_DTINTER": "Data Internação", 
        "SP_DTSAIDA": "Data Saída/Alta", "SP_NAIH": "Número AIH", "SP_PROCREA": "Procedimento Realizado",
        "SP_QTD_ATO": "Quantidade do Ato", "SP_UF": "UF Internação", "SP_VALATO": "Valor Pago (R$)"
    },
    "SINASC": {
        "IDADEMAE": "Idade da Mãe (Anos)", "APGAR1": "Apgar 1º Minuto", "APGAR5": "Apgar 5º Minuto", 
        "CODANOMAL": "CID Anomalia", "CODESTAB": "Código Maternidade (CNES)", "CONSULTAS": "Consultas Pré-Natal", 
        "DTNASC": "Data Nascimento", "ESTCIVMAE": "Estado Civil Mãe", "GESTACAO": "Semanas Gestação", 
        "GRAVIDEZ": "Tipo Gravidez", "IDANOMAL": "Anomalia Congênita", "LOCNASC": "Local Nascimento", 
        "PARTO": "Tipo Parto", "PESO": "Peso (g)", "RACACOR": "Raça/Cor Bebê", "SEXO": "Sexo Bebê"
    },
    "SINAN": {
        "DT_NOTIFIC": "Data de Notificação", "DT_SIN_PRI": "Data Primeiros Sintomas",
        "ID_MUNICIP": "Município Notificação (IBGE)", "ID_MN_RESI": "Município Residência (IBGE)",
        "NU_IDADE_N": "Idade Formatada", "CS_SEXO": "Sexo", "CS_RACA": "Raça/Cor",
        "CS_GESTANT": "Gestante", "CS_ESCOL_N": "Escolaridade", "ID_UNIDADE": "Código CNES Notificador",
        "CLASSI_FIN": "Classificação Final", "CRITERIO": "Critério Confirmação", 
        "EVOLUCAO": "Evolução do Caso", "DT_OBITO": "Data do Óbito"
    }
}

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    
    sigla_sistema = "SIM"
    if "SINASC" in sistema: sigla_sistema = "SINASC"
    elif "SIH" in sistema: sigla_sistema = "SIH"
    elif "CNES" in sistema: sigla_sistema = "CNES"
    elif "SINAN" in sistema: sigla_sistema = "SINAN"
    
    # 1. Tratamento Específico da Regra de Idade
    if sigla_sistema == "SIM" and "IDADE" in df_tratado.columns:
        df_tratado["IDADE"] = df_tratado["IDADE"].apply(decodificar_idade_datasus)
        
    if sigla_sistema == "SINASC" and "IDADEMAE" in df_tratado.columns:
        df_tratado["IDADEMAE"] = df_tratado["IDADEMAE"].apply(decodificar_idade_datasus)
        
    if sigla_sistema == "SINAN" and "NU_IDADE_N" in df_tratado.columns:
        df_tratado["NU_IDADE_N"] = df_tratado["NU_IDADE_N"].apply(decodificar_idade_datasus)

    # 2. Traduzir Valores (De-Para) usando .fillna() para evitar erros
    dict_valores = DICIONARIOS_VALORES.get(sigla_sistema, {})
    for coluna, de_para in dict_valores.items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].astype(str).map(de_para).fillna("Ignorado/Outros")
            
    # 3. Renomear Cabeçalhos
    dict_cabecalhos = TRADUCAO_CABECALHOS.get(sigla_sistema, {})
    df_tratado = df_tratado.rename(columns=dict_cabecalhos)
    
    return df_tratado

# --- CONECTORES DE DADOS ---

@st.cache_data
def buscar_datasus_v7(sistema, ufs_lista, ano, mes=None, agravo=None):
    if not sim: return pd.DataFrame({"Erro": ["Biblioteca PySUS não detectada."]})
    
    df_final = pd.DataFrame()
    for uf in ufs_lista:
        try:
            if sistema == "Mortalidade (SIM)":
                res = sim(state=uf, year=ano)
            elif sistema == "Internações (SIH-SP)":
                res = sih(state=uf, year=ano, month=mes)
            elif sistema == "Nascimentos (SINASC)":
                res = sinasc(state=uf, year=ano)
            elif sistema == "Estabelecimentos (CNES)":
                res = cnes(state=uf, year=ano, month=mes)
            elif sistema == "Notificações (SINAN)":
                res = sinan(disease=agravo, state=uf, year=ano)
            
            if isinstance(res, list) and len(res) > 0:
                df_uf = pd.read_parquet(res[0])
            elif not isinstance(res, list) and res is not None:
                df_uf = pd.read_parquet(res)
            else:
                continue
                
            df_final = pd.concat([df_final, df_uf], ignore_index=True)
        except Exception:
            continue
            
    if df_final.empty:
        return pd.DataFrame({"Erro": ["Dados ainda não disponíveis no servidor federal para este período ou agravo."]})
    return df_final

def baixar_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados')
    return output.getvalue()

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

if fonte == "🏥 Saúde (DATASUS)":
    sistema = st.sidebar.selectbox("Sistema:", [
        "Mortalidade (SIM)", "Internações (SIH-SP)", "Nascimentos (SINASC)", 
        "Estabelecimentos (CNES)", "Notificações (SINAN)"
    ])
    
    # NOVO: Filtro Específico para o SINAN
    agravo_sel = None
    if sistema == "Notificações (SINAN)":
        mapa_doencas = {
            "AIDS": "AIDS",
            "Câncer Relacionado ao Trabalho": "CANC",
            "Chikungunya": "CHIK",
            "Dengue": "DENG",
            "Doença de Chagas": "CHAG",
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
            "Zika Vírus": "ZIKA"
        }
        nome_agravo = st.sidebar.selectbox("Doença/Agravo:", sorted(list(mapa_doencas.keys())))
        agravo_sel = mapa_doencas[nome_agravo]
    
    ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis())
    
    mes_sel = None
    if sistema in ["Internações (SIH-SP)", "Estabelecimentos (CNES)"]:
        nome_mes = st.sidebar.selectbox("Mês de Competência:", list(MESES.keys()))
        mes_sel = MESES[nome_mes]
    
    if st.button(f"🔍 Consultar Base"):
        with st.spinner(f"Extraindo dados de {sistema} para {nome_local} em {ano_sel}..."):
            df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel, agravo_sel)
            
            if not df_bruto.empty and "Erro" not in df_bruto.columns:
                
                if nivel_terr == "Município":
                    col_map = {
                        "Mortalidade (SIM)": "CODMUNRES", "Internações (SIH-SP)": "SP_GESTOR",
                        "Nascimentos (SINASC)": "CODMUNRES", "Estabelecimentos (CNES)": "CODUFMUN",
                        "Notificações (SINAN)": "ID_MN_RESI" # Filtra pelo município de residência do paciente no SINAN
                    }
                    col_filtro = col_map.get(sistema)
                    if col_filtro in df_bruto.columns:
                        df_bruto = df_bruto[df_bruto[col_filtro].astype(str).str.startswith(id_datasus_alvo)]
                
                df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                
                agravo_titulo = f" ({nome_agravo})" if agravo_sel else ""
                st.markdown(f'<div class="metric-card"><h2>{len(df_bruto)} Registros Encontrados</h2><p>{sistema}{agravo_titulo} - {nome_local} ({ano_sel})</p></div>', unsafe_allow_html=True)
                
                st.info("💡 Apenas as primeiras 100 linhas são exibidas na tela. Os botões abaixo exportam a base completa.")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("✅ Planilha Tratada")
                    st.dataframe(df_tratado.head(100), use_container_width=True)
                    st.download_button(
                        label="📥 Baixar Dados TRATADOS",
                        data=df_tratado.to_csv(index=False, sep=';', decimal=','),
                        file_name=f"tratado_{sistema}_{nome_local}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                with col2:
                    st.subheader("⚙️ Planilha Bruta")
                    st.dataframe(df_bruto.head(100), use_container_width=True)
                    st.download_button(
                        label="📥 Baixar Dados BRUTOS",
                        data=df_bruto.to_csv(index=False, sep=';', decimal=','),
                        file_name=f"bruto_{sistema}_{nome_local}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            else:
                st.error(df_bruto["Erro"].iloc[0] if not df_bruto.empty else "Sem dados.")

else:
    # Lógica VIS DATA 3 (MDS)
    st.subheader(f"🏠 Indicadores Sociais - {nome_local}")
    st.info("Conectando ao sistema VIS DATA 3 (MDS / SAGICAD).")
    
    if st.button("🔍 Extrair Tabelas MDS"):
        with st.spinner("Ultrapassando protocolos do servidor federal..."):
            url_mds = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={id_ibge_alvo}"
            headers_mds = {'User-Agent': 'Mozilla/5.0'}
            
            try:
                res = requests.get(url_mds, headers=headers_mds, timeout=15, verify=False)
                tabelas = pd.read_html(io.StringIO(res.text))
                
                if len(tabelas) == 0:
                    st.warning("Nenhum dado social foi retornado para este município.")
                else:
                    for i, t in enumerate(tabelas):
                        st.write(f"**Tabela {i+1}**")
                        st.dataframe(t, use_container_width=True)
                        st.download_button(
                            label=f"📥 Baixar Tabela {i+1}", 
                            data=t.to_csv(index=False, sep=';'), 
                            file_name=f"mds_tabela_{i+1}_{id_ibge_alvo}.csv", 
                            mime="text/csv",
                            key=f"btn_{i}"
                        )
            except Exception as e:
                st.error("O servidor do Ministério encontra-se fora do ar ou bloqueou a conexão. Tente mais tarde.")

st.divider()
st.caption("Sistema Otimizado. Para bases pesadas (acima de 100.000 linhas), aguarde o botão de download preparar o arquivo.")
