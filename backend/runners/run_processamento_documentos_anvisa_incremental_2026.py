# -*- coding: utf-8 -*-
"""
Runner isolado — processamento incremental de documentos Anvisa/Dicol — 2026.

Objetivo desta etapa:
- selecionar somente documentos com status NOVO_PENDENTE;
- pesquisar TODOS os processos ativos da planilha, inclusive historico pendente;
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
import os
import shutil
import sys
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
from backend.services.conciliacao_dicol_diaria_service import conciliar_dicol_diaria
from backend.services.controle_monitoramento_processos_service import (
    CAMINHO_CONTROLE as CAMINHO_CONTROLE_PROCESSOS,
    STATUS_INATIVO,
    carregar_json_seguro,
    carregar_processos_atuais,
    obter_processos_ativos_incrementais,
    obter_processos_historicos_pendentes,
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
PASTA_DIARIO_DOCUMENTOS = PASTA_SAIDA / "resultados_por_documento"


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


def validar_carteira_sem_sincronizar() -> dict[str, Any]:
    """Verifica correspondencia com a planilha, sem atualizar o cadastro.

    A sincronizacao efetiva (novos, inativos e reativados) e uma operacao
    independente e deve ser revisada antes de processar PDFs.
    """
    cadastro = carregar_json_seguro(CAMINHO_CONTROLE_PROCESSOS)
    registrados = cadastro.get("processos", {})
    if not isinstance(registrados, dict):
        raise RuntimeError("Cadastro de processos: estrutura invalida")
    atuais = tuple(carregar_processos_atuais())
    if not atuais:
        raise RuntimeError("Planilha PROCESSOS vazia; processamento bloqueado")
    ativos = {
        str(processo)
        for processo, registro in registrados.items()
        if isinstance(registro, dict)
        and str(registro.get("status") or "") != STATUS_INATIVO
        and bool(registro.get("ativo", True))
    }
    planilha = set(atuais)
    if planilha != ativos:
        diferencas = {
            "novos_na_planilha": sorted(planilha - ativos),
            "ausentes_na_planilha": sorted(ativos - planilha),
        }
        raise RuntimeError(
            "ABORTADO: planilha e carteira de monitoramento divergentes. "
            "Nao houve sincronizacao automatica: "
            + json.dumps(diferencas, ensure_ascii=False)
        )
    return {"status": "CONFERIDO_SOMENTE_LEITURA", "total": len(ativos)}


def validar_diagnostico_pdf(diagnostico: dict[str, Any]) -> None:
    """Nunca marcar sucesso sem texto pesquisavel e cobertura integral."""
    if not isinstance(diagnostico, dict):
        raise RuntimeError("Diagnostico PDF inexistente/invalido")
    estado = str(diagnostico.get("status_leitura") or "")
    if estado not in {"TEXTO_EXTRAIDO", "TEXTO_EXTRAIDO_OCR"}:
        raise RuntimeError(
            "PDF sem texto pesquisavel confirmado; OCR pendente ou falhou: "
            f"status_leitura={estado!r}; "
            f"ocr_erro={diagnostico.get('ocr_erro')!r}"
        )
    if str(diagnostico.get("ocr_status") or "").upper() == "ERRO":
        raise RuntimeError("OCR falhou: " + str(diagnostico.get("ocr_erro") or ""))
    total = int(diagnostico.get("total_paginas") or 0)
    com_texto = int(diagnostico.get("paginas_com_texto") or 0)
    erros = int(diagnostico.get("erros_paginas") or 0)
    caracteres = int(diagnostico.get("caracteres_extraidos") or 0)
    if total <= 0 or com_texto < total or erros > 0 or caracteres <= 0:
        raise RuntimeError(
            "Cobertura do texto PDF incompleta; manter pendente: "
            f"paginas_com_texto={com_texto}/{total}; "
            f"erros_paginas={erros}; caracteres={caracteres}"
        )


def caminho_diario_documento(chave: str) -> Path:
    if len(chave) != 64 or any(c not in "0123456789abcdef" for c in chave.lower()):
        raise ValueError("Chave de documento nao e SHA-256")
    return PASTA_DIARIO_DOCUMENTOS / (chave.lower() + ".json")


def criar_backup_controle() -> Path:
    """Backup identico do controle imediatamente antes de alterar status."""
    origem = CAMINHO_CONTROLE_INCREMENTAL
    instante = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = origem.with_name(origem.name + ".backup_pre_processamento_seguro_" + instante)
    if destino.exists():
        raise RuntimeError("Backup ja existente: " + str(destino))
    shutil.copy2(origem, destino)
    if calcular_sha256(origem) != calcular_sha256(destino):
        raise RuntimeError("Backup diverge do controle; abortado")
    print("[ANVISA] Backup validado:", destino)
    return destino


def carregar_resultado_existente(data_execucao: str) -> dict[str, Any]:
    caminho = caminho_resultado_json(data_execucao)
    if not caminho.exists():
        return {"resultados": [], "resumo": {}}
    anterior = carregar_json(caminho)
    if not isinstance(anterior.get("resultados"), list):
        raise RuntimeError("Relatorio diario existente invalido; nao sobrescrever")
    if not isinstance(anterior.get("resumo"), dict):
        raise RuntimeError("Resumo diario existente invalido; nao sobrescrever")
    return anterior


def recuperar_diarios_processados(controle: dict[str, Any], data_execucao: str):
    """Recupera resultados em disco apos interrupcao, sem reler PDFs."""
    resultados = []
    detalhes = []
    for chave, registro in controle.get("documentos", {}).items():
        if not isinstance(registro, dict):
            continue
        if registro.get("status") != STATUS_PROCESSADO_INCREMENTAL:
            continue
        if not str(registro.get("processado_em") or "").startswith(data_execucao):
            continue
        caminho = caminho_diario_documento(str(chave))
        if not caminho.exists():
            if registro.get("resultado_journal"):
                raise RuntimeError("Registro processado sem seu diario duravel: " + str(chave))
            continue  # registros antigos, anteriores a esta correcao
        bruto = carregar_json(caminho)
        if bruto.get("chave_documento") != chave:
            raise RuntimeError("Diario de documento com chave inconsistente: " + str(chave))
        itens = bruto.get("resultados")
        detalhe = bruto.get("documento_processado")
        if not isinstance(itens, list) or not isinstance(detalhe, dict):
            raise RuntimeError("Diario de documento invalido: " + str(chave))
        resultados.extend(itens)
        detalhes.append(detalhe)
    return resultados, detalhes


def unificar_detalhes(detalhes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vistos = {}
    for item in detalhes:
        chave = str(item.get("chave_documento") or "")
        if not chave:
            raise RuntimeError("Detalhe do processamento sem chave_documento")
        vistos[chave] = item
    return list(vistos.values())


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

    anterior = carregar_resultado_existente(data_execucao)
    journal_resultados, journal_detalhes = recuperar_diarios_processados(
        controle, data_execucao
    )
    resultados = remover_resultados_duplicados(
        list(anterior["resultados"]) + journal_resultados + resultados
    )
    detalhes_anteriores = anterior["resumo"].get("documentos_processados_detalhes", [])
    if not isinstance(detalhes_anteriores, list):
        raise RuntimeError("Detalhes de relatorio anterior invalidos")
    documentos_processados = unificar_detalhes(
        detalhes_anteriores + journal_detalhes + documentos_processados
    )
    # Falhas superadas nao devem manter status de pendencia indefinidamente.
    erros_anteriores = anterior["resumo"].get("erros", [])
    if not isinstance(erros_anteriores, list):
        raise RuntimeError("Erros anteriores invalidos")
    chaves_processadas = {x["chave_documento"] for x in documentos_processados}
    erros_combinados = {}
    for item in erros_anteriores + documentos_com_erro:
        chave = str(item.get("chave_documento") or "")
        if chave and chave not in chaves_processadas:
            erros_combinados[chave] = item
    documentos_com_erro = list(erros_combinados.values())

    status = (
        "CONCLUIDO_COM_PENDENCIAS"
        if documentos_com_erro
        else "SEM_DOCUMENTOS_NOVOS_PENDENTES"
        if documentos_pendentes_iniciais == 0
        else "SUCESSO"
    )

    resumo = {
        "status": status,
        "gerado_em": agora_iso(),
        "modo": "ANVISA_INCREMENTAL",
        "data_execucao": data_execucao,
        "total_processos_ativos": len(processos),
        "processos_elegiveis": list(processos),
        "comprovacao_individual": "VERIFICAR_PROCESSOS_PESQUISADOS_EM_CADA_DIARIO_DE_DOCUMENTO",
        "cobertura_individual_consolidada": False,
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

    destino_csv = caminho_resultado_csv(data_execucao)
    temporario_csv = destino_csv.with_suffix(destino_csv.suffix + ".tmp")
    with temporario_csv.open(
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
    os.replace(temporario_csv, destino_csv)

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

    destino_txt = caminho_resultado_txt(data_execucao)
    temporario_txt = destino_txt.with_suffix(destino_txt.suffix + ".tmp")
    temporario_txt.write_text("\n".join(linhas), encoding="utf-8")
    os.replace(temporario_txt, destino_txt)

    salvar_json_atomico(caminho_status_execucao(data_execucao), resumo)
    return resumo


def executar() -> dict[str, Any]:
    data_execucao = hoje_iso()
    instante_inicio = agora_iso()

    print("=" * 80)
    print("PROCESSAMENTO INCREMENTAL DE DOCUMENTOS ANVISA — 2026")
    print("=" * 80)
    print("Regra: processar documentos NOVO_PENDENTE para TODA a planilha.")
    print("Carteira de processos: SOMENTE LEITURA (sem sincronizacao automatica)")
    print("Confiabilidade PDF: falha OCR/cobertura incompleta mantem pendente")
    print("Resultados: diarios por documento antes de marcar processado")
    print("Documentos do baseline reprocessados: 0")
    print("Pesquisa DOU: NÃO")
    print("Envio de e-mail: NÃO")
    print("=" * 80)

    conferencia = validar_carteira_sem_sincronizar()
    print("[ANVISA] Carteira conferida sem sincronizacao/gravar:", conferencia["total"])
    # Nao permitir sobrescrever um relatorio diario danificado.
    carregar_resultado_existente(data_execucao)
    historicos_pendentes = obter_processos_historicos_pendentes()

    if historicos_pendentes:
        print(
            f"[ANVISA] {len(historicos_pendentes)} processo(s) aguardam "
            "revisao historica, MAS participam da pesquisa incremental. "
            "O status historico nao sera alterado."
        )

    # A correspondencia entre planilha e carteira foi conferida acima.
    # O status de revisao historica NAO filtra a pesquisa de documentos novos.
    processos = tuple(carregar_processos_atuais())
    if not processos:
        raise RuntimeError("Planilha PROCESSOS vazia; processamento bloqueado")

    controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)
    pendentes = selecionar_documentos_pendentes(controle)

    print(f"Processos elegiveis dos PDFs novos: {len(processos)}")
    print(f"Documentos NOVO_PENDENTE: {len(pendentes)}")
    print("=" * 80)

    if not pendentes:
        # Importante: uma execucao sem documentos novos NAO comprova a
        # pesquisa de 36 processos em PDFs antigos. Nao sobrescrever o
        # relatorio do dia (que pode registrar apenas 31 processos).
        anterior = caminho_resultado_json(data_execucao).is_file()
        resumo = {
            "status": "SEM_DOCUMENTOS_NOVOS_PENDENTES",
            "data_execucao": data_execucao,
            "processos_elegiveis": len(processos),
            "total_processos_ativos": len(processos),
            "documentos_pendentes_iniciais": 0,
            "documentos_processados": 0,
            "documentos_com_erro": 0,
            "total_resultados": 0,
            "relatorio_anterior_preservado": anterior,
            "pesquisa_individual_comprovada_nesta_execucao": False,
        }
        print("Nenhum documento novo exige processamento.")
        print("Nenhuma pesquisa de processo foi executada nesta chamada.")
        print("Relatorios anteriores preservados: ", anterior)
        resumo["controle_diario"] = conciliar_dicol_diaria(
            data=data_execucao, processos=processos, controle=controle
        )
        print("Conciliacao diaria DICOL:", resumo["controle_diario"]["status"])
        print("Nenhum PDF foi baixado e nenhum OCR foi executado.")
        print("=" * 80)
        return resumo

    if not controle.get("baseline_inicializado"):
        raise RuntimeError("Baseline ANVISA nao inicializado")
    criar_backup_controle()

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
                validar_diagnostico_pdf(diagnostico)
                hash_conteudo = calcular_sha256(caminho_pdf)

                resultados_simplificados = [
                    simplificar_resultado(item, processado_em=processado_em)
                    for item in resultados_pdf
                ]
                detalhe = {
                    "chave_documento": chave,
                    "fonte": documento.get("fonte"),
                    "titulo": documento.get("titulo"),
                    "url_pdf": documento.get("url_pdf"),
                    "arquivo_pdf": str(caminho_pdf),
                    "status_leitura": diagnostico.get("status_leitura"),
                    "ocr_aplicado": diagnostico.get("ocr_aplicado"),
                    "resultados": len(resultados_pdf),
                    "processado_em": processado_em,
                }
                journal = caminho_diario_documento(chave)
                salvar_json_atomico(journal, {
                    "chave_documento": chave,
                    "hash_conteudo": hash_conteudo,
                    "processos_pesquisados": list(processos),
                    "diagnostico_pdf": diagnostico,
                    "documento_processado": detalhe,
                    "resultados": resultados_simplificados,
                })
                # Somente marcar PROCESSADO apos guardar os resultados duravelmente.
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
                registro["ocr_aplicado"] = bool(diagnostico.get("ocr_aplicado"))
                registro["hash_conteudo"] = hash_conteudo
                registro["total_resultados_incremental"] = len(resultados_pdf)
                registro["resultado_journal"] = str(journal)
                registro["ultimo_erro"] = None
                registro["ultima_tentativa_processamento_em"] = processado_em
                registro["observacao"] = (
                    "Documento processado com texto pesquisavel, "
                    "resultados registrados em diario duravel."
                )
                resultados_finais.extend(resultados_simplificados)
                documentos_processados.append(detalhe)

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
    resumo["controle_diario"] = conciliar_dicol_diaria(
        data=data_execucao, processos=processos, controle=controle
    )
    print("Conciliacao diaria DICOL:", resumo["controle_diario"]["status"])
    print("Documentos do baseline reprocessados: 0")
    print(f"JSON: {caminho_resultado_json(data_execucao)}")
    print(f"CSV: {caminho_resultado_csv(data_execucao)}")
    print(f"TXT: {caminho_resultado_txt(data_execucao)}")
    print("=" * 80)

    return resumo


def executar_preflight() -> None:
    """Diagnostico de processamento, totalmente sem gravacao."""
    carteira = validar_carteira_sem_sincronizar()
    controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)
    if not controle.get("baseline_inicializado"):
        raise RuntimeError("Baseline ANVISA nao inicializado")
    registros = controle.get("documentos", {})
    if not isinstance(registros, dict):
        raise RuntimeError("Controle de documentos invalido")
    pendentes = selecionar_documentos_pendentes(controle)
    relatorio = carregar_resultado_existente(hoje_iso())
    historicos = [x for x in registros.values() if isinstance(x, dict) and x.get("baseline")]
    print("========== PREFLIGHT ANVISA PROCESSAMENTO SEGURO ==========")
    print("BASELINE:", controle.get("baseline_em"))
    print("REGISTROS NO CONTROLE:", len(registros))
    print("REGISTROS HISTORICOS (baseline=True):", len(historicos))
    print("NOVO_PENDENTE PARA PROCESSAR:", len(pendentes))
    print("PROCESSOS NA CARTEIRA (conferidos sem alterar):", carteira["total"])
    print("PROCESSOS ATIVO_INCREMENTAL:", len(obter_processos_ativos_incrementais()))
    print("PROCESSOS HISTORICOS PENDENTES:", len(obter_processos_historicos_pendentes()))
    processos_planilha = tuple(carregar_processos_atuais())
    print("PROCESSOS ELEGIVEIS PROXIMOS PDFS:", len(processos_planilha))
    # Conferencia diagnostica de diarios anteriores. NAO reprocessa PDFs.
    faltas = {}
    completos_verificaveis = 0
    for chave, registro in registros.items():
        if not isinstance(registro, dict):
            continue
        if registro.get("status") != STATUS_PROCESSADO_INCREMENTAL:
            continue
        journal = registro.get("resultado_journal")
        if not journal:
            continue
        caminho = Path(journal)
        if not caminho.is_file():
            raise RuntimeError("Diario declarado, mas ausente: " + str(caminho))
        arquivo = carregar_json(caminho)
        if arquivo.get("chave_documento") != chave:
            raise RuntimeError("Diario com chave divergente: " + str(chave))
        pesquisados = arquivo.get("processos_pesquisados")
        if not isinstance(pesquisados, list):
            raise RuntimeError("Diario sem processos_pesquisados: " + str(chave))
        ausentes = sorted(set(processos_planilha) - set(pesquisados))
        if ausentes:
            faltas[chave] = ausentes
        else:
            completos_verificaveis += 1
    print("DOCUMENTOS COM DIARIO E COBERTURA DE 36:", completos_verificaveis)
    print("DOCUMENTOS COM DIARIO SEM COBERTURA DE TODOS:", len(faltas))
    print("PROCESSOS AINDA AUSENTES DESSES DIARIOS:",
          len(set(x for grupo in faltas.values() for x in grupo)))
    print("NOTA: esta etapa NAO refaz PDFs anteriores e NAO conclui historicos.")
    print("RESULTADOS JA GUARDADOS HOJE:", len(relatorio["resultados"]))
    print("STATUS: SOMENTE LEITURA; nenhum PDF ou controle alterado")
    print("===========================================================")


def main() -> None:
    if sys.argv[1:]:
        if sys.argv[1:] == ["--preflight"]:
            executar_preflight()
        elif sys.argv[1:] == ["--conciliar-diario"]:
            validar_carteira_sem_sincronizar()
            processos = tuple(carregar_processos_atuais())
            controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)
            resumo = conciliar_dicol_diaria(
                data=hoje_iso(), processos=processos, controle=controle
            )
            print("CONCILIACAO DIARIA DICOL:", resumo)
            print("SEM REPROCESSAMENTO DE PDFs / SEM INTERNET / SEM OCR")
        else:
            raise SystemExit("Opcao nao reconhecida; use --preflight ou --conciliar-diario")
    else:
        executar()


if __name__ == "__main__":
    main()
