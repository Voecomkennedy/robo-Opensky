# robo-Opensky

Robô de busca automática de passagens (OpenSky / Smiles-GOL) que envia as
oportunidades encontradas para um grupo de WhatsApp via Z-API.

## O que ele faz

1. Abre o site do OpenSky.
2. Se aparecer a tela "ACESSO RESTRITO", digita a chave e desbloqueia.
3. Busca a ida e a volta juntas numa única busca por lote (o próprio site já devolve os dois sentidos).
4. Combina a ida e a volta mais baratas dentro do teto de milhas combinado (ida + volta somadas), priorizando os itinerários prontos do site — que já vêm com link direto de reserva quando disponíveis.
5. Monta uma mensagem de WhatsApp.
6. Envia pro grupo via Z-API.

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
4. Ajuste a lista `BUSCAS` e o `TETO_MILHAS_IDA_VOLTA` em `robo_opensky.py`
   conforme sua necessidade.
5. Rode:
   ```bash
   python robo_opensky.py
   ```

## Importante

Nunca faça commit da sua chave de acesso do OpenSky nem do token do Z-API.
Use variáveis de ambiente (`.env`, que já está no `.gitignore`) em vez de
colar as credenciais direto no código.
