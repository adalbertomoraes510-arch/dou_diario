# ============================================================
# RUNNER — Extração Real Texto Integral DOU
# Extrai todas as publicações coletadas para uma data
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from backend.drivers.dou.comum.extrator_texto_integral import (
    extrair_multiplas_publicacoes,
)


DATA_TESTE = datetime.date(2026, 5, 8)

# None = extrai todas as publicações disponíveis
LIMITE_PUBLICACOES = None

# Quantidade máxima de publicações extraídas ao mesmo tempo
MAX_CONCORRENCIA_EXTRACAO = 5

ROOT_DIR = Path(__file__).resolve().parents[2]

BRUTO_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"
SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"

ARQUIVO_LINKS = BRUTO_DIR / f"links_dou_{DATA_TESTE.isoformat()}.json"
ARQUIVO_SAIDA = SAIDA_DIR / f"publicacoes_{DATA_TESTE.isoformat()}.json"


async def main():
    print("=" * 80)
    print("EXTRAÇÃO REAL — TEXTO INTEGRAL DOU")
    print(f"Data: {DATA_TESTE.isoformat()}")
    print(f"Limite publicações: {LIMITE_PUBLICACOES}")
    print(f"Concorrência máxima extração: {MAX_CONCORRENCIA_EXTRACAO}")
    print("=" * 80)

    if not ARQUIVO_LINKS.exists():
        raise FileNotFoundError(
            f"Arquivo de links não encontrado: {ARQUIVO_LINKS}"
        )

    dados_links = json.loads(
        ARQUIVO_LINKS.read_text(encoding="utf-8")
    )

    links = dados_links.get("links", [])

    if not links:
        payload = {
            "data": DATA_TESTE.isoformat(),
            "arquivo_origem_links": str(ARQUIVO_LINKS),
            "status": "SEM_LINKS",
            "limite_publicacoes": LIMITE_PUBLICACOES,
            "max_concorrencia_extracao": MAX_CONCORRENCIA_EXTRACAO,
            "total_links_disponiveis": 0,
            "total_extraidas": 0,
            "sucesso": 0,
            "erro": 0,
            "publicacoes": []
        }

        ARQUIVO_SAIDA.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print("Nenhum link disponível para extração.")
        print(f"Arquivo: {ARQUIVO_SAIDA}")
        return

    urls = [
        item["url"]
        for item in links
        if item.get("url")
    ]

    print(f"Total links disponíveis: {len(urls)}")

    publicacoes = await extrair_multiplas_publicacoes(
        urls=urls,
        limite=LIMITE_PUBLICACOES,
        max_concorrencia=MAX_CONCORRENCIA_EXTRACAO,
    )

    sucesso = sum(
        1 for p in publicacoes
        if p.get("status_extracao") == "SUCESSO"
    )

    erro = sum(
        1 for p in publicacoes
        if p.get("status_extracao") == "ERRO"
    )

    payload = {
        "data": DATA_TESTE.isoformat(),
        "arquivo_origem_links": str(ARQUIVO_LINKS),
        "status": "FINALIZADO",
        "limite_publicacoes": LIMITE_PUBLICACOES,
        "max_concorrencia_extracao": MAX_CONCORRENCIA_EXTRACAO,
        "total_links_disponiveis": len(urls),
        "total_extraidas": len(publicacoes),
        "sucesso": sucesso,
        "erro": erro,
        "publicacoes": publicacoes
    }

    ARQUIVO_SAIDA.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("=" * 80)
    print("EXTRAÇÃO REAL FINALIZADA")
    print(f"Total links disponíveis: {payload['total_links_disponiveis']}")
    print(f"Total extraídas: {payload['total_extraidas']}")
    print(f"Sucesso: {payload['sucesso']}")
    print(f"Erro: {payload['erro']}")
    print(f"Concorrência máxima extração: {payload['max_concorrencia_extracao']}")
    print(f"Arquivo: {ARQUIVO_SAIDA}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())