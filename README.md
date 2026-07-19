# robo-Opensky

Robô de busca automática de passagens (OpenSky / Smiles-GOL) que envia as
oportunidades encontradas para um grupo de WhatsApp via Z-API.

## O que ele faz

1. Abre o site do OpenSky.
2. Se aparecer a tela "ACESSO RESTRITO", digita a chave e desbloqueia.
3. Preenche origem e destinos.
4. Clica em "INICIAR GARIMPAGEM".
5. Captura os preços encontrados.
6. Filtra só o que está abaixo do teto de milhas definido.
7. Monta uma mensagem de WhatsApp.
8. Envia pro grupo via Z-API.

## Como usar

1. Instale o Python: https://www.python.org
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt --break-system-packages
   playwright install chromium
   ```
3. Copie `.env.example` para `.env` e preencha com a sua chave de acesso do
   OpenSky e os dados da sua instância Z-API. Depois exporte essas variáveis
   no ambiente (ou use um pacote como `python-dotenv` para carregá-las
   automaticamente) — nunca deixe a chave escrita direto no arquivo.
4. Ajuste a lista `BUSCAS` e o `TETO_MILHAS_NACIONAL` em `robo_opensky.py`
   conforme sua necessidade.
5. Rode:
   ```bash
   python robo_opensky.py
   ```

## Importante

Nunca faça commit da sua chave de acesso do OpenSky nem do token do Z-API.
Use variáveis de ambiente (`.env`, que já está no `.gitignore`) em vez de
colar as credenciais direto no código.
