import requests
from bs4 import BeautifulSoup
import re
import google.generativeai as genai
import os
import json

# --- Início da Configuração do Gemini ---
API_KEY = 'AIzaSyDiNznFsU4bBZVtwWLDOUytsCNDpXgXdGs' 

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# MODIFICADO: Adicionada a categoria 'Carro'
LISTA_DE_CATEGORIAS = [
    'Mercado', 'Alimentação', 'Saúde', 'Cuidados pessoais', 'Bares e restaurantes', 
    'Carro', 'Pets', 'Casa', 'Transporte', 'Lazer e hobbies', 'Roupas', 'Educação', 
    'Assinaturas e serviços', 'Viagem', 'Presentes e doações', 'Investimentos', 
    'Impostos e Taxas', 'Trabalho', 'Outros', 'Não Categorizado'
]
CATEGORIAS_PARA_PROMPT = ", ".join(f"'{cat}'" for cat in LISTA_DE_CATEGORIAS)
# --- Fim da Configuração do Gemini ---

# --- FUNÇÕES DE IA ---

def classificar_local_com_ia(nome_local):
    print("--- Entrando na função classificar_local_com_ia ---")
    if not API_KEY or API_KEY == 'SUA_CHAVE_DE_API_AQUI':
        print("-> FALHA: Chave de API não configurada.")
        return "Desconhecido"
    try:
        prompt = (f"Qual é o tipo mais provável deste estabelecimento comercial: '{nome_local}'? "
                  "Responda de forma curta e direta, como 'Supermercado', 'Farmácia', 'Posto de Combustível', 'Loja de Eletrônicos', etc.")
        
        print("-> Enviando requisição para classificar local...")
        response = model.generate_content(prompt)
        
        if response.prompt_feedback.block_reason:
            print(f"### ERRO: Requisição para classificar local foi bloqueada. Razão: {response.prompt_feedback.block_reason} ###")
            return "Desconhecido"
        
        if not response.parts:
            print(f"### ERRO: A resposta da IA para classificar local veio vazia. Feedback: {response.prompt_feedback} ###")
            return "Desconhecido"

        print(f"  -> Resposta bruta da IA (Local): '{response.text.strip()}'")
        return response.text.strip()

    except Exception as e:
        print(f"### ERRO INESPERADO ao classificar local: {e} ###")
        return "Desconhecido"

def categorizar_lista_inteira_com_ia(itens, tipo_local):
    print("--- Entrando na função categorizar_lista_inteira_com_ia ---")
    if not API_KEY or API_KEY == 'SUA_CHAVE_DE_API_AQUI':
        return {item['nome']: 'Não Categorizado' for item in itens}

    try:
        nomes_itens = [item['nome'] for item in itens]
        lista_formatada = "\n".join(f"- {nome}" for nome in nomes_itens)
        
        prompt = (f"A compra a seguir foi feita em um '{tipo_local}'. "
                  f"Analise a lista de itens e retorne um array JSON com a categoria de cada um, escolhida da lista [{CATEGORIAS_PARA_PROMPT}].\n"
                  f"Use a categoria 'Outros' para itens muito específicos que não se encaixam bem nas demais, como componentes eletrônicos.\n"
                  f"Leve em conta o contexto. Exemplo: 'gasolina' em um 'Posto de Combustível' deve ser 'Carro'.\n"
                  f"Lista:\n{lista_formatada}\n"
                  "O JSON de saída deve ter o formato: [{\"item\": \"NOME_DO_ITEM\", \"categoria\": \"CATEGORIA_ESCOLHIDA\"}]")
        
        print("-> Enviando requisição para categorizar lista de itens...")
        response = model.generate_content(
            prompt,
            safety_settings={
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
            }
        )
        
        print(f"  -> Resposta bruta da IA (Itens): '{response.text.strip()}'")
        
        if response.prompt_feedback.block_reason:
            print(f"### ERRO: Requisição para categorizar lista foi bloqueada. Razão: {response.prompt_feedback.block_reason} ###")
            return {item['nome']: 'Não Categorizado' for item in itens}
        
        if not response.parts:
            print(f"### ERRO: A resposta da IA para categorizar lista veio vazia. Feedback: {response.prompt_feedback} ###")
            return {item['nome']: 'Não Categorizado' for item in itens}

        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        categorias_json = json.loads(resposta_texto)
        
        return {item['item']: item['categoria'] for item in categorias_json}

    except Exception as e:
        print(f"### ERRO INESPERADO ao categorizar lista: {e} ###")
        if 'response' in locals():
            print(f"A resposta da IA que pode ter causado o erro foi: {response.text.strip()}")
        return {item['nome']: 'Não Categorizado' for item in itens}

# --- FUNÇÃO PRINCIPAL ---
def extrair_dados_nota_fiscal(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        info_local_div = soup.find('div', class_='txtCenter')
        nome_local = "Não encontrado"
        if info_local_div:
            nome_local_el = info_local_div.find('div', id='u20', class_='txtTopo')
            if nome_local_el: nome_local = nome_local_el.text.strip()

        print(f"Classificando o local: '{nome_local}'...")
        tipo_local = classificar_local_com_ia(nome_local)
        print(f"-> Tipo de local identificado: '{tipo_local}'")

        data_el = soup.find('strong', string=re.compile(r'Emissão:'))
        data_emissao = "Não encontrada"
        if data_el:
            data_limpa = re.search(r'(\d{2}/\d{2}/\d{4})', data_el.next_sibling.strip())
            if data_limpa: data_emissao = data_limpa.group(1)
        
        itens_brutos = []
        titulos_itens = soup.find_all('span', class_='txtTit')
        for titulo in titulos_itens:
            nome_item = titulo.text.strip()
            td_pai = titulo.parent
            quantidade_el = td_pai.find('span', class_='Rqtd')
            valor_unitario_el = td_pai.find('span', class_='RvlUnit')
            if quantidade_el and valor_unitario_el:
                itens_brutos.append({
                    'nome': nome_item,
                    'quantidade': float(quantidade_el.text.strip().replace('Qtde.:', '')),
                    'valor_unitario': float(valor_unitario_el.text.strip().replace('Vl. Unit.:', '').replace(',', '.').strip()),
                })

        print(f"Enviando {len(itens_brutos)} itens para categorização em lote...")
        mapa_categorias_ia = categorizar_lista_inteira_com_ia(itens_brutos, tipo_local)

        itens_comprados = []
        for item in itens_brutos:
            item['categoria'] = mapa_categorias_ia.get(item['nome'], 'Não Categorizado')
            itens_comprados.append(item)
            print(f"-> Item: '{item['nome']}', Categoria: '{item['categoria']}'")

        valor_total_el = soup.find('span', class_='valor')
        valor_total_limpo = float(valor_total_el.text.strip().replace(',', '.').strip()) if valor_total_el else None

        return {
            'nome_local': nome_local,
            'cnpj': "Não encontrado",
            'endereco': "Não encontrado",
            'data': data_emissao,
            'itens_comprados': itens_comprados,
            'valor_total': valor_total_limpo
        }

    except Exception as e:
        print(f"Erro ao extrair dados: {e}")
        return None