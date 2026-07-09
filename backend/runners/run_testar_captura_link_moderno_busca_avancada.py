# ============================================================
# RUNNER — Testar Captura do Link Moderno por Busca Avançada DOU
# Projeto Informativos / DOU
#
# Objetivo:
# - Testar isoladamente se o sistema captura o link moderno correto:
#   https://www.in.gov.br/web/dou/-/...
#
# Importante:
# - NÃO altera base.
# - NÃO altera match.
# - NÃO envia e-mail.
# - NÃO altera orquestrador.
# - Apenas abre a busca avançada por URL direta, captura candidatos
#   e valida se o link encontrado corresponde ao título oficial.
# ============================================================

import asyncio
import datetime
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIGURAÇÃO DO TESTE
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 15)

TITULO_OFICIAL = "DESPACHO DO DIRETOR PRESIDENTE Nº 71-E, DE 14 DE MAIO DE 2026"

LINK_ESPERADO = (
    "https://www.in.gov.br/web/dou/-/"
    "despacho-do-diretor-presidente-n-71-e-de-14-de-maio-de-2026-705714875"
)

# Dados esperados na página moderna.
# Deixe vazio se quiser não validar algum campo.
DATA_PUBLICACAO_ESPERADA = "15/05/2026"
SECAO_ESPERADA = "1"
PAGINA_ESPERADA = "19"

# False abre navegador para visualizar.
# True roda sem abrir janela.
HEADLESS = False

TIMEOUT_NAVEGACAO_MS = 60000
TIMEOUT_VALIDACAO_MS = 30000

ROOT_DIR = Path(__file__).resolve().parents[2]

SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug" / "teste_link_moderno"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)

SAIDA_JSON = SAIDA_DIR / f"teste_captura_link_moderno_{DATA_EXECUCAO.isoformat()}.json"
SAIDA_TXT = SAIDA_DIR / f"teste_captura_link_moderno_{DATA_EXECUCAO.isoformat()}.txt"
SAIDA_SCREENSHOT_BUSCA = SAIDA_DIR / f"teste_captura_link_moderno_busca_{DATA_EXECUCAO.isoformat()}.png"
SAIDA_SCREENSHOT_LINK = SAIDA_DIR / f"teste_captura_link_moderno_link_{DATA_EXECUCAO.isoformat()}.png"


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_texto(valor) -> str:
    texto = str(valor or "")
    texto = html.unescape(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()

    # Normalização de símbolos comuns
    texto = texto.replace("º", "")
    texto = texto.replace("°", "")
    texto = texto.replace("ª", "")
    texto = texto.replace("nº", "n")
    texto = texto.replace("n°", "n")

    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_comparacao(valor) -> str:
    texto = normalizar_texto(valor)
    texto = re.sub(r"[^a-z0-9/.-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def titulo_bate(titulo_esperado: str, texto_candidato: str) -> bool:
    esperado = normalizar_comparacao(titulo_esperado)
    candidato = normalizar_comparacao(texto_candidato)

    if not esperado or not candidato:
        return False

    if esperado == candidato:
        return True

    if esperado in candidato:
        return True

    # tolerância para caixa/pontuação, mas mantendo todos os termos fortes
    termos = [
        t for t in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", esperado)
        if len(t) >= 3
    ]

    if not termos:
        return False

    presentes = sum(1 for termo in termos if termo in candidato)

    return presentes == len(termos)


def montar_url_busca_avancada(titulo: str, data_execucao: datetime.date) -> str:
    data_br_url = data_execucao.strftime("%d-%m-%Y")

    # O mapeamento mostrou que a busca exata gera q entre aspas.
    q = quote_plus(f'"{titulo}"')

    return (
        "https://www.in.gov.br/consulta/-/buscar/dou"
        f"?q={q}"
        "&s=todos"
        "&exactDate=personalizado"
        "&sortType=0"
        f"&publishFrom={data_br_url}"
        f"&publishTo={data_br_url}"
    )


async def coletar_links_modernos(page) -> list[dict]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            texto: (a.innerText || a.textContent || '').trim(),
            href: a.href
        })).filter(x => x.href && x.href.includes('/web/dou/-/'))
        """
    )


async def validar_pagina_moderno(context, url: str, titulo_oficial: str) -> dict:
    page = await context.new_page()

    resultado = {
        "url": url,
        "url_final": "",
        "http_ok": False,
        "titulo_pagina": "",
        "bate_titulo": False,
        "bate_data": False,
        "bate_secao": False,
        "bate_pagina": False,
        "aprovado": False,
        "motivos": [],
        "erro": "",
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_VALIDACAO_MS)
        await page.wait_for_timeout(3000)

        resultado["url_final"] = page.url
        resultado["titulo_pagina"] = await page.title()

        body_text = await page.locator("body").inner_text(timeout=10000)
        body_norm = normalizar_comparacao(body_text)

        titulo_ok = titulo_bate(titulo_oficial, resultado["titulo_pagina"]) or titulo_bate(titulo_oficial, body_text)
        resultado["bate_titulo"] = titulo_ok

        if titulo_ok:
            resultado["motivos"].append("titulo_confirmado_na_pagina")

        if DATA_PUBLICACAO_ESPERADA:
            data_ok = DATA_PUBLICACAO_ESPERADA in body_text
            resultado["bate_data"] = data_ok
            if data_ok:
                resultado["motivos"].append("data_publicacao_confirmada")
        else:
            resultado["bate_data"] = True

        if SECAO_ESPERADA:
            # Aceita "Seção: 1", "Seção 1" ou texto equivalente.
            padroes_secao = [
                f"seção: {SECAO_ESPERADA}",
                f"secao: {SECAO_ESPERADA}",
                f"seção {SECAO_ESPERADA}",
                f"secao {SECAO_ESPERADA}",
            ]
            secao_ok = any(p in body_norm for p in [normalizar_comparacao(x) for x in padroes_secao])
            resultado["bate_secao"] = secao_ok
            if secao_ok:
                resultado["motivos"].append("secao_confirmada")
        else:
            resultado["bate_secao"] = True

        if PAGINA_ESPERADA:
            padroes_pagina = [
                f"página: {PAGINA_ESPERADA}",
                f"pagina: {PAGINA_ESPERADA}",
                f"página {PAGINA_ESPERADA}",
                f"pagina {PAGINA_ESPERADA}",
            ]
            pagina_ok = any(p in body_norm for p in [normalizar_comparacao(x) for x in padroes_pagina])
            resultado["bate_pagina"] = pagina_ok
            if pagina_ok:
                resultado["motivos"].append("pagina_confirmada")
        else:
            resultado["bate_pagina"] = True

        resultado["http_ok"] = True

        resultado["aprovado"] = all([
            resultado["http_ok"],
            resultado["bate_titulo"],
            resultado["bate_data"],
            resultado["bate_secao"],
            resultado["bate_pagina"],
        ])

        if resultado["aprovado"]:
            resultado["motivos"].append("link_moderno_validado")

        try:
            await page.screenshot(path=str(SAIDA_SCREENSHOT_LINK), full_page=True)
        except Exception:
            pass

    except Exception as erro:
        resultado["erro"] = str(erro)

    try:
        await page.close()
    except Exception:
        pass

    return resultado


# ============================================================
# EXECUÇÃO
# ============================================================

async def main():
    url_busca = montar_url_busca_avancada(TITULO_OFICIAL, DATA_EXECUCAO)

    print("=" * 80)
    print("TESTE — CAPTURA DO LINK MODERNO DOU POR BUSCA AVANÇADA")
    print("=" * 80)
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Título oficial: {TITULO_OFICIAL}")
    print(f"URL busca: {url_busca}")
    print(f"Link esperado: {LINK_ESPERADO}")
    print("=" * 80)

    resultado = {
        "data": DATA_EXECUCAO.isoformat(),
        "titulo_oficial": TITULO_OFICIAL,
        "url_busca": url_busca,
        "link_esperado": LINK_ESPERADO,
        "headless": HEADLESS,
        "links_encontrados": [],
        "candidatos_avaliados": [],
        "link_capturado": "",
        "bate_com_esperado": False,
        "status": "",
        "mensagem": "",
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        await page.goto(url_busca, wait_until="domcontentloaded", timeout=TIMEOUT_NAVEGACAO_MS)

        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_timeout(5000)

        print("URL final da busca:", page.url)
        print("Título da página:", await page.title())

        try:
            await page.screenshot(path=str(SAIDA_SCREENSHOT_BUSCA), full_page=True)
        except Exception:
            pass

        links = await coletar_links_modernos(page)
        resultado["links_encontrados"] = links

        print("=" * 80)
        print(f"Links modernos encontrados: {len(links)}")
        print("=" * 80)

        for idx, link in enumerate(links, start=1):
            texto = link.get("texto", "")
            href = link.get("href", "")

            candidato = {
                "ordem": idx,
                "texto": texto,
                "href": href,
                "titulo_bate_no_resultado": titulo_bate(TITULO_OFICIAL, texto),
                "validacao_pagina": {},
                "aprovado": False,
            }

            print(f"Candidato {idx}")
            print("Texto:", texto)
            print("Href:", href)
            print("Título bate no resultado:", candidato["titulo_bate_no_resultado"])

            if candidato["titulo_bate_no_resultado"]:
                validacao = await validar_pagina_moderno(
                    context=context,
                    url=href,
                    titulo_oficial=TITULO_OFICIAL,
                )
                candidato["validacao_pagina"] = validacao
                candidato["aprovado"] = bool(validacao.get("aprovado"))

                print("Validação página:", validacao)

                if candidato["aprovado"] and not resultado["link_capturado"]:
                    resultado["link_capturado"] = href

            resultado["candidatos_avaliados"].append(candidato)
            print("-" * 80)

        await browser.close()

    resultado["bate_com_esperado"] = resultado["link_capturado"] == LINK_ESPERADO

    if resultado["link_capturado"] and resultado["bate_com_esperado"]:
        resultado["status"] = "OK"
        resultado["mensagem"] = "Capturou e validou exatamente o link moderno esperado."
    elif resultado["link_capturado"]:
        resultado["status"] = "PARCIAL"
        resultado["mensagem"] = "Capturou um link moderno validado, mas diferente do esperado."
    else:
        resultado["status"] = "NAO_ENCONTRADO"
        resultado["mensagem"] = "Não capturou link moderno validado."

    SAIDA_JSON.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = []
    linhas.append("=" * 80)
    linhas.append("TESTE — CAPTURA DO LINK MODERNO DOU POR BUSCA AVANÇADA")
    linhas.append("=" * 80)
    linhas.append(f"Data: {resultado['data']}")
    linhas.append(f"Título oficial: {resultado['titulo_oficial']}")
    linhas.append(f"URL busca: {resultado['url_busca']}")
    linhas.append(f"Link esperado: {resultado['link_esperado']}")
    linhas.append(f"Link capturado: {resultado['link_capturado']}")
    linhas.append(f"Bate com esperado: {resultado['bate_com_esperado']}")
    linhas.append(f"Status: {resultado['status']}")
    linhas.append(f"Mensagem: {resultado['mensagem']}")
    linhas.append("")
    linhas.append("CANDIDATOS")
    linhas.append("-" * 80)

    for c in resultado["candidatos_avaliados"]:
        linhas.append(f"{c['ordem']}. {c['texto']}")
        linhas.append(f"href={c['href']}")
        linhas.append(f"titulo_bate_no_resultado={c['titulo_bate_no_resultado']}")
        linhas.append(f"aprovado={c['aprovado']}")
        linhas.append(f"validacao={json.dumps(c.get('validacao_pagina', {}), ensure_ascii=False)}")
        linhas.append("")

    SAIDA_TXT.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 80)
    print("RESULTADO FINAL")
    print("=" * 80)
    print("Link esperado:", LINK_ESPERADO)
    print("Link capturado:", resultado["link_capturado"])
    print("Bate com esperado:", resultado["bate_com_esperado"])
    print("Status:", resultado["status"])
    print("Mensagem:", resultado["mensagem"])
    print("JSON:", SAIDA_JSON)
    print("TXT:", SAIDA_TXT)
    print("Screenshot busca:", SAIDA_SCREENSHOT_BUSCA)
    print("Screenshot link:", SAIDA_SCREENSHOT_LINK)
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
