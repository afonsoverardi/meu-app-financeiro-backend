import os
import json
from google.oauth2 import service_account
from google.cloud import vision

# --- INÍCIO DO BLOCO DE DIAGNÓSTICO ---

print("--- [FASE 1 de 3] O ficheiro dados.py começou a ser importado. ---")

# Inicializa as variáveis para verificação
vision_client = None
erro_na_inicializacao = ""

# Define os caminhos possíveis para as credenciais
render_credentials_path = "/etc/secrets/credentials.json"
local_credentials_path = "credentials.json"

CREDENTIALS_PATH = ""
if os.path.exists(render_credentials_path):
    CREDENTIALS_PATH = render_credentials_path
elif os.path.exists(local_credentials_path):
    CREDENTIALS_PATH = local_credentials_path

if CREDENTIALS_PATH:
    print(f"--- [FASE 2 de 3] Ficheiro de credenciais encontrado em: {CREDENTIALS_PATH} ---")
    try:
        credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)
        vision_client = vision.ImageAnnotatorClient(credentials=credentials)
        print("--- [FASE 3 de 3] SUCESSO! Cliente do Google Cloud Vision inicializado. ---")
    except Exception as e:
        erro_na_inicializacao = f"FALHA na FASE 3: Erro ao carregar credenciais: {e}"
        print(f"--- [FASE 3 de 3] {erro_na_inicializacao} ---")
else:
    erro_na_inicializacao = "FALHA na FASE 2: Ficheiro 'credentials.json' não foi encontrado."
    print(f"--- [FASE 2 de 3] {erro_na_inicializacao} ---")

# --- FIM DO BLOCO DE DIAGNÓSTICO ---


# --- O resto do código foi simplificado para o teste ---

def extrair_dados_nota_fiscal(url):
    # Função mantida para que a importação não falhe
    return {"status": "Função de NFe não testada"}

def analisar_imagem_comprovante(arquivo_imagem):
    """
    Função de teste que verifica se a inicialização funcionou.
    """
    print("--- A função analisar_imagem_comprovante foi chamada. ---")
    if vision_client:
        return {"status": "SUCESSO", "mensagem": "O cliente do Vision está pronto!"}
    else:
        return {"status": "FALHA", "mensagem": erro_na_inicializacao}