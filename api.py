from flask import Flask, request, jsonify
from dotenv import load_dotenv
from dados import extrair_dados_nota_fiscal, analisar_imagem_comprovante

load_dotenv() 

app = Flask(__name__)

@app.route('/processar_nota', methods=['POST'])
def processar_nota():
    try:
        link_nota = request.json.get('url')
        if not link_nota:
            return jsonify({'erro': 'URL da nota fiscal não fornecida.'}), 400

        dados_extraidos = extrair_dados_nota_fiscal(link_nota)

        if dados_extraidos:
            return jsonify(dados_extraidos)
        else:
            return jsonify({'erro': 'Não foi possível processar a nota fiscal.'}), 500

    except Exception as e:
        return jsonify({'erro': str(e)}), 500

@app.route('/processar_imagem', methods=['POST'])
def processar_imagem():
    try:
        if 'comprovante' not in request.files:
            return jsonify({'erro': 'Nenhum arquivo de imagem enviado.'}), 400
        
        arquivo_imagem = request.files['comprovante']
        
        dados_extraidos = analisar_imagem_comprovante(arquivo_imagem)
        
        if dados_extraidos:
            return jsonify(dados_extraidos)
        else:
            return jsonify({'erro': 'Não foi possível analisar o comprovante.'}), 500

    except Exception as e:
        return jsonify({'erro': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)