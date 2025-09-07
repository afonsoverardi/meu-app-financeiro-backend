#!/usr/bin/env bash
# exit on error
set -o errexit

# 1. Instala as dependências do sistema operacional (Tesseract e o pacote de idioma português)
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-por

# 2. Instala as dependências do Python, como antes
pip install -r requirements.txt