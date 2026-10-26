from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from backend.operacao.config import (
    AMBIENTE,
    DOU_DATA_DIR,
    PAINEL_DATA_DIR,
    PAINEL_REGISTRY_PATH,
    PROCESSOS_CONTROLE_PATH,
    PROCESSOS_INCREMENTAL_DIR,
    PROCESSOS_SYNC_STATUS_PATH,
    ROOT_DIR,
)


def _ler_json(caminho: Path) -> dict[str, Any]:
    try:
        if not caminho.exists():
            return {}
        payload = json.loads(caminho.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else {}
    except Exception as erro:
        return {"status": "ERRO_LEITURA", "erro": str(erro)}


def _iso_mtime(caminho: Path) -> str | None:
    try:
        return dt.datetime.fromtimestamp(
            caminho.stat().st_mtime
        ).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def _status_payload(payload: dict[str, Any]) -> str | None:
    for chave in ("status", "situacao", "resultado"):
        valor = payload.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()

    resumo = payload.get("resumo")
    if isinstance(resumo, dict):
        for chave in ("status", "situacao", "resultado"):
            valor = resumo.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()

    return None


def git_info() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *args],
                cwd=ROOT_DIR,
                text=True,
                encoding="utf-8",
                errors="replace",
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return ""

    status = run("status", "--short")
    branch = run("branch", "--show-current")
    commit = run("rev-parse", "--short", "HEAD")
    origin = run("rev-parse", "--short", "origin/main")

    return {
        "branch": branch or None,
        "commit": commit or None,
        "origin_main": origin or None,
        "limpo": not bool(status),
        "alteracoes": status.splitlines() if status else [],
    }


def resumo_processos() -> dict[str, Any]:
    estado = _ler_json(PROCESSOS_CONTROLE_PATH)
    processos = estado.get("processos", {})
    if not isinstance(processos, dict):
        processos = {}

    contagem_status: dict[str, int] = {}
    linhas = []
    datas = []

    for processo, registro in processos.items():
        if not isinstance(registro, dict):
            continue

        status = str(registro.get("status") or "SEM_STATUS")
        contagem_status[status] = contagem_status.get(status, 0) + 1

        ultima_data = registro.get("ultima_data_dou_processada")
        if ultima_data:
            datas.append(str(ultima_data))

        linhas.append({
            "processo": processo,
            "status": status,
            "ativo": bool(registro.get("ativo")),
            "historico_revisado": bool(registro.get("historico_revisado")),
            "ultima_data_dou_processada": ultima_data,
            "ultima_execucao_incremental_em": registro.get(
                "ultima_execucao_incremental_em"
            ),
            "observacao": registro.get("observacao"),
        })

    linhas.sort(
        key=lambda x: (
            x.get("status") or "",
            x.get("processo") or "",
        )
    )

    pendentes = sum(
        quantidade
        for status, quantidade in contagem_status.items()
        if "PENDENTE" in status.upper()
    )

    ativos = contagem_status.get("ATIVO_INCREMENTAL", 0)

    return {
        "arquivo": str(PROCESSOS_CONTROLE_PATH),
        "existe": PROCESSOS_CONTROLE_PATH.exists(),
        "modificado_em": _iso_mtime(PROCESSOS_CONTROLE_PATH),
        "total": len(linhas),
        "ativos_incrementais": ativos,
        "pendentes": pendentes,
        "status": contagem_status,
        "ultima_data_dou": max(datas) if datas else None,
        "processos": linhas,
    }


def _resultado_incremental_mais_recente() -> dict[str, Any]:
    if not PROCESSOS_INCREMENTAL_DIR.exists():
        return {
            "existe": False,
            "status": "SEM_ARQUIVO",
            "arquivo": None,
        }

    arquivos = sorted(
        PROCESSOS_INCREMENTAL_DIR.glob(
            "resultado_processos_incremental_*.json"
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not arquivos:
        return {
            "existe": False,
            "status": "SEM_ARQUIVO",
            "arquivo": None,
        }

    caminho = arquivos[0]
    payload = _ler_json(caminho)
    resumo = payload.get("resumo")
    if not isinstance(resumo, dict):
        resumo = {}

    return {
        "existe": True,
        "arquivo": str(caminho),
        "modificado_em": _iso_mtime(caminho),
        "status": (
            resumo.get("status")
            or payload.get("status")
            or "SEM_STATUS"
        ),
        "data_execucao": (
            resumo.get("data_execucao")
            or resumo.get("data")
            or payload.get("data_execucao")
        ),
        "total_processos_ativos": resumo.get(
            "total_processos_ativos"
        ),
        "total_registros_base": resumo.get(
            "total_registros_base"
        ),
        "total_resultados": resumo.get("total_resultados"),
        "catchup_automatico": resumo.get("catchup_automatico"),
    }


def _ultimo_status_sincronizacao() -> dict[str, Any]:
    payload = _ler_json(PROCESSOS_SYNC_STATUS_PATH)
    return {
        "existe": PROCESSOS_SYNC_STATUS_PATH.exists(),
        "arquivo": str(PROCESSOS_SYNC_STATUS_PATH),
        "modificado_em": _iso_mtime(PROCESSOS_SYNC_STATUS_PATH),
        "status": _status_payload(payload) or "SEM_STATUS",
        "processos_historicos_pendentes": payload.get(
            "processos_historicos_pendentes", []
        ),
        "revisao_historica": payload.get("revisao_historica"),
    }


def _carregar_execucoes_painel() -> list[dict[str, Any]]:
    payload = _ler_json(PAINEL_REGISTRY_PATH)
    itens = payload.get("execucoes", [])

    if not isinstance(itens, list):
        return []

    enriquecidos = []

    for item in itens:
        if not isinstance(item, dict):
            continue

        registro = dict(item)
        identificador = str(
            registro.get("id")
            or registro.get("job_id")
            or registro.get("execucao_id")
            or ""
        ).strip()

        atividades = {}

        if (
            identificador
            and len(identificador) <= 64
            and all(c.isalnum() or c in "_-" for c in identificador)
        ):
            caminho = PAINEL_DATA_DIR / "eventos" / f"{identificador}.jsonl"

            if caminho.is_file():
                try:
                    with caminho.open("r", encoding="utf-8") as arquivo:
                        for linha in arquivo:
                            if not linha.strip():
                                continue

                            evento = json.loads(linha)
                            if not isinstance(evento, dict):
                                continue

                            etapa = str(evento.get("etapa") or "").strip()
                            if not etapa:
                                continue

                            atividades[etapa] = {
                                "etapa": etapa,
                                "status": evento.get("status"),
                                "detalhes": evento.get("detalhes") or {},
                                "registrado_em": evento.get("data_hora") or evento.get("registrado_em"),
                            }
                except (OSError, ValueError):
                    registro["erro_leitura_eventos"] = True

        registro["atividades"] = list(atividades.values())
        registro["total_atividades_registradas"] = len(atividades)

        estados_finais = {"CONCLUIDA", "PARCIAL", "ERRO", "IGNORADA"}
        finalizadas = sum(
            1
            for atividade in atividades.values()
            if str(atividade.get("status") or "").upper() in estados_finais
        )

        registro["atividades_finalizadas"] = finalizadas
        registro["progresso_atividades_registradas"] = (
            round(finalizadas * 100 / len(atividades), 2)
            if atividades else 0
        )

        enriquecidos.append(registro)

    return enriquecidos

def _procurar_artefato(
    palavras: tuple[str, ...],
) -> dict[str, Any]:
    candidatos: list[Path] = []

    for raiz in (DOU_DATA_DIR, PAINEL_DATA_DIR):
        if not raiz.exists():
            continue

        try:
            for caminho in raiz.rglob("*"):
                if not caminho.is_file():
                    continue

                nome = caminho.name.lower()
                if not any(p in nome for p in palavras):
                    continue

                if caminho.suffix.lower() not in {
                    ".json",
                    ".txt",
                    ".log",
                    ".csv",
                }:
                    continue

                candidatos.append(caminho)
        except Exception:
            continue

    if not candidatos:
        return {
            "existe": False,
            "status": "SEM_EVIDENCIA",
            "arquivo": None,
        }

    caminho = max(candidatos, key=lambda p: p.stat().st_mtime)
    status = None

    if caminho.suffix.lower() == ".json":
        status = _status_payload(_ler_json(caminho))

    return {
        "existe": True,
        "status": status or "ARQUIVO_ENCONTRADO",
        "arquivo": str(caminho),
        "modificado_em": _iso_mtime(caminho),
    }


def possivel_execucao_hoje() -> bool:
    hoje = dt.date.today().isoformat()
    atual = _resultado_incremental_mais_recente()
    if str(atual.get("data_execucao") or "") == hoje:
        return True

    for item in _carregar_execucoes_painel():
        if (
            item.get("acao") == "ORQUESTRADOR_HOJE"
            and str(item.get("data_referencia") or "") == hoje
            and item.get("status") == "SUCESSO"
        ):
            return True

    return False


def status_geral() -> dict[str, Any]:
    processos = resumo_processos()
    incremental = _resultado_incremental_mais_recente()
    sincronizacao = _ultimo_status_sincronizacao()
    execucoes = _carregar_execucoes_painel()

    etapas = {
        "dou_incremental": incremental,
        "sincronizacao_processos": sincronizacao,
        "anvisa": _procurar_artefato(("anvisa",)),
        "email": _procurar_artefato(("email",)),
        "cloudflare": _procurar_artefato(
            ("cloudflare", "wrangler", "worker")
        ),
        "integras": _procurar_artefato(("integra", "integras")),
    }

    alertas = []

    if processos.get("pendentes", 0):
        alertas.append({
            "nivel": "critico",
            "mensagem": (
                f"{processos['pendentes']} processo(s) com status pendente."
            ),
        })

    if processos.get("total", 0) and not processos.get(
        "ativos_incrementais", 0
    ):
        alertas.append({
            "nivel": "critico",
            "mensagem": "Nenhum processo está em ATIVO_INCREMENTAL.",
        })

    git = git_info()
    if not git["limpo"]:
        alertas.append({
            "nivel": "atencao",
            "mensagem": "Há alterações locais não commitadas no Git.",
        })

    if AMBIENTE == "PROD":
        alertas.append({
            "nivel": "info",
            "mensagem": (
                "Ambiente PROD: ações de execução exigem confirmação explícita."
            ),
        })

    return {
        "agora": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "ambiente": AMBIENTE,
        "root": str(ROOT_DIR),
        "git": git,
        "processos": {
            k: v
            for k, v in processos.items()
            if k != "processos"
        },
        "etapas": etapas,
        "execucao_painel_atual": execucoes[0] if execucoes else None,
        "possivel_execucao_hoje": possivel_execucao_hoje(),
        "alertas": alertas,
    }


def listar_processos() -> list[dict[str, Any]]:
    return resumo_processos()["processos"]


def listar_execucoes(limite: int = 50) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite), 200))
    return _carregar_execucoes_painel()[:limite]


def listar_logs(limite: int = 80) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite), 250))
    candidatos: list[Path] = []

    for raiz in (DOU_DATA_DIR, PAINEL_DATA_DIR):
        if not raiz.exists():
            continue

        try:
            for caminho in raiz.rglob("*"):
                if not caminho.is_file():
                    continue

                if caminho.suffix.lower() not in {
                    ".txt",
                    ".log",
                    ".json",
                }:
                    continue

                candidatos.append(caminho)
        except Exception:
            continue

    candidatos.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    resultado = []
    for caminho in candidatos[:limite]:
        try:
            rel = caminho.resolve().relative_to(ROOT_DIR.resolve())
        except Exception:
            continue

        resultado.append({
            "path": rel.as_posix(),
            "nome": caminho.name,
            "tamanho": caminho.stat().st_size,
            "modificado_em": _iso_mtime(caminho),
        })

    return resultado


def ler_log(rel_path: str, max_bytes: int = 120_000) -> dict[str, Any]:
    caminho = (ROOT_DIR / rel_path).resolve()
    root = ROOT_DIR.resolve()

    try:
        caminho.relative_to(root)
    except ValueError:
        raise ValueError("Caminho de log fora do projeto.")

    if not caminho.exists() or not caminho.is_file():
        raise FileNotFoundError(rel_path)

    if caminho.suffix.lower() not in {".txt", ".log", ".json"}:
        raise ValueError("Tipo de arquivo não permitido.")

    tamanho = caminho.stat().st_size
    inicio = max(0, tamanho - max_bytes)

    with caminho.open("rb") as f:
        f.seek(inicio)
        dados = f.read(max_bytes)

    texto = dados.decode("utf-8", errors="replace")

    return {
        "path": rel_path,
        "tamanho": tamanho,
        "truncado": inicio > 0,
        "conteudo": texto,
    }
