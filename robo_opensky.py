"""
Robô de busca automática - OpenSky (Smiles/GOL) -> WhatsApp (Z-API)
=====================================================================
Seletores dos campos, botão de busca e o endpoint de rede
("scan-spreadsheet") foram todos conferidos com o site real (via
DevTools). Pronto pra testar de ponta a ponta.

O QUE ESSE ROBÔ FAZ (na ordem):
1. Abre o site do OpenSky
2. Se aparecer a tela "ACESSO RESTRITO", digita a chave e desbloqueia
3. Busca a ida e a volta juntas numa única busca por lote (o próprio
   site já devolve os dois sentidos)
4. Combina as datas de ida e volta mais baratas dentro do teto de milhas
   combinado que você definir (ida + volta somadas) — priorizando os
   itinerários prontos do site, que já vêm com link direto de reserva
5. Monta uma mensagem de WhatsApp
6. Envia pro grupo via Z-API

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
    {"origem": "SAO", "destinos": ["MCZ", "FOR", "SSA", "REC", "BPS"]},
]

# Teto de milhas para o PACOTE COMPLETO (ida + volta somadas).
# Só entra na mensagem se (milhas da ida + milhas da volta) ficar dentro
# desse valor — não existe mais um teto separado por trecho.
TETO_MILHAS_IDA_VOLTA = 35000  # valor definitivo


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
    """Preenche origem/destinos, clica em buscar, e captura o resultado.

    Serve tanto pra busca de ida (origem -> destinos) quanto de volta
    (destino -> [origem]) — é só trocar quem entra em cada parâmetro.
    """
    resultado_capturado = {}

    def capturar_resposta(response):
        if "scan-spreadsheet" in response.url and response.status == 200:
            try:
                resultado_capturado["dados"] = response.json()
            except Exception:
                pass

    page.on("response", capturar_resposta)
    try:
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
    finally:
        # Sem isso, cada busca extra (ida + uma por destino na volta)
        # deixaria mais um listener "response" acumulado na mesma página.
        page.remove_listener("response", capturar_resposta)


def indexar_resultados(dados_json):
    """Indexa os resultados da API por par (origem, destino).

    Cada resultado já traz ida (rankings.outbound), volta (rankings.inbound)
    e itinerários sugeridos (suggestedItineraries) juntos — uma única busca
    origem -> destinos basta pra ter os dois sentidos de cada rota.
    """
    por_rota = {}
    if not dados_json:
        return por_rota

    for rota in dados_json.get("results", []):
        origem = rota["route"]["origin"]
        destino = rota["route"]["destination"]
        por_rota[(origem, destino)] = rota

    return por_rota


def _voos(rota, direcao):
    """Extrai a lista de voos (ida ou volta) de um resultado de rota.

    `direcao` é "outbound" (ida) ou "inbound" (volta) — as duas já vêm
    juntas no mesmo resultado da API.
    """
    voos = [
        {"date": voo["date"], "miles": voo["miles"]}
        for voo in rota.get("rankings", {}).get(direcao, [])
    ]
    voos.sort(key=lambda v: v["date"])  # "AAAA-MM-DD" ordena certo como string
    return voos


def extrair_itinerarios_sugeridos(rota):
    """Achata os itinerários prontos que o próprio site já calcula.

    Cada um já vem com o link direto de reserva (ida + volta preenchidas).
    """
    sugeridos = []
    for mes in rota.get("suggestedItineraries", []):
        for slot in mes.get("departureSlots", []):
            for volta in slot.get("returns", []):
                sugeridos.append({
                    "data_ida": slot["departureDate"],
                    "milhas_ida": slot["outboundMiles"],
                    "data_volta": volta["returnDate"],
                    "milhas_volta": volta["inboundMiles"],
                    "total": volta["totalMiles"],
                    "link": volta.get("bookingLink"),
                })
    return sugeridos


def escolher_melhor_combinacao(voos_ida, voos_volta, teto_total):
    """Acha a combinação ida+volta mais barata dentro do teto total.

    Regra: qualquer volta com data depois da ida é válida (sem exigir
    número mínimo/máximo de noites). Em caso de empate no total, fica
    com a ida mais cedo e depois a volta mais cedo.
    """
    melhor = None
    for ida in voos_ida:
        for volta in voos_volta:
            if volta["date"] <= ida["date"]:
                continue
            total = ida["miles"] + volta["miles"]
            if total > teto_total:
                continue
            candidato = {
                "data_ida": ida["date"],
                "milhas_ida": ida["miles"],
                "data_volta": volta["date"],
                "milhas_volta": volta["miles"],
                "total": total,
            }
            if melhor is None or (
                (candidato["total"], candidato["data_ida"], candidato["data_volta"])
                < (melhor["total"], melhor["data_ida"], melhor["data_volta"])
            ):
                melhor = candidato

    return melhor


def melhor_combinacao(voos_ida, voos_volta, sugeridos, teto_total):
    """Escolhe a melhor combinação pra uma rota, priorizando itinerários
    prontos do site (que já vêm com link direto de reserva).

    Se algum itinerário sugerido já couber no teto, usa ele. Só cai pra
    busca livre (sem limite de noites, sem link) quando nenhum sugerido
    servir — assim continuamos cobrindo "qualquer combinação dentro do
    teto" mesmo fora da janela de noites que o site sugere.
    """
    melhor_sugerido = None
    for s in sugeridos:
        if s["total"] > teto_total:
            continue
        if melhor_sugerido is None or (
            (s["total"], s["data_ida"], s["data_volta"])
            < (melhor_sugerido["total"], melhor_sugerido["data_ida"], melhor_sugerido["data_volta"])
        ):
            melhor_sugerido = s

    if melhor_sugerido:
        return melhor_sugerido

    return escolher_melhor_combinacao(voos_ida, voos_volta, teto_total)


def buscar_oportunidades_ida_volta(pagina, origem, destinos):
    """Busca ida+volta (uma única busca por lote) e monta a lista de
    oportunidades dentro do teto combinado."""
    oportunidades = []

    dados = buscar_precos(pagina, origem, destinos)
    rotas = indexar_resultados(dados)

    for destino in destinos:
        rota = rotas.get((origem, destino))
        if not rota:
            print(f"⚠️  Sem dados para {origem} → {destino}, pulando.")
            continue

        voos_ida = _voos(rota, "outbound")
        voos_volta = _voos(rota, "inbound")
        if not voos_ida or not voos_volta:
            print(f"⚠️  Sem dados de ida ou volta para {origem} → {destino}, pulando.")
            continue

        sugeridos = extrair_itinerarios_sugeridos(rota)
        combo = melhor_combinacao(voos_ida, voos_volta, sugeridos, TETO_MILHAS_IDA_VOLTA)
        if combo:
            oportunidades.append({"origem": origem, "destino": destino, **combo})
        else:
            ida_mais_barata = min(v["miles"] for v in voos_ida)
            volta_mais_barata = min(v["miles"] for v in voos_volta)
            print(
                f"Nenhuma combinação dentro do teto para {origem} ⇄ {destino} "
                f"(ida mais barata encontrada: {_fmt_milhas(ida_mais_barata)}, "
                f"volta mais barata encontrada: {_fmt_milhas(volta_mais_barata)})."
            )

    return oportunidades


def _fmt_milhas(valor):
    return f"{valor:,}".replace(",", ".")


def _fmt_data(valor):
    """Formata uma data pra dd/mm, aceitando tanto "AAAA-MM-DD" (rankings)
    quanto epoch em milissegundos (formato usado nos itinerários sugeridos)."""
    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor / 1000).strftime("%d/%m")
    return datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m")


def formatar_mensagem(oportunidades):
    """Monta o texto pronto pro WhatsApp."""
    if not oportunidades:
        return None

    linhas = ["✈️ *OPORTUNIDADES IDA E VOLTA*", ""]
    for op in oportunidades[:10]:  # limita pra não ficar gigante
        data_ida = _fmt_data(op["data_ida"])
        data_volta = _fmt_data(op["data_volta"])
        linhas.append(
            f"{op['origem']} ⇄ {op['destino']} | "
            f"Ida {data_ida} ({_fmt_milhas(op['milhas_ida'])}) + "
            f"Volta {data_volta} ({_fmt_milhas(op['milhas_volta'])}) = "
            f"{_fmt_milhas(op['total'])} milhas"
        )
        if op.get("link"):
            linhas.append(f"🔗 {op['link']}")
        linhas.append("")

    return "\n".join(linhas).rstrip()


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
            print(f"🔍 Buscando ida e volta: {busca['origem']} ⇄ {busca['destinos']}")
            oportunidades = buscar_oportunidades_ida_volta(
                pagina, busca["origem"], busca["destinos"]
            )
            mensagem = formatar_mensagem(oportunidades)

            if mensagem:
                enviar_whatsapp(mensagem)
            else:
                print("Nada dentro do teto dessa vez.")

        navegador.close()


if __name__ == "__main__":
    rodar()
