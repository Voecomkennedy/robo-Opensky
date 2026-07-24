# robo-Opensky

Robô de busca automática de passagens (OpenSky / Smiles-GOL) que envia as
oportunidades encontradas para um grupo de WhatsApp via Z-API.

## O que ele faz

1. Abre o site do OpenSky e faz login uma única vez.
2. Fica rodando sozinho em loop, dentro do horário comercial: a cada ciclo, passa por cada região do Brasil (Centro-Oeste, Sudeste, Nordeste, Sul, Norte) e busca todas as rotas configuradas daquela região — ida e volta juntas, numa única busca por lote (o próprio site já devolve os dois sentidos).
3. Combina a ida e a volta mais baratas dentro do teto de milhas combinado (ida + volta somadas), priorizando os itinerários prontos do site — que já vêm com link direto de reserva quando disponíveis.
4. Monta uma mensagem de WhatsApp com as oportunidades da região.
5. Envia pro grupo de WhatsApp daquela região via Z-API.
6. Espera o intervalo configurado e repete o ciclo, até você parar o robô (Ctrl+C) ou o horário comercial acabar.

### Ajustando regiões, rotas e agendamento

No topo de `robo_opensky.py`:

- `REGIOES`: um dicionário por região, cada uma com o `grupo_id` (variável de ambiente do grupo de WhatsApp) e a lista `rotas` de `(origem, [destinos])`. Pode colocar quantos destinos quiser por origem — o robô divide sozinho em lotes de até 5 (limite do site).
- `INTERVALO_MINUTOS`, `HORA_INICIO`, `HORA_FIM`: controlam de quanto em quanto tempo o ciclo se repete e em qual janela do dia o robô roda (fora dela ele só espera).
- Enquanto as variáveis `ZAPI_GRUPO_*` de cada região não forem preenchidas, todas as regiões mandam pro mesmo grupo (`WHATSAPP_GROUP_ID`). Preencha a variável de uma região só quando quiser separar o disparo dela pra outro grupo.

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
4. Ajuste `REGIOES` e o `TETO_MILHAS_IDA_VOLTA` em `robo_opensky.py`
   conforme sua necessidade.
5. Rode:
   ```bash
   python robo_opensky.py
   ```

## Importante

Nunca faça commit da sua chave de acesso do OpenSky nem do token do Z-API.
Use variáveis de ambiente (`.env`, que já está no `.gitignore`) em vez de
colar as credenciais direto no código.
