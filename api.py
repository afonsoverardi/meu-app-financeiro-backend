from flask import Flask, request, jsonify
from dotenv import load_dotenv # Adicionado para carregar o arquivo .env
from dados import extrair_dados_nota_fiscal

# Adicionado para carregar as variáveis do arquivo .env no ambiente local
load_dotenv() 

app = Flask(__name__) #

@app.route('/processar_nota', methods=['POST'])
def processar_nota():
    try:
        link_nota = request.json.get('url') #
        if not link_nota:
            return jsonify({'erro': 'URL da nota fiscal não fornecida.'}), 400 #

        dados_extraidos = extrair_dados_nota_fiscal(link_nota) #

        if dados_extraidos:
            return jsonify(dados_extraidos) #
        else:
            return jsonify({'erro': 'Não foi possível processar a nota fiscal.'}), 500 #

    except Exception as e:
        return jsonify({'erro': str(e)}), 500 #

if __name__ == '__main__':
    # Usamos host='0.0.0.0' para permitir conexões da sua rede local (seu celular)
    app.run(host='0.0.0.0', debug=True)