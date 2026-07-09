# ============================================================
# RUNNER — Gerar Base Auditável Publicações DOU
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from backend.services.base_publicacoes_service import (
    montar_base_publicacoes,
    salvar_base_publicacoes,
)


DATA_TESTE = datetime.date(2026, 5, 8)

ROOT_DIR = Path(__file__).resolve().parents[2]

BRUTO_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"

ARQUIVO_PUBLICACOES = (
    BRUTO_DIR
    / f"publicacoes_{DATA_TESTE.isoformat()}.json"
)


async def main():

    print("=" * 80)
    print("GERAÇÃO BASE AUDITÁVEL DOU")
    print(f"Data: {DATA_TESTE.isoformat()}")
    print("=" * 80)

    if not ARQUIVO_PUBLICACOES.exists():
        raise FileNotFoundError(
            f"Arquivo não encontrado: {ARQUIVO_PUBLICACOES}"
        )

    payload = json.loads(
        ARQUIVO_PUBLICACOES.read_text(
            encoding="utf-8"
        )
    )

    registros = montar_base_publicacoes(payload)

    caminho = salvar_base_publicacoes(
        data_referencia=DATA_TESTE.isoformat(),
        registros=registros
    )

    total = len(registros)

    sucesso = sum(
        1
        for r in registros
        if r.get("status_extracao") == "SUCESSO"
    )

    erro = sum(
        1
        for r in registros
        if r.get("status_extracao") == "ERRO"
    )

    print("=" * 80)
    print("BASE GERADA")
    print(f"Total registros: {total}")
    print(f"Sucesso: {sucesso}")
    print(f"Erro: {erro}")
    print(f"Arquivo: {caminho}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())