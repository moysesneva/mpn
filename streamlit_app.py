import streamlit as st
import pandas as pd
import requests
import io
import openai
import os
from pandas.tseries.offsets import BusinessDay  # Para calcular dias úteis

st.set_page_config(page_title="Agente de Leads Prioritários", layout="wide")

# 1) Cabeçalho e instruções
st.title("Análise de Leads Prioritários")
st.markdown("""
Este aplicativo permite carregar uma base de dados de atendimentos em formato Excel (.xlsx).
Você pode fazer upload do arquivo ou inserir uma URL direta.
Após o carregamento, o sistema identificará automaticamente os leads que requerem atenção urgente e gerará um relatório detalhado usando um agente inteligente.

**Critérios de Prioridade:**
- Leads com sinais de interesse/objeção no registro
- Leads sem contato nos últimos 2 dias úteis

**Certifique-se de ter configurado sua chave da API do OpenAI em**
`.streamlit/secrets.toml` **ou como variável de ambiente** `OPENAI_API_KEY`.
""")

# 2) Carregamento da chave e inicialização do cliente
api_key = None
try:
    # Tenta ler do st.secrets, que no Streamlit Cloud lê do Secrets
    api_key = st.secrets["openai"]["api_key"]
    st.sidebar.success("Chave da API carregada de secrets.")
    st.write(f"Chave encontrada (secrets): {api_key[:5]}...") # Feedback visual
except KeyError:
    # Se não encontrar em secrets, tenta ler da variável de ambiente
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        st.sidebar.success("Chave da API carregada de variável de ambiente.")
        st.write(f"Chave encontrada (ambiente): {api_key[:5]}...") # Feedback visual
    else:
        st.sidebar.error(
            "Chave da API do OpenAI não encontrada. "
            "Configure-a nas 'Secrets' do Streamlit Cloud ou como variável de ambiente `OPENAI_API_KEY`."
        )
        st.stop() # Para a execução do app se a chave não for encontrada

try:
    client = openai.OpenAI(api_key=api_key)
except Exception as e:
    st.sidebar.error(f"Erro ao inicializar cliente OpenAI: {e}")
    st.stop() # Para a execução se o cliente não puder ser inicializado

# 3) Upload ou URL do Excel
st.header("1. Carregar Base de Conhecimento (.xlsx)")
source = st.radio("Selecione a origem do arquivo:", ("Upload", "URL"))

excel_bytes = None
if source == "Upload":
    uploaded_file = st.file_uploader("Selecione o arquivo .xlsx", type=["xlsx"])
    if uploaded_file:
        excel_bytes = uploaded_file.read()
else:
    url = st.text_input("Insira a URL do arquivo .xlsx")
    if url:
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            excel_bytes = resp.content
        except Exception as e:
            st.error(f"Erro ao baixar o arquivo: {e}")

if excel_bytes is None:
    st.info("Por favor, faça o upload do arquivo ou insira a URL para continuar.")
    st.stop() # Para a execução se o arquivo não for carregado

# 4) Leitura e tratamento básico
try:
    df = pd.read_excel(io.BytesIO(excel_bytes), engine="openpyxl")
    df['Data do Atendimento'] = pd.to_datetime(df['Data do Atendimento'], errors='coerce')
    df.dropna(subset=['Data do Atendimento'], inplace=True)
    df["Registro"] = df["Registro"].astype(str).fillna("")
    df["Atendente"] = df["Atendente"].astype(str).fillna("Não Informado")
except Exception as e:
    st.error(f"Falha ao ler/processar o Excel: {e}")
    st.stop() # Para a execução se houver erro no processamento do Excel

required_cols = ["Data do Atendimento", "Nome do Atendido", "Atendente", "Registro"]
missing = [c for c in required_cols if c not in df.columns]
if missing:
    st.error(f"Colunas faltantes no arquivo: {missing}")
    st.stop() # Para a execução se colunas essenciais estiverem faltando

# 5) Filtragem de leads prioritários
keywords = r"repique|novo repique|objeção|objeções|urgente|fechar|matricula|interessado|proposta"
mask_kw = df["Registro"].str.contains(keywords, case=False, na=False)
two_bd_ago = pd.Timestamp.now() - BusinessDay(2)
mask_date = df['Data do Atendimento'] <= two_bd_ago
df_priority = df[mask_kw | mask_date].reset_index(drop=True)

st.header("2. Leads Prioritários Identificados (Critérios Atualizados)")
if df_priority.empty:
    st.warning("Nenhum lead prioritário encontrado com os critérios atuais.")
    st.stop() # Para a execução se não houver leads prioritários
else:
    st.dataframe(df_priority)

# 6) Prompt do agente - Adaptado para processar UM lead por vez
agent_prompt = """
<agente>[Role]
Você é um agente especialista em análise de dados de leads, focado em identificar leads que requerem atenção imediata e fornecer sugestões de abordagem via WhatsApp. Você é um consultor de vendas experiente.

[Objetivo]
Seu objetivo é analisar os dados de **UM ÚNICO LEAD** fornecido e gerar APENAS a seção do relatório correspondente a este lead, incluindo uma sugestão de mensagem para WhatsApp.

[Cenário]
Você receberá os dados de um lead prioritário por vez. Sua tarefa é gerar a saída formatada para este lead específico.

[Solução Esperada]
Gere a seção do relatório para o lead fornecido, formatada em **Markdown**, seguindo este modelo EXATO:

---
**Lead Prioritário:**
Nome: [Nome completo do Atendido]
Atendente: [Primeiro nome do Atendente]
Data: [Data do Atendimento]
Motivo da Prioridade: [Breve descrição do motivo, baseada no 'Registro' ou na falta de contato recente. Exemplos: "Objeção de Preço", "Interesse em Fechar Matrícula", "Sem Contato há mais de 2 dias úteis", "Repique Pendente"].
Sugestão de Abordagem (WhatsApp): [Mensagem objetiva, jovial, com uso moderado de emojis, pronta para envio. Personalize com base no 'Registro' ou falta de contato. Inclua placeholders como "[Nome do Lead]", "[Seu Nome]".]
---

-   Use **negrito** para os títulos de seção conforme o modelo.
-   Inclua a linha horizontal (`---`) **apenas no início e no fim** da seção deste lead.
-   Se o 'Registro' mencionar "Repique" ou "novo repique", adicione uma linha extra APÓS a Sugestão de Abordagem, formatada como: **Alerta Especial: Repique/Novo Repique para [Nome Completo do Lead]**.
-   Seja conciso e direto.

[Exemplo de Entrada (você receberá os dados neste formato)]
Dados do Lead Prioritário:
- Nome Lead: Josiele Pereira
  Atendente: Mariana
  Data: 2025-01-04
  Registro Completo: O lead mencionou que achou o preço alto, mas ficou de pensar. Possível objeção de preço.

[Exemplo de Saída Esperada (em Markdown)]
---
**Lead Prioritário:**
Nome: Josiele Pereira
Atendente: Mariana
Data: 2025-01-04
Motivo da Prioridade: Objeção de Preço
Sugestão de Abordagem (WhatsApp):
Olá, Josiele! 👋 Tudo bem por aí?

Vi aqui que você mencionou sua dúvida sobre valores. Queria ver se consigo te ajudar rapidinho com isso! Que tal a gente conversar 5 minutinhos? ✨

Me diz o melhor horário pra você! 😊
---
""".strip()


def gerar_relatorio(client: openai.OpenAI, df_leads: pd.DataFrame) -> str:
    relatorio_completo = []
    total_leads = len(df_leads)

    # Itera sobre cada lead no DataFrame de prioritários
    for index, row in df_leads.iterrows():
        st.info(f"Processando lead {index + 1} de {total_leads}...") # Feedback de progresso

        atendente = str(row["Atendente"]).split()[0] if pd.notna(row["Atendente"]) else "N/A"
        registro_str = str(row["Registro"]) if pd.notna(row["Registro"]) else ""

        # Prepara o conteúdo para este lead específico
        user_content = (
            "Dados do Lead Prioritário:\n"
            f"- Nome Lead: {row['Nome do Atendido']}\n"
            f"  Atendente: {atendente}\n"
            f"  Data: {row['Data do Atendimento'].strftime('%Y-%m-%d') if pd.notna(row['Data do Atendimento']) else 'N/A'}\n"
            f"  Registro Completo: {registro_str}"
        )

        try:
            # Chama a API para este lead individual
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": agent_prompt},
                    {"role": "user",   "content": user_content}
                ],
                max_tokens=500, # Reduzido, pois agora processa apenas um lead por vez
                temperature=0.7
            )
            # Adiciona a resposta do agente (seção do relatório) à lista
            relatorio_completo.append(resp.choices[0].message.content)

        except Exception as e:
            # Adiciona uma mensagem de erro para este lead específico se a API falhar
            st.error(f"Erro na chamada da API para {row['Nome do Atendido']}: {e}")
            st.write(e) # Mostra o erro detalhado da API
            relatorio_completo.append(
                f"---"
                f"\n**Lead Prioritário:**\nNome: {row['Nome do Atendido']}\n"
                f"Atendente: {atendente}\nData: {row['Data do Atendimento'].strftime('%Y-%m-%d') if pd.notna(row['Data do Atendimento']) else 'N/A'}\n"
                f"Motivo da Prioridade: Erro ao processar\n"
                f"Sugestão de Abordagem (WhatsApp): Erro na geração\n" # Mensagem genérica de erro na sugestão
                f"---"
            )


    # Junta todas as seções geradas pelo agente em um único relatório
    # Note que o agente já inclui os "---" no início e fim de cada seção
    return "".join(relatorio_completo)


# 7) Botão e exibição em Markdown
if st.button("Gerar Relatório de Leads Prioritários"):
    with st.spinner("Processando e gerando relatório..."):
        relatorio = gerar_relatorio(client, df_priority)
        st.header("3. Relatório Gerado pelo Agente")
        # Exibe o relatório completo. Como o agente já formata com Markdown e "---",
        # st.markdown renderizará corretamente.
        st.markdown(relatorio)
