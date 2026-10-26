from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.operacao.config import (
    AMBIENTE,
    PAINEL_LOGS_DIR,
    PAINEL_REGISTRY_PATH,
    ROOT_DIR,
)
from backend.operacao.services.status_service import (
    possivel_execucao_hoje,
)


_LOCK = threading.Lock()
_JOB_ATUAL: str | None = None


ACOES = {
    "ORQUESTRADOR_HOJE": {
        "titulo": "Rodar DOU hoje",
        "modulo": "backend.runners.run_orquestrador_dou_periodo",
        "aceita_data": False,
    },
    "SINCRONIZAR_PROCESSOS": {
        "titulo": "Sincronizar processos",
        "modulo": (
            "backend.runners."
            "run_sincronizacao_processos_incremental_2026"
        ),
        "aceita_data": False,
    },
    "INCREMENTAL_DOU": {
        "titulo": "Incremental DOU por data",
        "modulo": (
            "backend.runners."
            "run_pesquisa_processos_incremental_dou_2026"
        ),
        "aceita_data": True,
    },
}


def _ler_registry() -> dict[str, Any]:
    try:
        if not PAINEL_REGISTRY_PATH.exists():
            return {"execucoes": []}
        payload = json.loads(
            PAINEL_REGISTRY_PATH.read_text(encoding="utf-8-sig")
        )
        return payload if isinstance(payload, dict) else {"execucoes": []}
    except Exception:
        return {"execucoes": []}


def _salvar_registry(payload: dict[str, Any]) -> None:
    PAINEL_REGISTRY_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    tmp = PAINEL_REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    tmp.replace(PAINEL_REGISTRY_PATH)


def _atualizar_execucao(
    job_id: str,
    **campos: Any,
) -> None:
    with _LOCK:
        payload = _ler_registry()
        execucoes = payload.get("execucoes", [])
        if not isinstance(execucoes, list):
            execucoes = []

        for item in execucoes:
            if isinstance(item, dict) and item.get("id") == job_id:
                item.update(campos)
                break

        payload["execucoes"] = execucoes[:200]
        _salvar_registry(payload)


def _registrar_nova_execucao(item: dict[str, Any]) -> None:
    with _LOCK:
        payload = _ler_registry()
        execucoes = payload.get("execucoes", [])
        if not isinstance(execucoes, list):
            execucoes = []

        execucoes.insert(0, item)
        payload["execucoes"] = execucoes[:200]
        _salvar_registry(payload)


def _validar_confirmacao(
    confirmacao: str,
) -> None:
    esperado = AMBIENTE
    if esperado == "DESCONHECIDO":
        esperado = "CONFIRMAR"

    if str(confirmacao or "").strip().upper() != esperado:
        raise ValueError(
            f"Confirmação inválida. Digite exatamente: {esperado}"
        )


def _montar_comando(
    acao: str,
    data_referencia: str | None,
) -> list[str]:
    config = ACOES.get(acao)
    if not config:
        raise ValueError("Ação não permitida.")

    comando = [
        sys.executable,
        "-m",
        config["modulo"],
    ]

    if config["aceita_data"]:
        if not data_referencia:
            raise ValueError("Informe a data da execução.")

        try:
            data_obj = dt.date.fromisoformat(data_referencia)
        except ValueError as erro:
            raise ValueError(
                "Data inválida. Use AAAA-MM-DD."
            ) from erro

        comando.extend(["--data", data_obj.isoformat()])

    return comando


def _executar_job(
    job_id: str,
    comando: list[str],
    log_path: Path,
) -> None:
    global _JOB_ATUAL

    inicio = dt.datetime.now().astimezone()

    _atualizar_execucao(
        job_id,
        status="EM_EXECUCAO",
        progresso_percentual=0,
        etapa_atual="Iniciando processamento",
        iniciado_em=inicio.isoformat(timespec="seconds"),
    )

    env = os.environ.copy()
    if AMBIENTE == "DEV":
        from dotenv import dotenv_values
        arquivo_env = ROOT_DIR / ".env"
        if not arquivo_env.is_file():
            raise RuntimeError("Arquivo .env do DEV ausente; execucao bloqueada.")
        env.update({k: v for k, v in dotenv_values(arquivo_env).items() if v is not None})
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["DOU_ENV"] = AMBIENTE
    env["DOU_EXECUCAO_ID"] = job_id
    if comando[2] == "backend.runners.run_orquestrador_dou_periodo":
        env["DOU_FINALIDADE"] = "dou_diario"
        if AMBIENTE == "DEV":
            # Respeitar o .env do DEV; o envio real exige
            # DOU_DEV_EMAIL_AUTORIZADO no email_service.py.
            env.pop("EMAIL_MODO_SIMULACAO", None)

    codigo_saida = None
    erro_texto = None

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with log_path.open(
            "w",
            encoding="utf-8",
            errors="replace",
        ) as log:
            log.write(
                f"PAINEL OPERACIONAL DOU\n"
                f"JOB: {job_id}\n"
                f"AMBIENTE: {AMBIENTE}\n"
                f"COMANDO: {' '.join(comando)}\n"
                f"INICIO: {inicio.isoformat(timespec='seconds')}\n"
                + "=" * 100
                + "\n"
            )
            log.flush()

            processo = subprocess.Popen(
                comando,
                cwd=ROOT_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
            )

            if processo.stdout is not None:
                for linha in processo.stdout:
                    log.write(linha)
                    log.flush()

            codigo_saida = processo.wait()

        fim = dt.datetime.now().astimezone()
        # O codigo de saida nao comprova sucesso de todas as atividades.
        status = "SUCESSO" if codigo_saida == 0 else "ERRO"

        if codigo_saida == 0:
            from backend.operacao.config import PAINEL_DATA_DIR

            caminho_eventos = (
                PAINEL_DATA_DIR / "eventos" / f"{job_id}.jsonl"
            )
            ultimos_eventos = {}

            if caminho_eventos.is_file():
                try:
                    with caminho_eventos.open(
                        "r", encoding="utf-8"
                    ) as arquivo_eventos:
                        for linha_evento in arquivo_eventos:
                            if not linha_evento.strip():
                                continue
                            evento = json.loads(linha_evento)
                            etapa = str(evento.get("etapa") or "")
                            if etapa:
                                ultimos_eventos[etapa] = str(
                                    evento.get("status") or ""
                                ).upper()
                except (OSError, ValueError, TypeError):
                    status = "PARCIAL"

            if status == "SUCESSO":
                if not ultimos_eventos:
                    status = "PARCIAL"
                elif any(
                    valor == "ERRO"
                    for valor in ultimos_eventos.values()
                ):
                    status = "ERRO"
                elif any(
                    valor in {"PARCIAL", "INICIADA"}
                    for valor in ultimos_eventos.values()
                ):
                    status = "PARCIAL"
                elif "INLABS" not in ultimos_eventos:
                    status = "PARCIAL"

        if codigo_saida == 0 and status != "SUCESSO":
            print(
                f"[PAINEL] Execucao {job_id}: status operacional {status}",
                flush=True,
            )

        _atualizar_execucao(
            job_id,
            status=status,
            codigo_saida=codigo_saida,
            finalizado_em=fim.isoformat(timespec="seconds"),
            duracao_segundos=round(
                (fim - inicio).total_seconds(), 2
            ),
        )

    except Exception as erro:
        erro_texto = str(erro)
        fim = dt.datetime.now().astimezone()

        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    "\n"
                    + "=" * 100
                    + f"\nERRO DO PAINEL: {erro}\n"
                )
        except Exception:
            pass

        _atualizar_execucao(
            job_id,
            status="ERRO",
            codigo_saida=codigo_saida,
            erro=erro_texto,
            finalizado_em=fim.isoformat(timespec="seconds"),
            duracao_segundos=round(
                (fim - inicio).total_seconds(), 2
            ),
        )

    finally:
        with _LOCK:
            if _JOB_ATUAL == job_id:
                _JOB_ATUAL = None


def iniciar_execucao(
    *,
    acao: str,
    confirmacao: str,
    data_referencia: str | None = None,
    forcar: bool = False,
) -> dict[str, Any]:
    global _JOB_ATUAL

    _validar_confirmacao(confirmacao)

    if acao not in ACOES:
        raise ValueError("Ação não permitida.")

    if (
        acao == "ORQUESTRADOR_HOJE"
        and AMBIENTE == "PROD"
        and possivel_execucao_hoje()
        and not forcar
    ):
        raise RuntimeError(
            "Há evidência de processamento na data de hoje. "
            "Para evitar e-mail/processamento duplicado, a execução "
            "foi bloqueada. Marque 'forçar reexecução' somente se "
            "você tiver certeza."
        )

    comando = _montar_comando(
        acao=acao,
        data_referencia=data_referencia,
    )

    with _LOCK:
        if _JOB_ATUAL:
            raise RuntimeError(
                f"Já existe uma execução em andamento: {_JOB_ATUAL}"
            )

        job_id = uuid.uuid4().hex[:12]
        _JOB_ATUAL = job_id

    agora = dt.datetime.now().astimezone()
    log_path = (
        PAINEL_LOGS_DIR
        / f"{agora.strftime('%Y%m%d_%H%M%S')}_{acao.lower()}_{job_id}.log"
    )

    item = {
        "id": job_id,
        "acao": acao,
        "titulo": ACOES[acao]["titulo"],
        "ambiente": AMBIENTE,
        "status": "AGENDADO",
        "criado_em": agora.isoformat(timespec="seconds"),
        "data_referencia": (
            data_referencia
            or (
                dt.date.today().isoformat()
                if acao == "ORQUESTRADOR_HOJE"
                else None
            )
        ),
        "forcar": bool(forcar),
        "log_path": str(
            log_path.resolve().relative_to(ROOT_DIR.resolve())
        ).replace("\\", "/"),
        "comando": comando,
    }

    _registrar_nova_execucao(item)

    thread = threading.Thread(
        target=_executar_job,
        args=(job_id, comando, log_path),
        daemon=True,
        name=f"dou-painel-{job_id}",
    )
    thread.start()

    return item


def execucao_atual() -> str | None:
    with _LOCK:
        return _JOB_ATUAL
