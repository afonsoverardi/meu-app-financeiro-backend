import requests
from bs4 import BeautifulSoup
import re
import google.generativeai as genai
import os
import json
from PIL import Image
from google.cloud import vision
from google.oauth2 import service_account

# --- Início da Configuração ---

# 1. Configuração do Gemini (para categorização)
API_KEY = os.getenv('GEMINI_API_KEY')
model = None
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("AVISO: GEMINI_API_KEY não foi encontrada no ambiente.")

# 2. Configuração do Google Cloud Vision (para ler imagens - OCR)
vision_client = None
render_credentials_path = "/etc/secrets/credentials.json"
local_credentials_path = "credentials.json"
CREDENTIALS_PATH = ""

if os.path.exists(render_credentials_path):
    CREDENTIALS_PATH = render_credentials_path
elif os.path.exists(local_credentials_path):
    CREDENTIALS_PATH = local_credentials_path

if CREDENTIALS_PATH:
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)
        vision_client = vision.ImageAnnotatorClient(credentials=credentials)
        print("-> Cliente do Google Cloud Vision inicializado com sucesso.")
    except Exception as e:
        print(f"### ERRO ao inicializar cliente do Google Cloud Vision: {e} ###")
else:
    print("AVISO: Arquivo de credenciais 'credentials.json' não foi encontrado.")

# 3. Lista de Categorias para a IA
LISTA_DE_CATEGORias = [
    'Mercado', 'Alimentação', 'Saúde', 'Cuidados pessoais', 'Bares e restaurantes', 
    'Carro', 'Pets', 'Casa', 'Transporte', 'Lazer e hobbies', 'Roupas', 'Educação', 
    'Assinaturas e serviços', 'Viagem', 'Presentes e doações', 'Investimentos', 
    'Impostos e Taxas', 'Trabalho', 'Outros', 'Não Categorizado'
]
CATEGORIAS_PARA_PROMPT = ", ".join(f"'{cat}'" for cat in LISTA_DE_CATEGORIAS)

# --- Fim da Configuração ---


# --- Funções Auxiliares de IA ---

def classificar_local_com_ia(nome_local):
    if not model: return "Desconhecido"
    try:
        prompt = (f"Classifique o tipo do seguinte estabelecimento comercial: '{nome_local}'. "
                  "Responda com uma única palavra ou expressão curta, como 'Supermercado', 'Farmácia', 'Posto de Combustível', etc.")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"### ERRO ao classificar local: {e} ###")
        return "Desconhecido"

def categorizar_lista_inteira_com_ia(itens, tipo_local):
    if not model: return {item['nome']: 'Não Categorizado' for item in itens}
    try:
        nomes_itens = [item['nome'] for item in itens]
        lista_formatada = "\n".join(f"- {nome}" for nome in nomes_itens)
        prompt = (f"A compra a seguir foi feita em um '{tipo_local}'. "
                  f"Analise a lista de itens e retorne um array JSON com a categoria de cada um, escolhida da lista [{CATEGORIAS_PARA_PROMPT}].\n"
                  f"Use a categoria 'Outros' para itens que não se encaixam bem nas demais.\n"
                  f"Contexto: 'doguinho' em um 'Posto de Combustível' é 'Alimentação'. 'Gasolina' é 'Carro'.\n"
                  f"Lista:\n{lista_formatada}\n"
                  "O JSON de saída deve ter o formato: [{\"item\": \"NOME_DO_ITEM\", \"categoria\": \"CATEGORIA_ESCOLHIDA\"}]")
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        categorias_json = json.loads(resposta_texto)
        return {item['item']: item['categoria'] for item in categorias_json}
    except Exception as e:
        print(f"### ERRO ao categorizar lista: {e} ###")
        return {item['nome']: 'Não Categorizado' for item in itens}

def resumir_e_categorizar_compra_com_ia(texto_completo):
    if not model: return {"nome": "Compra em Cartão", "categoria": "Outros"}
    try:
        prompt = (f"Analise o texto de um comprovante: '{texto_completo}'.\n"
                  f"Crie um nome curto para esta compra (ex: 'Remédios', 'Combustível') "
                  f"e escolha a categoria mais apropriada da lista: [{CATEGORIAS_PARA_PROMPT}].\n"
                  "Responda com um JSON no formato: {\"nome\": \"NOME_SUGERIDO\", \"categoria\": \"CATEGORIA_SUGERIDA\"}")
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(resposta_texto)
    except Exception as e:
        print(f"### ERRO ao resumir compra: {e} ###")
        return {"nome": "Compra em Cartão", "categoria": "Outros"}


# --- Funções Principais de Processamento ---

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
                    'valor_unitario': float(valor_unitario_el.text.strip().replace('Vl. Unit.:', '').replace(',', '.')),
                })
        
        print(f"Enviando {len(itens_brutos)} itens para categorização em lote...")
        mapa_categorias_ia = categorizar_lista_inteira_com_ia(itens_brutos, tipo_local)

        itens_comprados = []
        for item in itens_brutos:
            item['categoria'] = mapa_categorias_ia.get(item['nome'], 'Não Categorizado')
            itens_comprados.append(item)
        
        valor_total_el = soup.find('span', class_='valor')
        valor_total_limpo = float(valor_total_el.text.strip().replace(',', '.')) if valor_total_el else None

        return {
            'data': data_emissao,
            'itens_comprados': itens_comprados,
            'valor_total': valor_total_limpo
        }
    except Exception as e:
        print(f"Erro ao extrair dados da nota fiscal: {e}")
        return None

def analisar_imagem_comprovante(arquivo_imagem):
    if not vision_client:
        print("### ERRO CRÍTICO: Cliente do Google Cloud Vision não está inicializado. Verifique o 'Secret File' na Render. ###")
        return None

    try:
        conteudo_imagem = arquivo_imagem.read()
        imagem_vision = vision.Image(content=conteudo_imagem)

        print("Enviando imagem para a Google Cloud Vision API...")
        response = vision_client.document_text_detection(image=imagem_vision)
        texto_extraido = response.full_text_annotation.text
        
        print("\n--- Texto extraído pela Vision API ---")
        print(texto_extraido)
        print("------------------------------------\n")

        data_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto_extraido)
        valor_match = re.search(r"(?:TOTAL|Valor:)\s*R\$\s*([\d,]+\.?\d*)", texto_extraido, re.IGNORECASE)

        data_compra = data_match.group(1) if data_match else "Data não encontrada"
        valor_total = float(valor_match.group(1).replace(',', '.')) if valor_match else 0.0

        print(f"Enviando texto para IA resumir e categorizar...")
        resumo_ia = resumir_e_categorizar_compra_com_ia(texto_extraido)
        print(f"-> Resumo da IA: {resumo_ia}")

        item_unico = {
            'nome': resumo_ia.get('nome', 'Compra em Cartão'),
            'quantidade': 1.0,
            'valor_unitario': valor_total,
            'categoria': resumo_ia.get('categoria', 'Outros')
        }
        
        return {
            'data': data_compra,
            'itens_comprados': [item_unico],
            'valor_total': valor_total
        }
    except Exception as e:
        print(f"Erro no processamento com a Vision API: {e}")
        return None