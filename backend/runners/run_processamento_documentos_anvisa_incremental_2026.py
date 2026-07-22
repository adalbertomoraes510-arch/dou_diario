# -*- coding: utf-8 -*-
"""
Runner isolado — processamento incremental de documentos Anvisa/Dicol — 2026.

Objetivo desta etapa:
- selecionar somente documentos com status NOVO_PENDENTE;
- pesquisar somente os processos ATIVO_INCREMENTAL;
- baixar e processar apenas os documentos novos;
- reutilizar OCR quando aplicável;
- manter documento pendente quando ocorrer erro, permitindo nova tentativa;
- não pesquisar novamente os 22 documentos do baseline;
- não pesquisar o DOU;
- não enviar e-mail.

Este runner não substitui o fluxo oficial. Ele valida isoladamente o
processamento incremental antes da integração ao orquestrador diário.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import traceback
from pathlib import Path
from typing import Any

import backend.runners.run_pesquisa_processos_dou_2026 as runner_anual

from backend.services.controle_documentos_anvisa_service import (
    CAMINHO_CONTROLE_INCREMENTAL,
    STATUS_NOVO_PENDENTE,
    STATUS_PROCESSADO_INCREMENTAL,
    carregar_json,
    montar_resumo,
    salvar_json_atomico,
)
from backend.services.controle_monitoramento_processos_service import (
    obter_processos_ativos_incrementais,
    obter_processos_historicos_pendentes,
    sincronizar_com_planilha,
)


ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_SAIDA = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
    / "anvisa_incremental"
)

PASTA_POR_DATA = PASTA_SAIDA / "por_data"
PASTA_LOGS = PASTA_SAIDA / "logs"


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def hoje_iso() -> str:
    return dt.date.today().isoformat()


def caminho_resultado_json(data_execucao: str) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_anvisa_incremental_{data_execucao}.json"
    )


def caminho_resultado_csv(data_execucao: str) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_anvisa_incremental_{data_execucao}.csv"
    )


def caminho_resultado_txt(data_execucao: str) -> Path:
    return (
        PASTA_POR_DATA
        / f"resultado_processos_anvisa_incremental_{data_execucao}_resumo.txt"
    )


def caminho_status_execucao(data_execucao: str) -> Path:
    return (
        PASTA_LOGS
        / f"status_processamento_anvisa_incremental_{data_execucao}.json"
    )


def calcular_sha256(caminho: Path) -> str:
    hash_obj = hashlib.sha256()

    with caminho.open("rb") as arquivo:
        while True:
            bloco = arquivo.read(1024 * 1024)

            if not bloco:
                break

            hash_obj.update(bloco)

    return hash_obj.hexdigest()


def selecionar_documentos_pendentes(
    controle: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    documentos = controle.get("documentos", {})

    if not isinstance(documentos, dict):
        raise RuntimeError(
            "O campo 'documentos' do controle incremental possui "
            "formato inválido."
        )

    pendentes: list[tuple[str, dict[str, Any]]] = []

    for chave, registro in documentos.items():
        if not isinstance(registro, dict):
            continue

        if str(registro.get("status") or "") != STATUS_NOVO_PENDENTE:
            continue

        if bool(registro.get("processado")):
            continue

        pendentes.append((str(chave), registro))

    pendentes.sort(
        key=lambda item: (
            str(item[1].get("fonte") or ""),
            str(item[1].get("titulo") or ""),
            str(item[1].get("url_pdf") or ""),
        )
    )

    return pendentes


def montar_documento_runner(registro: dict[str, Any]) -> dict[str, Any]:
    return {
        "fonte": str(registro.get("fonte") or "").strip(),
        "titulo": str(registro.get("titulo") or "").strip(),
        "url_item": str(registro.get("url_item") or "").strip(),
        "url_pdf": str(registro.get("url_pdf") or "").strip(),
    }


def simplificar_resultado(
    item: dict[str, Any],
    *,
    processado_em: str,
) -> dict[str, Any]:
    return {
        "fonte": str(item.get("fonte") or ""),
        "processo": str(item.get("processo") or ""),
        "tipo_match": str(item.get("tipo_match") or ""),
        "data": hoje_iso(),
        "titulo": str(item.get("titulo") or ""),
        "orgao": "ANVISA — Diretoria Colegiada",
        "pagina": item.get("pagina_pdf") or "",
        "valor_encontrado": str(item.get("valor_encontrado") or ""),
        "trecho": str(item.get("trecho") or ""),
        "url_item": str(item.get("url_item") or ""),
        "url_pdf": str(item.get("url_pdf") or ""),
        "arquivo_pdf": str(item.get("arquivo_pdf") or ""),
        "origem_texto": str(item.get("origem_texto") or "EXTRACAO_PDF"),
        "chave_resultado": str(item.get("chave_resultado") or ""),
        "processado_em": processado_em,
    }


def remover_resultados_duplicados(
    resultados: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for item in resultados:
        chave = str(
            item.get("chave_resultado")
            or (
                f"{item.get('processo')}|"
                f"{item.get('url_pdf')}|"
                f"{item.get('pagina')}|"
                f"{item.get('valor_encontrado')}"
            )
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        saida.append(item)

    return saida


def salvar_resultados(
    *,
    data_execucao: str,
    processos: tuple[str, ...],
    documentos_pendentes_iniciais: int,
    documentos_processados: list[dict[str, Any]],
    documentos_com_erro: list[dict[str, Any]],
    resultados: list[dict[str, Any]],
    controle: dict[str, Any],
) -> dict[str, Any]:
    PASTA_POR_DATA.mkdir(parents=True, exist_ok=True)
    PASTA_LOGS.mkdir(parents=True, exist_ok=True)

    resultados = remover_resultados_duplicados(resultados)

    status = (
        "SUCESSO"
        if not documentos_com_erro
        else "CONCLUIDO_COM_PENDENCIAS"
    )

    resumo = {
        "status": status,
        "gerado_em": agora_iso(),
        "modo": "ANVISA_INCREMENTAL",
        "data_execucao": data_execucao,
        "total_processos_ativos": len(processos),
        "documentos_pendentes_iniciais": documentos_pendentes_iniciais,
        "documentos_processados": len(documentos_processados),
        "documentos_com_erro": len(documentos_com_erro),
        "total_resultados": len(resultados),
        "processos": list(processos),
        "controle_documentos": montar_resumo(controle),
        "documentos_processados_detalhes": documentos_processados,
        "erros": documentos_com_erro,
    }

    payload = {
        "resumo": resumo,
        "resultados": resultados,
    }

    salvar_json_atomico(
        caminho_resultado_json(data_execucao),
        payload,
    )
    salvar_json_atomico(
        caminho_status_execucao(data_execucao),
        resumo,
    )

    campos = [
        "fonte",
        "processo",
        "tipo_match",
        "data",
        "titulo",
        "orgao",
        "pagina",
        "valor_encontrado",
        "trecho",
        "url_item",
        "url_pdf",
        "arquivo_pdf",
        "origem_texto",
        "chave_resultado",
        "processado_em",
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
        escritor.writerows(resultados)

    linhas = [
        "=" * 80,
        "PROCESSAMENTO INCREMENTAL DE DOCUMENTOS ANVISA — 2026",
        "=" * 80,
        f"Status: {status}",
        f"Processos ativos pesquisados: {len(processos)}",
        (
            "Documentos novos pendentes no início: "
            f"{documentos_pendentes_iniciais}"
        ),
        f"Documentos processados: {len(documentos_processados)}",
        f"Documentos com erro: {len(documentos_com_erro)}",
        f"Resultados encontrados: {len(resultados)}",
        "Documentos do baseline reprocessados: 0",
        "Pesquisa DOU executada: NÃO",
        "Envio de e-mail: NÃO",
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


def executar() -> dict[str, Any]:
    data_execucao = hoje_iso()
    instante_inicio = agora_iso()

    print("=" * 80)
    print("PROCESSAMENTO INCREMENTAL DE DOCUMENTOS ANVISA — 2026")
    print("=" * 80)
    print("Regra: processar somente documentos NOVO_PENDENTE.")
    print("Documentos do baseline reprocessados: 0")
    print("Pesquisa DOU: NÃO")
    print("Envio de e-mail: NÃO")
    print("=" * 80)

    sincronizacao = sincronizar_com_planilha()
    historicos_pendentes = obter_processos_historicos_pendentes()

    if historicos_pendentes:
        raise RuntimeError(
            "Existem processos com revisão histórica pendente. "
            "Execute primeiro a sincronização/revisão histórica. "
            f"Pendentes: {len(historicos_pendentes)}"
        )

    processos = tuple(obter_processos_ativos_incrementais())

    if not processos:
        raise RuntimeError(
            "Nenhum processo ATIVO_INCREMENTAL foi encontrado."
        )

    controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)
    pendentes = selecionar_documentos_pendentes(controle)

    print(f"Processos ativos: {len(processos)}")
    print(f"Documentos NOVO_PENDENTE: {len(pendentes)}")
    print("=" * 80)

    if not pendentes:
        resumo = salvar_resultados(
            data_execucao=data_execucao,
            processos=processos,
            documentos_pendentes_iniciais=0,
            documentos_processados=[],
            documentos_com_erro=[],
            resultados=[],
            controle=controle,
        )
        resumo["status"] = "SEM_DOCUMENTOS_NOVOS_PENDENTES"

        salvar_json_atomico(
            caminho_status_execucao(data_execucao),
            resumo,
        )

        print("Nenhum documento novo exige processamento.")
        print("Nenhum PDF foi baixado.")
        print("Nenhum OCR foi executado.")
        print(f"Status: {caminho_status_execucao(data_execucao)}")
        print("=" * 80)

        return resumo

    runner_anual.PROCESSOS_PESQUISA = processos

    sessao = runner_anual.criar_sessao_http_anvisa()
    resultados_finais: list[dict[str, Any]] = []
    documentos_processados: list[dict[str, Any]] = []
    documentos_com_erro: list[dict[str, Any]] = []

    try:
        for indice, (chave, registro) in enumerate(
            pendentes,
            start=1,
        ):
            documento = montar_documento_runner(registro)
            processado_em = agora_iso()

            print(
                f"[{indice}/{len(pendentes)}] "
                f"{documento.get('fonte')} | "
                f"{documento.get('titulo')}"
            )

            try:
                caminho_pdf = runner_anual.baixar_pdf_anvisa(
                    sessao=sessao,
                    documento=documento,
                    forcar_download=False,
                )

                documento["_forcar_ocr"] = False

                resultados_pdf, diagnostico = (
                    runner_anual.pesquisar_processos_pdf_anvisa(
                        caminho_pdf=caminho_pdf,
                        documento=documento,
                    )
                )

                documento.pop("_forcar_ocr", None)

                hash_conteudo = calcular_sha256(caminho_pdf)

                registro["status"] = STATUS_PROCESSADO_INCREMENTAL
                registro["processado"] = True
                registro["processado_em"] = processado_em
                registro["arquivo_pdf"] = str(caminho_pdf)
                registro["arquivo_pdf_ocr"] = str(
                    documento.get("arquivo_pdf_ocr") or ""
                )
                registro["origem_arquivo"] = str(
                    documento.get("origem_arquivo") or ""
                )
                registro["status_leitura"] = str(
                    diagnostico.get("status_leitura") or ""
                )
                registro["ocr_aplicado"] = bool(
                    diagnostico.get("ocr_aplicado")
                )
                registro["hash_conteudo"] = hash_conteudo
                registro["total_resultados_incremental"] = len(
                    resultados_pdf
                )
                registro["ultimo_erro"] = None
                registro["ultima_tentativa_processamento_em"] = (
                    processado_em
                )
                registro["observacao"] = (
                    "Documento novo processado com sucesso no fluxo "
                    "incremental."
                )

                resultados_simplificados = [
                    simplificar_resultado(
                        item,
                        processado_em=processado_em,
                    )
                    for item in resultados_pdf
                ]
                resultados_finais.extend(resultados_simplificados)

                documentos_processados.append({
                    "chave_documento": chave,
                    "fonte": documento.get("fonte"),
                    "titulo": documento.get("titulo"),
                    "url_pdf": documento.get("url_pdf"),
                    "arquivo_pdf": str(caminho_pdf),
                    "status_leitura": diagnostico.get("status_leitura"),
                    "ocr_aplicado": diagnostico.get("ocr_aplicado"),
                    "resultados": len(resultados_pdf),
                    "processado_em": processado_em,
                })

            except Exception as erro:
                registro["status"] = STATUS_NOVO_PENDENTE
                registro["processado"] = False
                registro["ultima_tentativa_processamento_em"] = (
                    processado_em
                )
                registro["ultimo_erro"] = str(erro)
                registro["tentativas_processamento"] = (
                    int(registro.get("tentativas_processamento") or 0)
                    + 1
                )
                registro["observacao"] = (
                    "Falha no processamento incremental. O documento "
                    "permanece pendente para nova tentativa."
                )

                documentos_com_erro.append({
                    "chave_documento": chave,
                    "fonte": documento.get("fonte"),
                    "titulo": documento.get("titulo"),
                    "url_pdf": documento.get("url_pdf"),
                    "erro": str(erro),
                    "traceback": traceback.format_exc(),
                    "tentativa_em": processado_em,
                })

            controle["atualizado_em"] = agora_iso()
            controle["documentos"][chave] = registro
            controle["resumo"] = montar_resumo(controle)
            salvar_json_atomico(
                CAMINHO_CONTROLE_INCREMENTAL,
                controle,
            )

    finally:
        try:
            sessao.close()
        except Exception:
            pass

    controle["atualizado_em"] = agora_iso()
    controle["ultima_execucao_processamento_incremental_em"] = (
        instante_inicio
    )
    controle["resumo"] = montar_resumo(controle)
    salvar_json_atomico(
        CAMINHO_CONTROLE_INCREMENTAL,
        controle,
    )

    resumo = salvar_resultados(
        data_execucao=data_execucao,
        processos=processos,
        documentos_pendentes_iniciais=len(pendentes),
        documentos_processados=documentos_processados,
        documentos_com_erro=documentos_com_erro,
        resultados=resultados_finais,
        controle=controle,
    )

    print("=" * 80)
    print("PROCESSAMENTO INCREMENTAL ANVISA CONCLUÍDO")
    print("=" * 80)
    print(f"Status: {resumo['status']}")
    print(
        "Processos ativos pesquisados: "
        f"{resumo['total_processos_ativos']}"
    )
    print(
        "Documentos novos pendentes no início: "
        f"{resumo['documentos_pendentes_iniciais']}"
    )
    print(
        "Documentos processados: "
        f"{resumo['documentos_processados']}"
    )
    print(
        "Documentos com erro: "
        f"{resumo['documentos_com_erro']}"
    )
    print(
        "Resultados encontrados: "
        f"{resumo['total_resultados']}"
    )
    print("Documentos do baseline reprocessados: 0")
    print(f"JSON: {caminho_resultado_json(data_execucao)}")
    print(f"CSV: {caminho_resultado_csv(data_execucao)}")
    print(f"TXT: {caminho_resultado_txt(data_execucao)}")
    print("=" * 80)

    return resumo


def main() -> None:
    executar()


if __name__ == "__main__":
    main()
