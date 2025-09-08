import requests
from bs4 import BeautifulSoup
import re
import google.generativeai as genai
import os
import json
from PIL import Image
from google.cloud import vision
from google.oauth2 import service_account

# --- Início da Configuração do Gemini ---
API_KEY = os.getenv('GEMINI_API_KEY')

if API_KEY:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("AVISO DE SEGURANÇA: A variável de ambiente GEMINI_API_KEY não foi encontrada.")
    model = None

LISTA_DE_CATEGORIAS = [
    'Mercado', 'Alimentação', 'Saúde', 'Cuidados pessoais', 'Bares e restaurantes', 
    'Carro', 'Pets', 'Casa', 'Transporte', 'Lazer e hobbies', 'Roupas', 'Educação', 
    'Assinaturas e serviços', 'Viagem', 'Presentes e doações', 'Investimentos', 
    'Impostos e Taxas', 'Trabalho', 'Outros', 'Não Categorizado'
]
CATEGORIAS_PARA_PROMPT = ", ".join(f"'{cat}'" for cat in LISTA_DE_CATEGORIAS)
# --- Fim da Configuração do Gemini ---


# **** MODIFICADO: Bloco de configuração do Google Cloud Vision ****
# Procura o arquivo de credenciais em dois locais possíveis
render_credentials_path = "/etc/secrets/credentials.json"
local_credentials_path = "credentials.json" # Para testes no seu PC

CREDENTIALS_PATH = ""
if os.path.exists(render_credentials_path):
    CREDENTIALS_PATH = render_credentials_path
elif os.path.exists(local_credentials_path):
    CREDENTIALS_PATH = local_credentials_path

vision_client = None
if CREDENTIALS_PATH:
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)
        vision_client = vision.ImageAnnotatorClient(credentials=credentials)
        print("Cliente do Google Cloud Vision inicializado com sucesso.")
    except Exception as e:
        print(f"### ERRO ao inicializar cliente do Google Cloud Vision: {e} ###")
else:
    print("AVISO: Arquivo de credenciais do Google Cloud Vision não encontrado.")
# **** Fim da Modificação ****


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
    if not model:
        return {item['nome']: 'Não Categorizado' for item in itens}

    try:
        nomes_itens = [item['nome'] for item in itens]
        lista_formatada = "\n".join(f"- {nome}" for nome in nomes_itens)
        prompt = (f"A compra a seguir foi feita em um '{tipo_local}'. "
                  f"Analise a lista de itens e retorne um array JSON com a categoria de cada um, escolhida da lista [{CATEGORIAS_PARA_PROMPT}].\n"
                  f"Use a categoria 'Outros' para itens muito específicos que não se encaixam bem nas demais.\n"
                  f"Leve em conta o contexto. Exemplo: 'gasolina' em um 'Posto de Combustível' deve ser 'Carro'.\n"
                  f"Lista:\n{lista_formatada}\n"
                  "O JSON de saída deve ter o formato: [{\"item\": \"NOME_DO_ITEM\", \"categoria\": \"CATEGORIA_ESCOLHIDA\"}]")
        
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        categorias_json = json.loads(resposta_texto)
        
        return {item['item']: item['categoria'] for item in categorias_json}
    except Exception as e:
        print(f"### ERRO INESPERADO ao categorizar lista: {e} ###")
        if 'response' in locals():
            print(f"A resposta da IA que pode ter causado o erro foi: {response.text.strip()}")
        return {item['nome']: 'Não Categorizado' for item in itens}

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
        if data_el:
            data_texto_completo = data_el.next_sibling.strip()
            data_limpa = re.search(r'(\d{2}/\d{2}/\d{4})', data_texto_completo)
            data_emissao = data_limpa.group(1) if data_limpa else 'Não encontrada'
        else:
            data_emissao = 'Não encontrada'
        
        itens_brutos = []
        titulos_itens = soup.find_all('span', class_='txtTit')

        for titulo in titulos_itens:
            nome_item = titulo.text.strip()
            td_pai = titulo.parent
            
            quantidade_el = td_pai.find('span', class_='Rqtd')
            valor_unitario_el = td_pai.find('span', class_='RvlUnit')
            
            if quantidade_el and valor_unitario_el:
                quantidade_limpa = quantidade_el.text.strip().replace('Qtde.:', '')
                valor_unitario_limpo = valor_unitario_el.text.strip().replace('Vl. Unit.:', '').replace(',', '.').strip()
                
                itens_brutos.append({
                    'nome': nome_item,
                    'quantidade': float(quantidade_limpa),
                    'valor_unitario': float(valor_unitario_limpo)
                })
        
        print(f"Enviando {len(itens_brutos)} itens para categorização em lote...")
        mapa_categorias_ia = categorizar_lista_inteira_com_ia(itens_brutos, tipo_local)

        itens_comprados = []
        for item in itens_brutos:
            item['categoria'] = mapa_categorias_ia.get(item['nome'], 'Não Categorizado')
            itens_comprados.append(item)
            print(f"-> Item: '{item['nome']}', Categoria: '{item['categoria']}'")

        valor_total_el = soup.find('span', class_='valor')
        if valor_total_el:
            valor_total = valor_total_el.text.strip().replace(',', '.').strip()
            valor_total_limpo = float(valor_total)
        else:
            valor_total_limpo = None

        return {
            'data': data_emissao,
            'itens_comprados': itens_comprados,
            'valor_total': valor_total_limpo
        }
    except requests.exceptions.RequestException as e:
        print(f"Erro na requisição: {e}")
        return None
    except Exception as e:
        print(f"Erro ao extrair dados: {e}")
        return None

def resumir_e_categorizar_compra_com_ia(texto_completo):
    if not model:
        return {"nome": "Compra em Cartão", "categoria": "Outros"}
    try:
        prompt = (f"Analise o texto extraído de um comprovante de pagamento: '{texto_completo}'.\n"
                  f"Com base no nome do estabelecimento e no contexto, crie um nome curto e genérico para esta compra (ex: 'Remédios', 'Combustível', 'Restaurante') "
                  f"e escolha a categoria mais apropriada da lista: [{CATEGORIAS_PARA_PROMPT}].\n"
                  "Responda com um JSON no formato: {\"nome\": \"NOME_SUGERIDO\", \"categoria\": \"CATEGORIA_SUGERIDA\"}")
        
        response = model.generate_content(prompt)
        resposta_texto = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(resposta_texto)
    except Exception as e:
        print(f"### ERRO ao resumir compra com IA: {e} ###")
        return {"nome": "Compra em Cartão", "categoria": "Outros"}

def analisar_imagem_comprovante(arquivo_imagem):
    if not vision_client:
        print("### ERRO CRÍTICO: Cliente do Google Cloud Vision não está inicializado. Verifique as credenciais. ###")
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

        nome_local_match = re.search(r"Estabelecimento:\s*(.*)", texto_extraido, re.IGNORECASE)
        data_match = re.search(r"(\d{2}/\d{2}/\d{4})", texto_extraido)
        valor_match = re.search(r"Valor:\s*R\$\s*([\d,]+\.?\d*)", texto_extraido, re.IGNORECASE)

        nome_local = nome_local_match.group(1).strip() if nome_local_match else "Não identificado"
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
            'nome_local': nome_local,
            'data': data_compra,
            'itens_comprados': [item_unico],
            'valor_total': valor_total
        }
    except Exception as e:
        print(f"Erro no processamento com a Vision API: {e}")
        return None