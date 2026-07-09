# ============================================================
# RUNNER — Aplicar Match DOU
# Aplica palavras-chave/processos sobre a base auditável diária
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from backend.services.match_service import (
    aplicar_match_base,
    salvar_resultado_match,
)


DATA_TESTE = datetime.date(2026, 4, 9)

ROOT_DIR = Path(__file__).resolve().parents[2]

BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "base"

ARQUIVO_BASE = (
    BASE_DIR
    / f"base_publicacoes_{DATA_TESTE.isoformat()}.json"
)


async def main():
    print("=" * 80)
    print("APLICAR MATCH — DOU")
    print(f"Data: {DATA_TESTE.isoformat()}")
    print("=" * 80)

    if not ARQUIVO_BASE.exists():
        raise FileNotFoundError(
            f"Arquivo base não encontrado: {ARQUIVO_BASE}"
        )

    payload_base = json.loads(
        ARQUIVO_BASE.read_text(encoding="utf-8")
    )

    registros = payload_base.get("registros", [])

    if not registros:
        raise RuntimeError(
            f"Base sem registros para match: {ARQUIVO_BASE}"
        )

    print(f"Total registros na base: {len(registros)}")

    registros_com_match = aplicar_match_base(registros)

    caminho_saida = salvar_resultado_match(
        data_referencia=DATA_TESTE.isoformat(),
        registros=registros_com_match
    )

    total_com_match = sum(
        1 for r in registros_com_match
        if r.get("status_match") == "COM_MATCH"
    )

    total_sem_match = sum(
        1 for r in registros_com_match
        if r.get("status_match") == "SEM_MATCH"
    )

    print("=" * 80)
    print("MATCH FINALIZADO")
    print(f"Total registros: {len(registros_com_match)}")
    print(f"Com match: {total_com_match}")
    print(f"Sem match: {total_sem_match}")
    print(f"Arquivo: {caminho_saida}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())