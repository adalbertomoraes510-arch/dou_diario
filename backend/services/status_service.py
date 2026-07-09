# ============================================================
# SERVICE — Status de Execução
# Projeto Informativos — DOU Auditável
# ============================================================

import json
import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STATUS_DIR = ROOT_DIR / "backend" / "data" / "dou" / "status"
LOG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "logs_execucao"


STATUS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _data_str(data: datetime.date) -> str:
    return data.isoformat()


def _status_path(data: datetime.date) -> Path:
    return STATUS_DIR / f"status_{_data_str(data)}.json"


def _log_path(data: datetime.date) -> Path:
    return LOG_DIR / f"log_{_data_str(data)}.txt"


def _salvar_status(data: datetime.date, payload: dict) -> None:
    caminho = _status_path(data)
    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _carregar_status(data: datetime.date) -> dict:
    caminho = _status_path(data)

    if not caminho.exists():
        return {}

    return json.loads(caminho.read_text(encoding="utf-8"))


def _registrar_log(data: datetime.date, mensagem: str) -> None:
    caminho = _log_path(data)

    linha = f"[{_agora_iso()}] {mensagem}\n"

    with open(caminho, "a", encoding="utf-8") as f:
        f.write(linha)

    print(mensagem)


def iniciar_execucao(data: datetime.date, perfil: str = "dou") -> dict:
    execucao_id = f"{perfil}_{data.isoformat()}"

    payload = {
        "execucao_id": execucao_id,
        "perfil": perfil,
        "data": data.isoformat(),
        "status": "EM_EXECUCAO",
        "etapa_atual": "INICIAR_EXECUCAO",
        "progresso": 0,
        "inicio": _agora_iso(),
        "fim": None,
        "ultima_atualizacao": _agora_iso(),
        "etapas": [],
        "resumo": {
            "publicacoes_coletadas": 0,
            "publicacoes_processadas": 0,
            "falhas": 0,
            "matches_diario": 0,
            "matches_mensal": 0,
            "arquivos_gerados": []
        }
    }

    _salvar_status(data, payload)
    _registrar_log(data, f"[STATUS] INICIAR_EXECUCAO | perfil={perfil}")

    return payload


def atualizar_etapa(
    data: datetime.date,
    etapa: str,
    status_etapa: str = "EM_EXECUCAO",
    progresso: int | None = None,
    detalhes: dict | None = None
) -> dict:
    payload = _carregar_status(data)

    if not payload:
        payload = iniciar_execucao(data)

    evento = {
        "etapa": etapa,
        "status": status_etapa,
        "progresso": progresso,
        "detalhes": detalhes or {},
        "timestamp": _agora_iso()
    }

    payload["etapa_atual"] = etapa
    payload["ultima_atualizacao"] = _agora_iso()

    if progresso is not None:
        payload["progresso"] = max(0, min(100, int(progresso)))

    payload["etapas"].append(evento)

    _salvar_status(data, payload)

    msg = f"[STATUS] {etapa} | {status_etapa}"
    if progresso is not None:
        msg += f" | {payload['progresso']}%"

    _registrar_log(data, msg)

    return payload


def atualizar_resumo(data: datetime.date, **kwargs) -> dict:
    payload = _carregar_status(data)

    if not payload:
        payload = iniciar_execucao(data)

    resumo = payload.setdefault("resumo", {})

    for chave, valor in kwargs.items():
        resumo[chave] = valor

    payload["ultima_atualizacao"] = _agora_iso()

    _salvar_status(data, payload)
    _registrar_log(data, f"[RESUMO] {kwargs}")

    return payload


def finalizar_execucao(
    data: datetime.date,
    sucesso: bool = True,
    com_alertas: bool = False,
    detalhes: dict | None = None
) -> dict:
    payload = _carregar_status(data)

    if not payload:
        payload = iniciar_execucao(data)

    if sucesso and not com_alertas:
        status_final = "CONCLUIDO"
    elif sucesso and com_alertas:
        status_final = "CONCLUIDO_COM_ALERTAS"
    else:
        status_final = "ERRO"

    payload["status"] = status_final
    payload["etapa_atual"] = "FINALIZAR_EXECUCAO"
    payload["progresso"] = 100 if sucesso else payload.get("progresso", 0)
    payload["fim"] = _agora_iso()
    payload["ultima_atualizacao"] = _agora_iso()

    payload["etapas"].append({
        "etapa": "FINALIZAR_EXECUCAO",
        "status": status_final,
        "progresso": payload["progresso"],
        "detalhes": detalhes or {},
        "timestamp": _agora_iso()
    })

    _salvar_status(data, payload)
    _registrar_log(data, f"[STATUS] FINALIZAR_EXECUCAO | {status_final}")

    return payload


def obter_status(data: datetime.date) -> dict:
    return _carregar_status(data)