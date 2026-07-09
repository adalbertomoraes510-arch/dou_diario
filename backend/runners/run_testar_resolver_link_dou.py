# ============================================================
# RUNNER — Testar Resolvedor de Link Moderno DOU
# Projeto Informativos / DOU
# ============================================================
#
# Este runner NÃO altera base, match, e-mail ou relatório.
# Apenas testa se o service consegue resolver o link moderno
# individual de uma publicação já conhecida.
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from backend.services.dou_link_resolver_service import resolver_link_moderno_dou


ROOT_DIR = Path(__file__).resolve().parents[2]
SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)

DATA_PUBLICACAO = datetime.date(2026, 5, 15)
TITULO = "Edital de Notificação nº 9/2026 - Dipro"
LINK_ESPERADO = "https://www.in.gov.br/web/dou/-/edital-de-notificacao-n-9/2026-dipro-705977328"

# Para ver o navegador trabalhando, deixe False.
# Para rodar em produção depois, usaremos True.
HEADLESS = False


async def main():
    print("=" * 80)
    print("TESTE — RESOLVEDOR DE LINK MODERNO DOU")
    print("=" * 80)
    print(f"Data: {DATA_PUBLICACAO.isoformat()}")
    print(f"Título: {TITULO}")
    print(f"Link esperado: {LINK_ESPERADO}")
    print(f"Headless: {HEADLESS}")
    print("=" * 80)

    resultado = await resolver_link_moderno_dou(
        titulo=TITULO,
        data_publicacao=DATA_PUBLICACAO,
        headless=HEADLESS,
        espera_ms=7000,
    )

    caminho_json = SAIDA_DIR / f"teste_resolvedor_link_dou_{DATA_PUBLICACAO.isoformat()}.json"
    caminho_json.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    encontrado = resultado.get("url_publicacao_web") or ""

    print("=" * 80)
    print("RESULTADO")
    print("=" * 80)
    print("Status:", resultado.get("status_resolucao_link"))
    print("Mensagem:", resultado.get("mensagem"))
    print("Query usada:", resultado.get("query_usada"))
    print("Score:", resultado.get("score"))
    print("Texto link:", resultado.get("texto_link"))
    print("Link encontrado:", encontrado)
    print("Link esperado:", LINK_ESPERADO)
    print("Bate com esperado:", encontrado == LINK_ESPERADO)
    print("Total candidatos:", len(resultado.get("candidatos", []) or []))
    print("JSON:", caminho_json)
    print("=" * 80)

    if encontrado == LINK_ESPERADO:
        print("STATUS FINAL: OK — resolvedor pronto para ser plugado no e-mail.")
    elif encontrado:
        print("STATUS FINAL: PARCIAL — encontrou link, mas diferente do esperado.")
    else:
        print("STATUS FINAL: FALHOU — não encontrou link moderno confiável.")

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
