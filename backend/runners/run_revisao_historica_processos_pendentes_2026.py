# -*- coding: utf-8 -*-
"""
Runner isolado — revisão histórica somente de processos pendentes — 2026.

Objetivo desta etapa:
- sincronizar a planilha com o controle incremental;
- selecionar SOMENTE processos com status NOVO_HISTORICO_PENDENTE;
- pesquisar esses processos no acervo DOU já validado no baseline;
- pesquisar esses processos em todas as atas/pautas Anvisa disponíveis;
- gerar relatório separado para validação;
- não alterar o e-mail;
- não marcar o histórico como concluído sem a opção --confirmar.

Este runner não substitui o runner oficial. Ele é usado para validar,
de forma isolada, a regra de revisão histórica de processos novos.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import Any

import backend.runners.run_pesquisa_processos_dou_2026 as runner_anual

from backend.services.base_publicacoes_service import montar_base_publicacoes
from backend.services.controle_monitoramento_processos_service import (
    CAMINHO_CONTROLE,
    carregar_json_seguro as carregar_controle,
    marcar_historico_revisado,
    obter_processos_historicos_pendentes,
    sincronizar_com_planilha,
)
from backend.services.pesquisa_processos_dou_service import (
    pesquisar_processos_nos_registros,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"
BASE_DOU_DIR = DATA_DOU_DIR / "base"

PASTA_SAIDA = (
    DATA_DOU_DIR
    / "pesquisas"
    / "processos_2026"
    / "historico_pendentes"
)

CAMINHO_JSON = PASTA_SAIDA / "resultado_historico_pendentes_2026.json"
CAMINHO_CSV = PASTA_SAIDA / "resultado_historico_pendentes_2026.csv"
CAMINHO_TXT = PASTA_SAIDA / "resultado_historico_pendentes_2026_resumo.txt"


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


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


def gerar_datas(data_inicio: dt.date, data_fim: dt.date) -> list[dt.date]:
    datas: list[dt.date] = []
    atual = data_inicio

    while atual <= data_fim:
        datas.append(atual)
        atual += dt.timedelta(days=1)

    return datas


def caminho_base_dou(data_execucao: dt.date) -> Path:
    return BASE_DOU_DIR / f"base_publicacoes_{data_execucao.isoformat()}.json"


def extrair_registros_base(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

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
            return [item for item in valor if isinstance(item, dict)]

    return []


def carregar_json_local(caminho: Path) -> Any:
    if not caminho.exists():
        return None

    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None


def montar_registros_dos_zips_sem_salvar(
    data_execucao: dt.date,
) -> list[dict]:
    publicacoes = runner_anual.carregar_publicacoes_dos_zips(data_execucao)

    publicacoes_validas = [
        item
        for item in publicacoes
        if isinstance(item, dict)
        and item.get("texto_integral")
    ]

    if not publicacoes_validas:
        return []

    payload = {
        "data": data_execucao.isoformat(),
        "fonte": "INLABS",
        "origem": "INLABS",
        "gerado_em": agora_iso(),
        "status_busca": "COM_PUBLICACOES",
        "total_publicacoes": len(publicacoes_validas),
        "total_links": len(publicacoes_validas),
        "publicacoes": publicacoes_validas,
        "links": publicacoes_validas,
    }

    return montar_base_publicacoes(payload)


def carregar_registros_dou_para_revisao(
    data_execucao: dt.date,
) -> tuple[list[dict] | None, str, str]:
    """
    Retorna:
    - registros ou None;
    - origem;
    - erro técnico, vazio quando não houver erro.
    """

    caminho_base = caminho_base_dou(data_execucao)
    payload_base = carregar_json_local(caminho_base)

    if payload_base is not None:
        registros = extrair_registros_base(payload_base)
        return registros, "BASE_DOU_EXISTENTE", ""

    resumo_local = runner_anual.carregar_resumo_download_local_reutilizavel(
        data_execucao
    )

    if not isinstance(resumo_local, dict):
        return (
            None,
            "SEM_BASE_E_SEM_COLETA_LOCAL_VALIDADA",
            (
                "Não existe base diária nem coleta local validada para "
                f"{data_execucao.isoformat()}."
            ),
        )

    status = resumo_local.get("status")

    if status == runner_anual.STATUS_SEM_PUBLICACOES:
        return [], "SEM_PUBLICACOES_CONFIRMADO", ""

    if status != runner_anual.STATUS_COLETA_OK:
        return (
            None,
            "COLETA_LOCAL_NAO_UTILIZAVEL",
            (
                f"Coleta local não utilizável em {data_execucao.isoformat()}: "
                f"status={status}"
            ),
        )

    try:
        registros = montar_registros_dos_zips_sem_salvar(data_execucao)
    except Exception as erro:
        return (
            None,
            "ERRO_LEITURA_ZIPS_LOCAIS",
            f"{data_execucao.isoformat()}: {erro}",
        )

    if not registros:
        return (
            None,
            "ZIP_VALIDO_SEM_REGISTROS",
            (
                "A coleta local foi considerada válida, mas não produziu "
                f"registros em {data_execucao.isoformat()}."
            ),
        )

    return registros, "ZIPS_LOCAIS_REUTILIZADOS", ""


def chave_resultado_dou(item: dict) -> str:
    return str(
        item.get("chave_resultado")
        or (
            f"{item.get('processo') or item.get('processo_normalizado')}|"
            f"{item.get('id_publicacao')}|"
            f"{item.get('data_publicacao')}|"
            f"{item.get('pagina')}"
        )
    )


def pesquisar_historico_dou(
    processos: tuple[str, ...],
    data_inicio: dt.date,
    data_fim: dt.date,
) -> tuple[list[dict], dict]:
    resultados: list[dict] = []
    chaves_vistas: set[str] = set()
    erros: list[dict] = []

    datas = gerar_datas(data_inicio, data_fim)
    bases_existentes = 0
    zips_reutilizados = 0
    sem_publicacoes = 0

    print("=" * 80)
    print("REVISÃO HISTÓRICA — DOU LOCAL")
    print("=" * 80)
    print(f"Processos pendentes: {len(processos)}")
    print(f"Período: {data_inicio.isoformat()} a {data_fim.isoformat()}")
    print("Regra: não baixar novamente o DOU nesta etapa.")
    print("=" * 80)

    for indice, data_execucao in enumerate(datas, start=1):
        registros, origem, erro = carregar_registros_dou_para_revisao(
            data_execucao
        )

        print(
            f"[{indice}/{len(datas)}] "
            f"{data_execucao.isoformat()} | {origem}"
        )

        if erro:
            erros.append({
                "data": data_execucao.isoformat(),
                "origem": origem,
                "erro": erro,
            })
            continue

        if origem == "BASE_DOU_EXISTENTE":
            bases_existentes += 1
        elif origem == "ZIPS_LOCAIS_REUTILIZADOS":
            zips_reutilizados += 1
        elif origem == "SEM_PUBLICACOES_CONFIRMADO":
            sem_publicacoes += 1

        resultados_data = pesquisar_processos_nos_registros(
            registros=registros or [],
            processos=processos,
        )

        for item in resultados_data:
            if not isinstance(item, dict):
                continue

            chave = chave_resultado_dou(item)

            if chave in chaves_vistas:
                continue

            chaves_vistas.add(chave)
            resultados.append(item)

    resultados.sort(
        key=lambda item: (
            item.get("data_publicacao") or "",
            item.get("processo") or item.get("processo_normalizado") or "",
            item.get("titulo") or "",
        )
    )

    resumo = {
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "total_datas": len(datas),
        "bases_existentes": bases_existentes,
        "zips_reutilizados": zips_reutilizados,
        "sem_publicacoes_confirmado": sem_publicacoes,
        "total_erros": len(erros),
        "erros": erros,
        "total_resultados": len(resultados),
    }

    return resultados, resumo


def simplificar_resultado_dou(item: dict) -> dict:
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
        "chave_resultado": chave_resultado_dou(item),
    }


def simplificar_resultado_anvisa(item: dict) -> dict:
    return {
        "fonte": item.get("fonte") or "",
        "processo": item.get("processo") or "",
        "tipo_match": item.get("tipo_match") or "",
        "data": "",
        "titulo": item.get("titulo") or "",
        "orgao": "ANVISA — Diretoria Colegiada",
        "secao": "",
        "pagina": item.get("pagina_pdf") or "",
        "trecho": item.get("trecho") or "",
        "url": item.get("url_pdf") or "",
        "arquivo": item.get("arquivo_pdf") or "",
        "chave_resultado": item.get("chave_resultado") or "",
    }


def salvar_resultado_final(
    *,
    processos: tuple[str, ...],
    resultados_dou: list[dict],
    resumo_dou: dict,
    resultados_anvisa: list[dict],
    resumo_anvisa: dict,
    confirmado: bool,
) -> dict:
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

    resultados = [
        simplificar_resultado_dou(item)
        for item in resultados_dou
    ]
    resultados.extend(
        simplificar_resultado_anvisa(item)
        for item in resultados_anvisa
    )

    resultados.sort(
        key=lambda item: (
            item.get("processo") or "",
            item.get("fonte") or "",
            item.get("data") or "",
            item.get("titulo") or "",
            str(item.get("pagina") or ""),
        )
    )

    resumo = {
        "gerado_em": agora_iso(),
        "status": (
            "SUCESSO"
            if int(resumo_dou.get("total_erros") or 0) == 0
            and int(resumo_anvisa.get("total_erros") or 0) == 0
            else "CONCLUIDO_COM_PENDENCIAS"
        ),
        "processos_pendentes_pesquisados": len(processos),
        "processos": list(processos),
        "resultados_dou": len(resultados_dou),
        "resultados_anvisa": len(resultados_anvisa),
        "total_resultados": len(resultados),
        "erros_dou": int(resumo_dou.get("total_erros") or 0),
        "erros_anvisa": int(resumo_anvisa.get("total_erros") or 0),
        "historico_confirmado_no_controle": confirmado,
        "resumo_dou": resumo_dou,
        "resumo_anvisa": resumo_anvisa,
    }

    salvar_json_atomico(
        CAMINHO_JSON,
        {
            "resumo": resumo,
            "resultados": resultados,
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

    with CAMINHO_CSV.open(
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
        escritor.writerows(resultados)

    linhas = [
        "=" * 80,
        "REVISÃO HISTÓRICA DE PROCESSOS PENDENTES — 2026",
        "=" * 80,
        f"Status: {resumo['status']}",
        f"Processos pesquisados: {len(processos)}",
        f"Resultados DOU: {len(resultados_dou)}",
        f"Resultados Anvisa: {len(resultados_anvisa)}",
        f"Total de resultados: {len(resultados)}",
        f"Erros DOU: {resumo['erros_dou']}",
        f"Erros Anvisa: {resumo['erros_anvisa']}",
        (
            "Histórico confirmado no controle: "
            f"{'SIM' if confirmado else 'NÃO'}"
        ),
        "-" * 80,
    ]

    for processo in processos:
        total_processo = sum(
            1
            for item in resultados
            if item.get("processo") == processo
        )
        linhas.append(
            f"{processo} | resultados={total_processo}"
        )

    linhas.extend([
        "-" * 80,
        f"JSON: {CAMINHO_JSON}",
        f"CSV: {CAMINHO_CSV}",
        f"TXT: {CAMINHO_TXT}",
        "=" * 80,
    ])

    CAMINHO_TXT.write_text(
        "\n".join(linhas),
        encoding="utf-8",
    )

    return resumo


def resolver_data_fim_historico() -> dt.date:
    estado = carregar_controle(CAMINHO_CONTROLE)

    valor = (
        estado.get("ultima_data_dou_validada_baseline")
        or estado.get("baseline_em")
    )

    if not valor:
        raise RuntimeError(
            "O controle não possui uma data final válida para o baseline."
        )

    return dt.date.fromisoformat(str(valor))


def executar(confirmar: bool = False) -> dict:
    sincronizacao = sincronizar_com_planilha()
    processos = tuple(obter_processos_historicos_pendentes())

    print("=" * 80)
    print("PROCESSOS PENDENTES PARA REVISÃO HISTÓRICA")
    print("=" * 80)
    print(f"Processos na planilha: {sincronizacao.get('processos_planilha')}")
    print(f"Pendentes: {len(processos)}")

    for processo in processos:
        print(f"- {processo}")

    print("=" * 80)

    if not processos:
        return {
            "status": "SEM_PROCESSOS_HISTORICOS_PENDENTES",
            "processos": [],
            "total_processos": 0,
        }

    # As funções Anvisa do runner anual usam esta variável global.
    runner_anual.PROCESSOS_PESQUISA = processos

    data_inicio = runner_anual.DATA_INICIO_COBERTURA_INLABS
    data_fim = resolver_data_fim_historico()

    resultados_dou, resumo_dou = pesquisar_historico_dou(
        processos=processos,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    try:
        resultados_anvisa, resumo_anvisa = (
            runner_anual.pesquisar_processos_anvisa_dicol(
                forcar_download=False,
            )
        )
    except Exception as erro:
        resultados_anvisa = []
        resumo_anvisa = {
            "status": "ERRO",
            "total_documentos": 0,
            "total_resultados": 0,
            "total_erros": 1,
            "erro": str(erro),
        }

    erros_totais = (
        int(resumo_dou.get("total_erros") or 0)
        + int(resumo_anvisa.get("total_erros") or 0)
    )

    confirmado = False

    if confirmar:
        if erros_totais > 0:
            raise RuntimeError(
                "A revisão histórica possui pendências técnicas. "
                "O controle não será promovido para incremental."
            )

        for processo in processos:
            marcar_historico_revisado(
                processo,
                data_revisao=dt.date.today().isoformat(),
                ultima_data_dou_processada=data_fim.isoformat(),
            )

        confirmado = True

    resumo_final = salvar_resultado_final(
        processos=processos,
        resultados_dou=resultados_dou,
        resumo_dou=resumo_dou,
        resultados_anvisa=resultados_anvisa,
        resumo_anvisa=resumo_anvisa,
        confirmado=confirmado,
    )

    print("=" * 80)
    print("REVISÃO HISTÓRICA DE PENDENTES CONCLUÍDA")
    print("=" * 80)
    print(f"Status: {resumo_final['status']}")
    print(
        "Processos pesquisados: "
        f"{resumo_final['processos_pendentes_pesquisados']}"
    )
    print(f"Resultados DOU: {resumo_final['resultados_dou']}")
    print(f"Resultados Anvisa: {resumo_final['resultados_anvisa']}")
    print(f"Total de resultados: {resumo_final['total_resultados']}")
    print(f"Erros DOU: {resumo_final['erros_dou']}")
    print(f"Erros Anvisa: {resumo_final['erros_anvisa']}")
    print(
        "Histórico confirmado no controle: "
        f"{'SIM' if confirmado else 'NÃO — aguardando validação'}"
    )
    print(f"JSON: {CAMINHO_JSON}")
    print(f"CSV: {CAMINHO_CSV}")
    print(f"TXT: {CAMINHO_TXT}")
    print("=" * 80)

    return resumo_final


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pesquisa somente os processos novos que ainda possuem "
            "revisão histórica pendente."
        )
    )

    parser.add_argument(
        "--confirmar",
        action="store_true",
        help=(
            "Após uma execução sem erros, marca os processos como "
            "histórico revisado e promove para ATIVO_INCREMENTAL."
        ),
    )

    return parser


def main() -> None:
    parser = montar_parser()
    args = parser.parse_args()
    executar(confirmar=args.confirmar)


if __name__ == "__main__":
    main()
