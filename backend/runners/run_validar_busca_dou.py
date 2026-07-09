# ============================================================
# RUNNER — Validar Busca Diária DOU
# Testa data não útil e data útil
# ============================================================

import asyncio
import datetime
import json
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

from backend.drivers.dou.comum.busca_diaria import coletar_links_dou_diario


DATAS_TESTE = [
    datetime.date(2026, 5, 9),  # não útil
    datetime.date(2026, 5, 8),  # útil
]

ROOT_DIR = Path(__file__).resolve().parents[2]

SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"
DEBUG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug"

SAIDA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

MAX_PAGINAS_TESTE = 2


async def executar_data(page, data_teste: datetime.date) -> dict:
    print("=" * 80)
    print(f"VALIDANDO DATA: {data_teste.isoformat()}")
    print("=" * 80)

    resultado = await coletar_links_dou_diario(
        page=page,
        data_alvo=data_teste,
        max_paginas=MAX_PAGINAS_TESTE
    )

    caminho = SAIDA_DIR / f"links_dou_{data_teste.isoformat()}.json"

    caminho.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("-" * 80)
    print(f"Status busca: {resultado.get('status_busca')}")
    print(f"Mensagem: {resultado.get('mensagem')}")
    print(f"Total links: {resultado.get('total_links')}")
    print(f"Arquivo: {caminho}")
    print("-" * 80)

    return resultado


async def executar(headless: bool) -> bool:
    print("=" * 80)
    print(f"EXECUTANDO DOU | HEADLESS={headless}")
    print("=" * 80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768}
        )

        page = await context.new_page()

        resultados = []

        try:
            for data_teste in DATAS_TESTE:
                resultados.append(await executar_data(page, data_teste))

            resumo_path = SAIDA_DIR / "validacao_busca_dou_resumo.json"
            resumo_path.write_text(
                json.dumps(resultados, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            print("=" * 80)
            print("VALIDAÇÃO FINALIZADA")
            print(f"Resumo: {resumo_path}")
            print("=" * 80)

            return True

        finally:
            try:
                await context.close()
            except Exception:
                pass

            try:
                await browser.close()
            except Exception:
                pass


async def main():
    print("=" * 80)
    print("VALIDAÇÃO — BUSCA DIÁRIA DOU")
    print("Datas teste:")
    for data_teste in DATAS_TESTE:
        print(f"- {data_teste.isoformat()}")
    print("=" * 80)

    try:
        ok = await executar(headless=True)

        if ok:
            return

    except Exception as e:
        print("=" * 80)
        print("FALHA EM HEADLESS")
        print(repr(e))
        print("=" * 80)

        erro_headless = DEBUG_DIR / "erro_headless_validacao_busca_dou.txt"
        erro_headless.write_text(
            traceback.format_exc(),
            encoding="utf-8"
        )

    print("=" * 80)
    print("FALLBACK PARA MODO VISUAL")
    print("=" * 80)

    try:
        await executar(headless=False)

    except Exception as e:
        erro_final = DEBUG_DIR / "erro_final_validacao_busca_dou.txt"

        erro_final.write_text(
            traceback.format_exc(),
            encoding="utf-8"
        )

        print("=" * 80)
        print("ERRO FINAL")
        print(repr(e))
        print(f"Detalhes: {erro_final}")
        print("=" * 80)

        raise


if __name__ == "__main__":
    asyncio.run(main())