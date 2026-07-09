# ============================================================
# RUNNER — Mapeamento Técnico da Tela do DOU
# Atividade 1 — Diagnóstico de seletores e estrutura da página
# ============================================================

import json
import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://www.in.gov.br/inicio"

DATA_TESTE = datetime.date.today()
DATA_STR = DATA_TESTE.strftime("%d/%m/%Y")

ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT_DIR / "backend" / "data" / "dou" / "mapeamentos" / DATA_TESTE.isoformat()


def salvar_json(nome: str, dados: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    caminho = OUTPUT_DIR / nome
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[JSON] {caminho}")


def salvar_screenshot(page, nome: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    caminho = OUTPUT_DIR / nome
    page.screenshot(path=str(caminho), full_page=True)
    print(f"[SCREENSHOT] {caminho}")


def status_selector(page, seletor: str) -> dict:
    try:
        loc = page.locator(seletor)
        count = loc.count()
        return {
            "seletor": seletor,
            "encontrado": count > 0,
            "quantidade": count,
            "visivel": loc.first.is_visible() if count > 0 else False,
        }
    except Exception as e:
        return {
            "seletor": seletor,
            "encontrado": False,
            "quantidade": 0,
            "visivel": False,
            "erro": str(e),
        }


def mapear_inputs(page) -> list:
    inputs = []
    total = page.locator("input").count()

    for i in range(total):
        el = page.locator("input").nth(i)
        try:
            inputs.append({
                "index": i,
                "type": el.get_attribute("type"),
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "placeholder": el.get_attribute("placeholder"),
                "value": el.get_attribute("value"),
                "checked": el.is_checked() if (el.get_attribute("type") or "").lower() in ["checkbox", "radio"] else None,
                "visivel": el.is_visible(),
            })
        except Exception as e:
            inputs.append({
                "index": i,
                "erro": str(e)
            })

    return inputs


def mapear_botoes(page) -> list:
    botoes = []

    seletores = ["button", "a", "input[type='submit']"]

    for seletor in seletores:
        total = page.locator(seletor).count()

        for i in range(total):
            el = page.locator(seletor).nth(i)
            try:
                texto = ""
                try:
                    texto = el.inner_text(timeout=1000).strip()
                except Exception:
                    texto = el.get_attribute("value") or ""

                botoes.append({
                    "seletor_base": seletor,
                    "index": i,
                    "texto": texto,
                    "id": el.get_attribute("id"),
                    "name": el.get_attribute("name"),
                    "href": el.get_attribute("href"),
                    "type": el.get_attribute("type"),
                    "visivel": el.is_visible(),
                })
            except Exception as e:
                botoes.append({
                    "seletor_base": seletor,
                    "index": i,
                    "erro": str(e)
                })

    return botoes


def mapear_resultados(page) -> dict:
    resultados = page.locator("div.resultado")
    total = resultados.count()

    itens = []

    for i in range(min(total, 10)):
        item = resultados.nth(i)

        try:
            link_el = item.locator("h5.title-marker a")
            link = link_el.get_attribute("href") if link_el.count() else None
            titulo = link_el.inner_text(timeout=2000).strip() if link_el.count() else ""

            resumo = ""
            if item.locator("p").count() > 0:
                resumo = item.locator("p").first.inner_text(timeout=2000).strip()

            itens.append({
                "index": i,
                "titulo": titulo,
                "link": link,
                "resumo": resumo,
            })

        except Exception as e:
            itens.append({
                "index": i,
                "erro": str(e)
            })

    return {
        "total_resultados_na_pagina": total,
        "amostra_primeiros_10": itens,
        "seletores_testados": {
            "container_resultado": status_selector(page, "div.resultado"),
            "link_publicacao": status_selector(page, "div.resultado h5.title-marker a"),
            "paginacao": status_selector(page, "div.paginacao"),
            "botoes_paginacao": status_selector(page, "li.page-item button.page-link"),
        }
    }


def mapear_publicacao(page, url: str) -> dict:
    print(f"[PUBLICACAO] Acessando: {url}")

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)

    salvar_screenshot(page, "screenshot_publicacao.png")

    dados = {
        "url": url,
        "titulo_pagina": page.title(),
        "seletores_testados": {
            "article_materia": status_selector(page, "article#materia"),
            "div_identifica": status_selector(page, "div.identifica"),
            "detalhes_dou": status_selector(page, "div.detalhes-dou"),
            "texto_dou": status_selector(page, "div.texto-dou"),
            "titulo_oficial": status_selector(page, "div.texto-dou p.identifica"),
            "tabelas": status_selector(page, "div.texto-dou table"),
            "paragrafos": status_selector(page, "div.texto-dou p"),
        },
        "amostra_texto": ""
    }

    try:
        texto = page.locator("article#materia").inner_text(timeout=5000)
        dados["amostra_texto"] = texto[:3000]
    except Exception as e:
        dados["erro_amostra_texto"] = str(e)

    salvar_json("tela_publicacao.json", dados)
    return dados


def executar_busca_teste(page) -> dict:
    print("[BUSCA] Executando busca teste no DOU")

    resultado = {
        "data_teste": DATA_TESTE.isoformat(),
        "data_str": DATA_STR,
        "sucesso": False,
        "erro": None,
        "etapas": []
    }

    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#search-bar", timeout=30000)

        resultado["etapas"].append("pagina_inicial_carregada")

        if page.locator("text=Pesquisa Avançada").count() > 0:
            page.locator("text=Pesquisa Avançada").first.click()
            page.wait_for_timeout(500)
            resultado["etapas"].append("pesquisa_avancada_aberta")

        if page.locator("#data-inicio").count() > 0:
            page.fill("#data-inicio", DATA_STR)
            resultado["etapas"].append("data_inicio_preenchida")

        if page.locator("#data-fim").count() > 0:
            page.fill("#data-fim", DATA_STR)
            resultado["etapas"].append("data_fim_preenchida")

        if page.locator("#jornal-todos").count() > 0:
            page.locator("#jornal-todos").check()
            resultado["etapas"].append("jornal_todos_marcado")

        page.click("#data-fim")
        page.wait_for_timeout(500)

        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)

        try:
            page.locator("button:has-text('PESQUISAR')").click(timeout=3000)
            resultado["etapas"].append("botao_pesquisar_clicado")
        except Exception:
            resultado["etapas"].append("botao_pesquisar_nao_clicado_fallback_enter")

        page.wait_for_function(
            """() => {
                const el = document.querySelector('div.resultado');
                return el && el.innerText.length > 20;
            }""",
            timeout=30000
        )

        resultado["sucesso"] = True
        resultado["etapas"].append("resultados_carregados")

    except Exception as e:
        resultado["erro"] = str(e)

    return resultado


def main():
    print("=" * 80)
    print("MAPEAMENTO TÉCNICO — DOU")
    print(f"Data teste: {DATA_STR}")
    print(f"Saída: {OUTPUT_DIR}")
    print("=" * 80)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-dev-shm-usage"]
        )

        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()

        # ====================================================
        # 1. Tela inicial
        # ====================================================
        print("[1/4] Mapeando tela inicial")

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        salvar_screenshot(page, "screenshot_inicial.png")

        tela_inicial = {
            "url": BASE_URL,
            "titulo_pagina": page.title(),
            "data_mapeamento": datetime.datetime.now().isoformat(),
            "seletores_criticos": {
                "search_bar": status_selector(page, "#search-bar"),
                "pesquisa_avancada_texto": status_selector(page, "text=Pesquisa Avançada"),
                "data_inicio": status_selector(page, "#data-inicio"),
                "data_fim": status_selector(page, "#data-fim"),
                "jornal_todos": status_selector(page, "#jornal-todos"),
                "botao_pesquisar": status_selector(page, "button:has-text('PESQUISAR')"),
            },
            "inputs": mapear_inputs(page),
            "botoes_links": mapear_botoes(page),
        }

        salvar_json("tela_inicial.json", tela_inicial)

        # ====================================================
        # 2. Executar busca teste
        # ====================================================
        print("[2/4] Executando busca teste")

        busca = executar_busca_teste(page)
        salvar_json("busca_teste.json", busca)

        salvar_screenshot(page, "screenshot_resultado.png")

        # ====================================================
        # 3. Mapear resultados
        # ====================================================
        print("[3/4] Mapeando tela de resultados")

        tela_resultado = {
            "url_atual": page.url,
            "titulo_pagina": page.title(),
            "data_mapeamento": datetime.datetime.now().isoformat(),
            "busca": busca,
            "resultados": mapear_resultados(page),
            "inputs": mapear_inputs(page),
            "botoes_links": mapear_botoes(page),
        }

        salvar_json("tela_resultado.json", tela_resultado)

        # ====================================================
        # 4. Abrir primeira publicação
        # ====================================================
        print("[4/4] Mapeando primeira publicação")

        primeira_url = None

        try:
            link_el = page.locator("div.resultado h5.title-marker a").first
            if link_el.count() > 0:
                primeira_url = link_el.get_attribute("href")

                if primeira_url and primeira_url.startswith("/"):
                    primeira_url = "https://www.in.gov.br" + primeira_url

        except Exception as e:
            print(f"[AVISO] Não foi possível obter primeira publicação: {e}")

        if primeira_url:
            mapear_publicacao(page, primeira_url)
        else:
            salvar_json("tela_publicacao.json", {
                "status": "nao_mapeada",
                "motivo": "nenhuma_publicacao_encontrada"
            })

        context.close()
        browser.close()

    print("=" * 80)
    print("MAPEAMENTO FINALIZADO")
    print(f"Arquivos gerados em: {OUTPUT_DIR}")
    print("=" * 80)


if __name__ == "__main__":
    main()