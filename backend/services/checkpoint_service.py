# ============================================================
# SERVICE — Checkpoint de Execução
# Projeto Informativos — DOU Auditável
# ============================================================

import json
import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
CHECKPOINT_DIR = ROOT_DIR / "backend" / "data" / "dou" / "checkpoint"

CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def _agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _checkpoint_path(data: datetime.date) -> Path:
    return CHECKPOINT_DIR / f"checkpoint_{data.isoformat()}.json"


def carregar_checkpoint(data: datetime.date) -> dict:
    caminho = _checkpoint_path(data)

    if not caminho.exists():
        return {
            "data": data.isoformat(),
            "existe": False,
            "ultima_etapa_concluida": None,
            "etapas_concluidas": [],
            "pendencias": [],
            "atualizado_em": None
        }

    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_checkpoint(
    data: datetime.date,
    etapa: str,
    detalhes: dict | None = None
) -> dict:
    checkpoint = carregar_checkpoint(data)

    etapas = checkpoint.get("etapas_concluidas", [])

    if etapa not in etapas:
        etapas.append(etapa)

    checkpoint.update({
        "data": data.isoformat(),
        "existe": True,
        "ultima_etapa_concluida": etapa,
        "etapas_concluidas": etapas,
        "detalhes_ultima_etapa": detalhes or {},
        "atualizado_em": _agora_iso()
    })

    caminho = _checkpoint_path(data)
    caminho.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"[CHECKPOINT] {etapa} salvo")

    return checkpoint


def etapa_ja_concluida(data: datetime.date, etapa: str) -> bool:
    checkpoint = carregar_checkpoint(data)
    return etapa in checkpoint.get("etapas_concluidas", [])


def definir_pendencias(data: datetime.date, pendencias: list[str]) -> dict:
    checkpoint = carregar_checkpoint(data)

    checkpoint["pendencias"] = pendencias
    checkpoint["atualizado_em"] = _agora_iso()

    caminho = _checkpoint_path(data)
    caminho.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"[CHECKPOINT] pendências atualizadas: {pendencias}")

    return checkpoint


def limpar_checkpoint(data: datetime.date) -> bool:
    caminho = _checkpoint_path(data)

    if caminho.exists():
        caminho.unlink()
        print(f"[CHECKPOINT] removido: {caminho}")
        return True

    print("[CHECKPOINT] nenhum checkpoint para remover")
    return False