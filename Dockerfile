# Usar uma imagem oficial do Python como base
FROM python:3.11-slim

# Definir o diretório de trabalho
WORKDIR /app

# Copiar e instalar as dependências do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código do aplicativo
COPY . .

# Expor a porta
EXPOSE 10000

# Comando para iniciar o servidor
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "api:app"]