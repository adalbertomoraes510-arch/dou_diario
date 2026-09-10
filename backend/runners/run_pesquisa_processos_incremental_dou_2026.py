# -*- coding: utf-8 -*-
"""
Runner isolado — pesquisa incremental diária de processos no DOU — 2026.

Objetivo desta etapa:
- usar somente processos com status ATIVO_INCREMENTAL;
- pesquisar somente a base DOU da data informada;
- não baixar novamente o DOU;
- não acessar a Anvisa;
- não enviar e-mail;
- salvar resultado diário separado;
- registrar a data processada no controle somente após sucesso.

Este runner não substitui o runner oficial. Ele valida isoladamente
a pesquisa incremental diária antes da integração ao orquestrador.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

from backend.services.controle_monitoramento_processos_service import (
    obter_processos_ativos_incrementais,
    registrar_execucao_incremental,
    sincronizar_com_planilha,
)
from backend.services.pesquisa_processos_dou_service import (
    pesquisar_processos_nos_registros,
)
from backend.runners.run_revisao_historica_processos_pendentes_2026 import (
    garantir_cobertura_dou_para_revisao,
    pesquisar_historico_dou_pendentes_por_faixa,
    resolver_data_inicio_processo_pendente,
)


ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"
BASE_DOU_DIR = DATA_DOU_DIR / "base"

PASTA_SAIDA = (
    DATA_DOU_DIR
    / "pesquisas"
    / "processos_2026"
    / "incremental_dou"
)

PASTA_POR_DATA = PASTA_SAIDA / "por_data"


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def converter_data(valor: str) -> dt.date:
    try:
        return dt.date.fromisoformat(valor)
    except ValueError as erro:
        raise argparse.ArgumentTypeError(
            f"Data inválida: {valor!r}. Use AAAA-MM-DD."
        ) from erro


def salvar_json_atomico(caminho: Path, payload: Any) -> None:
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


def caminho_base_dou(data_execucao: dt.date) -> Path:
    return BASE_DOU_DIR / f"base_publicacoes_{data_execucao.isoformat()}.json"


def caminho_resultado_json(data_execucao: dt.date) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_incremental_{data_execucao.isoformat()}.json"
    )


def caminho_resultado_csv(data_execucao: dt.date) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_incremental_{data_execucao.isoformat()}.csv"
    )


def caminho_resultado_txt(data_execucao: dt.date) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_incremental_{data_execucao.isoformat()}_resumo.txt"
    )


def carregar_json(caminho: Path) -> Any:
    if not caminho.exists():
        raise FileNotFoundError(
            "Base DOU da data não encontrada. "
            "Este runner não baixa o DOU e deve ser executado somente "
            f"após a geração da base diária: {caminho}"
        )

    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as erro:
        raise RuntimeError(
            f"Falha ao ler a base DOU: {caminho} | {erro}"
        ) from erro


def extrair_registros_base(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [
            item
            for item in payload
            if isinstance(item, dict)
        ]

    if not isinstance(payload, dict):
        return []

    for chave in (
        "registros",
        "publicacoes",
        "base_publicacoes",
        "dados",
        "itens",
        "links",
    ):
        valor = payload.get(chave)

        if isinstance(valor, list):
            return [
                item
                for item in valor
                if isinstance(item, dict)
            ]

    return []


def chave_resultado(item: dict) -> str:
    return str(
        item.get("chave_resultado")
        or (
            f"{item.get('processo') or item.get('processo_normalizado')}|"
            f"{item.get('id_publicacao')}|"
            f"{item.get('data_publicacao')}|"
            f"{item.get('pagina')}"
        )
    )


def remover_duplicados(resultados: list[dict]) -> list[dict]:
    saida: list[dict] = []
    vistos: set[str] = set()

    for item in resultados:
        if not isinstance(item, dict):
            continue

        chave = chave_resultado(item)

        if chave in vistos:
            continue

        vistos.add(chave)
        saida.append(item)

    return saida


def simplificar_resultado(item: dict) -> dict:
    return {
        "fonte": "DOU_INLABS",
        "processo": (
            item.get("processo")
            or item.get("processo_formatado")
            or item.get("processo_normalizado")
            or ""
        ),
        "tipo_match": item.get("tipo_match") or "EXATO",
        "data": item.get("data_publicacao") or item.get("data") or "",
        "titulo": item.get("titulo") or item.get("ementa") or "",
        "orgao": item.get("orgao") or "",
        "secao": item.get("secao") or item.get("jornal") or "",
        "pagina": item.get("pagina") or "",
        "trecho": (
            item.get("trecho_encontrado")
            or item.get("trecho")
            or item.get("contexto")
            or ""
        ),
        "url": item.get("url") or item.get("link") or "",
        "arquivo": item.get("arquivo_xml") or "",
        "chave_resultado": chave_resultado(item),
    }



def executar_catchup_ativos_se_necessario(
    *,
    processos: tuple[str, ...],
    data_execucao: dt.date,
) -> tuple[list[dict], dict]:
    """
    Garante que cada processo ativo esteja coberto ate a vespera
    da data incremental que sera processada.

    Somente processos realmente atrasados entram no catch-up.
    O marco do controle nao e alterado aqui.
    """
    data_fim = data_execucao - dt.timedelta(days=1)

    inicios_por_processo = {
        processo: resolver_data_inicio_processo_pendente(
            processo
        )
        for processo in processos
    }

    processos_atrasados = tuple(
        processo
        for processo, data_inicio
        in inicios_por_processo.items()
        if data_inicio <= data_fim
    )

    if not processos_atrasados:
        return [], {
            "status": "SEM_CATCHUP_NECESSARIO",
            "data_fim": data_fim.isoformat(),
            "total_processos": 0,
            "processos": [],
            "total_datas": 0,
            "total_resultados": 0,
            "total_erros": 0,
            "processos_catchup_validados": [],
        }

    data_inicio = min(
        inicios_por_processo[processo]
        for processo in processos_atrasados
    )

    print("=" * 80)
    print("CATCH-UP AUTOMATICO DE PROCESSOS ATIVOS")
    print("=" * 80)
    print(
        f"Periodo: {data_inicio.isoformat()} "
        f"a {data_fim.isoformat()}"
    )
    print(
        f"Processos atrasados: {len(processos_atrasados)}"
    )
    print("=" * 80)

    cobertura = garantir_cobertura_dou_para_revisao(
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    resultados, pesquisa = (
        pesquisar_historico_dou_pendentes_por_faixa(
            processos=processos_atrasados,
            data_fim=data_fim,
        )
    )

    total_erros = (
        int(cobertura.get("total_erros") or 0)
        + int(pesquisa.get("total_erros") or 0)
    )

    if total_erros:
        raise RuntimeError(
            "Catch-up dos processos ativos possui pendencias "
            "tecnicas. O marco incremental nao sera avancado. "
            f"Erros: {total_erros}"
        )

    return resultados, {
        "status": "CATCHUP_VALIDADO",
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "total_processos": len(processos_atrasados),
        "processos": list(processos_atrasados),
        "total_datas": pesquisa.get("total_datas", 0),
        "total_resultados": len(resultados),
        "total_erros": 0,
        "cobertura": cobertura,
        "pesquisa": pesquisa,
        "processos_catchup_validados": list(
            processos_atrasados
        ),
    }


def salvar_resultados(
    *,
    data_execucao: dt.date,
    processos: tuple[str, ...],
    registros: list[dict],
    resultados: list[dict],
    sincronizacao: dict,
    controle_atualizado: dict,
    resumo_catchup: dict,
) -> dict:
    PASTA_POR_DATA.mkdir(parents=True, exist_ok=True)

    resultados_simplificados = [
        simplificar_resultado(item)
        for item in resultados
    ]

    resumo = {
        "status": "SUCESSO",
        "gerado_em": agora_iso(),
        "modo": "INCREMENTAL_DIARIO",
        "data_execucao": data_execucao.isoformat(),
        "base_dou": str(caminho_base_dou(data_execucao)),
        "total_processos_ativos": len(processos),
        "total_registros_base": len(registros),
        "total_resultados": len(resultados_simplificados),
        "processos": list(processos),
        "sincronizacao": {
            "processos_planilha": sincronizacao.get("processos_planilha"),
            "ativos_incrementais": sincronizacao.get("ativos_incrementais"),
            "historicos_pendentes": sincronizacao.get("historicos_pendentes"),
            "inativos": sincronizacao.get("inativos"),
            "novos": sincronizacao.get("novos", []),
            "removidos": sincronizacao.get("removidos", []),
            "reativados": sincronizacao.get("reativados", []),
        },
        "controle_incremental": controle_atualizado,
        "catchup_automatico": resumo_catchup,
    }

    salvar_json_atomico(
        caminho_resultado_json(data_execucao),
        {
            "resumo": resumo,
            "resultados": resultados_simplificados,
        },
    )

    campos = [
        "fonte",
        "processo",
        "tipo_match",
        "data",
        "titulo",
        "orgao",
        "secao",
        "pagina",
        "trecho",
        "url",
        "arquivo",
        "chave_resultado",
    ]

    with caminho_resultado_csv(data_execucao).open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=campos,
            delimiter=";",
            extrasaction="ignore",
        )
        escritor.writeheader()
        escritor.writerows(resultados_simplificados)

    linhas = [
        "=" * 80,
        "PESQUISA INCREMENTAL DIÁRIA DE PROCESSOS — DOU — 2026",
        "=" * 80,
        f"Status: {resumo['status']}",
        f"Data pesquisada: {data_execucao.isoformat()}",
        f"Processos ativos pesquisados: {len(processos)}",
        f"Registros da base diária: {len(registros)}",
        f"Resultados encontrados: {len(resultados_simplificados)}",
        (
            "Datas de catch-up pesquisadas: "
            f"{resumo_catchup.get('total_datas', 0)}"
        ),
        (
            "INLABS no catch-up: somente quando existir "
            "lacuna de cobertura."
        ),
        "Pesquisa Anvisa realizada por este runner: NÃO",
        "-" * 80,
        f"JSON: {caminho_resultado_json(data_execucao)}",
        f"CSV: {caminho_resultado_csv(data_execucao)}",
        f"TXT: {caminho_resultado_txt(data_execucao)}",
        "=" * 80,
    ]

    caminho_resultado_txt(data_execucao).write_text(
        "\n".join(linhas),
        encoding="utf-8",
    )

    return resumo


def validar_data(data_execucao: dt.date) -> None:
    if data_execucao.year != 2026:
        raise ValueError(
            "Este runner foi criado exclusivamente para 2026."
        )

    if data_execucao > dt.date.today():
        raise ValueError(
            "A data de execução não pode ser futura."
        )


def executar(data_execucao: dt.date) -> dict:
    validar_data(data_execucao)

    print("=" * 80)
    print("PESQUISA INCREMENTAL DIARIA DE PROCESSOS - DOU - 2026")
    print("=" * 80)
    print(f"Data: {data_execucao.isoformat()}")
    print(
        "Regra: catch-up automatico ate a vespera "
        "antes da pesquisa da data corrente."
    )
    print(
        "INLABS: somente para preencher lacunas "
        "de cobertura detectadas no catch-up."
    )
    print("Pesquisa Anvisa nesta etapa: 0")
    print("=" * 80)

    sincronizacao = sincronizar_com_planilha()

    pendentes = int(
        sincronizacao.get("historicos_pendentes") or 0
    )

    if pendentes > 0:
        raise RuntimeError(
            "Existem processos com revisao historica pendente. "
            "Execute primeiro o runner de sincronizacao historica. "
            f"Pendentes: {pendentes}"
        )

    processos = tuple(obter_processos_ativos_incrementais())

    if not processos:
        raise RuntimeError(
            "Nenhum processo ativo incremental foi encontrado."
        )

    caminho_base = caminho_base_dou(data_execucao)
    payload_base = carregar_json(caminho_base)
    registros = extrair_registros_base(payload_base)

    if not registros:
        status_busca = ""

        if isinstance(payload_base, dict):
            status_busca = str(
                payload_base.get("status_busca")
                or payload_base.get("status")
                or ""
            ).upper()

        if status_busca not in {
            "SEM_PUBLICACOES",
            "SEM_PUBLICACOES_CONFIRMADO",
        }:
            raise RuntimeError(
                "A base diaria foi encontrada, mas nao contem "
                "registros nem indicacao confirmada de ausencia "
                "de publicacoes. "
                f"Base: {caminho_base}"
            )

    resultados_catchup, resumo_catchup = (
        executar_catchup_ativos_se_necessario(
            processos=processos,
            data_execucao=data_execucao,
        )
    )

    print(f"Processos ativos: {len(processos)}")
    print(f"Registros na base diaria: {len(registros)}")
    print(
        "Processos com catch-up: "
        f"{resumo_catchup.get('total_processos', 0)}"
    )
    print("=" * 80)

    resultados_dia = pesquisar_processos_nos_registros(
        registros=registros,
        processos=processos,
    )

    resultados = remover_duplicados(
        list(resultados_catchup) + list(resultados_dia)
    )

    processos_catchup_validados = (
        resumo_catchup.get(
            "processos_catchup_validados",
            [],
        )
        or []
    )

    # O controle avanca uma unica vez, somente depois de:
    # 1. catch-up sem erro;
    # 2. pesquisa da data corrente sem erro.
    controle_atualizado = registrar_execucao_incremental(
        processos=processos,
        data_dou_processada=data_execucao.isoformat(),
        processos_catchup_validados=(
            processos_catchup_validados
        ),
    )

    resumo = salvar_resultados(
        data_execucao=data_execucao,
        processos=processos,
        registros=registros,
        resultados=resultados,
        sincronizacao=sincronizacao,
        controle_atualizado=controle_atualizado,
        resumo_catchup=resumo_catchup,
    )

    print("=" * 80)
    print("PESQUISA INCREMENTAL DIARIA CONCLUIDA")
    print("=" * 80)
    print(f"Status: {resumo['status']}")
    print(f"Data pesquisada: {resumo['data_execucao']}")
    print(
        "Processos ativos pesquisados: "
        f"{resumo['total_processos_ativos']}"
    )
    print(
        "Registros da base diaria: "
        f"{resumo['total_registros_base']}"
    )
    print(
        "Datas de catch-up pesquisadas: "
        f"{resumo_catchup.get('total_datas', 0)}"
    )
    print(
        "Processos com catch-up validado: "
        f"{len(processos_catchup_validados)}"
    )
    print(f"Resultados encontrados: {resumo['total_resultados']}")
    print(
        "INLABS no catch-up: somente quando existir "
        "lacuna de cobertura."
    )
    print("Pesquisa Anvisa por este runner: NAO")
    print(f"JSON: {caminho_resultado_json(data_execucao)}")
    print(f"CSV: {caminho_resultado_csv(data_execucao)}")
    print(f"TXT: {caminho_resultado_txt(data_execucao)}")
    print("=" * 80)

    return resumo

def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pesquisa os processos ativos somente na base DOU "
            "da data informada."
        )
    )

    parser.add_argument(
        "--data",
        type=converter_data,
        default=dt.date.today(),
        help="Data no formato AAAA-MM-DD. Padrão: hoje.",
    )

    return parser


def main() -> None:
    parser = montar_parser()
    args = parser.parse_args()
    executar(args.data)


if __name__ == "__main__":
    main()
