# ============================================================
# SERVICE — Auditoria e Erros
# Projeto Informativos — DOU Auditável
# ============================================================

import json
import datetime
import traceback
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ERROS_DIR = ROOT_DIR / "backend" / "data" / "dou" / "erros"
LOG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "logs_execucao"

ERROS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _erros_path(data: datetime.date) -> Path:
    return ERROS_DIR / f"erros_{data.isoformat()}.json"


def _log_path(data: datetime.date) -> Path:
    return LOG_DIR / f"log_{data.isoformat()}.txt"


def _carregar_erros(data: datetime.date) -> list:
    caminho = _erros_path(data)

    if not caminho.exists():
        return []

    return json.loads(caminho.read_text(encoding="utf-8"))


def _salvar_erros(data: datetime.date, erros: list) -> None:
    caminho = _erros_path(data)
    caminho.write_text(
        json.dumps(erros, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def registrar_evento_auditoria(
    data: datetime.date,
    evento: str,
    detalhes: dict | None = None
) -> None:
    linha = {
        "timestamp": _agora_iso(),
        "tipo": "EVENTO",
        "evento": evento,
        "detalhes": detalhes or {}
    }

    caminho = _log_path(data)

    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")

    print(f"[AUDITORIA] {evento}")


def registrar_erro(
    data: datetime.date,
    etapa: str,
    erro: Exception | str,
    detalhes: dict | None = None,
    incluir_traceback: bool = True
) -> dict:
    erros = _carregar_erros(data)

    if isinstance(erro, Exception):
        erro_msg = str(erro)
        erro_tipo = erro.__class__.__name__
        tb = traceback.format_exc() if incluir_traceback else None
    else:
        erro_msg = str(erro)
        erro_tipo = "ErroManual"
        tb = None

    item = {
        "timestamp": _agora_iso(),
        "etapa": etapa,
        "tipo": erro_tipo,
        "erro": erro_msg,
        "detalhes": detalhes or {},
        "traceback": tb
    }

    erros.append(item)
    _salvar_erros(data, erros)

    registrar_evento_auditoria(
        data=data,
        evento=f"ERRO_REGISTRADO::{etapa}",
        detalhes={
            "tipo": erro_tipo,
            "erro": erro_msg
        }
    )

    print(f"[ERRO] {etapa} | {erro_tipo}: {erro_msg}")

    return item


def obter_erros(data: datetime.date) -> list:
    return _carregar_erros(data)


def gerar_resumo_erros(data: datetime.date) -> dict:
    erros = _carregar_erros(data)

    por_etapa = {}

    for e in erros:
        etapa = e.get("etapa", "DESCONHECIDA")
        por_etapa[etapa] = por_etapa.get(etapa, 0) + 1

    return {
        "data": data.isoformat(),
        "total_erros": len(erros),
        "por_etapa": por_etapa,
        "tem_erros": len(erros) > 0
    }