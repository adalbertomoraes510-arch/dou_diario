# ============================================================
# RUNNER — Status Operacional DOU
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Testar o service status_operacional_dou_service.py e gerar
# um diagnóstico operacional dos arquivos já gerados pelo pipeline.
#
# Este runner NÃO executa busca.
# Este runner NÃO altera match.
# Este runner NÃO altera curadoria.
# Este runner NÃO altera relatório.
# Este runner apenas consulta os artefatos existentes.
# ============================================================

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List

from backend.services.status_operacional_dou_service import (
    salvar_status_operacional_dou,
    salvar_status_operacional_dou_periodo,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# Data única para diagnóstico operacional
DATA_REFERENCIA = dt.date(2026, 5, 14)

# Período para diagnóstico operacional consolidado
DATA_INICIO = dt.date(2026, 5, 13)
DATA_FIM = dt.date(2026, 5, 14)

FINALIDADES = [
    "dou_diario",
    "informativos",
]

APENAS_DIAS_UTEIS = True


# ============================================================
# UTILITÁRIOS DE IMPRESSÃO
# ============================================================

def imprimir_titulo(texto: str) -> None:
    print("=" * 80)
    print(texto)
    print("=" * 80)


def imprimir_bloco(texto: str) -> None:
    print("")
    print("-" * 80)
    print(texto)
    print("-" * 80)


def formatar_status_existe(existe: bool | None) -> str:
    if existe is True:
        return "OK"

    if existe is False:
        return "PENDENTE"

    return "NAO_APLICAVEL"


def obter_resumo_check(check: Dict[str, Any]) -> str:
    nome = check.get("nome")
    existe = formatar_status_existe(check.get("existe"))
    obrigatorio = "OBRIGATORIO" if check.get("obrigatorio") else "OPCIONAL"
    caminho = check.get("caminho")
    total = check.get("total_registros_estimado")

    texto = f"{existe} | {obrigatorio} | {nome}"

    if total is not None:
        texto += f" | registros estimados: {total}"

    texto += f"\n    {caminho}"

    return texto


def imprimir_resumo_geral(resumo: Dict[str, Any]) -> None:
    print(f"Status geral: {resumo.get('status_geral')}")
    print(
        "Percentual obrigatórios OK: "
        f"{resumo.get('percentual_conclusao_obrigatorios')}%"
    )
    print(
        "Checks obrigatórios: "
        f"{resumo.get('total_checks_obrigatorios_ok')}/"
        f"{resumo.get('total_checks_obrigatorios')}"
    )
    print(
        "Pendências obrigatórias: "
        f"{resumo.get('total_checks_obrigatorios_pendentes')}"
    )
    print(
        "Checks opcionais OK: "
        f"{resumo.get('total_checks_opcionais_ok')}/"
        f"{resumo.get('total_checks_opcionais')}"
    )


def imprimir_pendencias(resumo: Dict[str, Any]) -> None:
    pendencias: List[Dict[str, Any]] = resumo.get("pendencias_obrigatorias") or []

    if not pendencias:
        print("Nenhuma pendência obrigatória.")
        return

    for indice, pendencia in enumerate(pendencias, start=1):
        print("")
        print(f"{indice}. {pendencia.get('nome')}")
        print(f"   Descrição: {pendencia.get('descricao')}")
        print(f"   Caminho: {pendencia.get('caminho')}")


def imprimir_camada_fonte(status_data: Dict[str, Any]) -> None:
    camada_fonte = status_data.get("camada_fonte") or {}

    imprimir_bloco("CAMADA FONTE DOU")

    for _, check in camada_fonte.items():
        if isinstance(check, dict):
            print(obter_resumo_check(check))


def imprimir_finalidades(status_data: Dict[str, Any]) -> None:
    finalidades = status_data.get("finalidades") or {}

    imprimir_bloco("FINALIDADES")

    for nome_finalidade, dados_finalidade in finalidades.items():
        print("")
        print(f"Finalidade: {nome_finalidade}")

        for chave, check in dados_finalidade.items():
            if chave == "finalidade":
                continue

            if isinstance(check, dict):
                print(obter_resumo_check(check))


def imprimir_status_periodo(status_periodo: Dict[str, Any]) -> None:
    imprimir_bloco("STATUS DO PERIODO")

    print(f"Período: {status_periodo.get('data_inicio')} a {status_periodo.get('data_fim')}")
    print(f"Apenas dias úteis: {status_periodo.get('apenas_dias_uteis')}")
    print(f"Total dias considerados: {status_periodo.get('total_dias_considerados')}")
    print(f"Dias considerados: {', '.join(status_periodo.get('dias_considerados') or [])}")

    imprimir_bloco("ARTEFATOS CONSOLIDADOS POR FINALIDADE")

    status_finalidades = status_periodo.get("status_periodo_finalidades") or {}

    for nome_finalidade, dados_finalidade in status_finalidades.items():
        print("")
        print(f"Finalidade: {nome_finalidade}")

        for chave, check in dados_finalidade.items():
            if chave == "finalidade":
                continue

            if isinstance(check, dict):
                print(obter_resumo_check(check))


def imprimir_status_dias_resumido(status_periodo: Dict[str, Any]) -> None:
    imprimir_bloco("RESUMO POR DIA")

    status_dias = status_periodo.get("status_dias") or []

    if not status_dias:
        print("Nenhum dia retornado no período.")
        return

    for item in status_dias:
        data = item.get("data_referencia")
        resumo = item.get("resumo") or {}

        print("")
        print(f"Data: {data}")
        print(f"Status geral: {resumo.get('status_geral')}")
        print(
            "Obrigatórios OK: "
            f"{resumo.get('total_checks_obrigatorios_ok')}/"
            f"{resumo.get('total_checks_obrigatorios')}"
        )
        print(
            "Pendências: "
            f"{resumo.get('total_checks_obrigatorios_pendentes')}"
        )


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    imprimir_titulo("STATUS OPERACIONAL DOU — DATA UNICA")

    status_data = salvar_status_operacional_dou(
        data_referencia=DATA_REFERENCIA,
        finalidades=FINALIDADES,
    )

    print(f"Fonte: {status_data.get('fonte')}")
    print(f"Data referência: {status_data.get('data_referencia')}")
    print(f"Gerado em: {status_data.get('gerado_em')}")
    print(f"Arquivo saída: {status_data.get('arquivo_saida')}")

    imprimir_bloco("RESUMO GERAL — DATA UNICA")
    imprimir_resumo_geral(status_data.get("resumo") or {})

    imprimir_camada_fonte(status_data)
    imprimir_finalidades(status_data)

    imprimir_bloco("PENDENCIAS OBRIGATORIAS — DATA UNICA")
    imprimir_pendencias(status_data.get("resumo") or {})

    imprimir_titulo("STATUS OPERACIONAL DOU — PERIODO")

    status_periodo = salvar_status_operacional_dou_periodo(
        data_inicio=DATA_INICIO,
        data_fim=DATA_FIM,
        finalidades=FINALIDADES,
        apenas_dias_uteis=APENAS_DIAS_UTEIS,
    )

    print(f"Fonte: {status_periodo.get('fonte')}")
    print(f"Período: {status_periodo.get('data_inicio')} a {status_periodo.get('data_fim')}")
    print(f"Gerado em: {status_periodo.get('gerado_em')}")
    print(f"Arquivo saída: {status_periodo.get('arquivo_saida')}")

    imprimir_bloco("RESUMO GERAL — PERIODO")
    imprimir_resumo_geral(status_periodo.get("resumo") or {})

    imprimir_status_periodo(status_periodo)
    imprimir_status_dias_resumido(status_periodo)

    imprimir_bloco("PENDENCIAS OBRIGATORIAS — PERIODO")
    imprimir_pendencias(status_periodo.get("resumo") or {})

    imprimir_titulo("STATUS OPERACIONAL FINALIZADO")


if __name__ == "__main__":
    main()
    