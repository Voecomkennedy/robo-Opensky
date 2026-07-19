"""
Robô de busca automática - OpenSky (Smiles/GOL) -> WhatsApp (Z-API)
=====================================================================
Campos de origem/destino e botão de busca já foram conferidos com o HTML
real do site (via DevTools). O ponto que ainda falta confirmar é o nome
exato do endpoint de rede que devolve os resultados da garimpagem
(hoje o script espera algo com "scan-spreadsheet" na URL — ver função
buscar_precos).

O QUE ESSE ROBÔ FAZ (na ordem):
1. Abre o site do OpenSky
2. Se aparecer a tela "ACESSO RESTRITO", digita a chave e desbloqueia
3. Preenche origem e destinos
4. Clica em "INICIAR GARIMPAGEM"
5. Captura os preços que o site encontrou
6. Filtra só o que está abaixo do teto de milhas que você definir
7. Monta uma mensagem de WhatsApp
8. Envia pro grupo via Z-API

COMO USAR (passo a passo pra rodar no seu computador ou no Claude Code):
1. Instalar o Python, se ainda não tiver: https://www.python.org
2. No terminal, instalar as ferramentas:
     pip install playwright requests --break-system-packages
     playwright install chromium
3. Preencher a sua CHAVE DE ACESSO e os dados do Z-API na seção
   "CONFIGURAÇÃO" logo abaixo (ou, melhor ainda, usar variáveis de
   ambiente do sistema, pra não deixar a chave escrita no arquivo).
4. Rodar:  python robo_opensky.py

IMPORTANTE: nunca cole sua chave de acesso nem o token do Z-API em
nenhuma mensagem pra mim (Claude) nem em nenhum lugar público. Esse
arquivo é só seu, roda só no seu computador ou no seu ambiente.
"""

import os
from datetime import datetime
from playwright.sync_api import sync_playwright
import requests

# ============================================================
# CONFIGURAÇÃO — preencha aqui ou use variáveis de ambiente
# ============================================================

OPENSKY_URL = "https://open-sky-pied.vercel.app"
OPENSKY_ACCESS_KEY = os.environ.get("OPENSKY_ACCESS_KEY", "")   # sua chave de acesso do OpenSky

ZAPI_INSTANCE_ID = os.environ.get("ZAPI_INSTANCE_ID", "")       # ID da instância Z-API
ZAPI_TOKEN = os.environ.get("ZAPI_TOKEN", "")                   # Token da instância Z-API
ZAPI_CLIENT_TOKEN = os.environ.get("ZAPI_CLIENT_TOKEN", "")     # Client-Token (segurança da conta)
WHATSAPP_GROUP_ID = os.environ.get("WHATSAPP_GROUP_ID", "")     # ex: "120363xxxxxxxxxx-group"

# Cada busca aceita até 5 destinos de uma vez (igual você faz na tela).
# Adicione quantos "lotes" de busca quiser na lista abaixo.
BUSCAS = [
    {"origem": "GYN", "destinos": ["MCZ", "BPS", "NVT", "REC", "SSA"]},
    # {"origem": "GYN", "destinos": ["FOR", "JPA", "MAO", "BEL", "THE"]},
]

# Só entra na mensagem se a IDA custar até essa quantidade de milhas
TETO_MILHAS_NACIONAL = 20000


# ============================================================
# FUNÇÕES
# ============================================================

def fazer_login_se_precisar(page):
    """Se a tela 'ACESSO RESTRITO' aparecer, digita a chave e desbloqueia."""
    try:
        campo_chave = page.get_by_placeholder("Digite sua chave de acesso...")
        if campo_chave.is_visible(timeout=5000):
            print("🔐 Tela de acesso restrito detectada, desbloqueando...")
            campo_chave.fill(OPENSKY_ACCESS_KEY)
            page.get_by_role("button", name="DESBLOQUEAR SISTEMA").click()
            page.wait_for_timeout(2000)  # espera a tela do sistema carregar
    except Exception:
        # já estava desbloqueado, ou a tela não apareceu dessa vez — segue
        pass


def buscar_precos(page, origem, destinos):
    """Preenche origem/destinos, clica em buscar, e captura o resultado."""
    resultado_capturado = {}

    def capturar_resposta(response):
        if "scan-spreadsheet" in response.url and response.status == 200:
            try:
                resultado_capturado["dados"] = response.json()
            except Exception:
                pass

    page.on("response", capturar_resposta)

    # Seletores confirmados via DevTools (HTML real do formulário #skyForm):
    #   <input type="text" id="origin" ...>
    #   <input type="text" id="destinations" ...>
    #   <button type="submit" ...>⚡ INICIAR GARIMPAGEM</button>
    page.locator("#origin").fill(origem)
    page.locator("#destinations").fill(", ".join(destinos))

    page.locator("#skyForm button[type='submit']").click()

    # espera a resposta chegar (até 30 segundos)
    for _ in range(30):
        if "dados" in resultado_capturado:
            break
        page.wait_for_timeout(1000)

    return resultado_capturado.get("dados")


def filtrar_oportunidades(dados_json):
    """Pega só as datas de ida com preço abaixo do teto definido."""
    oportunidades = []
    if not dados_json:
        return oportunidades

    for rota in dados_json.get("results", []):
        origem = rota["route"]["origin"]
        destino = rota["route"]["destination"]
        for voo in rota.get("rankings", {}).get("outbound", []):
            if voo["miles"] <= TETO_MILHAS_NACIONAL:
                oportunidades.append({
                    "origem": origem,
                    "destino": destino,
                    "data": voo["date"],
                    "milhas": voo["miles"],
                })

    return oportunidades


def formatar_mensagem(oportunidades):
    """Monta o texto pronto pro WhatsApp."""
    if not oportunidades:
        return None

    linhas = ["✈️ *OPORTUNIDADES ENCONTRADAS*", ""]
    for op in oportunidades[:10]:  # limita pra não ficar gigante
        data_formatada = datetime.strptime(op["data"], "%Y-%m-%d").strftime("%d/%m")
        milhas_fmt = f"{op['milhas']:,}".replace(",", ".")
        linhas.append(f"{op['origem']} → {op['destino']} | {data_formatada} | {milhas_fmt} milhas")

    return "\n".join(linhas)


def enviar_whatsapp(mensagem):
    """Envia a mensagem pro grupo via Z-API."""
    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    headers = {"Client-Token": ZAPI_CLIENT_TOKEN}
    payload = {"phone": WHATSAPP_GROUP_ID, "message": mensagem}

    resposta = requests.post(url, json=payload, headers=headers)
    print(f"📤 Envio: {resposta.status_code} - {resposta.text}")


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def rodar():
    with sync_playwright() as p:
        # headless=True roda "invisível" (bom pra rodar sozinho na nuvem)
        # mude pra False se quiser VER a tela do navegador rodando, pra testar
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page()
        pagina.goto(OPENSKY_URL)

        fazer_login_se_precisar(pagina)

        for busca in BUSCAS:
            print(f"🔍 Buscando: {busca['origem']} → {busca['destinos']}")
            dados = buscar_precos(pagina, busca["origem"], busca["destinos"])
            oportunidades = filtrar_oportunidades(dados)
            mensagem = formatar_mensagem(oportunidades)

            if mensagem:
                enviar_whatsapp(mensagem)
            else:
                print("Nada abaixo do teto dessa vez.")

        navegador.close()


if __name__ == "__main__":
    rodar()
