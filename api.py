import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, JWTManager

# IMPORTANTE: Adicione as funções do seu arquivo de dados
from dados import extrair_dados_nota_fiscal, analisar_imagem_comprovante

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- Configuração Inicial ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-key-change-me')

# --- Inicialização das Extensões ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

# --- Modelos do Banco de Dados ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False) # Já corrigido

    compras = db.relationship('Compra', backref='user', lazy=True, cascade="all, delete-orphan")
    custos_fixos = db.relationship('CustoFixo', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Compra(db.Model):
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    data = db.Column(db.String(10), nullable=False)
    categoria = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

class CustoFixo(db.Model):
    __tablename__ = 'custos_fixos'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    tipo_recorrencia = db.Column(db.String(20), nullable=False)
    dia_do_mes = db.Column(db.Integer, nullable=False)
    mes_de_inicio = db.Column(db.Integer, nullable=False, default=1)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


# --- Rotas de Autenticação ---

@app.route('/')
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"erro": "Email e senha são obrigatórios"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"erro": "Este email já está em uso"}), 409

    new_user = User(email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"mensagem": "Usuário criado com sucesso!"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token)
    return jsonify({"erro": "Credenciais inválidas"}), 401

# --- ROTAS PROTEGIDAS ---

@app.route('/processar_nota', methods=['POST'])
@jwt_required() # <--- AQUI ESTÁ A TRANCA!
def processar_nota():
    # Pega o ID do usuário a partir do token
    current_user_id = get_jwt_identity()
    print(f"Requisição recebida para o usuário ID: {current_user_id}")

    link_nota = request.json.get('url')
    if not link_nota:
        return jsonify({'erro': 'URL da nota fiscal não fornecida.'}), 400

    dados_extraidos = extrair_dados_nota_fiscal(link_nota)

    if dados_extraidos:
        # Futuramente, aqui salvaremos as compras associadas ao current_user_id
        return jsonify(dados_extraidos)
    else:
        return jsonify({'erro': 'Não foi possível processar a nota fiscal.'}), 500


@app.route('/processar_imagem', methods=['POST'])
@jwt_required() # <--- AQUI ESTÁ A TRANCA!
def processar_imagem():
    # Pega o ID do usuário a partir do token
    current_user_id = get_jwt_identity()
    print(f"Requisição de imagem recebida para o usuário ID: {current_user_id}")
    
    if 'comprovante' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo de imagem enviado.'}), 400
    
    arquivo_imagem = request.files['comprovante']
    dados_extraidos = analisar_imagem_comprovante(arquivo_imagem)
    
    if dados_extraidos:
        # Futuramente, aqui salvaremos a compra associada ao current_user_id
        return jsonify(dados_extraidos)
    else:
        return jsonify({'erro': 'Não foi possível analisar o comprovante.'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))