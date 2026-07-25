#!/bin/bash
# Dê DUPLO CLIQUE neste arquivo pelo Finder pra ligar o robô.
# Ele entra sozinho na pasta certa, atualiza o código e roda — não
# precisa abrir o Terminal manualmente nem digitar nada.

cd "$(dirname "$0")"

if [ ! -f "minhas_chaves.sh" ]; then
  echo "⚠️  Não encontrei o arquivo minhas_chaves.sh nesta pasta."
  echo ""
  echo "Copie 'minhas_chaves.sh.example' para 'minhas_chaves.sh' e"
  echo "preencha com suas chaves reais (só precisa fazer isso uma vez)."
  read -p "Pressione Enter pra fechar..."
  exit 1
fi

source minhas_chaves.sh

echo "🔄 Atualizando o robô..."
git pull

echo ""
echo "🚀 Iniciando o robô..."
echo ""
python3 robo_opensky.py

echo ""
read -p "O robô terminou. Pressione Enter pra fechar esta janela..."
