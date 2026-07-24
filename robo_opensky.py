"""
Robô de busca automática - OpenSky (Smiles/GOL) -> WhatsApp (Z-API)
=====================================================================
Seletores dos campos, botão de busca e o endpoint de rede
("scan-spreadsheet") foram todos conferidos com o site real (via
DevTools). Pronto pra testar de ponta a ponta.

O QUE ESSE ROBÔ FAZ (na ordem):
1. Abre o site do OpenSky e faz login uma única vez
2. Fica rodando sozinho em loop, dentro do horário comercial: a cada
   ciclo, passa por cada REGIÃO do Brasil (Centro-Oeste, Sudeste,
   Nordeste, Sul, Norte) e busca todas as rotas configuradas daquela
   região (ida e volta juntas, numa única busca por lote — o próprio
   site já devolve os dois sentidos)
3. Combina as datas de ida e volta mais baratas dentro do teto de milhas
   combinado que você definir (ida + volta somadas) — priorizando os
   itinerários prontos do site, que já vêm com link direto de reserva
4. Monta uma mensagem de WhatsApp com as oportunidades da região
5. Envia pro grupo de WhatsApp DAQUELA região via Z-API
6. Espera o intervalo configurado e repete o ciclo, até você parar o
   robô (Ctrl+C) ou o horário comercial acabar

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
import time
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

# Grupo padrão: enquanto você não separar os grupos por região, todo
# mundo cai aqui (o mesmo grupo único que você já usa hoje).
WHATSAPP_GRUPO_PADRAO = os.environ.get("WHATSAPP_GROUP_ID", "")

# Cada região manda pro seu próprio grupo de WhatsApp (ID vem de uma
# variável de ambiente própria — preencha no seu .env local). Se a
# variável da região específica estiver vazia, usa o grupo padrão acima.
# Cada origem aceita quantos destinos quiser na lista: o robô divide
# sozinho em lotes de até 5 (limite do formulário do site).
REGIOES = {
    "CENTRO-OESTE": {
        "grupo_id": os.environ.get("ZAPI_GRUPO_CENTRO_OESTE", "") or WHATSAPP_GRUPO_PADRAO,
        "rotas": [
            ("GYN", ["SAO", "RIO", "SSA", "REC", "FOR", "MCZ", "BPS"]),
            ("BSB", ["RIO", "SAO", "SSA", "REC", "FOR", "MAO"]),
            ("CGB", ["SAO"]),
        ],
    },
    "SUDESTE": {
        "grupo_id": os.environ.get("ZAPI_GRUPO_SUDESTE", "") or WHATSAPP_GRUPO_PADRAO,
        "rotas": [
            ("SAO", ["GYN", "BSB", "CNF", "CWB", "FLN", "POA", "SSA", "REC", "FOR", "MCZ", "NAT"]),
            ("RIO", ["BSB", "GYN", "SSA", "REC"]),
        ],
    },
    "NORDESTE": {
        "grupo_id": os.environ.get("ZAPI_GRUPO_NORDESTE", "") or WHATSAPP_GRUPO_PADRAO,
        "rotas": [
            ("REC", ["SAO", "RIO", "BSB"]),
            ("SSA", ["SAO", "RIO", "BSB"]),
            ("FOR", ["SAO", "RIO"]),
            ("MCZ", ["SAO", "RIO"]),
            ("NAT", ["SAO"]),
            ("AJU", ["SSA"]),
        ],
    },
    "SUL": {
        "grupo_id": os.environ.get("ZAPI_GRUPO_SUL", "") or WHATSAPP_GRUPO_PADRAO,
        "rotas": [
            ("CWB", ["SAO", "RIO"]),
            ("FLN", ["SAO", "RIO"]),
            ("POA", ["SAO", "RIO"]),
        ],
    },
    "NORTE": {
        "grupo_id": os.environ.get("ZAPI_GRUPO_NORTE", "") or WHATSAPP_GRUPO_PADRAO,
        "rotas": [
            ("MAO", ["BSB", "SAO", "RIO"]),
            ("BEL", ["SAO", "RIO", "BSB"]),
            ("PVH", ["BSB", "SAO"]),
        ],
    },
}

# Teto de milhas para o PACOTE COMPLETO (ida + volta somadas).
# Só entra na mensagem se (milhas da ida + milhas da volta) ficar dentro
# desse valor — não existe mais um teto separado por trecho.
TETO_MILHAS_IDA_VOLTA = 35000  # valor definitivo

# Agendamento: de quanto em quanto tempo o robô refaz o ciclo completo
# (todas as regiões), e em que horário do dia ele deve rodar. Fora desse
# horário, o robô só fica esperando (não faz buscas nem gasta dados).
INTERVALO_MINUTOS = 60
HORA_INICIO = 8   # começa a rodar às 08h
HORA_FIM = 20     # para de rodar às 20h


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
            # Espera a camada de bloqueio (#authOverlay) sumir de verdade,
            # em vez de uma espera fixa — ela às vezes demora mais que
            # 2 segundos pra sumir e fica bloqueando o clique na busca.
            page.locator("#authOverlay").wait_for(state="hidden", timeout=15000)
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


def enviar_whatsapp(mensagem, grupo_id):
    """Envia a mensagem pro grupo (da região) via Z-API."""
    url = f"https://api.z-api.io/instances/{ZAPI_INSTANCE_ID}/token/{ZAPI_TOKEN}/send-text"
    headers = {"Client-Token": ZAPI_CLIENT_TOKEN}
    payload = {"phone": grupo_id, "message": mensagem}

    resposta = requests.post(url, json=payload, headers=headers)
    print(f"📤 Envio: {resposta.status_code} - {resposta.text}")


def dividir_em_lotes(lista, tamanho=5):
    """Quebra uma lista de destinos em pedaços de até `tamanho` itens
    (limite que o formulário do site aceita por busca)."""
    for i in range(0, len(lista), tamanho):
        yield lista[i:i + tamanho]


def chave_oportunidade(op):
    """Identifica uma oportunidade por rota + datas + total de milhas.

    Mesma rota com as mesmas datas e o mesmo total já foi mandada antes;
    se qualquer um desses mudar (outras datas, ou valor diferente), conta
    como uma oportunidade nova.
    """
    return (op["origem"], op["destino"], op["data_ida"], op["data_volta"], op["total"])


def filtrar_novas(oportunidades, ja_enviadas):
    """Remove oportunidades que já foram mandadas antes (mesma chave) e
    registra as novas em `ja_enviadas`, pra não repetir nos próximos ciclos."""
    novas = []
    for op in oportunidades:
        chave = chave_oportunidade(op)
        if chave in ja_enviadas:
            continue
        ja_enviadas.add(chave)
        novas.append(op)
    return novas


def processar_regiao(pagina, nome_regiao, config_regiao, ja_enviadas):
    """Busca todas as rotas de uma região e manda uma única mensagem,
    só com as oportunidades NOVAS (que ainda não foram enviadas), pro
    grupo daquela região."""
    oportunidades_regiao = []

    for origem, destinos in config_regiao["rotas"]:
        for lote in dividir_em_lotes(destinos):
            print(f"🔍 [{nome_regiao}] {origem} ⇄ {lote}")
            try:
                oportunidades_regiao.extend(
                    buscar_oportunidades_ida_volta(pagina, origem, lote)
                )
            except Exception as erro:
                print(f"⚠️  Erro buscando {origem} ⇄ {lote} ({nome_regiao}): {erro}")

    novas = filtrar_novas(oportunidades_regiao, ja_enviadas)
    mensagem = formatar_mensagem(novas)
    if mensagem:
        enviar_whatsapp(mensagem, config_regiao["grupo_id"])
    else:
        print(f"Nada novo dentro do teto pra {nome_regiao} dessa vez.")


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def dentro_do_horario_comercial():
    return HORA_INICIO <= datetime.now().hour < HORA_FIM


def rodar():
    with sync_playwright() as p:
        # headless=True roda "invisível" (bom pra rodar sozinho na nuvem)
        # mude pra False se quiser VER a tela do navegador rodando, pra testar
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page()
        pagina.goto(OPENSKY_URL)

        fazer_login_se_precisar(pagina)

        # Guarda o que já foi mandado (rota + datas + total) enquanto o
        # robô estiver rodando, pra não repetir a mesma oportunidade a
        # cada ciclo. Reinicia do zero se você parar e rodar de novo.
        ja_enviadas = set()

        try:
            while True:
                if dentro_do_horario_comercial():
                    for nome_regiao, config_regiao in REGIOES.items():
                        processar_regiao(pagina, nome_regiao, config_regiao, ja_enviadas)
                else:
                    print("😴 Fora do horário comercial, aguardando...")

                print(f"⏳ Aguardando {INTERVALO_MINUTOS} minutos até o próximo ciclo...")
                time.sleep(INTERVALO_MINUTOS * 60)
        except KeyboardInterrupt:
            print("\n🛑 Robô parado. Até mais!")
        finally:
            navegador.close()


if __name__ == "__main__":
    rodar()
