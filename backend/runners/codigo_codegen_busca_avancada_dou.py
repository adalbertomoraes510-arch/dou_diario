import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect


async def run(playwright: Playwright) -> None:
    browser = await playwright.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://www.in.gov.br/inicio")
    await page.get_by_role("button", name="PESQUISA AVANÇADA ").click()
    await page.get_by_role("textbox", name="Busca").click()
    await page.get_by_role("textbox", name="Busca").fill(" DESPACHO DE 15 DE MAIO DE 2026")
    await page.get_by_text("Resultado exato").click()
    await page.get_by_text("Personalizado").click()
    await page.get_by_role("textbox", name="Início").click()
    await page.get_by_role("link", name="15").click()
    await page.get_by_role("textbox", name="Fim").click()
    await page.get_by_role("link", name="15").click()
    await page.get_by_role("button", name="PESQUISAR").click()
    await page.get_by_role("link", name="DESPACHO DE 15 DE MAIO DE").click()
    await page.close()

    # ---------------------
    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
