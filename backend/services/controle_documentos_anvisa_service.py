# -*- coding: utf-8 -*-
"""
Controle incremental de documentos da Anvisa/Dicol — 2026.

Atividade desta versão:
- criar o baseline dos PDFs já conhecidos no manifesto anual;
- registrar os documentos atuais como já processados;
- evitar que os 22 PDFs existentes sejam reprocessados diariamente;
- não acessar a internet;
- não baixar PDFs;
- não executar OCR;
- não pesquisar processos;
- não enviar e-mail.

O controle criado por este serviço será usado posteriormente para detectar
somente documentos novos ou alterados.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag


VERSAO_SCHEMA = 1
ANO = 2026

ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_PROCESSOS = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
)

CAMINHO_MANIFESTO_ANUAL = (
    PASTA_PROCESSOS
    / "manifesto_anvisa_dicol_2026.json"
)

CAMINHO_CONTROLE_INCREMENTAL = (
    PASTA_PROCESSOS
    / "controle_documentos_anvisa_2026.json"
)

STATUS_CONHECIDO_BASELINE = "CONHECIDO_BASELINE"
STATUS_NOVO_PENDENTE = "NOVO_PENDENTE"
STATUS_PROCESSADO_INCREMENTAL = "PROCESSADO_INCREMENTAL"
STATUS_INDISPONIVEL = "INDISPONIVEL"


def agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def hoje_iso() -> str:
    return dt.date.today().isoformat()


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


def carregar_json(caminho: Path) -> dict[str, Any]:
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as erro:
        raise RuntimeError(
            f"Falha ao ler JSON: {caminho} | {erro}"
        ) from erro

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"Formato inválido no JSON: {caminho}"
        )

    return payload


def normalizar_url(url: Any) -> str:
    texto = str(url or "").strip()

    if not texto:
        return ""

    texto, _ = urldefrag(texto)
    texto = texto.rstrip("/")

    if texto.lower().endswith(".pdf/view"):
        texto = texto[:-5]

    return texto


def chave_documento(url_pdf: str) -> str:
    url_normalizada = normalizar_url(url_pdf)

    if not url_normalizada:
        raise ValueError("Documento sem URL PDF válida.")

    return hashlib.sha256(
        url_normalizada.encode("utf-8")
    ).hexdigest()


def extrair_documentos_manifesto(payload: dict[str, Any]) -> list[dict]:
    documentos = payload.get("documentos", [])

    if isinstance(documentos, list):
        return [
            item
            for item in documentos
            if isinstance(item, dict)
        ]

    return []


def montar_registro_baseline(
    documento: dict[str, Any],
    *,
    instante: str,
    data_baseline: str,
) -> dict[str, Any]:
    url_pdf = normalizar_url(documento.get("url_pdf"))
    chave = chave_documento(url_pdf)

    arquivo_pdf = str(documento.get("arquivo_pdf") or "").strip()
    arquivo_pdf_ocr = str(documento.get("arquivo_pdf_ocr") or "").strip()

    diagnostico = documento.get("diagnostico_pdf", {})

    if not isinstance(diagnostico, dict):
        diagnostico = {}

    return {
        "chave_documento": chave,
        "url_pdf": url_pdf,
        "url_item": normalizar_url(documento.get("url_item")),
        "fonte": str(documento.get("fonte") or "").strip(),
        "titulo": str(documento.get("titulo") or "").strip(),
        "status": STATUS_CONHECIDO_BASELINE,
        "processado": True,
        "baseline": True,
        "baseline_em": data_baseline,
        "primeira_identificacao_em": instante,
        "ultima_identificacao_em": instante,
        "processado_em": data_baseline,
        "arquivo_pdf": arquivo_pdf,
        "arquivo_pdf_ocr": arquivo_pdf_ocr,
        "origem_arquivo": str(
            documento.get("origem_arquivo") or ""
        ).strip(),
        "status_leitura": str(
            diagnostico.get("status_leitura") or ""
        ).strip(),
        "ocr_aplicado": bool(
            diagnostico.get("ocr_aplicado")
        ),
        "total_resultados_baseline": int(
            documento.get("total_resultados") or 0
        ),
        "hash_conteudo": None,
        "ultima_verificacao_remota_em": None,
        "observacao": (
            "Documento registrado no baseline incremental. "
            "Seu conteúdo já foi analisado no teste histórico."
        ),
    }


def montar_resumo(controle: dict[str, Any]) -> dict[str, int]:
    documentos = controle.get("documentos", {})

    if not isinstance(documentos, dict):
        documentos = {}

    conhecidos = 0
    novos_pendentes = 0
    processados_incrementais = 0
    indisponiveis = 0

    for registro in documentos.values():
        if not isinstance(registro, dict):
            continue

        status = str(registro.get("status") or "")

        if status == STATUS_CONHECIDO_BASELINE:
            conhecidos += 1
        elif status == STATUS_NOVO_PENDENTE:
            novos_pendentes += 1
        elif status == STATUS_PROCESSADO_INCREMENTAL:
            processados_incrementais += 1
        elif status == STATUS_INDISPONIVEL:
            indisponiveis += 1

    return {
        "total_documentos": len(documentos),
        "conhecidos_baseline": conhecidos,
        "novos_pendentes": novos_pendentes,
        "processados_incrementais": processados_incrementais,
        "indisponiveis": indisponiveis,
    }


def inicializar_baseline(
    *,
    forcar: bool = False,
    data_baseline: str | None = None,
) -> dict[str, Any]:
    """
    Registra como conhecidos todos os documentos presentes no manifesto anual.

    Segurança:
    - não sobrescreve controle existente sem --forcar;
    - não acessa a Anvisa;
    - não baixa nem abre PDFs.
    """

    if CAMINHO_CONTROLE_INCREMENTAL.exists() and not forcar:
        raise FileExistsError(
            "O controle incremental da Anvisa já existe. "
            f"Arquivo: {CAMINHO_CONTROLE_INCREMENTAL}. "
            "Use --forcar somente se a reinicialização for intencional."
        )

    data_baseline = str(data_baseline or hoje_iso())

    try:
        dt.date.fromisoformat(data_baseline)
    except ValueError as erro:
        raise ValueError(
            f"Data baseline inválida: {data_baseline!r}. "
            "Use AAAA-MM-DD."
        ) from erro

    manifesto = carregar_json(CAMINHO_MANIFESTO_ANUAL)
    documentos_manifesto = extrair_documentos_manifesto(manifesto)

    if not documentos_manifesto:
        raise RuntimeError(
            "O manifesto anual não contém documentos da Anvisa. "
            f"Manifesto: {CAMINHO_MANIFESTO_ANUAL}"
        )

    instante = agora_iso()
    registros: dict[str, dict[str, Any]] = {}
    ignorados_sem_url = 0
    duplicados = 0

    for documento in documentos_manifesto:
        url_pdf = normalizar_url(documento.get("url_pdf"))

        if not url_pdf:
            ignorados_sem_url += 1
            continue

        chave = chave_documento(url_pdf)

        if chave in registros:
            duplicados += 1
            continue

        registros[chave] = montar_registro_baseline(
            documento,
            instante=instante,
            data_baseline=data_baseline,
        )

    controle: dict[str, Any] = {
        "versao_schema": VERSAO_SCHEMA,
        "ano": ANO,
        "criado_em": instante,
        "atualizado_em": instante,
        "baseline_inicializado": True,
        "baseline_em": data_baseline,
        "manifesto_origem": str(CAMINHO_MANIFESTO_ANUAL),
        "ultima_descoberta_remota_em": None,
        "documentos": registros,
        "metricas_inicializacao": {
            "documentos_no_manifesto": len(documentos_manifesto),
            "documentos_registrados": len(registros),
            "ignorados_sem_url": ignorados_sem_url,
            "duplicados": duplicados,
        },
    }

    controle["resumo"] = montar_resumo(controle)
    salvar_json_atomico(CAMINHO_CONTROLE_INCREMENTAL, controle)

    return {
        "status": "BASELINE_ANVISA_INICIALIZADO",
        "caminho_controle": str(CAMINHO_CONTROLE_INCREMENTAL),
        "manifesto_origem": str(CAMINHO_MANIFESTO_ANUAL),
        **controle["metricas_inicializacao"],
        **controle["resumo"],
    }


def mostrar_controle() -> dict[str, Any]:
    controle = carregar_json(CAMINHO_CONTROLE_INCREMENTAL)

    return {
        "status": "CONTROLE_ANVISA_CARREGADO",
        "caminho_controle": str(CAMINHO_CONTROLE_INCREMENTAL),
        "manifesto_origem": controle.get("manifesto_origem"),
        **montar_resumo(controle),
    }


def imprimir_resultado(resultado: dict[str, Any]) -> None:
    print("=" * 80)
    print("CONTROLE INCREMENTAL DE DOCUMENTOS ANVISA — 2026")
    print("=" * 80)
    print(f"Status: {resultado.get('status')}")
    print(
        "Documentos no manifesto anual: "
        f"{resultado.get('documentos_no_manifesto', '-')}"
    )
    print(
        "Documentos registrados no baseline: "
        f"{resultado.get('documentos_registrados', '-')}"
    )
    print(
        "Total de documentos no controle: "
        f"{resultado.get('total_documentos', 0)}"
    )
    print(
        "Conhecidos no baseline: "
        f"{resultado.get('conhecidos_baseline', 0)}"
    )
    print(
        "Novos pendentes: "
        f"{resultado.get('novos_pendentes', 0)}"
    )
    print(
        "Processados incrementais: "
        f"{resultado.get('processados_incrementais', 0)}"
    )
    print(
        "Indisponíveis: "
        f"{resultado.get('indisponiveis', 0)}"
    )

    if resultado.get("duplicados") not in [None, 0]:
        print(f"Duplicados ignorados: {resultado.get('duplicados')}")

    if resultado.get("ignorados_sem_url") not in [None, 0]:
        print(
            "Ignorados sem URL: "
            f"{resultado.get('ignorados_sem_url')}"
        )

    print(f"Controle: {resultado.get('caminho_controle')}")
    print("=" * 80)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inicializa o baseline incremental dos documentos "
            "Anvisa/Dicol já analisados em 2026."
        )
    )

    grupo = parser.add_mutually_exclusive_group(required=True)

    grupo.add_argument(
        "--inicializar-baseline",
        action="store_true",
        help=(
            "Registra como conhecidos os documentos já presentes "
            "no manifesto anual da Anvisa."
        ),
    )

    grupo.add_argument(
        "--mostrar",
        action="store_true",
        help="Exibe o resumo atual do controle incremental.",
    )

    parser.add_argument(
        "--data-baseline",
        default=None,
        help="Data do baseline em AAAA-MM-DD. Padrão: hoje.",
    )

    parser.add_argument(
        "--forcar",
        action="store_true",
        help=(
            "Sobrescreve um controle existente. "
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
        )
    else:
        resultado = mostrar_controle()

    imprimir_resultado(resultado)


if __name__ == "__main__":
    main()
