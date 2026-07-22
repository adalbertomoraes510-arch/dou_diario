# -*- coding: utf-8 -*-
"""
Runner isolado — descoberta incremental de documentos Anvisa/Dicol — 2026.

Objetivo desta etapa:
- consultar somente as páginas públicas de Atas e Pautas da Dicol/Anvisa;
- descobrir os PDFs atualmente publicados;
- comparar com o baseline incremental já criado;
- registrar somente documentos realmente novos como NOVO_PENDENTE;
- não baixar PDFs;
- não executar OCR;
- não pesquisar processos;
- não enviar e-mail.

Este runner não substitui o fluxo oficial. Ele valida isoladamente a
descoberta incremental antes da integração ao orquestrador diário.
"""

from __future__ import annotations

import datetime as dt
import json
import traceback
from pathlib import Path
from typing import Any

import backend.runners.run_pesquisa_processos_dou_2026 as runner_anual

from backend.services.controle_documentos_anvisa_service import (
    CAMINHO_CONTROLE_INCREMENTAL,
    STATUS_NOVO_PENDENTE,
    chave_documento,
    carregar_json,
    montar_resumo,
    normalizar_url,
    salvar_json_atomico,
)


ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_LOGS = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
    / "anvisa_incremental"
    / "logs"
)

CAMINHO_ULTIMO_STATUS = (
    PASTA_LOGS
    / "ultima_descoberta_documentos_anvisa_2026.json"
)


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def salvar_status(payload: dict[str, Any]) -> None:
    salvar_json_atomico(CAMINHO_ULTIMO_STATUS, payload)


def novo_registro_pendente(
    documento: dict[str, Any],
    *,
    instante: str,
) -> dict[str, Any]:
    url_pdf = normalizar_url(documento.get("url_pdf"))
    chave = chave_documento(url_pdf)

    return {
        "chave_documento": chave,
        "url_pdf": url_pdf,
        "url_item": normalizar_url(documento.get("url_item")),
        "fonte": str(documento.get("fonte") or "").strip(),
        "titulo": str(documento.get("titulo") or "").strip(),
        "status": STATUS_NOVO_PENDENTE,
        "processado": False,
        "baseline": False,
        "baseline_em": None,
        "primeira_identificacao_em": instante,
        "ultima_identificacao_em": instante,
        "processado_em": None,
        "arquivo_pdf": "",
        "arquivo_pdf_ocr": "",
        "origem_arquivo": "",
        "status_leitura": "",
        "ocr_aplicado": False,
        "total_resultados_baseline": 0,
        "hash_conteudo": None,
        "ultima_verificacao_remota_em": instante,
        "observacao": (
            "Documento novo identificado na descoberta incremental. "
            "Download, leitura e pesquisa ainda não executados."
        ),
    }


def descobrir_documentos_remotos() -> tuple[list[dict], list[dict]]:
    sessao = runner_anual.criar_sessao_http_anvisa()
    documentos: list[dict] = []
    erros: list[dict] = []

    try:
        for nome_fonte, url_raiz in runner_anual.ANVISA_FONTES.items():
            try:
                encontrados = runner_anual.descobrir_pdfs_fonte_anvisa(
                    sessao=sessao,
                    nome_fonte=nome_fonte,
                    url_raiz=url_raiz,
                )
                documentos.extend(encontrados)
            except Exception as erro:
                erros.append({
                    "fonte": nome_fonte,
                    "url_raiz": url_raiz,
                    "etapa": "DESCOBERTA_DOCUMENTOS",
                    "erro": str(erro),
                })
    finally:
        try:
            sessao.close()
        except Exception:
            pass

    unicos: dict[str, dict] = {}

    for documento in documentos:
        url_pdf = normalizar_url(documento.get("url_pdf"))

        if not url_pdf:
            continue

        chave = chave_documento(url_pdf)

        if chave not in unicos:
            documento = dict(documento)
            documento["url_pdf"] = url_pdf
            documento["url_item"] = normalizar_url(
                documento.get("url_item")
            )
            unicos[chave] = documento

    documentos_unicos = sorted(
        unicos.values(),
        key=lambda item: (
            str(item.get("fonte") or ""),
            str(item.get("titulo") or ""),
            str(item.get("url_pdf") or ""),
        ),
    )

    return documentos_unicos, erros


def executar() -> dict[str, Any]:
    print("=" * 80)
    print("DESCOBERTA INCREMENTAL DE DOCUMENTOS ANVISA — 2026")
    print("=" * 80)
    print("Ação: consultar páginas de Atas e Pautas.")
    print("Download de PDFs: NÃO")
    print("OCR: NÃO")
    print("Pesquisa de processos: NÃO")
    print("Envio de e-mail: NÃO")
    print("=" * 80)

    controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)
    registros = controle.get("documentos", {})

    if not isinstance(registros, dict):
        raise RuntimeError(
            "O campo 'documentos' do controle incremental possui "
            "formato inválido."
        )

    instante = agora_iso()

    try:
        documentos_remotos, erros = descobrir_documentos_remotos()
    except Exception as erro:
        resultado_erro = {
            "status": "ERRO",
            "gerado_em": instante,
            "erro": str(erro),
            "traceback": traceback.format_exc(),
            "controle": str(CAMINHO_CONTROLE_INCREMENTAL),
        }
        salvar_status(resultado_erro)
        raise

    novos: list[dict] = []
    conhecidos: list[dict] = []

    for documento in documentos_remotos:
        url_pdf = normalizar_url(documento.get("url_pdf"))
        chave = chave_documento(url_pdf)
        registro = registros.get(chave)

        if isinstance(registro, dict):
            registro["ultima_identificacao_em"] = instante
            registro["ultima_verificacao_remota_em"] = instante

            # Preserva os dados históricos, mas atualiza metadados públicos
            # quando a página apresentar título ou URL de item mais completos.
            titulo_atual = str(documento.get("titulo") or "").strip()
            url_item_atual = normalizar_url(documento.get("url_item"))
            fonte_atual = str(documento.get("fonte") or "").strip()

            if titulo_atual:
                registro["titulo"] = titulo_atual

            if url_item_atual:
                registro["url_item"] = url_item_atual

            if fonte_atual:
                registro["fonte"] = fonte_atual

            conhecidos.append({
                "chave_documento": chave,
                "fonte": registro.get("fonte"),
                "titulo": registro.get("titulo"),
                "url_pdf": registro.get("url_pdf"),
                "status": registro.get("status"),
            })
            continue

        novo = novo_registro_pendente(
            documento,
            instante=instante,
        )
        registros[chave] = novo
        novos.append({
            "chave_documento": chave,
            "fonte": novo.get("fonte"),
            "titulo": novo.get("titulo"),
            "url_pdf": novo.get("url_pdf"),
            "status": novo.get("status"),
        })

    controle["atualizado_em"] = instante
    controle["ultima_descoberta_remota_em"] = instante
    controle["documentos"] = registros
    controle["ultima_descoberta"] = {
        "status": (
            "SUCESSO"
            if not erros
            else "CONCLUIDO_COM_PENDENCIAS"
        ),
        "executado_em": instante,
        "documentos_remotos": len(documentos_remotos),
        "documentos_conhecidos": len(conhecidos),
        "documentos_novos": len(novos),
        "erros": erros,
    }
    controle["resumo"] = montar_resumo(controle)

    salvar_json_atomico(CAMINHO_CONTROLE_INCREMENTAL, controle)

    resultado = {
        "status": (
            "SUCESSO"
            if not erros
            else "CONCLUIDO_COM_PENDENCIAS"
        ),
        "gerado_em": instante,
        "documentos_remotos": len(documentos_remotos),
        "documentos_conhecidos": len(conhecidos),
        "documentos_novos": len(novos),
        "novos": novos,
        "erros": erros,
        "total_erros": len(erros),
        "controle": str(CAMINHO_CONTROLE_INCREMENTAL),
        "status_path": str(CAMINHO_ULTIMO_STATUS),
        **controle["resumo"],
    }

    salvar_status(resultado)

    print("=" * 80)
    print("DESCOBERTA INCREMENTAL CONCLUÍDA")
    print("=" * 80)
    print(f"Status: {resultado['status']}")
    print(f"Documentos remotos encontrados: {len(documentos_remotos)}")
    print(f"Documentos já conhecidos: {len(conhecidos)}")
    print(f"Documentos novos: {len(novos)}")
    print(f"Erros: {len(erros)}")
    print(
        "Novos pendentes no controle: "
        f"{resultado.get('novos_pendentes', 0)}"
    )

    for item in novos:
        print(
            f"NOVO | {item.get('fonte')} | "
            f"{item.get('titulo')} | {item.get('url_pdf')}"
        )

    print("PDFs baixados: 0")
    print("PDFs processados: 0")
    print(f"Controle: {CAMINHO_CONTROLE_INCREMENTAL}")
    print(f"Status: {CAMINHO_ULTIMO_STATUS}")
    print("=" * 80)

    return resultado


def main() -> None:
    executar()


if __name__ == "__main__":
    main()
