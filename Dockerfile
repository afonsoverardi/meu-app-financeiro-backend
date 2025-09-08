# Usar uma imagem oficial e leve do Python como base
FROM python:3.11-slim

# Definir o diretório de trabalho dentro do container
WORKDIR /app

# Copiar o arquivo de dependências do Python
COPY requirements.txt .

# Instalar as dependências do Python (agora muito mais rápido)
RUN pip install --no-cache-dir -r requirements.txt

# Copiar o resto do código do seu aplicativo
COPY . .

# Expor a porta que o Gunicorn usará
EXPOSE 10000

# Comando para iniciar o servidor quando o container rodar
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "api:app"]