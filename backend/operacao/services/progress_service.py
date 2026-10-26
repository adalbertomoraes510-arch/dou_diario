from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

from backend.operacao.config import PAINEL_DATA_DIR


EVENTOS_DIR = PAINEL_DATA_DIR / "eventos"
STATUS_PERMITIDOS = {
    "INICIADA", "CONCLUIDA", "PARCIAL", "ERRO", "IGNORADA",
}


def registrar_evento(
    etapa: str,
    status: str,
    detalhes: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    execucao_id = os.getenv("DOU_EXECUCAO_ID", "").strip()

    if not execucao_id:
        return None

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", execucao_id):
        raise ValueError("Identificador de execucao invalido.")

    status = status.upper().strip()
    if status not in STATUS_PERMITIDOS:
        raise ValueError(f"Status de evento invalido: {status}")

    evento = {
        "execucao_id": execucao_id,
        "data_hora": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "etapa": etapa,
        "status": status,
        "detalhes": detalhes or {},
    }

    EVENTOS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = EVENTOS_DIR / f"{execucao_id}.jsonl"

    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(
            json.dumps(evento, ensure_ascii=False, default=str) + "\n"
        )

    return evento
