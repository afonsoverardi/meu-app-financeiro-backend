# Usa uma imagem oficial e leve do Python como base
FROM python:3.11-slim

# Define o diretório de trabalho dentro do ambiente
WORKDIR /app

# Executa os comandos de instalação do sistema (incluindo Tesseract) como administrador
RUN apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-por

# Copia o arquivo de dependências do Python
COPY requirements.txt .

# Instala as dependências do Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia o resto do código do seu aplicativo para dentro do ambiente
COPY . .

# Expõe a porta que o servidor usará
EXPOSE 10000

# Define o comando para iniciar o servidor (o mesmo que tínhamos na Render)
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "api:app"]