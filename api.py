import os
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, JWTManager
from dados import extrair_dados_nota_fiscal, analisar_imagem_comprovante
from datetime import datetime, timedelta, timezone, date
import secrets
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

# --- Configuração Inicial e Extensões ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')

db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

# --- Modelos do Banco de Dados ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiration = db.Column(db.DateTime(timezone=True), nullable=True)
    compras = db.relationship('Compra', backref='user', lazy=True, cascade="all, delete-orphan")
    custos_fixos = db.relationship('CustoFixo', backref='user', lazy=True, cascade="all, delete-orphan")
    categorias = db.relationship('Categoria', backref='user', lazy=True, cascade="all, delete-orphan")
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

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    pictogram = db.Column(db.Integer, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subcategorias = db.relationship('Categoria', backref=db.backref('parent', remote_side=[id]), cascade="all, delete-orphan")
    def to_dict(self):
        return {'id': self.id, 'nome': self.nome, 'pictogram': self.pictogram, 'parentId': self.parent_id}

# --- FUNÇÃO AUXILIAR PARA ENVIAR E-MAIL ---
def send_password_reset_email(user):
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expiration = datetime.now(timezone.utc) + timedelta(hours=1)
    db.session.commit()
    message = Mail(
        from_email=os.getenv('MAIL_FROM', 'seu-email-verificado@exemplo.com'),
        to_emails=user.email,
        subject='Redefinição de Senha - App Gestão Financeira',
        html_content=f'''<p>Olá,</p><p>Você solicitou a redefinição de sua senha. Use o seguinte token para criar uma nova senha no aplicativo:</p><h3>{token}</h3><p>Este token expirará em uma hora.</p><p>Se você não solicitou isso, por favor, ignore este e-mail.</p>'''
    )
    try:
        sendgrid_client = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        response = sendgrid_client.send(message)
        print(f"SendGrid response status: {response.status_code}")
    except Exception as e:
        print(f"Erro ao enviar email pelo SendGrid: {e}")

# --- ROTAS ---
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
    categorias_padrao = [
        {'nome': 'Alimentação', 'pictogram': 0xe25a}, {'nome': 'Assinaturas e serviços', 'pictogram': 0xe638},
        {'nome': 'Bares e restaurantes', 'pictogram': 0xe37a}, {'nome': 'Carro', 'pictogram': 0xe1d7},
        {'nome': 'Casa', 'pictogram': 0xe318}, {'nome': 'Compras', 'pictogram': 0xe59c},
        {'nome': 'Cuidados pessoais', 'pictogram': 0xeaae}, {'nome': 'Dívidas e empréstimos', 'pictogram': 0xe424},
        {'nome': 'Educação', 'pictogram': 0xea3c}, {'nome': 'Família e filhos', 'pictogram': 0xe23a},
        {'nome': 'Impostos e Taxas', 'pictogram': 0xe03f}, {'nome': 'Investimentos', 'pictogram': 0xe67d},
        {'nome': 'Lazer e hobbies', 'pictogram': 0xe13d}, {'nome': 'Mercado', 'pictogram': 0xe59c},
        {'nome': 'Outros', 'pictogram': 0xe148}, {'nome': 'Pets', 'pictogram': 0xe4a1},
        {'nome': 'Presentes e doações', 'pictogram': 0xe503}, {'nome': 'Roupas', 'pictogram': 0xe15f},
        {'nome': 'Saúde', 'pictogram': 0xe38e}, {'nome': 'Trabalho', 'pictogram': 0xe6e9},
        {'nome': 'Transporte', 'pictogram': 0xe1d5}, {'nome': 'Viagem', 'pictogram': 0xe071},
    ]
    for cat_data in categorias_padrao:
        nova_cat = Categoria(nome=cat_data['nome'], pictogram=cat_data['pictogram'], user_id=new_user.id)
        db.session.add(nova_cat)
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

@app.route('/forgot-password', methods=['POST'])
def forgot_password():
    dados = request.get_json()
    email = dados.get('email')
    if not email:
        return jsonify({'erro': 'E-mail é obrigatório'}), 400
    user = User.query.filter_by(email=email).first()
    if user:
        send_password_reset_email(user)
    return jsonify({'mensagem': 'Se um usuário com este e-mail existir, um token de redefinição foi enviado.'}), 200

@app.route('/reset-password', methods=['POST'])
def reset_password():
    dados = request.get_json()
    token = dados.get('token')
    new_password = dados.get('password')
    if not token or not new_password:
        return jsonify({'erro': 'Token e nova senha são obrigatórios'}), 400
    user = User.query.filter_by(reset_token=token).first()
    if not user or user.reset_token_expiration < datetime.now(timezone.utc):
        return jsonify({'erro': 'Token inválido ou expirado'}), 400
    user.set_password(new_password)
    user.reset_token = None
    user.reset_token_expiration = None
    db.session.commit()
    return jsonify({'mensagem': 'Senha redefinida com sucesso!'}), 200

@app.route('/processar_nota', methods=['POST'])
@jwt_required()
def processar_nota_e_salvar():
    current_user_id = int(get_jwt_identity())
    link_nota = request.json.get('url')
    if not link_nota: return jsonify({'erro': 'URL da nota fiscal não fornecida.'}), 400
    dados_extraidos = extrair_dados_nota_fiscal(link_nota)
    if dados_extraidos and dados_extraidos.get('itens_comprados'):
        for item in dados_extraidos['itens_comprados']:
            nova_compra = Compra(nome=item.get('nome', 'Item desconhecido'), quantidade=item.get('quantidade', 1.0), valor_unitario=item.get('valor_unitario', 0.0), data=dados_extraidos.get('data', datetime.now().strftime("%d/%m/%Y")), categoria=item.get('categoria'), user_id=current_user_id)
            db.session.add(nova_compra)
        db.session.commit()
        return jsonify(dados_extraidos)
    else:
        return jsonify({'erro': 'Não foi possível processar a nota fiscal.'}), 500

@app.route('/processar_imagem', methods=['POST'])
@jwt_required()
def processar_imagem_e_salvar():
    current_user_id = int(get_jwt_identity())
    if 'comprovante' not in request.files: return jsonify({'erro': 'Nenhum arquivo de imagem enviado.'}), 400
    arquivo_imagem = request.files['comprovante']
    dados_extraidos = analisar_imagem_comprovante(arquivo_imagem)
    if dados_extraidos and dados_extraidos.get('itens_comprados'):
        for item in dados_extraidos['itens_comprados']:
            nova_compra = Compra(nome=item.get('nome', 'Compra de imagem'), quantidade=item.get('quantidade', 1.0), valor_unitario=item.get('valor_unitario', 0.0), data=dados_extraidos.get('data', datetime.now().strftime("%d/%m/%Y")), categoria=item.get('categoria'), user_id=current_user_id)
            db.session.add(nova_compra)
        db.session.commit()
        return jsonify(dados_extraidos)
    else:
        return jsonify({'erro': 'Não foi possível analisar o comprovante.'}), 500

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

@app.route('/categorias', methods=['GET'])
@jwt_required()
def get_categorias():
    current_user_id = int(get_jwt_identity())
    categorias = Categoria.query.filter_by(user_id=current_user_id).order_by(Categoria.nome).all()
    return jsonify([c.to_dict() for c in categorias]), 200

@app.route('/categorias', methods=['POST'])
@jwt_required()
def add_categoria():
    current_user_id = int(get_jwt_identity())
    dados = request.get_json()
    if not dados or not 'nome' in dados or not 'pictogram' in dados:
        return jsonify({'erro': 'Dados da categoria estão incompletos.'}), 400
    nova_categoria = Categoria(nome=dados['nome'], pictogram=dados['pictogram'], parent_id=dados.get('parentId'), user_id=current_user_id)
    db.session.add(nova_categoria)
    db.session.commit()
    return jsonify(nova_categoria.to_dict()), 201

@app.route('/categorias/<int:categoria_id>', methods=['PUT'])
@jwt_required()
def update_categoria(categoria_id):
    current_user_id = int(get_jwt_identity())
    cat = Categoria.query.get(categoria_id)
    if not cat: return jsonify({'erro': 'Categoria não encontrada'}), 404
    if cat.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    dados = request.get_json()
    if not dados: return jsonify({'erro': 'Nenhum dado fornecido'}), 400
    cat.nome = dados.get('nome', cat.nome)
    cat.pictogram = dados.get('pictogram', cat.pictogram)
    db.session.commit()
    return jsonify(cat.to_dict()), 200

@app.route('/categorias/<int:categoria_id>', methods=['DELETE'])
@jwt_required()
def delete_categoria(categoria_id):
    current_user_id = int(get_jwt_identity())
    cat = Categoria.query.get(categoria_id)
    if not cat: return jsonify({'erro': 'Categoria não encontrada'}), 404
    if cat.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'mensagem': 'Categoria deletada com sucesso'}), 200

@app.route('/relatorios/gastos-por-categoria', methods=['GET'])
@jwt_required()
def get_gastos_por_categoria():
    current_user_id = int(get_jwt_identity())
    mes_query = request.args.get('mes', default=datetime.now().month, type=int)
    ano_query = request.args.get('ano', default=datetime.now().year, type=int)
    mes_ano_str = f"{mes_query:02d}/{ano_query}"
    compras_variaveis = Compra.query.filter(Compra.user_id == current_user_id, Compra.data.like(f"%/{mes_ano_str}")).all()
    custos_fixos_todos = CustoFixo.query.filter_by(user_id=current_user_id).all()
    gastos_totais = {}
    for compra in compras_variaveis:
        categoria = compra.categoria if compra.categoria else 'Não Categorizado'
        valor = compra.quantidade * compra.valor_unitario
        gastos_totais[categoria] = gastos_totais.get(categoria, 0) + valor
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
            categoria = custo.categoria if custo.categoria else 'Não Categorizado'
            gastos_totais[categoria] = gastos_totais.get(categoria, 0) + custo.valor
    return jsonify(gastos_totais), 200

@app.route('/dashboard', methods=['GET'])
@jwt_required()
def get_dashboard_data():
    current_user_id = int(get_jwt_identity())
    hoje = date.today()
    mes_atual = hoje.month
    ano_atual = hoje.year

    # --- 1. Calcular Gastos Totais e por Categoria ---
    gastos_por_categoria = {}
    mes_ano_str = f"{mes_atual:02d}/{ano_atual}"
    compras_variaveis = Compra.query.filter(Compra.user_id == current_user_id, Compra.data.like(f"%/{mes_ano_str}")).all()
    for compra in compras_variaveis:
        categoria = compra.categoria if compra.categoria else 'Não Categorizado'
        valor = compra.quantidade * compra.valor_unitario
        gastos_por_categoria[categoria] = gastos_por_categoria.get(categoria, 0) + valor
    custos_fixos_todos = CustoFixo.query.filter_by(user_id=current_user_id).all()
    for custo in custos_fixos_todos:
        adicionar = False
        mes_base = custo.mes_de_inicio
        if custo.tipo_recorrencia == 'mensal': adicionar = True
        elif custo.tipo_recorrencia == 'bimestral':
            if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 2 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'trimestral':
            if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 3 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'semestral':
            if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 6 == 0: adicionar = True
        elif custo.tipo_recorrencia == 'anual':
            if mes_atual == mes_base: adicionar = True
        if adicionar:
            categoria = custo.categoria if custo.categoria else 'Não Categorizado'
            gastos_por_categoria[categoria] = gastos_por_categoria.get(categoria, 0) + custo.valor
    
    total_gasto_mes = sum(gastos_por_categoria.values())
    maiores_categorias_ordenadas = sorted(gastos_por_categoria.items(), key=lambda item: item[1], reverse=True)
    maiores_categorias = [{'categoria': k, 'valor': v} for k, v in maiores_categorias_ordenadas[:5]]

    # --- 2. Calcular Próximos Custos Fixos (LÓGICA CORRIGIDA) ---
    proximos_custos_fixos = []
    for custo in custos_fixos_todos:
        if custo.dia_do_mes >= hoje.day:
            adicionar = False
            mes_base = custo.mes_de_inicio
            if custo.tipo_recorrencia == 'mensal': adicionar = True
            elif custo.tipo_recorrencia == 'bimestral':
                if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 2 == 0: adicionar = True
            elif custo.tipo_recorrencia == 'trimestral':
                if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 3 == 0: adicionar = True
            elif custo.tipo_recorrencia == 'semestral':
                if (mes_atual - mes_base) >= 0 and (mes_atual - mes_base) % 6 == 0: adicionar = True
            elif custo.tipo_recorrencia == 'anual':
                if mes_atual == mes_base: adicionar = True
            
            if adicionar:
                proximos_custos_fixos.append({
                    'nome': custo.nome,
                    'diaVencimento': custo.dia_do_mes,
                    'valor': custo.valor
                })
    
    proximos_custos_fixos.sort(key=lambda item: item['diaVencimento'])
    
    # --- 3. Montar o JSON Final ---
    dashboard_data = {
        'totalGastoMes': total_gasto_mes,
        'maioresCategorias': maiores_categorias,
        'proximosCustosFixos': proximos_custos_fixos[:3]
    }
    return jsonify(dashboard_data), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))