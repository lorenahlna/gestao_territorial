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
    """Busca municípios apenas da UF selecionada para evitar timeout do IBGE"""
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_sigla}/municipios"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10).json()
        mun_dict = {}
        for m in res:
            nome = m['nome']
            id7 = str(m['id'])
            id6 = id7[:6] # Padrão DATASUS
            mun_dict[nome] = {"id7": id7, "id6": id6, "nome": nome, "uf": uf_sigla}
        return mun_dict
    except:
        st.error(f"Erro ao acessar API do IBGE para a UF {uf_sigla}.")
        return {"Belo Horizonte": {"id7": "3106200", "id6": "310620", "nome": "Belo Horizonte", "uf": "MG"}}

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

# --- DICIONÁRIOS E TRADUÇÃO DE CABEÇALHOS ---

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
        "ESTCIVMAE": {"1": "Solteira", "2": "Casada", "3": "Viúva", "4": "Separada/Divorciada", "5": "União Consensual"},
        "GRAVIDEZ": {"1": "Única", "2": "Dupla", "3": "Tripla ou mais"},
        "IDANOMAL": {"1": "Sim", "2": "Não", "9": "Ignorado"},
        "LOCNASC": {"1": "Hospital", "2": "Outro estabelecimento", "3": "Domicílio"},
        "PARTO": {"1": "Vaginal/Normal", "2": "Cesáreo"},
        "RACACOR": {"1": "Branca", "2": "Preta", "3": "Amarela", "4": "Parda", "5": "Indígena"},
        "SEXO": {"1": "Masculino", "2": "Feminino"}
    }
}

TRADUCAO_CABECALHOS = {
    "SIM": {
        "ACIDTRAB": "Acidente de Trabalho", "ASSISTMED": "Assistência Médica", "CAUSABAS": "Causa Básica (CID-10)",
        "CIRCOBITO": "Circunstância do Óbito", "CODESTAB": "Código CNES (Óbito)", "CODMUNOCOR": "Município Ocorrência",
        "CODMUNRES": "Município Residência", "DTNASC": "Data de Nascimento", "DTOBITO": "Data do Óbito",
        "ESC": "Escolaridade", "ESC2010": "Escolaridade (2010)", "ESCMAE": "Escolaridade da Mãe",
        "ESTCIV": "Estado Civil", "FONTE": "Fonte da Informação", "HORAOBITO": "Hora do Óbito",
        "IDADE": "Idade", "IDADEMAE": "Idade da Mãe", "LINHAA": "Causa Imediata (Linha A)",
        "LINHAB": "Causa Antecedente (Linha B)", "LINHAC": "Causa Antecedente (Linha C)",
        "LINHAD": "Causa Antecedente (Linha D)", "LINHAII": "Outras Condições (Linha II)",
        "LOCOCOR": "Local de Ocorrência", "NECROPSIA": "Necropsia", "OBITOGRAV": "Óbito na Gravidez",
        "OBITOPUERP": "Óbito no Puerpério", "OCUP": "Ocupação (CBO)", "QTDFILMORT": "Filhos Mortos",
        "QTDFILVIVO": "Filhos Vivos", "RACACOR": "Raça/Cor", "SEXO": "Sexo", "TIPOBITO": "Tipo de Óbito"
    },
    "SIH": {
        "SP_AA": "Ano Competência", "SP_ATOPROF": "Ato Profissional", "SP_CNES": "Código Hospital (CNES)",
        "SP_CPFCGC": "CPF/CNPJ Prestador", "SP_DTINTER": "Data Internação", "SP_DTSAIDA": "Data Saída/Alta",
        "SP_GESTOR": "Gestor Responsável", "SP_MM": "Mês Competência", "SP_NAIH": "Número AIH",
        "SP_NF": "Nota Fiscal", "SP_NUM_PR": "Documento Profissional", "SP_PROCREA": "Procedimento Realizado",
        "SP_PTSP": "Pontos Serviço", "SP_QTD_ATO": "Quantidade do Ato", "SP_TIPO": "Tipo de Documento",
        "SP_TP_ATO": "Tipo de Ato", "SP_UF": "UF Internação", "SP_VALATO": "Valor Pago (R$)"
    },
    "SINASC": {
        "APGAR1": "Apgar 1º Minuto", "APGAR5": "Apgar 5º Minuto", "CODANOMAL": "CID Anomalia",
        "CODBAINASC": "Bairro Nascimento", "CODMUNNASC": "Município Nascimento", "CODBAIRES": "Bairro Residência Mãe",
        "CODMUNRES": "Município Residência Mãe", "CODESTAB": "Código Maternidade (CNES)", "CODOCUPMAE": "Ocupação Mãe",
        "CONSULTAS": "Consultas Pré-Natal", "contador": "ID Registro", "DTCADASTRO": "Data Cadastro",
        "DTRECEBIM": "Data Recebimento", "DTNASC": "Data Nascimento", "ESCMAE": "Escolaridade Mãe",
        "ESTCIVMAE": "Estado Civil Mãe", "GESTACAO": "Semanas Gestação", "GRAVIDEZ": "Tipo Gravidez",
        "HORANASC": "Hora Nascimento", "IDADEMAE": "Idade Mãe", "IDANOMAL": "Anomalia Congênita",
        "LOCNASC": "Local Nascimento", "PARTO": "Tipo Parto", "PESO": "Peso (g)",
        "QTDFILMORT": "Filhos Mortos Anteriores", "QTDFILVIVO": "Filhos Vivos Anteriores",
        "RACACOR": "Raça/Cor Bebê", "SEXO": "Sexo Bebê", "UFINFORM": "UF Informante"
    },
    "CNES": {
        "ATEND_PR": "Possui Pronto-Socorro", "ATIVIDAD": "Atividade Ensino/Pesquisa", "CLIENTEL": "Fluxo Clientela",
        "CNES": "Código CNES", "CNPJ_MAN": "CNPJ Mantenedora", "CODUFMUN": "Município (IBGE)",
        "COMPETEN": "Competência (AAAAMM)", "CPF_CNPJ": "CPF/CNPJ Estabelecimento", "ESFERA_A": "Esfera Administrativa",
        "NATUREZA": "Natureza Jurídica", "NIV_HIER": "Nível Hierarquia", "PF_PJ": "PF ou PJ",
        "TPGESTAO": "Tipo Gestão", "TP_PREST": "Tipo Prestador", "TP_UNID": "Tipo Unidade",
        "TURNO_AT": "Turno Atendimento", "VINC_SUS": "Atende SUS"
    }
}

def tratar_e_traduzir_df(df, sistema):
    df_tratado = df.copy()
    sigla_sistema = "SIM" if "SIM" in sistema else "SINASC" if "SINASC" in sistema else "SIH" if "SIH" in sistema else "CNES"
    
    # 1. Traduzir os Valores das linhas
    dict_valores = DICIONARIOS_VALORES.get(sigla_sistema, {})
    for coluna, de_para in dict_valores.items():
        if coluna in df_tratado.columns:
            df_tratado[coluna] = df_tratado[coluna].astype(str).map(de_para).fillna(df_tratado[coluna])
            
    # 2. Renomear os Cabeçalhos
    dict_cabecalhos = TRADUCAO_CABECALHOS.get(sigla_sistema, {})
    df_tratado = df_tratado.rename(columns=dict_cabecalhos)
    
    return df_tratado

# --- CONECTORES DE DADOS ---

@st.cache_data
def buscar_datasus_v7(sistema, ufs_lista, ano, mes=None):
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
            else: # CNES
                res = cnes(state=uf, year=ano, month=mes)
            
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
        return pd.DataFrame({"Erro": ["Dados ainda não disponíveis no servidor federal para este período."]})
    return df_final

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
    muns_estado = buscar_municipios_por_uf(uf_sel) # Carrega só o estado selecionado (MUITO MAIS RÁPIDO)
    
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
        "Mortalidade (SIM)", "Internações (SIH-SP)", "Nascimentos (SINASC)", "Estabelecimentos (CNES)"
    ])
    
    ano_sel = st.sidebar.selectbox("Ano de Referência:", listar_anos_disponiveis())
    
    mes_sel = None
    if sistema in ["Internações (SIH-SP)", "Estabelecimentos (CNES)"]:
        nome_mes = st.sidebar.selectbox("Mês de Competência:", list(MESES.keys()))
        mes_sel = MESES[nome_mes]
    
    if st.button(f"🔍 Consultar Base"):
        with st.spinner(f"Extraindo dados do Datasus para {nome_local} em {ano_sel}..."):
            df_bruto = buscar_datasus_v7(sistema, ufs_selecionadas, ano_sel, mes_sel)
            
            if not df_bruto.empty and "Erro" not in df_bruto.columns:
                
                # Filtro territorial preciso
                if nivel_terr == "Município":
                    col_map = {
                        "Mortalidade (SIM)": "CODMUNRES", "Internações (SIH-SP)": "SP_GESTOR",
                        "Nascimentos (SINASC)": "CODMUNRES", "Estabelecimentos (CNES)": "CODUFMUN"
                    }
                    col_filtro = col_map.get(sistema)
                    if col_filtro in df_bruto.columns:
                        df_bruto = df_bruto[df_bruto[col_filtro].astype(str).str.startswith(id_datasus_alvo)]
                
                # Gera as duas versões independentes
                df_tratado = tratar_e_traduzir_df(df_bruto, sistema)
                
                st.markdown(f'<div class="metric-card"><h2>{len(df_bruto)} Registros Encontrados</h2><p>{sistema} - {nome_local} ({ano_sel})</p></div>', unsafe_allow_html=True)
                
                st.info("💡 Apenas as primeiras 100 linhas são exibidas na tela para o navegador não travar. Os botões de download exportam a base completa.")
                
                col1, col2 = st.columns(2)
                
                # Interface lado a lado (resolve o problema da "aba escondida")
                with col1:
                    st.subheader("✅ Planilha Tratada")
                    st.caption("Cabeçalhos renomeados e códigos descritos.")
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
                    st.caption("Formato original, direto do FTP Ministério da Saúde.")
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
    # Correção Robusta VIS DATA 3
    st.subheader(f"🏠 Indicadores Sociais - {nome_local}")
    st.info("Conectando ao sistema VIS DATA 3 (MDS / SAGICAD).")
    
    if st.button("🔍 Extrair Tabelas MDS"):
        with st.spinner("Ultrapassando protocolos do servidor federal..."):
            url_mds = f"https://aplicacoes.cidadania.gov.br/vis/data3/v.php?ibge={id_ibge_alvo}"
            # Disfarce para não ser bloqueado pela API do Governo
            headers_mds = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'}
            
            try:
                # verify=False força a conexão mesmo se o certificado do governo estiver vencido
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
                st.error("O servidor do Ministério (VIS DATA) encontra-se fora do ar ou bloqueou a conexão no momento. Tente novamente mais tarde.")

st.divider()
st.caption("Sistema Otimizado. Para bases pesadas (acima de 100.000 linhas), aguarde o botão de download preparar o arquivo.")
