# -*- coding: utf-8 -*-
"""
Controle incremental do monitoramento de processos — DOU/Anvisa — 2026.

Responsabilidades:
- ler os processos da aba PROCESSOS / coluna PROCESSO;
- criar o baseline inicial dos processos já validados;
- identificar processos novos, removidos e reativados;
- controlar quais processos ainda exigem revisão histórica;
- registrar a última data do DOU processada por processo.

Este serviço NÃO pesquisa o DOU.
Este serviço NÃO pesquisa a Anvisa.
Este serviço NÃO envia e-mail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from backend.services.pesquisa_processos_dou_service import (
    carregar_processos_planilha,
)


VERSAO_SCHEMA = 1
ANO_MONITORAMENTO = 2026

STATUS_ATIVO_INCREMENTAL = "ATIVO_INCREMENTAL"
STATUS_NOVO_HISTORICO_PENDENTE = "NOVO_HISTORICO_PENDENTE"
STATUS_INATIVO = "INATIVO"

ROOT_DIR = Path(__file__).resolve().parents[2]

CAMINHO_PLANILHA = (
    ROOT_DIR
    / "backend"
    / "config"
    / "finalidades"
    / "dou_diario"
    / "palavras_chave.xlsx"
)

PASTA_CONTROLE = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
)

CAMINHO_CONTROLE = (
    PASTA_CONTROLE
    / "controle_monitoramento_processos_2026.json"
)

NOME_ABA = "PROCESSOS"
NOME_COLUNA = "PROCESSO"


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def hoje_iso() -> str:
    return dt.date.today().isoformat()


def converter_data_iso(valor: str | None) -> str | None:
    if valor in [None, ""]:
        return None

    try:
        return dt.date.fromisoformat(str(valor)).isoformat()
    except ValueError as erro:
        raise ValueError(
            f"Data inválida: {valor!r}. Use o formato AAAA-MM-DD."
        ) from erro


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


def carregar_json_seguro(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise FileNotFoundError(
            f"Controle de monitoramento ainda não foi criado: {caminho}"
        )

    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as erro:
        raise RuntimeError(
            f"Falha ao ler o controle de monitoramento: {caminho} | {erro}"
        ) from erro

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Formato inválido no controle de monitoramento: {caminho}"
        )

    return payload


def carregar_processos_atuais() -> tuple[str, ...]:
    return carregar_processos_planilha(
        caminho_planilha=CAMINHO_PLANILHA,
        nome_aba=NOME_ABA,
        nome_coluna=NOME_COLUNA,
    )


def novo_registro_processo_baseline(
    processo: str,
    *,
    instante: str,
    data_baseline: str,
    ultima_data_dou_validada: str | None,
) -> dict[str, Any]:
    return {
        "processo": processo,
        "status": STATUS_ATIVO_INCREMENTAL,
        "ativo": True,
        "historico_revisado": True,
        "historico_revisado_em": data_baseline,
        "origem_historico": "BASELINE_VALIDADO_DEV",
        "primeira_identificacao_em": instante,
        "ultima_identificacao_planilha_em": instante,
        "removido_em": None,
        "reativado_em": None,
        "ultima_data_dou_processada": ultima_data_dou_validada,
        "ultima_execucao_incremental_em": None,
        "observacao": (
            "Processo incluído no baseline inicial. "
            "O histórico anterior já foi validado nos testes do DEV."
        ),
    }


def novo_registro_processo_pendente(
    processo: str,
    *,
    instante: str,
) -> dict[str, Any]:
    return {
        "processo": processo,
        "status": STATUS_NOVO_HISTORICO_PENDENTE,
        "ativo": True,
        "historico_revisado": False,
        "historico_revisado_em": None,
        "origem_historico": None,
        "primeira_identificacao_em": instante,
        "ultima_identificacao_planilha_em": instante,
        "removido_em": None,
        "reativado_em": None,
        "ultima_data_dou_processada": None,
        "ultima_execucao_incremental_em": None,
        "observacao": (
            "Processo novo identificado na planilha. "
            "A revisão histórica anual deve ocorrer uma única vez."
        ),
    }


def montar_resumo_estado(estado: dict[str, Any]) -> dict[str, int]:
    processos = estado.get("processos", {}) or {}

    if not isinstance(processos, dict):
        processos = {}

    ativos_incrementais = 0
    historicos_pendentes = 0
    inativos = 0

    for registro in processos.values():
        if not isinstance(registro, dict):
            continue

        status = str(registro.get("status") or "")

        if status == STATUS_ATIVO_INCREMENTAL:
            ativos_incrementais += 1
        elif status == STATUS_NOVO_HISTORICO_PENDENTE:
            historicos_pendentes += 1
        elif status == STATUS_INATIVO:
            inativos += 1

    return {
        "total_registrados": len(processos),
        "ativos_incrementais": ativos_incrementais,
        "historicos_pendentes": historicos_pendentes,
        "inativos": inativos,
    }


def inicializar_baseline(
    *,
    forcar: bool = False,
    data_baseline: str | None = None,
    ultima_data_dou_validada: str | None = None,
) -> dict[str, Any]:
    """
    Cria o baseline inicial.

    Os processos atuais da planilha são registrados como:
    - histórico já revisado;
    - ativos em modo incremental;
    - sem necessidade de nova varredura anual.

    Por segurança, não sobrescreve um controle existente sem `forcar=True`.
    """

    data_baseline = converter_data_iso(data_baseline) or hoje_iso()
    ultima_data_dou_validada = converter_data_iso(
        ultima_data_dou_validada
    )

    if CAMINHO_CONTROLE.exists() and not forcar:
        raise FileExistsError(
            "O baseline já existe e não foi sobrescrito. "
            f"Arquivo: {CAMINHO_CONTROLE}. "
            "Use --forcar somente quando a reinicialização for intencional."
        )

    processos = carregar_processos_atuais()
    instante = agora_iso()

    registros = {
        processo: novo_registro_processo_baseline(
            processo,
            instante=instante,
            data_baseline=data_baseline,
            ultima_data_dou_validada=ultima_data_dou_validada,
        )
        for processo in processos
    }

    estado: dict[str, Any] = {
        "versao_schema": VERSAO_SCHEMA,
        "ano": ANO_MONITORAMENTO,
        "criado_em": instante,
        "atualizado_em": instante,
        "baseline_inicializado": True,
        "baseline_em": data_baseline,
        "ultima_data_dou_validada_baseline": ultima_data_dou_validada,
        "fonte_processos": str(CAMINHO_PLANILHA),
        "aba_processos": NOME_ABA,
        "coluna_processos": NOME_COLUNA,
        "ultima_sincronizacao_planilha_em": instante,
        "processos": registros,
    }

    estado["resumo"] = montar_resumo_estado(estado)
    salvar_json_atomico(CAMINHO_CONTROLE, estado)

    return {
        "status": "BASELINE_INICIALIZADO",
        "caminho_controle": str(CAMINHO_CONTROLE),
        "processos_planilha": len(processos),
        "processos_registrados_baseline": len(processos),
        **estado["resumo"],
    }


def sincronizar_com_planilha() -> dict[str, Any]:
    """
    Sincroniza o arquivo de controle com a lista atual da planilha.

    Regras:
    - processo novo: NOVO_HISTORICO_PENDENTE;
    - processo removido: INATIVO;
    - processo reativado:
        - se o histórico já foi revisado, volta para ATIVO_INCREMENTAL;
        - caso contrário, volta para NOVO_HISTORICO_PENDENTE.
    """

    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    registros = estado.setdefault("processos", {})

    if not isinstance(registros, dict):
        raise RuntimeError(
            "O campo 'processos' do controle possui formato inválido."
        )

    processos_atuais = carregar_processos_atuais()
    atuais = set(processos_atuais)
    instante = agora_iso()

    novos: list[str] = []
    removidos: list[str] = []
    reativados: list[str] = []

    for processo in processos_atuais:
        registro = registros.get(processo)

        if not isinstance(registro, dict):
            registros[processo] = novo_registro_processo_pendente(
                processo,
                instante=instante,
            )
            novos.append(processo)
            continue

        registro["ultima_identificacao_planilha_em"] = instante

        if registro.get("status") == STATUS_INATIVO or not registro.get(
            "ativo", True
        ):
            registro["ativo"] = True
            registro["removido_em"] = None
            registro["reativado_em"] = instante

            # Todo processo reativado deve validar o período
            # em que permaneceu fora do monitoramento.
            registro["status"] = STATUS_NOVO_HISTORICO_PENDENTE

            if bool(registro.get("historico_revisado")):
                registro["observacao"] = (
                    "Processo reativado. Aguardando catch-up desde "
                    "a última data DOU processada antes de retornar "
                    "ao modo incremental."
                )
            else:
                registro["observacao"] = (
                    "Processo reativado com revisão histórica "
                    "ainda pendente."
                )

            reativados.append(processo)

    for processo, registro in registros.items():
        if not isinstance(registro, dict):
            continue

        if processo in atuais:
            continue

        if registro.get("status") != STATUS_INATIVO:
            registro["status"] = STATUS_INATIVO
            registro["ativo"] = False
            registro["removido_em"] = instante
            registro["observacao"] = (
                "Processo removido da planilha e desativado no monitoramento."
            )
            removidos.append(processo)

    estado["atualizado_em"] = instante
    estado["ultima_sincronizacao_planilha_em"] = instante
    estado["resumo"] = montar_resumo_estado(estado)
    salvar_json_atomico(CAMINHO_CONTROLE, estado)

    return {
        "status": "SINCRONIZADO",
        "caminho_controle": str(CAMINHO_CONTROLE),
        "processos_planilha": len(processos_atuais),
        "novos": novos,
        "removidos": removidos,
        "reativados": reativados,
        **estado["resumo"],
    }


def listar_processos_por_status(status: str) -> list[str]:
    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    registros = estado.get("processos", {}) or {}

    return [
        processo
        for processo, registro in registros.items()
        if isinstance(registro, dict)
        and str(registro.get("status") or "") == status
    ]


def obter_processos_ativos_incrementais() -> list[str]:
    return listar_processos_por_status(STATUS_ATIVO_INCREMENTAL)


def obter_processos_historicos_pendentes() -> list[str]:
    return listar_processos_por_status(STATUS_NOVO_HISTORICO_PENDENTE)



def marcar_historico_revisado(
    processo: str,
    *,
    data_revisao: str | None = None,
    ultima_data_dou_processada: str | None = None,
) -> dict[str, Any]:
    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    registros = estado.get("processos", {}) or {}

    registro = registros.get(processo)

    if not isinstance(registro, dict):
        raise KeyError(
            f"Processo não encontrado no controle: {processo}"
        )

    data_revisao = converter_data_iso(data_revisao) or hoje_iso()

    ultima_data_dou_processada = converter_data_iso(
        ultima_data_dou_processada
    )

    data_atual = converter_data_iso(
        registro.get("ultima_data_dou_processada")
    )

    # Proteção monotônica:
    # uma revisão histórica nunca pode fazer a última data retroceder.
    if (
        ultima_data_dou_processada
        and data_atual
        and ultima_data_dou_processada < data_atual
    ):
        ultima_data_dou_processada = data_atual

    registro["historico_revisado"] = True
    registro["historico_revisado_em"] = data_revisao
    registro["origem_historico"] = "REVISAO_HISTORICA_AUTOMATICA"
    registro["status"] = STATUS_ATIVO_INCREMENTAL
    registro["ativo"] = True
    registro["ultima_data_dou_processada"] = (
        ultima_data_dou_processada
        or data_atual
    )
    registro["observacao"] = (
        "Revisão histórica concluída. "
        "Processo promovido ao modo incremental."
    )

    estado["atualizado_em"] = agora_iso()
    estado["resumo"] = montar_resumo_estado(estado)
    salvar_json_atomico(CAMINHO_CONTROLE, estado)

    return {
        "status": "HISTORICO_REVISADO",
        "processo": processo,
        "caminho_controle": str(CAMINHO_CONTROLE),
    }


def registrar_execucao_incremental(
    processos: list[str] | tuple[str, ...],
    *,
    data_dou_processada: str,
    processos_catchup_validados: (
        list[str] | tuple[str, ...] | set[str] | None
    ) = None,
) -> dict[str, Any]:
    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    registros = estado.get("processos", {}) or {}

    data_dou_processada = converter_data_iso(
        data_dou_processada
    )

    if not data_dou_processada:
        raise ValueError(
            "data_dou_processada deve ser uma data ISO v\u00e1lida."
        )

    data_nova_obj = dt.date.fromisoformat(
        data_dou_processada
    )

    catchup_validados = set(
        processos_catchup_validados or []
    )

    regressao_bloqueada: list[str] = []
    sem_marco_bloqueado: list[str] = []
    salto_bloqueado: list[str] = []
    salto_validado: list[str] = []

    # Preflight atomico:
    # nenhum marco e alterado se existir lacuna sem catch-up validado.
    for processo in processos:
        registro = registros.get(processo)

        if not isinstance(registro, dict):
            continue

        if registro.get("status") != STATUS_ATIVO_INCREMENTAL:
            continue

        data_atual = converter_data_iso(
            registro.get("ultima_data_dou_processada")
        )

        if not data_atual:
            if processo not in catchup_validados:
                sem_marco_bloqueado.append(processo)
            else:
                salto_validado.append(processo)
            continue

        data_atual_obj = dt.date.fromisoformat(data_atual)

        if data_nova_obj < data_atual_obj:
            regressao_bloqueada.append(processo)
            continue

        if data_nova_obj > (
            data_atual_obj + dt.timedelta(days=1)
        ):
            if processo in catchup_validados:
                salto_validado.append(processo)
            else:
                salto_bloqueado.append(processo)

    if sem_marco_bloqueado or salto_bloqueado:
        detalhes = []

        if sem_marco_bloqueado:
            detalhes.append(
                "sem marco anterior: "
                + ", ".join(sem_marco_bloqueado)
            )

        if salto_bloqueado:
            detalhes.append(
                "salto de datas: "
                + ", ".join(salto_bloqueado)
            )

        raise RuntimeError(
            "Avan\u00e7o incremental bloqueado. "
            "Execute o catch-up e valide toda a cobertura antes "
            "de registrar a data corrente. "
            + " | ".join(detalhes)
        )

    instante = agora_iso()
    atualizados: list[str] = []

    for processo in processos:
        registro = registros.get(processo)

        if not isinstance(registro, dict):
            continue

        if registro.get("status") != STATUS_ATIVO_INCREMENTAL:
            continue

        data_atual = converter_data_iso(
            registro.get("ultima_data_dou_processada")
        )

        if (
            data_atual
            and data_dou_processada < data_atual
        ):
            continue

        registro["ultima_data_dou_processada"] = (
            data_dou_processada
        )
        registro["ultima_execucao_incremental_em"] = instante
        atualizados.append(processo)

    estado["atualizado_em"] = instante
    estado["resumo"] = montar_resumo_estado(estado)
    salvar_json_atomico(CAMINHO_CONTROLE, estado)

    return {
        "status": "EXECUCAO_INCREMENTAL_REGISTRADA",
        "data_dou_processada": data_dou_processada,
        "processos_atualizados": len(atualizados),
        "processos": atualizados,
        "regressoes_bloqueadas": len(regressao_bloqueada),
        "processos_regressao_bloqueada": regressao_bloqueada,
        "saltos_validados": len(salto_validado),
        "processos_salto_validado": salto_validado,
        "saltos_bloqueados": 0,
        "processos_salto_bloqueado": [],
        "sem_marco_bloqueados": 0,
        "processos_sem_marco_bloqueado": [],
    }

def imprimir_resultado(resultado: dict[str, Any]) -> None:
    print("=" * 80)
    print("CONTROLE INCREMENTAL DE PROCESSOS — 2026")
    print("=" * 80)
    print(f"Status: {resultado.get('status')}")
    print(f"Processos encontrados na planilha: {resultado.get('processos_planilha', '-')}")
    print(
        "Processos registrados no baseline: "
        f"{resultado.get('processos_registrados_baseline', '-')}"
    )
    print(
        "Processos ativos incrementais: "
        f"{resultado.get('ativos_incrementais', 0)}"
    )
    print(
        "Processos históricos pendentes: "
        f"{resultado.get('historicos_pendentes', 0)}"
    )
    print(f"Processos inativos: {resultado.get('inativos', 0)}")

    if resultado.get("novos"):
        print(f"Novos: {', '.join(resultado['novos'])}")

    if resultado.get("removidos"):
        print(f"Removidos: {', '.join(resultado['removidos'])}")

    if resultado.get("reativados"):
        print(f"Reativados: {', '.join(resultado['reativados'])}")

    print(f"Controle: {resultado.get('caminho_controle')}")
    print("=" * 80)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inicializa e sincroniza o controle incremental "
            "dos processos monitorados em 2026."
        )
    )

    grupo = parser.add_mutually_exclusive_group(required=True)

    grupo.add_argument(
        "--inicializar-baseline",
        action="store_true",
        help=(
            "Registra todos os processos atuais como histórico já revisado "
            "e ativos no modo incremental."
        ),
    )

    grupo.add_argument(
        "--sincronizar",
        action="store_true",
        help=(
            "Compara a planilha atual com o controle e identifica "
            "processos novos, removidos e reativados."
        ),
    )

    grupo.add_argument(
        "--mostrar",
        action="store_true",
        help="Exibe o resumo atual do controle.",
    )

    parser.add_argument(
        "--data-baseline",
        default=None,
        help="Data do baseline no formato AAAA-MM-DD. Padrão: hoje.",
    )

    parser.add_argument(
        "--ultima-data-dou-validada",
        default=None,
        help=(
            "Última data já validada no histórico do DOU, "
            "no formato AAAA-MM-DD."
        ),
    )

    parser.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "Permite sobrescrever um baseline existente. "
            "Use somente quando a reinicialização for intencional."
        ),
    )

    return parser


def main() -> None:
    parser = montar_parser()
    args = parser.parse_args()

    if args.inicializar_baseline:
        resultado = inicializar_baseline(
            forcar=args.forcar,
            data_baseline=args.data_baseline,
            ultima_data_dou_validada=args.ultima_data_dou_validada,
        )
        imprimir_resultado(resultado)
        return

    if args.sincronizar:
        resultado = sincronizar_com_planilha()
        imprimir_resultado(resultado)
        return

    estado = carregar_json_seguro(CAMINHO_CONTROLE)
    resultado = {
        "status": "CONTROLE_CARREGADO",
        "caminho_controle": str(CAMINHO_CONTROLE),
        "processos_planilha": len(carregar_processos_atuais()),
        **montar_resumo_estado(estado),
    }
    imprimir_resultado(resultado)


if __name__ == "__main__":
    main()
