# -*- coding: utf-8 -*-
"""
Controle de comunicação por e-mail — monitoramento de processos — 2026.

Responsabilidades:
- registrar ocorrências novas encontradas no DOU ou na Anvisa;
- impedir o reenvio da mesma ocorrência em execuções futuras;
- manter ocorrências pendentes quando o e-mail falhar;
- marcar como comunicadas somente depois de envio bem-sucedido;
- preservar histórico técnico de tentativas.

Este serviço NÃO pesquisa o DOU.
Este serviço NÃO pesquisa a Anvisa.
Este serviço NÃO envia e-mail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


VERSAO_SCHEMA = 1
ANO = 2026

ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_CONTROLE = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
)

CAMINHO_CONTROLE_EMAIL = (
    PASTA_CONTROLE
    / "controle_email_processos_2026.json"
)


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def normalizar_texto(valor: Any) -> str:
    texto = str(valor or "").strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    texto = texto.casefold()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def salvar_json_atomico(caminho: Path, payload: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    temporario.replace(caminho)


def novo_controle() -> dict[str, Any]:
    instante = agora_iso()

    return {
        "versao_schema": VERSAO_SCHEMA,
        "ano": ANO,
        "criado_em": instante,
        "atualizado_em": instante,
        "pendentes": {},
        "comunicadas": {},
        "historico_envios": [],
        "resumo": {
            "pendentes": 0,
            "comunicadas": 0,
            "envios_registrados": 0,
        },
    }


def carregar_ou_inicializar_controle() -> dict[str, Any]:
    if not CAMINHO_CONTROLE_EMAIL.exists():
        controle = novo_controle()
        salvar_json_atomico(CAMINHO_CONTROLE_EMAIL, controle)
        return controle

    try:
        controle = json.loads(
            CAMINHO_CONTROLE_EMAIL.read_text(encoding="utf-8")
        )
    except Exception as erro:
        raise RuntimeError(
            "Falha ao ler o controle de e-mail de processos: "
            f"{CAMINHO_CONTROLE_EMAIL} | {erro}"
        ) from erro

    if not isinstance(controle, dict):
        raise RuntimeError(
            "Formato inválido no controle de e-mail de processos: "
            f"{CAMINHO_CONTROLE_EMAIL}"
        )

    controle.setdefault("versao_schema", VERSAO_SCHEMA)
    controle.setdefault("ano", ANO)
    controle.setdefault("criado_em", agora_iso())
    controle.setdefault("pendentes", {})
    controle.setdefault("comunicadas", {})
    controle.setdefault("historico_envios", [])

    if not isinstance(controle["pendentes"], dict):
        raise RuntimeError("O campo 'pendentes' possui formato inválido.")

    if not isinstance(controle["comunicadas"], dict):
        raise RuntimeError("O campo 'comunicadas' possui formato inválido.")

    if not isinstance(controle["historico_envios"], list):
        raise RuntimeError("O campo 'historico_envios' possui formato inválido.")

    atualizar_resumo(controle)
    return controle


def atualizar_resumo(controle: dict[str, Any]) -> None:
    controle["resumo"] = {
        "pendentes": len(controle.get("pendentes", {}) or {}),
        "comunicadas": len(controle.get("comunicadas", {}) or {}),
        "envios_registrados": len(
            controle.get("historico_envios", []) or []
        ),
    }
    controle["atualizado_em"] = agora_iso()


def construir_chave_ocorrencia(ocorrencia: dict[str, Any]) -> str:
    """
    Gera uma chave estável para deduplicação.

    Prioridade:
    1. chave_resultado já produzida pela pesquisa;
    2. composição dos campos estruturais da ocorrência.
    """

    fonte = normalizar_texto(
        ocorrencia.get("fonte")
        or ocorrencia.get("origem")
        or ""
    )

    chave_origem = str(
        ocorrencia.get("chave_resultado") or ""
    ).strip()

    if chave_origem:
        base = f"{fonte}|{chave_origem}"
    else:
        campos = [
            fonte,
            normalizar_texto(ocorrencia.get("processo")),
            normalizar_texto(
                ocorrencia.get("data")
                or ocorrencia.get("data_publicacao")
            ),
            normalizar_texto(ocorrencia.get("titulo")),
            normalizar_texto(
                ocorrencia.get("pagina")
                or ocorrencia.get("pagina_pdf")
            ),
            normalizar_texto(
                ocorrencia.get("url")
                or ocorrencia.get("url_pdf")
                or ocorrencia.get("url_publicacao")
            ),
            normalizar_texto(
                ocorrencia.get("trecho")
                or ocorrencia.get("trecho_encontrado")
                or ocorrencia.get("contexto")
            ),
        ]
        base = "|".join(campos)

    return hashlib.sha256(
        base.encode("utf-8")
    ).hexdigest()


def preparar_ocorrencia(
    ocorrencia: dict[str, Any],
    *,
    chave: str,
    instante: str,
) -> dict[str, Any]:
    item = dict(ocorrencia)

    item["chave_email"] = chave
    item.setdefault("descoberta_em", instante)
    item["ultima_atualizacao_em"] = instante
    item.setdefault("tentativas_envio", 0)
    item.setdefault("ultimo_erro_envio", None)

    return item


def registrar_ocorrencias_pendentes(
    ocorrencias: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """
    Registra ocorrências ainda não comunicadas.

    Regras:
    - ocorrência já comunicada não volta para pendente;
    - ocorrência já pendente apenas recebe atualização de metadados;
    - duplicidades no mesmo lote são ignoradas.
    """

    controle = carregar_ou_inicializar_controle()
    pendentes = controle["pendentes"]
    comunicadas = controle["comunicadas"]

    instante = agora_iso()
    novas: list[str] = []
    ja_pendentes: list[str] = []
    ja_comunicadas: list[str] = []
    duplicadas_lote: list[str] = []
    vistos_lote: set[str] = set()

    for ocorrencia in ocorrencias:
        if not isinstance(ocorrencia, dict):
            continue

        chave = construir_chave_ocorrencia(ocorrencia)

        if chave in vistos_lote:
            duplicadas_lote.append(chave)
            continue

        vistos_lote.add(chave)

        if chave in comunicadas:
            ja_comunicadas.append(chave)
            continue

        if chave in pendentes:
            registro_atual = pendentes[chave]

            if isinstance(registro_atual, dict):
                # Atualiza os dados funcionais da ocorrência,
                # preservando a trilha de auditoria/retry já existente.
                descoberta_em = registro_atual.get(
                    "descoberta_em"
                )
                tentativas_envio = int(
                    registro_atual.get("tentativas_envio") or 0
                )
                ultimo_erro_envio = registro_atual.get(
                    "ultimo_erro_envio"
                )
                ultima_tentativa_envio_em = registro_atual.get(
                    "ultima_tentativa_envio_em"
                )

                registro_atual.update(
                    preparar_ocorrencia(
                        ocorrencia,
                        chave=chave,
                        instante=instante,
                    )
                )

                if descoberta_em:
                    registro_atual["descoberta_em"] = (
                        descoberta_em
                    )

                registro_atual["tentativas_envio"] = (
                    tentativas_envio
                )
                registro_atual["ultimo_erro_envio"] = (
                    ultimo_erro_envio
                )

                if ultima_tentativa_envio_em:
                    registro_atual[
                        "ultima_tentativa_envio_em"
                    ] = ultima_tentativa_envio_em

            ja_pendentes.append(chave)
            continue

        pendentes[chave] = preparar_ocorrencia(
            ocorrencia,
            chave=chave,
            instante=instante,
        )
        novas.append(chave)

    atualizar_resumo(controle)
    salvar_json_atomico(CAMINHO_CONTROLE_EMAIL, controle)

    return {
        "status": "OCORRENCIAS_REGISTRADAS",
        "novas": novas,
        "ja_pendentes": ja_pendentes,
        "ja_comunicadas": ja_comunicadas,
        "duplicadas_lote": duplicadas_lote,
        "total_pendentes": len(pendentes),
        "caminho_controle": str(CAMINHO_CONTROLE_EMAIL),
    }


def obter_ocorrencias_pendentes() -> list[dict[str, Any]]:
    controle = carregar_ou_inicializar_controle()
    pendentes = controle.get("pendentes", {}) or {}

    itens = [
        dict(registro)
        for registro in pendentes.values()
        if isinstance(registro, dict)
    ]

    itens.sort(
        key=lambda item: (
            normalizar_texto(item.get("processo")),
            normalizar_texto(item.get("fonte")),
            normalizar_texto(
                item.get("data")
                or item.get("data_publicacao")
            ),
            normalizar_texto(item.get("titulo")),
            normalizar_texto(
                item.get("pagina")
                or item.get("pagina_pdf")
            ),
        )
    )

    return itens


def registrar_falha_envio(
    chaves: Iterable[str],
    *,
    erro: str,
) -> dict[str, Any]:
    controle = carregar_ou_inicializar_controle()
    pendentes = controle["pendentes"]
    instante = agora_iso()
    atualizadas: list[str] = []

    for chave in chaves:
        registro = pendentes.get(str(chave))

        if not isinstance(registro, dict):
            continue

        registro["tentativas_envio"] = (
            int(registro.get("tentativas_envio") or 0) + 1
        )
        registro["ultimo_erro_envio"] = str(erro)
        registro["ultima_tentativa_envio_em"] = instante
        atualizadas.append(str(chave))

    controle["historico_envios"].append({
        "status": "ERRO",
        "executado_em": instante,
        "quantidade_ocorrencias": len(atualizadas),
        "chaves": atualizadas,
        "erro": str(erro),
    })

    atualizar_resumo(controle)
    salvar_json_atomico(CAMINHO_CONTROLE_EMAIL, controle)

    return {
        "status": "FALHA_ENVIO_REGISTRADA",
        "ocorrencias_atualizadas": len(atualizadas),
        "chaves": atualizadas,
        "caminho_controle": str(CAMINHO_CONTROLE_EMAIL),
    }


def marcar_ocorrencias_comunicadas(
    chaves: Iterable[str],
    *,
    data_email: str,
    status_email: str,
) -> dict[str, Any]:
    """
    Move ocorrências de pendentes para comunicadas.

    Deve ser chamado somente após confirmação de envio real ou simulado
    considerado bem-sucedido pelo fluxo chamador.
    """

    controle = carregar_ou_inicializar_controle()
    pendentes = controle["pendentes"]
    comunicadas = controle["comunicadas"]
    instante = agora_iso()
    movidas: list[str] = []

    for chave in chaves:
        chave = str(chave)
        registro = pendentes.pop(chave, None)

        if not isinstance(registro, dict):
            continue

        registro["comunicada"] = True
        registro["comunicada_em"] = instante
        registro["data_email"] = str(data_email)
        registro["status_email"] = str(status_email)
        registro["ultimo_erro_envio"] = None

        comunicadas[chave] = registro
        movidas.append(chave)

    controle["historico_envios"].append({
        "status": str(status_email),
        "executado_em": instante,
        "data_email": str(data_email),
        "quantidade_ocorrencias": len(movidas),
        "chaves": movidas,
    })

    atualizar_resumo(controle)
    salvar_json_atomico(CAMINHO_CONTROLE_EMAIL, controle)

    return {
        "status": "OCORRENCIAS_COMUNICADAS",
        "ocorrencias_movidas": len(movidas),
        "chaves": movidas,
        "caminho_controle": str(CAMINHO_CONTROLE_EMAIL),
    }


def mostrar_resumo() -> dict[str, Any]:
    controle = carregar_ou_inicializar_controle()
    atualizar_resumo(controle)
    salvar_json_atomico(CAMINHO_CONTROLE_EMAIL, controle)

    return {
        "status": "CONTROLE_EMAIL_CARREGADO",
        "caminho_controle": str(CAMINHO_CONTROLE_EMAIL),
        **controle["resumo"],
    }


def imprimir_resultado(resultado: dict[str, Any]) -> None:
    print("=" * 80)
    print("CONTROLE DE E-MAIL — PROCESSOS — 2026")
    print("=" * 80)
    print(f"Status: {resultado.get('status')}")
    print(f"Ocorrências pendentes: {resultado.get('pendentes', 0)}")
    print(f"Ocorrências comunicadas: {resultado.get('comunicadas', 0)}")
    print(
        "Envios registrados: "
        f"{resultado.get('envios_registrados', 0)}"
    )
    print(f"Controle: {resultado.get('caminho_controle')}")
    print("=" * 80)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inicializa e consulta o controle de comunicação "
            "das ocorrências de processos."
        )
    )

    grupo = parser.add_mutually_exclusive_group(required=True)

    grupo.add_argument(
        "--inicializar",
        action="store_true",
        help="Cria o controle vazio, caso ainda não exista.",
    )

    grupo.add_argument(
        "--mostrar",
        action="store_true",
        help="Exibe o resumo atual do controle.",
    )

    return parser


def main() -> None:
    parser = montar_parser()
    parser.parse_args()

    resultado = mostrar_resumo()
    imprimir_resultado(resultado)


if __name__ == "__main__":
    main()
