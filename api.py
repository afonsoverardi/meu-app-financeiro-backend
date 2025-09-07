from flask import Flask, request, jsonify
import requests 
from bs4 import BeautifulSoup

# Importe o seu script de raspagem. 
# Mude 'dados_raspados' para o nome do seu arquivo de script.
from dados import extrair_dados_nota_fiscal

app = Flask(__name__)

@app.route('/processar_nota', methods=['POST'])
def processar_nota():
    try:
        # Pega o link da nota fiscal do corpo da requisição POST
        link_nota = request.json.get('url')
        if not link_nota:
            return jsonify({'erro': 'URL da nota fiscal não fornecida.'}), 400

        # Chama a sua função de raspagem para extrair os dados
        dados_extraidos = extrair_dados_nota_fiscal(link_nota)

        if dados_extraidos:
            return jsonify(dados_extraidos)
        else:
            return jsonify({'erro': 'Não foi possível processar a nota fiscal.'}), 500

    except Exception as e:
        return jsonify({'erro': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)