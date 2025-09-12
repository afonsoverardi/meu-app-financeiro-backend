import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, JWTManager

# Carrega as variáveis de ambiente do arquivo .env (ótimo para desenvolvimento local)
load_dotenv()

# --- Configuração Inicial ---
app = Flask(__name__)

# Configura a conexão com o banco de dados usando a variável de ambiente
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configura a chave secreta para o JWT (JSON Web Tokens)
# IMPORTANTE: Mude isso para uma string aleatória e segura em produção!
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'super-secret-key-change-me')

# --- Inicialização das Extensões ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

# --- Modelos do Banco de Dados (As "plantas" das nossas tabelas) ---

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    # Relacionamentos (links para outras tabelas)
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
    # Chave estrangeira para ligar a compra a um usuário
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
    # Chave estrangeeira para ligar o custo fixo a um usuário
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


# --- Rotas (Endpoints da API) ---

# Rota de Health Check (para a Render saber que o app está no ar)
@app.route('/')
def health_check():
    return jsonify({"status": "healthy"}), 200

# Rota para Registrar um novo usuário
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

# Rota para Fazer Login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()

    if user and user.check_password(password):
        access_token = create_access_token(identity=user.id)
        return jsonify(access_token=access_token)

    return jsonify({"erro": "Credenciais inválidas"}), 401


# As rotas /processar_nota e /processar_imagem serão protegidas e adaptadas depois
# Por enquanto, vamos nos concentrar em fazer a base de usuários funcionar.


if __name__ == '__main__':
    # O host '0.0.0.0' faz o app ser acessível na rede local
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))