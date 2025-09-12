import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, JWTManager
from dados import extrair_dados_nota_fiscal, analisar_imagem_comprovante

load_dotenv()

# --- Configuração Inicial ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')

# --- Inicialização das Extensões ---
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

# --- Modelos do Banco de Dados ---

class User(db.Model):
    # ... (nenhuma mudança aqui)
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    compras = db.relationship('Compra', backref='user', lazy=True, cascade="all, delete-orphan")
    custos_fixos = db.relationship('CustoFixo', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Compra(db.Model):
    # ... (nenhuma mudança aqui)
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    data = db.Column(db.String(10), nullable=False)
    categoria = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'nome': self.nome,
            'quantidade': self.quantidade,
            'valorUnitario': self.valor_unitario,
            'data': self.data,
            'categoria': self.categoria
        }

class CustoFixo(db.Model):
    # ... (nenhuma mudança aqui)
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
# ... (nenhuma mudança aqui)
@app.route('/')
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/register', methods=['POST'])
def register():
    # ...
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
    # ...
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
@jwt_required()
def processar_nota():
    # ...
    return jsonify({"mensagem": "Rota de processar nota funcionando!"})

@app.route('/processar_imagem', methods=['POST'])
@jwt_required()
def processar_imagem():
    # ...
    return jsonify({"mensagem": "Rota de processar imagem funcionando!"})


# --- ROTAS DE DADOS (CRUD) ---

@app.route('/compras', methods=['GET'])
@jwt_required()
def get_compras():
    # ... (nenhuma mudança aqui)
    current_user_id = int(get_jwt_identity())
    compras_do_usuario = Compra.query.filter_by(user_id=current_user_id).all()
    resultado = [compra.to_dict() for compra in compras_do_usuario]
    return jsonify(resultado), 200

# NOVA ROTA PARA ADICIONAR COMPRAS
@app.route('/compras', methods=['POST'])
@jwt_required()
def add_compra():
    current_user_id = int(get_jwt_identity())
    dados = request.get_json()

    # Validação simples dos dados recebidos do app
    if not dados or not all(k in dados for k in ['nome', 'quantidade', 'valor_unitario', 'data']):
        return jsonify({'erro': 'Dados da compra estão incompletos.'}), 400

    nova_compra = Compra(
        nome=dados['nome'],
        quantidade=dados['quantidade'],
        valor_unitario=dados['valor_unitario'],
        data=dados['data'],
        categoria=dados.get('categoria'), # .get() para campos opcionais
        user_id=current_user_id # Associando a compra ao usuário logado
    )
    
    db.session.add(nova_compra)
    db.session.commit()
    
    # Retorna os dados da compra recém-criada, incluindo o novo ID
    return jsonify(nova_compra.to_dict()), 201


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))