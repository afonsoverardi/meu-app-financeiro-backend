import requests
from bs4 import BeautifulSoup
import re
import google.generativeai as genai
import os
import json
from PIL import Image
from google.cloud import vision
from google.oauth2 import service_account
from datetime import datetime

# --- Configuração (sem alterações) ---
API_KEY = os.getenv('GEMINI_API_KEY')
model = None
if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("AVISO: GEMINI_API_KEY não foi encontrada no ambiente.")

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
        print(f"### ERRO AO INICIALIZAR CLIENTE DO GOOGLE CLOUD VISION: {e} ###")
else:
    print("AVISO: Arquivo de credenciais 'credentials.json' não foi encontrado.")

LISTA_DE_CATEGORIAS = [
    'Mercado', 'Alimentação', 'Saúde', 'Cuidados pessoais', 'Bares e restaurantes', 
    'Carro', 'Pets', 'Casa', 'Transporte', 'Lazer e hobbies', 'Roupas', 'Educação', 
    'Assinaturas e serviços', 'Viagem', 'Presentes e doações', 'Investimentos', 
    'Impostos e Taxas', 'Trabalho', 'Outros', 'Não Categorizado'
]
CATEGORIAS_PARA_PROMPT = ", ".join(f"'{cat}'" for cat in LISTA_DE_CATEGORIAS)
# --- Fim da Configuração ---


# --- Funções Auxiliares de IA (sem alterações, mas com uma nova função) ---
def classificar_local_com_ia(nome_local):
    #... (sem alterações)
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
    #... (sem alterações)
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
    #... (sem alterações)
    if not model: return {"nome": "Compra em Cartão", "categoria": "Outros"}
    try:
        prompt = (f"Analise o texto de um comprovante: '{texto_completo}'.\n"
                  f"Crie um nome curto para esta compra (ex: 'Remédios', 'Combustível', 'Restaurante', 'Lanche') "
                  f"e escolha a categoria mais apropriada da lista: [{CATEGORIAS_PARA_PROMPT}].\n"
                  "Responda com um JSON no formato: {\"nome\": \"NOME_SUGERIDO\", \"categoria\": \"CATEGORIA_SUGERIDA\"}")
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(resposta_texto)
    except Exception as e:
        print(f"### ERRO ao resumir compra: {e} ###")
        return {"nome": "Compra em Cartão", "categoria": "Outros"}

# --- NOVA FUNÇÃO DE IA ESPECIALISTA EM DANFE ---
def analisar_imagem_danfe_com_ia(texto_completo):
    if not model: return None
    print("-> Tentando extrair itens da DANFE com IA especializada...")
    try:
        # Prompt otimizado para extrair a tabela de produtos de uma DANFE
        prompt = (
            "Analise o texto extraído de uma DANFE (Nota Fiscal Eletrônica) e extraia a lista de produtos. "
            "O texto pode conter ruídos de OCR. Ignore cabeçalhos, rodapés e impostos. "
            "Foque na seção 'DADOS DOS PRODUTOS/SERVIÇOS'.\n"
            "Para cada produto, extraia a descrição, quantidade, valor unitário e valor total.\n"
            "Retorne a resposta como um array JSON no seguinte formato: "
            "[{\"nome\": \"NOME_DO_PRODUTO\", \"quantidade\": 1.0, \"valor_unitario\": 12.34, \"valor_total\": 12.34}]\n"
            f"Texto para análise:\n---\n{texto_completo}\n---"
        )
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "").strip()
        
        # Validação extra para garantir que a resposta é um JSON válido
        if not resposta_texto.startswith('[') or not resposta_texto.endswith(']'):
            print("AVISO: A resposta da IA para a DANFE não é um array JSON válido.")
            return None
            
        itens = json.loads(resposta_texto)
        
        # Verifica se a lista de itens não está vazia e se os itens têm a estrutura esperada
        if isinstance(itens, list) and len(itens) > 0 and 'nome' in itens[0]:
            print(f"-> SUCESSO: {len(itens)} itens extraídos da DANFE pela IA.")
            return itens
        else:
            return None

    except Exception as e:
        print(f"### ERRO na análise de DANFE com IA: {e} ###")
        return None

# --- Funções Principais de Processamento (sem alterações na assinatura) ---
def extrair_dados_nota_fiscal(url):
    #... (sem alterações)
    return None

def converter_valor_brasileiro(valor_str):
    #... (sem alterações)
    if not valor_str: return 0.0
    valor_limpo = valor_str.strip().replace("R$", "").replace(".", "").replace(",", ".")
    try:
        return float(valor_limpo)
    except ValueError:
        return 0.0

# --- FUNÇÃO PRINCIPAL ATUALIZADA ---
def analisar_imagem_comprovante(conteudo_imagem):
    if not vision_client:
        print("### ERRO CRÍTICO: Cliente do Google Cloud Vision não está inicializado. ###")
        return None
    try:
        imagem_vision = vision.Image(content=conteudo_imagem)
        print("Enviando imagem para a Google Cloud Vision API...")
        response = vision_client.document_text_detection(image=imagem_vision)
        
        if not response.full_text_annotation:
            print("AVISO: Nenhum texto foi detectado na imagem.")
            return None
            
        texto_extraido = response.full_text_annotation.text
        print("\n--- Texto extraído pela Vision API ---")
        print(texto_extraido[:500] + "...") # Imprime apenas os primeiros 500 caracteres
        print("------------------------------------\n")

        # --- LÓGICA ATUALIZADA ---
        
        # 1. Tenta extrair a lista de itens usando a nova IA especialista em DANFE
        itens_danfe = analisar_imagem_danfe_com_ia(texto_extraido)
        
        if itens_danfe:
            # Se conseguiu extrair itens, busca a data e o emitente
            data_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto_extraido)
            data_compra = data_match.group(1) if data_match else datetime.now().strftime("%d/%m/%Y")
            
            # Tenta encontrar o valor total para consistência, mas não é crucial
            valor_total_final = sum(item.get('valor_total', 0.0) for item in itens_danfe)

            # Categoriza os itens extraídos em lote
            # (Requer nome do local, podemos extrair ou usar um genérico)
            # Para simplificar, vamos deixar a categorização para o usuário por enquanto
            itens_comprados = []
            for item in itens_danfe:
                itens_comprados.append({
                    'nome': item.get('nome', 'Item desconhecido'),
                    'quantidade': float(item.get('quantidade', 1.0)),
                    'valor_unitario': float(item.get('valor_unitario', 0.0)),
                    'categoria': 'Não Categorizado'
                })

            return {
                'data': data_compra,
                'itens_comprados': itens_comprados,
                'valor_total': valor_total_final,
            }

        # 2. Se a IA de DANFE falhar, tenta a lógica antiga de resumir o comprovante
        print("-> A análise de DANFE falhou. Processando como comprovante simples...")
        data_match = re.search(r"(\d{2}/\d{2}/\d{2,4})", texto_extraido)
        data_compra = datetime.now().strftime("%d/%m/%Y")
        if data_match:
            data_str = data_match.group(1)
            if len(data_str.split('/')[2]) == 2:
                data_compra = datetime.strptime(data_str, '%d/%m/%y').strftime('%d/%m/%Y')
            else:
                data_compra = data_str
        
        valor_total = 0.0
        valores_encontrados = re.findall(r"[\d,]+\.\d{2}|[\d\.]+\,\d{2}", texto_extraido)
        if valores_encontrados:
            valor_total = converter_valor_brasileiro(valores_encontrados[-1])
        
        resumo_ia = resumir_e_categorizar_compra_com_ia(texto_extraido)
        
        item_unico = {
            'nome': resumo_ia.get('nome', 'Compra em Cartão'),
            'quantidade': 1.0,
            'valor_unitario': valor_total,
            'categoria': resumo_ia.get('categoria', 'Outros')
        }
        
        return {
            'data': data_compra,
            'itens_comprados': [item_unico],
            'valor_total': valor_total,
        }
        
    except Exception as e:
        print(f"Erro no processamento com a Vision API: {e}")
        return None