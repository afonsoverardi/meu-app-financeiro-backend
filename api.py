import os
import requests
import re # Adicionado para expressões regulares
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
    receitas = db.relationship('Receita', backref='user', lazy=True, cascade="all, delete-orphan")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Receita(db.Model):
    __tablename__ = 'receitas'
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(100), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    tipo_recorrencia = db.Column(db.String(20), nullable=False) 
    dia_do_mes = db.Column(db.Integer, nullable=True)
    mes_de_inicio = db.Column(db.Integer, nullable=True)
    ano_de_inicio = db.Column(db.Integer, nullable=True)
    data_unica = db.Column(db.String(10), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'descricao': self.descricao,
            'valor': self.valor,
            'tipoRecorrencia': self.tipo_recorrencia,
            'diaDoMes': self.dia_do_mes,
            'mesDeInicio': self.mes_de_inicio,
            'anoDeInicio': self.ano_de_inicio,
            'dataUnica': self.data_unica
        }

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
    ano_de_inicio = db.Column(db.Integer, nullable=False, server_default='2025')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    def to_dict(self):
        return {
            'id': self.id, 'nome': self.nome, 'valor': self.valor, 'categoria': self.categoria,
            'tipoRecorrencia': self.tipo_recorrencia, 'diaDoMes': self.dia_do_mes,
            'mesDeInicio': self.mes_de_inicio,
            'anoDeInicio': self.ano_de_inicio
        }

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


# --- FUNÇÕES AUXILIARES ---
def deve_incluir_custo_fixo(custo, mes_alvo, ano_alvo):
    data_inicio = date(custo.ano_de_inicio, custo.mes_de_inicio, 1)
    data_alvo = date(ano_alvo, mes_alvo, 1)
    if data_alvo < data_inicio:
        return False
    meses_de_diferenca = (data_alvo.year - data_inicio.year) * 12 + (data_alvo.month - data_inicio.month)
    if custo.tipo_recorrencia == 'mensal':
        return True
    elif custo.tipo_recorrencia == 'bimestral':
        return meses_de_diferenca % 2 == 0
    elif custo.tipo_recorrencia == 'trimestral':
        return meses_de_diferenca % 3 == 0
    elif custo.tipo_recorrencia == 'semestral':
        return meses_de_diferenca % 6 == 0
    elif custo.tipo_recorrencia == 'anual':
        return meses_de_diferenca % 12 == 0
    return False

def deve_incluir_receita(receita, mes_alvo, ano_alvo):
    if receita.tipo_recorrencia == 'unico':
        try:
            _, mes, ano = map(int, receita.data_unica.split('/'))
            return mes == mes_alvo and ano == ano_alvo
        except:
            return False
    data_inicio = date(receita.ano_de_inicio, receita.mes_de_inicio, 1)
    data_alvo = date(ano_alvo, mes_alvo, 1)
    if data_alvo < data_inicio:
        return False
    meses_de_diferenca = (data_alvo.year - data_inicio.year) * 12 + (data_alvo.month - data_inicio.month)
    if receita.tipo_recorrencia == 'mensal':
        return True
    elif receita.tipo_recorrencia == 'anual':
        return meses_de_diferenca % 12 == 0
    return False

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
    except Exception as e:
        print(f"Erro ao enviar email pelo SendGrid: {e}")

def calcular_gastos_do_mes(user_id, mes, ano):
    total_variavel = 0
    total_fixo = 0
    mes_ano_str = f"{mes:02d}/{ano}"
    compras_variaveis = Compra.query.filter(
        Compra.user_id == user_id,
        Compra.data.like(f"%/{mes_ano_str}")
    ).all()
    for compra in compras_variaveis:
        total_variavel += compra.quantidade * compra.valor_unitario
    custos_fixos_todos = CustoFixo.query.filter_by(user_id=user_id).all()
    for custo in custos_fixos_todos:
        if deve_incluir_custo_fixo(custo, mes, ano):
            total_fixo += custo.valor
    return total_variavel, total_fixo

# --- ROTAS ---
@app.route('/')
def health_check(): return jsonify({"status": "healthy"}), 200

# ROTAS DE AUTENTICAÇÃO E USUÁRIO
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

# ROTAS DE PROCESSAMENTO (QR CODE, IMAGEM, DANFE)
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

# --- ESTA É A ROTA ATUALIZADA ---
@app.route('/processar_imagem', methods=['POST'])
@jwt_required()
def processar_imagem_e_salvar():
    current_user_id = int(get_jwt_identity())
    if 'comprovante' not in request.files:
        return jsonify({'erro': 'Nenhum arquivo de imagem enviado.'}), 400
    
    arquivo_imagem = request.files['comprovante'].read()
    
    # A função em dados.py agora pode retornar dois formatos de dicionário
    dados_extraidos = analisar_imagem_comprovante(arquivo_imagem)

    if not dados_extraidos:
        return jsonify({'erro': 'Não foi possível extrair dados da imagem.'}), 500

    # Verifica se a função encontrou uma chave de acesso DANFE
    if dados_extraidos.get('tipo') == 'danfe_chave':
        chave_acesso = dados_extraidos.get('chave')
        print(f"Chave de acesso encontrada via Google Vision: {chave_acesso}")
        
        # Gera a URL da Sefaz e retorna para o app
        url_consulta = f"https://www.sefaz.rs.gov.br/NFCON/consultanfce.aspx?chNFe={chave_acesso}"
        return jsonify({'url_danfe': url_consulta}), 200
    
    # Se não era uma chave, então deve ser uma lista de itens de compra
    elif dados_extraidos.get('itens_comprados'):
        print("Analisando como comprovante de compras comum...")
        for item in dados_extraidos['itens_comprados']:
            nova_compra = Compra(
                nome=item.get('nome', 'Item desconhecido'),
                quantidade=item.get('quantidade', 1.0),
                valor_unitario=item.get('valor_unitario', 0.0),
                data=dados_extraidos.get('data', datetime.now().strftime("%d/%m/%Y")),
                categoria=item.get('categoria'),
                user_id=current_user_id
            )
            db.session.add(nova_compra)
        db.session.commit()
        return jsonify(dados_extraidos)

    # Se chegou até aqui, a imagem não continha nem uma chave nem itens válidos
    return jsonify({'erro': 'Não foi possível identificar uma chave DANFE ou itens de compra na imagem.'}), 422

# ROTA FINAL E DEFINITIVA PARA A FUNCIONALIDADE DANFE (ESTRATÉGIA WEBVIEW)
@app.route('/gerar-link-danfe', methods=['POST'])
@jwt_required()
def gerar_link_danfe():
    dados_req = request.get_json()
    chave_acesso = dados_req.get('chave')
    if not chave_acesso or len(chave_acesso) != 44 or not chave_acesso.isdigit():
        return jsonify({'erro': 'Chave de acesso inválida.'}), 400
    # O app irá abrir este link em uma WebView.
    url_consulta = f"https://www.sefaz.rs.gov.br/NFCON/consultanfce.aspx?chNFe={chave_acesso}"
    return jsonify({'url': url_consulta}), 200

# CRUD DE COMPRAS
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
        if deve_incluir_custo_fixo(custo, mes_query, ano_query):
            compra_projetada = {
                'id': -custo.id, 'nome': f"{custo.nome} (Fixo)", 'quantidade': 1,
                'valorUnitario': custo.valor, 'data': f"{custo.dia_do_mes:02d}/{mes_query:02d}/{ano_query}",
                'categoria': custo.categoria
            }
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

# CRUD DE CUSTOS FIXOS
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
    required_keys = ['nome', 'valor', 'categoria', 'tipoRecorrencia', 'diaDoMes', 'mesDeInicio', 'anoDeInicio']
    if not dados or not all(k in dados for k in required_keys): 
        return jsonify({'erro': 'Dados do custo fixo estão incompletos.'}), 400
        
    novo_custo = CustoFixo(
        user_id=current_user_id,
        nome=dados['nome'],
        valor=dados['valor'],
        categoria=dados['categoria'],
        tipo_recorrencia=dados['tipoRecorrencia'],
        dia_do_mes=dados['diaDoMes'],
        mes_de_inicio=dados['mesDeInicio'],
        ano_de_inicio=dados['anoDeInicio']
    )
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
    custo_para_atualizar.ano_de_inicio = dados.get('anoDeInicio', custo_para_atualizar.ano_de_inicio)
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

# CRUD DE CATEGORIAS
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

# CRUD DE RECEITAS
@app.route('/receitas', methods=['GET'])
@jwt_required()
def get_receitas():
    current_user_id = int(get_jwt_identity())
    templates_de_receita = Receita.query.filter_by(user_id=current_user_id).order_by(Receita.descricao).all()
    return jsonify([r.to_dict() for r in templates_de_receita]), 200

@app.route('/receitas', methods=['POST'])
@jwt_required()
def add_receita():
    current_user_id = int(get_jwt_identity())
    dados = request.get_json()
    if not dados or not all(k in dados for k in ['descricao', 'valor', 'tipoRecorrencia']):
        return jsonify({'erro': 'Dados essenciais da receita estão incompletos.'}), 400
    tipo_recorrencia = dados.get('tipoRecorrencia')
    if tipo_recorrencia == 'unico':
        if not dados.get('dataUnica'):
            return jsonify({'erro': 'Para receita de ocorrência única, a data é obrigatória.'}), 400
    elif tipo_recorrencia in ['mensal', 'anual']:
        if not all(k in dados and dados[k] is not None for k in ['diaDoMes', 'mesDeInicio', 'anoDeInicio']):
            return jsonify({'erro': 'Para receitas recorrentes, o dia, mês e ano de início são obrigatórios.'}), 400
    else:
        return jsonify({'erro': f'Tipo de recorrência inválido: {tipo_recorrencia}'}), 400
    nova_receita = Receita(
        user_id=current_user_id,
        descricao=dados['descricao'],
        valor=dados['valor'],
        tipo_recorrencia=dados['tipoRecorrencia'],
        dia_do_mes=dados.get('diaDoMes'),
        mes_de_inicio=dados.get('mesDeInicio'),
        ano_de_inicio=dados.get('anoDeInicio'),
        data_unica=dados.get('dataUnica')
    )
    db.session.add(nova_receita)
    db.session.commit()
    return jsonify(nova_receita.to_dict()), 201

@app.route('/receitas/<int:receita_id>', methods=['PUT'])
@jwt_required()
def update_receita(receita_id):
    current_user_id = int(get_jwt_identity())
    receita = Receita.query.get(receita_id)
    if not receita: return jsonify({'erro': 'Receita não encontrada'}), 404
    if receita.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    dados = request.get_json()
    if not dados: return jsonify({'erro': 'Nenhum dado para atualizar'}), 400
    tipo_recorrencia = dados.get('tipoRecorrencia', receita.tipo_recorrencia)
    if tipo_recorrencia == 'unico':
        if 'dataUnica' in dados and not dados.get('dataUnica'):
            return jsonify({'erro': 'Para receita de ocorrência única, a data é obrigatória.'}), 400
    elif tipo_recorrencia in ['mensal', 'anual']:
        required_keys = ['diaDoMes', 'mesDeInicio', 'anoDeInicio']
        if any(k in dados and dados[k] is None for k in required_keys):
             return jsonify({'erro': 'Para receitas recorrentes, o dia, mês e ano de início são obrigatórios.'}), 400
    receita.descricao = dados.get('descricao', receita.descricao)
    receita.valor = dados.get('valor', receita.valor)
    receita.tipo_recorrencia = dados.get('tipoRecorrencia', receita.tipo_recorrencia)
    if receita.tipo_recorrencia == 'unico':
        receita.data_unica = dados.get('dataUnica', receita.data_unica)
        receita.dia_do_mes = None
        receita.mes_de_inicio = None
        receita.ano_de_inicio = None
    else:
        receita.data_unica = None
        receita.dia_do_mes = dados.get('diaDoMes', receita.dia_do_mes)
        receita.mes_de_inicio = dados.get('mesDeInicio', receita.mes_de_inicio)
        receita.ano_de_inicio = dados.get('anoDeInicio', receita.ano_de_inicio)
    db.session.commit()
    return jsonify(receita.to_dict()), 200

@app.route('/receitas/<int:receita_id>', methods=['DELETE'])
@jwt_required()
def delete_receita(receita_id):
    current_user_id = int(get_jwt_identity())
    receita = Receita.query.get(receita_id)
    if not receita: return jsonify({'erro': 'Receita não encontrada'}), 404
    if receita.user_id != current_user_id: return jsonify({'erro': 'Acesso não autorizado'}), 403
    db.session.delete(receita)
    db.session.commit()
    return jsonify({'mensagem': 'Receita deletada com sucesso'}), 200

# ROTAS DE RELATÓRIOS E DASHBOARD
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
        if deve_incluir_custo_fixo(custo, mes_query, ano_query):
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
    total_variavel_atual, total_fixo_atual = calcular_gastos_do_mes(current_user_id, mes_atual, ano_atual)
    total_gasto_mes_atual = total_variavel_atual + total_fixo_atual
    templates_de_receita = Receita.query.filter_by(user_id=current_user_id).all()
    total_receita_mes_atual = 0
    for receita in templates_de_receita:
        if deve_incluir_receita(receita, mes_atual, ano_atual):
            total_receita_mes_atual += receita.valor
    mes_anterior = mes_atual - 1
    ano_anterior = ano_atual
    if mes_anterior == 0:
        mes_anterior = 12
        ano_anterior -= 1
    total_variavel_anterior, total_fixo_anterior = calcular_gastos_do_mes(current_user_id, mes_anterior, ano_anterior)
    total_gasto_mes_anterior = total_variavel_anterior + total_fixo_anterior
    proximos_custos_fixos = []
    custos_fixos_todos = CustoFixo.query.filter_by(user_id=current_user_id).all()
    for custo in custos_fixos_todos:
        if custo.dia_do_mes >= hoje.day and deve_incluir_custo_fixo(custo, mes_atual, ano_atual):
            proximos_custos_fixos.append({'nome': custo.nome, 'diaVencimento': custo.dia_do_mes, 'valor': custo.valor})
    proximos_custos_fixos.sort(key=lambda item: item['diaVencimento'])
    dashboard_data = {
        'totalGastoMes': total_gasto_mes_atual,
        'totalReceitaMes': total_receita_mes_atual,
        'saldoMes': total_receita_mes_atual - total_gasto_mes_atual,
        'totalVariavel': total_variavel_atual,
        'totalFixo': total_fixo_atual,
        'proximosCustosFixos': proximos_custos_fixos[:3],
        'comparativoMesAnterior': total_gasto_mes_atual - total_gasto_mes_anterior
    }
    return jsonify(dashboard_data), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))