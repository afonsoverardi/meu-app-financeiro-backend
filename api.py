import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, JWTManager
from dados import extrair_dados_nota_fiscal, analisar_imagem_comprovante
from datetime import datetime

load_dotenv()

# --- Configuração e Modelos ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    compras = db.relationship('Compra', backref='user', lazy=True, cascade="all, delete-orphan")
    custos_fixos = db.relationship('CustoFixo', backref='user', lazy=True, cascade="all, delete-orphan")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Compra(db.Model):
    __tablename__ = 'compras'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Float, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    data = db.Column(db.String(10), nullable=False)
    categoria = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    def to_dict(self):
        return {'id': self.id, 'nome': self.nome, 'quantidade': self.quantidade, 'valorUnitario': self.valor_unitario, 'data': self.data, 'categoria': self.categoria}

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
    def to_dict(self):
        return {'id': self.id, 'nome': self.nome, 'valor': self.valor, 'categoria': self.categoria, 'tipoRecorrencia': self.tipo_recorrencia, 'diaDoMes': self.dia_do_mes, 'mesDeInicio': self.mes_de_inicio}

# --- Rotas de Autenticação e Processamento ---
@app.route('/')
def health_check(): return jsonify({"status": "healthy"}), 200
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email, password = data.get('email'), data.get('password')
    if not email or not password: return jsonify({"erro": "Email e senha são obrigatórios"}), 400
    if User.query.filter_by(email=email).first(): return jsonify({"erro": "Este email já está em uso"}), 409
    new_user = User(email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"mensagem": "Usuário criado com sucesso!"}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email, password = data.get('email'), data.get('password')
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token)
    return jsonify({"erro": "Credenciais inválidas"}), 401
@app.route('/processar_nota', methods=['POST'])
@jwt_required()
def processar_nota(): return jsonify({"mensagem": "Rota de processar nota funcionando!"})
@app.route('/processar_imagem', methods=['POST'])
@jwt_required()
def processar_imagem(): return jsonify({"mensagem": "Rota de processar imagem funcionando!"})

# --- ROTAS DE DADOS (CRUD Compras) ---
@app.route('/compras', methods=['GET'])
@jwt_required()
def get_compras():
    current_user_id = int(get_jwt_identity())
    mes_query = request.args.get('mes', default=datetime.now().month, type=int)
    ano_query = request.args.get('ano', default=datetime.now().year, type=int)
    mes_ano_str = f"{mes_query:02d}/{ano_query}"
    compras_variaveis = Compra.query.filter(Compra.user_id == current_user_id, Compra.data.like(f"%/{mes_ano_str}")).all()
    custos_fixos_todos = CustoFixo.query.filter_by(user_id=current_user_id).all()
    compras_de_custos_fixos = []
    for custo in custos_fixos_todos:
        adicionar = False
        mes_base = custo.mes_de_inicio
        if custo.tipo_recorrencia == 'mensal': adicionar = True
        elif custo.tipo_recorrencia == 'bimestral':
            if (mes_query - mes_base) >= 0 and (mes_query - mes_base) % 2 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'trimestral':
            if (mes_query - mes_base) >= 0 and (mes_query - mes_base) % 3 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'semestral':
            if (mes_query - mes_base) >= 0 and (mes_query - mes_base) % 6 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'anual':
            if mes_query == mes_base: adicionar = True
        if adicionar:
            compra_projetada = {'id': -custo.id, 'nome': f"{custo.nome} (Fixo)", 'quantidade': 1, 'valorUnitario': custo.valor, 'data': f"{custo.dia_do_mes:02d}/{mes_query:02d}/{ano_query}", 'categoria': custo.categoria}
            compras_de_custos_fixos.append(compra_projetada)
    resultado_variaveis = [compra.to_dict() for compra in compras_variaveis]
    resultado_final = resultado_variaveis + compras_de_custos_fixos
    return jsonify(resultado_final), 200
@app.route('/compras', methods=['POST'])
@jwt_required()
def add_compra():
    current_user_id = int(get_jwt_identity())
    dados = request.get_json()
    if not dados or not all(k in dados for k in ['nome', 'quantidade', 'valor_unitario', 'data']): return jsonify({'erro': 'Dados da compra estão incompletos.'}), 400
    nova_compra = Compra(nome=dados['nome'], quantidade=dados['quantidade'], valor_unitario=dados['valor_unitario'], data=dados['data'], categoria=dados.get('categoria'), user_id=current_user_id)
    db.session.add(nova_compra)
    db.session.commit()
    return jsonify(nova_compra.to_dict()), 201
@app.route('/compras/<int:compra_id>', methods=['PUT'])
@jwt_required()
def update_compra(compra_id):
    current_user_id = int(get_jwt_identity())
    compra_para_atualizar = Compra.query.get(compra_id)
    if not compra_para_atualizar: return jsonify({'erro': 'Compra não encontrada'}), 404
    if compra_para_atualizar.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    dados = request.get_json()
    if not dados: return jsonify({'erro': 'Nenhum dado fornecido'}), 400
    compra_para_atualizar.nome = dados.get('nome', compra_para_atualizar.nome)
    compra_para_atualizar.quantidade = dados.get('quantidade', compra_para_atualizar.quantidade)
    compra_para_atualizar.valor_unitario = dados.get('valor_unitario', compra_para_atualizar.valor_unitario)
    compra_para_atualizar.data = dados.get('data', compra_para_atualizar.data)
    compra_para_atualizar.categoria = dados.get('categoria', compra_para_atualizar.categoria)
    db.session.commit()
    return jsonify(compra_para_atualizar.to_dict()), 200
@app.route('/compras/<int:compra_id>', methods=['DELETE'])
@jwt_required()
def delete_compra(compra_id):
    current_user_id = int(get_jwt_identity())
    compra_para_deletar = Compra.query.get(compra_id)
    if not compra_para_deletar: return jsonify({'erro': 'Compra não encontrada'}), 404
    if compra_para_deletar.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    db.session.delete(compra_para_deletar)
    db.session.commit()
    return jsonify({'mensagem': 'Compra deletada com sucesso'}), 200

# --- ROTAS DE CUSTOS FIXOS (CRUD) ---
@app.route('/custos-fixos', methods=['GET'])
@jwt_required()
def get_custos_fixos():
    current_user_id = int(get_jwt_identity())
    custos = CustoFixo.query.filter_by(user_id=current_user_id).order_by(CustoFixo.nome).all()
    return jsonify([custo.to_dict() for custo in custos]), 200

@app.route('/custos-fixos', methods=['POST'])
@jwt_required()
def add_custo_fixo():
    current_user_id = int(get_jwt_identity())
    dados = request.get_json()
    required_keys = ['nome', 'valor', 'categoria', 'tipoRecorrencia', 'diaDoMes', 'mesDeInicio']
    if not dados or not all(k in dados for k in required_keys): return jsonify({'erro': 'Dados do custo fixo estão incompletos.'}), 400
    novo_custo = CustoFixo(user_id=current_user_id, nome=dados['nome'], valor=dados['valor'], categoria=dados['categoria'], tipo_recorrencia=dados['tipoRecorrencia'], dia_do_mes=dados['diaDoMes'], mes_de_inicio=dados['mesDeInicio'])
    db.session.add(novo_custo)
    db.session.commit()
    return jsonify(novo_custo.to_dict()), 201

# NOVA ROTA PARA ATUALIZAR CUSTOS FIXOS
@app.route('/custos-fixos/<int:custo_id>', methods=['PUT'])
@jwt_required()
def update_custo_fixo(custo_id):
    current_user_id = int(get_jwt_identity())
    custo_para_atualizar = CustoFixo.query.get(custo_id)
    if not custo_para_atualizar: return jsonify({'erro': 'Custo fixo não encontrado'}), 404
    if custo_para_atualizar.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    
    dados = request.get_json()
    if not dados: return jsonify({'erro': 'Nenhum dado fornecido'}), 400

    custo_para_atualizar.nome = dados.get('nome', custo_para_atualizar.nome)
    custo_para_atualizar.valor = dados.get('valor', custo_para_atualizar.valor)
    custo_para_atualizar.categoria = dados.get('categoria', custo_para_atualizar.categoria)
    custo_para_atualizar.tipo_recorrencia = dados.get('tipoRecorrencia', custo_para_atualizar.tipo_recorrencia)
    custo_para_atualizar.dia_do_mes = dados.get('diaDoMes', custo_para_atualizar.dia_do_mes)
    custo_para_atualizar.mes_de_inicio = dados.get('mesDeInicio', custo_para_atualizar.mes_de_inicio)
    
    db.session.commit()
    return jsonify(custo_para_atualizar.to_dict()), 200

# NOVA ROTA PARA DELETAR CUSTOS FIXOS
@app.route('/custos-fixos/<int:custo_id>', methods=['DELETE'])
@jwt_required()
def delete_custo_fixo(custo_id):
    current_user_id = int(get_jwt_identity())
    custo_para_deletar = CustoFixo.query.get(custo_id)
    if not custo_para_deletar: return jsonify({'erro': 'Custo fixo não encontrado'}), 404
    if custo_para_deletar.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    
    db.session.delete(custo_para_deletar)
    db.session.commit()
    return jsonify({'mensagem': 'Custo fixo deletado com sucesso'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))