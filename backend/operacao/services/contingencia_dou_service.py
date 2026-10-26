from __future__ import annotations

import json
from pathlib import Path

from backend.operacao.config import PROCESSOS_CONTROLE_PATH


def carregar_processos_ativos() -> list[dict]:
    """Carrega processos ativos do cadastro oficial do DOU Diario."""
    caminho = Path(PROCESSOS_CONTROLE_PATH)

    dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    registros = dados.get("processos")

    if not isinstance(registros, dict):
        raise ValueError("Cadastro de processos com formato inesperado.")

    processos = []
    vistos = set()

    for registro in registros.values():
        if not isinstance(registro, dict):
            continue

        if registro.get("ativo") is not True:
            continue

        numero = str(registro.get("processo") or "").strip()

        if not numero:
            raise ValueError("Processo ativo sem numero cadastrado.")

        if numero in vistos:
            continue

        vistos.add(numero)
        processos.append({
            "processo": numero,
        })

    return processos
