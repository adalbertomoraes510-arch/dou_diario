from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
DATA_DIR = BACKEND_DIR / "data"
DOU_DATA_DIR = DATA_DIR / "dou"
PAINEL_DATA_DIR = DATA_DIR / "painel_operacional"
PAINEL_LOGS_DIR = PAINEL_DATA_DIR / "logs"
PAINEL_REGISTRY_PATH = PAINEL_DATA_DIR / "execucoes.json"

PROCESSOS_CONTROLE_PATH = (
    DOU_DATA_DIR
    / "pesquisas"
    / "processos_2026"
    / "controle_monitoramento_processos_2026.json"
)

PROCESSOS_SYNC_STATUS_PATH = (
    DOU_DATA_DIR
    / "pesquisas"
    / "processos_2026"
    / "logs"
    / "ultimo_status_sincronizacao_historica_2026.json"
)

PROCESSOS_INCREMENTAL_DIR = (
    DOU_DATA_DIR
    / "pesquisas"
    / "processos_2026"
    / "incremental_dou"
    / "por_data"
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def detectar_ambiente() -> str:
    nome = ROOT_DIR.name.upper()

    if nome == "DOU_DIARIO_DEV":
        return "DEV"

    if nome == "DOU_DIARIO_PROD":
        return "PROD"

    valor = str(os.getenv("DOU_ENV") or "").strip().upper()
    if valor in {"DEV", "PROD"}:
        return valor

    return "DESCONHECIDO"


AMBIENTE = detectar_ambiente()
