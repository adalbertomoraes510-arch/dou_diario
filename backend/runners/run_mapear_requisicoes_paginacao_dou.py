# ============================================================
# RUNNER — Mapear requisições de paginação do DOU
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from playwright.async_api import async_playwright


ROOT_DIR = Path(__file__).resolve().parents[2]
SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "mapeamentos" / "paginacao"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://www.in.gov.br/inicio"

DATA_ALVO = datetime.date(2026, 4, 1)
DATA_STR = DATA_ALVO.strftime("%d/%m/%Y")

HEADLESS = False
PAGINAS_TESTE = [2, 3, 4, 5]


async def main():
    eventos = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-dev-shm-usage"],
        )

        context = await browser.new_context()
        page = await context.new_page()

        async def registrar_request(request):
            url = request.url

            if "in.gov.br" not in url:
                return

            eventos.append({
                "tipo": "REQUEST",
                "method": request.method,
                "url": url,
                "headers": dict(request.headers),
                "post_data": request.post_data,
            })

        async def registrar_response(response):
            url = response.url

            if "in.gov.br" not in url:
                return

            item = {
                "tipo": "RESPONSE",
                "status": response.status,
                "url": url,
                "headers": dict(response.headers),
            }

            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "html" in ct or "text" in ct:
                    texto = await response.text()
                    item["body_preview"] = texto[:3000]
            except Exception as e:
                item["body_preview_erro"] = str(e)

            eventos.append(item)

        page.on("request", registrar_request)
        page.on("response", registrar_response)

        print("=" * 80)
        print("MAPEAMENTO DE PAGINAÇÃO DOU")
        print(f"Data: {DATA_ALVO}")
        print("=" * 80)

        print("[1] Abrindo página inicial")
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_selector("#search-bar", timeout=60000)

        print("[2] Preenchendo busca")
        await page.fill("#search-bar", "")

        if await page.locator("text=Pesquisa Avançada").count() > 0:
            await page.locator("text=Pesquisa Avançada").first.click()
            await asyncio.sleep(0.5)

        await page.get_by_label("Personalizado").check()
        await page.fill("#data-inicio", DATA_STR)
        await page.fill("#data-fim", DATA_STR)

        if await page.locator("#jornal-todos").count() > 0:
            await page.locator("#jornal-todos").check()

        await page.click("#data-fim")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")

        try:
            await page.locator("button:has-text('PESQUISAR')").click(timeout=2000)
        except Exception:
            pass

        print("[3] Aguardando resultados")
        await page.wait_for_selector("div.resultado", timeout=60000)
        await asyncio.sleep(2)

        total = await page.locator("div.resultado").count()
        print(f"[OK] Resultados página inicial: {total}")
        print(f"[URL] {page.url}")

        for pagina in PAGINAS_TESTE:
            print("=" * 80)
            print(f"[4] Tentando ir para página {pagina}")

            eventos.append({
                "tipo": "MARCADOR",
                "acao": f"ANTES_UPDATE_PAGE_{pagina}",
                "url_atual": page.url,
            })

            try:
                await page.evaluate(
                    """(p) => {
                        if (typeof window.updatePage === 'function') {
                            window.updatePage(p);
                        }
                    }""",
                    pagina,
                )

                await asyncio.sleep(4)

                eventos.append({
                    "tipo": "MARCADOR",
                    "acao": f"DEPOIS_UPDATE_PAGE_{pagina}",
                    "url_atual": page.url,
                })

                qtd = await page.locator("div.resultado").count()
                print(f"[OK] Página {pagina} | resultados visíveis: {qtd}")
                print(f"[URL] {page.url}")

            except Exception as e:
                print(f"[ERRO] Página {pagina}: {e}")
                eventos.append({
                    "tipo": "ERRO",
                    "pagina": pagina,
                    "erro": str(e),
                    "url_atual": page.url,
                })
                break

        saida_json = SAIDA_DIR / f"mapeamento_paginacao_dou_{DATA_ALVO.isoformat()}.json"
        saida_txt = SAIDA_DIR / f"mapeamento_paginacao_dou_{DATA_ALVO.isoformat()}.txt"

        saida_json.write_text(
            json.dumps(eventos, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with saida_txt.open("w", encoding="utf-8") as f:
            for e in eventos:
                f.write("=" * 100 + "\n")
                f.write(f"TIPO: {e.get('tipo')}\n")
                f.write(f"URL: {e.get('url') or e.get('url_atual')}\n")
                f.write(f"METHOD: {e.get('method')}\n")
                f.write(f"STATUS: {e.get('status')}\n")
                if e.get("post_data"):
                    f.write(f"POST_DATA: {e.get('post_data')}\n")
                if e.get("body_preview"):
                    f.write("\nBODY_PREVIEW:\n")
                    f.write(e.get("body_preview") + "\n")

        print("=" * 80)
        print("MAPEAMENTO SALVO")
        print(saida_json)
        print(saida_txt)
        print("=" * 80)

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())