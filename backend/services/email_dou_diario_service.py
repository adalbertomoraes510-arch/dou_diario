# ============================================================
# SERVICE — E-mail DOU Diário
# Projeto Informativos / DOU
# ============================================================
#
# Responsabilidade:
# - Localizar os arquivos gerados da finalidade dou_diario.
# - Ler o modelo JSON do relatório executivo.
# - Ler o arquivo de match do dia para montar a lista de publicações.
# - Enriquecer os links das publicações relevantes com o link moderno do DOU
#   quando possível, mantendo fallback para o link oficial da página do DOU.
# - Montar assunto e corpo HTML.
# - Anexar o relatório TXT.
# - Chamar o service genérico de e-mail.
#
# Este service NÃO executa o DOU.
# Este service NÃO envia informativos mensais.
# Este service é exclusivo da finalidade dou_diario.
# ============================================================

import asyncio
import os
import subprocess
import datetime
import html
import json
import re
import threading
from pathlib import Path
from typing import Any

from backend.services.email_service import enviar_email
from backend.services.controle_email_processos_service import (
    obter_ocorrencias_pendentes,
)

try:
    from backend.services.dou_link_resolver_service import resolver_links_modernos_dou_lote
except Exception:  # proteção para não quebrar envio caso o resolvedor não esteja disponível
    resolver_links_modernos_dou_lote = None


try:
    from backend.services.dou_integra_html_service import gerar_integras_do_json
except Exception:
    gerar_integras_do_json = None


# ============================================================
# CONFIGURAÇÃO
# ============================================================

FINALIDADE = "dou_diario"

ENVIAR_EMAIL_SEM_PUBLICACOES = False

ASSUNTO_PREFIXO = "DOU Diário"

TERMOS_NAO_EXIBIR_EMAIL = {
    "legado",
}

# Resolvedor de link moderno individual do portal DOU.
# Mantém INLABS como fonte oficial e usa Playwright apenas para enriquecer
# as publicações relevantes que entrarão no e-mail.
RESOLVER_LINK_MODERNO_EMAIL = True
RESOLVER_LINK_MODERNO_HEADLESS = True
RESOLVER_LINK_MODERNO_ESPERA_MS = 6000


# ============================================================
# CAMINHOS
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"

RELATORIOS_DIR = DATA_DOU_DIR / "relatorios" / FINALIDADE
MATCH_DIR = DATA_DOU_DIR / "match" / FINALIDADE
BASE_DIR = DATA_DOU_DIR / "base"
DEBUG_DIR = DATA_DOU_DIR / "debug"
LINK_CACHE_DIR = DATA_DOU_DIR / "links_resolvidos"
LINK_DEBUG_DIR = DEBUG_DIR / "links_modernos_dou"

LINK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LINK_DEBUG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FUNÇÕES AUXILIARES — DATA / CAMINHOS
# ============================================================

def formatar_data_br(data_execucao: datetime.date) -> str:
    return data_execucao.strftime("%d/%m/%Y")


def montar_caminho_modelo_json(data_execucao: datetime.date) -> Path:
    return (
        RELATORIOS_DIR
        / f"relatorio_executivo_modelo_{data_execucao.isoformat()}.json"
    )


def montar_caminho_relatorio_txt(data_execucao: datetime.date) -> Path:
    return (
        RELATORIOS_DIR
        / f"relatorio_executivo_{data_execucao.isoformat()}.txt"
    )


def montar_caminho_match_json(data_execucao: datetime.date) -> Path:
    return (
        MATCH_DIR
        / f"match_publicacoes_{data_execucao.isoformat()}.json"
    )


def montar_caminho_base_json(data_execucao: datetime.date) -> Path:
    return (
        BASE_DIR
        / f"base_publicacoes_{data_execucao.isoformat()}.json"
    )


def montar_caminho_cache_links(data_execucao: datetime.date) -> Path:
    return (
        LINK_CACHE_DIR
        / f"links_modernos_{data_execucao.isoformat()}.json"
    )


def montar_caminho_debug_links_email(data_execucao: datetime.date) -> Path:
    return (
        LINK_DEBUG_DIR
        / f"debug_links_modernos_email_{data_execucao.isoformat()}.json"
    )


def carregar_json_seguro(caminho: Path) -> dict:
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as erro:
        raise RuntimeError(f"Falha ao ler JSON: {caminho} | {erro}") from erro


def salvar_json_seguro(caminho: Path, payload: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# FUNÇÕES AUXILIARES — RESUMO
# ============================================================

def extrair_resumo_modelo(modelo_json: dict) -> dict:
    """
    Compatível com formatos usados no projeto:
    - modelo_json["resumo_executivo"]
    - modelo_json["resumo_executivo_consolidado"]["visao_geral"]
    """

    if not isinstance(modelo_json, dict):
        return {}

    resumo = modelo_json.get("resumo_executivo", {}) or {}

    if isinstance(resumo, dict) and resumo:
        return resumo

    consolidado = modelo_json.get("resumo_executivo_consolidado", {}) or {}

    if isinstance(consolidado, dict):
        visao_geral = consolidado.get("visao_geral", {}) or {}

        if isinstance(visao_geral, dict) and visao_geral:
            return visao_geral

    return {}


def valor_resumo(resumo: dict, chave: str, padrao=0):
    valor = resumo.get(chave)

    if valor is None:
        return padrao

    return valor


# ============================================================
# FUNÇÕES AUXILIARES — MATCH / PUBLICAÇÕES
# ============================================================

def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip()
    texto = re.sub(r"\s+", " ", texto)

    return texto


def normalizar_texto_busca(valor: Any) -> str:
    texto = normalizar_texto(valor).lower()

    substituicoes = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "ä": "a",
        "é": "e",
        "ê": "e",
        "è": "e",
        "ë": "e",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ï": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ò": "o",
        "ö": "o",
        "ú": "u",
        "ù": "u",
        "û": "u",
        "ü": "u",
        "ç": "c",
    }

    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)

    texto = re.sub(r"\s+", " ", texto).strip()

    return texto


def normalizar_chave_comparacao(valor: Any) -> str:
    texto = normalizar_texto_busca(valor)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def primeiro_valor(dados: dict, chaves: list[str], padrao: Any = "") -> Any:
    for chave in chaves:
        if chave in dados and dados.get(chave) not in [None, "", [], {}]:
            return dados.get(chave)

    return padrao


def selecionar_url_publicacao(dados: dict) -> str:
    """
    Seleciona a melhor URL disponível para exibição no e-mail.

    Prioridade:
    1. Link moderno individual do portal DOU (/web/dou/-/...), quando resolvido.
    2. Demais campos de publicação web, se existirem.
    3. Link oficial do INLABS/visualizador de página como fallback.
    """
    if not isinstance(dados, dict):
        return ""

    chaves_prioridade = [
        "url_publicacao_web",
        "url_web_dou",
        "url_moderno",
        "url_publicacao_moderno",
        "link_moderno",
        "url_publicacao",
        "link",
        "href",
        "url_consulta_dou",
        "url_pagina_dou",
        "url",
    ]

    for chave in chaves_prioridade:
        valor = str(dados.get(chave) or "").strip()
        if valor:
            return valor

    return ""


def selecionar_url_pagina_dou_fallback(dados: dict) -> str:
    """
    Retorna o link oficial da página do DOU/INLABS quando existir.
    Este link continua sendo fallback seguro caso o link moderno não seja resolvido.
    """
    if not isinstance(dados, dict):
        return ""

    for chave in ["url_pagina_dou", "url_consulta_dou", "url", "link", "href", "url_publicacao"]:
        valor = str(dados.get(chave) or "").strip()
        if not valor:
            continue

        if "pesquisa.in.gov.br/imprensa/jsp/visualiza" in valor.lower():
            return valor

    return selecionar_url_publicacao(dados)


def url_eh_link_moderno_dou(url: str) -> bool:
    url = str(url or "").lower()
    return "in.gov.br/web/dou/-/" in url


def extrair_lista_publicacoes_base(dados: Any) -> list[dict]:
    if isinstance(dados, list):
        return [item for item in dados if isinstance(item, dict)]

    if not isinstance(dados, dict):
        return []

    for chave in ["publicacoes", "registros", "dados", "base_publicacoes", "itens"]:
        valor = dados.get(chave)

        if isinstance(valor, list):
            return [item for item in valor if isinstance(item, dict)]

    return []


def montar_chaves_publicacao(dados: dict) -> list[str]:
    candidatos = [
        primeiro_valor(dados, ["id_publicacao", "id", "id_dou", "hash_conteudo"]),
        primeiro_valor(dados, [
            "url_publicacao_web",
            "url_web_dou",
            "url_publicacao",
            "url_pagina_dou",
            "url",
            "link",
            "href",
        ]),
        primeiro_valor(dados, ["titulo", "titulo_publicacao", "title", "nome", "ementa"]),
    ]

    chaves: list[str] = []

    for candidato in candidatos:
        chave = normalizar_chave_comparacao(candidato)

        if chave and chave not in chaves:
            chaves.append(chave)

    return chaves


def extrair_texto_util_publicacao(dados: dict) -> str:
    titulo = normalizar_texto(
        primeiro_valor(dados, ["titulo", "titulo_publicacao", "title", "nome", "ementa"])
    ).lower()

    for chave in [
        "texto_integral",
        "texto",
        "conteudo",
        "texto_publicacao",
        "resumo",
        "descricao",
        "ementa",
    ]:
        valor = normalizar_texto(dados.get(chave))

        if valor and valor.lower() != titulo and len(valor) > 40:
            return valor

    return ""


def carregar_indice_base_diaria(data_execucao: datetime.date) -> dict[str, dict]:
    caminho_base = montar_caminho_base_json(data_execucao)

    if not caminho_base.exists():
        return {}

    try:
        payload = carregar_json_seguro(caminho_base)
    except Exception:
        return {}

    publicacoes_base = extrair_lista_publicacoes_base(payload)
    indice: dict[str, dict] = {}

    for publicacao in publicacoes_base:
        for chave in montar_chaves_publicacao(publicacao):
            if chave and chave not in indice:
                indice[chave] = publicacao

    return indice


def complementar_publicacao_com_texto_base(
    publicacao: dict,
    indice_base: dict[str, dict],
) -> dict:
    if publicacao.get("texto_referencia"):
        return publicacao

    registro_original = publicacao.get("registro_original", {}) or {}

    for chave in montar_chaves_publicacao(registro_original) + montar_chaves_publicacao(publicacao):
        publicacao_base = indice_base.get(chave)

        if not publicacao_base:
            continue

        texto = extrair_texto_util_publicacao(publicacao_base)

        if texto:
            publicacao["texto_referencia"] = texto
            publicacao["texto_complementado_base"] = True

            # Também aproveita metadados preservados na base.
            for campo in [
                "url_publicacao_web",
                "url_web_dou",
                "url_publicacao",
                "url_pagina_dou",
                "url_consulta_dou",
                "url",
                "link",
                "href",
                "pagina",
                "jornal",
                "secao",
                "arquivo_xml",
                "zip",
            ]:
                if publicacao.get(campo) in [None, "", [], {}] and publicacao_base.get(campo) not in [None, "", [], {}]:
                    publicacao[campo] = publicacao_base.get(campo)

            publicacao["url"] = selecionar_url_publicacao(publicacao)
            return publicacao

    return publicacao


def destacar_termos_no_trecho_html(
    trecho: str,
    termos: list[str],
) -> str:
    """
    Escapa o trecho para HTML e destaca em negrito as palavras-chave encontradas.

    Não altera match.
    Não cria termo novo.
    Apenas melhora a visualização no corpo do e-mail.
    """
    trecho_html = html.escape(trecho)

    termos_ordenados = sorted(
        {
            normalizar_texto(termo)
            for termo in termos
            if normalizar_texto(termo)
        },
        key=len,
        reverse=True,
    )

    for termo in termos_ordenados:
        termo_escapado = html.escape(termo)
        termo_regex = re.escape(termo_escapado)

        trecho_html = re.sub(
            rf"(?i)(?<![\\w])({termo_regex})(?![\\w])",
            r"<strong>\1</strong>",
            trecho_html,
        )

    return trecho_html


def extrair_trecho_relevante_publicacao(
    publicacao: dict,
    margem: int = 180,
) -> str:
    texto = normalizar_texto(publicacao.get("texto_referencia", ""))

    if not texto:
        return ""

    termos = publicacao.get("termos", []) or []
    texto_busca = normalizar_texto_busca(texto)

    for termo in termos:
        termo_limpo = normalizar_texto(termo)
        termo_busca = normalizar_texto_busca(termo_limpo)

        if not termo_busca:
            continue

        posicao = texto_busca.find(termo_busca)

        if posicao < 0:
            continue

        inicio = max(0, posicao - margem)
        fim = min(len(texto), posicao + len(termo_limpo) + margem)

        trecho = texto[inicio:fim].strip()

        if inicio > 0:
            trecho = "..." + trecho

        if fim < len(texto):
            trecho = trecho + "..."

        return trecho

    if len(texto) > 420:
        return texto[:417].rstrip() + "..."

    return texto


def extrair_termos_match(registro: dict) -> list[str]:
    termos = []

    for campo in ("matchs", "matches", "matchs_detectados", "termos_detectados"):
        itens = registro.get(campo, [])

        if not isinstance(itens, list):
            continue

        for item in itens:
            if isinstance(item, dict):
                termo = item.get("termo") or item.get("palavra") or item.get("valor")
            else:
                termo = item

            if termo:
                termo_txt = str(termo).strip()
                termo_busca = normalizar_texto_busca(termo_txt)

                if (
                    termo_txt
                    and termo_busca not in TERMOS_NAO_EXIBIR_EMAIL
                    and termo_txt not in termos
                ):
                    termos.append(termo_txt)

    categorias = registro.get("categorias_encontradas", [])

    if isinstance(categorias, list):
        for categoria in categorias:
            categoria_txt = str(categoria).strip()
            categoria_busca = normalizar_texto_busca(categoria_txt)

            if (
                categoria_txt
                and categoria_busca not in TERMOS_NAO_EXIBIR_EMAIL
                and categoria_txt not in termos
            ):
                termos.append(categoria_txt)

    return termos


def registro_tem_match_executivo(registro: dict) -> bool:
    status_match = str(registro.get("status_match", "")).upper()
    score = str(registro.get("score", "") or registro.get("score_contextual", "")).upper()

    if status_match == "COM_MATCH":
        return True

    if score in {"ALTO", "FORTE"}:
        return True

    return False


def normalizar_publicacao(registro: dict) -> dict:
    titulo = (
        registro.get("titulo")
        or registro.get("titulo_publicacao")
        or registro.get("title")
        or ""
    )

    orgao = (
        registro.get("orgao")
        or registro.get("orgao_publicacao")
        or registro.get("órgão")
        or ""
    )

    url_fallback = selecionar_url_publicacao(registro)
    url_pagina_dou = selecionar_url_pagina_dou_fallback(registro)

    data_publicacao = (
        registro.get("data_publicacao")
        or registro.get("data")
        or ""
    )

    secao = (
        registro.get("secao")
        or registro.get("seção")
        or ""
    )

    pagina = (
        registro.get("pagina")
        or registro.get("página")
        or ""
    )

    termos = extrair_termos_match(registro)

    texto_referencia = extrair_texto_util_publicacao(registro)

    publicacao = {
        "titulo": str(titulo).strip(),
        "orgao": str(orgao).strip(),
        "url": str(url_fallback).strip(),
        "url_original": str(url_fallback).strip(),
        "url_publicacao_web": str(registro.get("url_publicacao_web") or "").strip(),
        "url_web_dou": str(registro.get("url_web_dou") or "").strip(),
        "url_publicacao": str(registro.get("url_publicacao") or "").strip(),
        "url_pagina_dou": str(registro.get("url_pagina_dou") or url_pagina_dou or "").strip(),
        "url_consulta_dou": str(registro.get("url_consulta_dou") or "").strip(),
        "link": str(registro.get("link") or "").strip(),
        "href": str(registro.get("href") or "").strip(),
        "data_publicacao": str(data_publicacao).strip(),
        "secao": str(secao).strip(),
        "pagina": str(pagina).strip(),
        "jornal": str(registro.get("jornal") or "").strip(),
        "arquivo_xml": str(registro.get("arquivo_xml") or "").strip(),
        "zip": str(registro.get("zip") or "").strip(),
        "termos": termos,
        "texto_referencia": texto_referencia,
        "trecho_relevante": "",
        "registro_original": registro,
    }

    publicacao["url"] = selecionar_url_publicacao(publicacao)
    publicacao["trecho_relevante"] = extrair_trecho_relevante_publicacao(publicacao)
    publicacao["trecho_relevante_html"] = destacar_termos_no_trecho_html(
        trecho=publicacao["trecho_relevante"],
        termos=termos,
    )

    return publicacao


def carregar_publicacoes_relevantes(data_execucao: datetime.date) -> list[dict]:
    caminho_match = montar_caminho_match_json(data_execucao)

    if not caminho_match.exists():
        return []

    payload = carregar_json_seguro(caminho_match)

    registros = payload.get("registros", [])

    if not isinstance(registros, list):
        return []

    indice_base = carregar_indice_base_diaria(data_execucao)

    publicacoes = []

    for registro in registros:
        if not isinstance(registro, dict):
            continue

        if not registro_tem_match_executivo(registro):
            continue

        publicacao = normalizar_publicacao(registro)
        publicacao = complementar_publicacao_com_texto_base(publicacao, indice_base)
        publicacao["url"] = selecionar_url_publicacao(publicacao)
        publicacao["trecho_relevante"] = extrair_trecho_relevante_publicacao(publicacao)
        publicacao["trecho_relevante_html"] = destacar_termos_no_trecho_html(
            trecho=publicacao["trecho_relevante"],
            termos=publicacao.get("termos", []) or [],
        )

        publicacoes.append(publicacao)

    return publicacoes


# ============================================================
# OCORRÊNCIAS PENDENTES — PROCESSOS MONITORADOS
# ============================================================

def primeiro_valor_ocorrencia(
    ocorrencia: dict,
    chaves: list[str],
    padrao: Any = "",
) -> Any:
    for chave in chaves:
        valor = ocorrencia.get(chave)

        if valor not in [None, "", [], {}]:
            return valor

    return padrao


def selecionar_url_ocorrencia_processo(ocorrencia: dict) -> str:
    fonte = normalizar_texto_busca(
        ocorrencia.get("fonte")
        or ocorrencia.get("origem")
    )

    if "anvisa" in fonte:
        chaves = [
            "url_item",
            "url_pdf",
            "url",
            "link",
        ]
    else:
        chaves = [
            "url_publicacao_web",
            "url_web_dou",
            "url_publicacao",
            "url_pagina_dou",
            "url_consulta_dou",
            "url",
            "link",
            "href",
        ]

    for chave in chaves:
        valor = str(ocorrencia.get(chave) or "").strip()

        if valor:
            return valor

    return ""


def normalizar_ocorrencia_processo_email(
    ocorrencia: dict,
) -> dict:
    processo = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["processo", "valor_encontrado"],
        )
    )

    fonte = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["fonte", "origem"],
            "MONITORAMENTO DE PROCESSOS",
        )
    )

    titulo = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            [
                "titulo",
                "titulo_publicacao",
                "ementa",
                "nome_documento",
            ],
            "Ocorrência de processo monitorado",
        )
    )

    orgao = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["orgao", "órgão", "orgao_publicacao"],
            fonte,
        )
    )

    data_publicacao = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["data_publicacao", "data"],
        )
    )

    secao = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["secao", "seção"],
        )
    )

    pagina = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            ["pagina", "página", "pagina_pdf"],
        )
    )

    trecho = normalizar_texto(
        primeiro_valor_ocorrencia(
            ocorrencia,
            [
                "trecho",
                "trecho_encontrado",
                "contexto",
                "texto_referencia",
            ],
        )
    )

    url = selecionar_url_ocorrencia_processo(ocorrencia)
    chave_email = str(ocorrencia.get("chave_email") or "").strip()

    registro_original = dict(ocorrencia)
    registro_original["processos_monitorados_detectados"] = (
        [processo] if processo else []
    )

    return {
        "titulo": titulo,
        "orgao": orgao,
        "url": url,
        "url_original": url,
        "url_publicacao_web": str(
            ocorrencia.get("url_publicacao_web") or ""
        ).strip(),
        "url_web_dou": str(
            ocorrencia.get("url_web_dou") or ""
        ).strip(),
        "url_publicacao": str(
            ocorrencia.get("url_publicacao") or ""
        ).strip(),
        "url_pagina_dou": str(
            ocorrencia.get("url_pagina_dou") or ""
        ).strip(),
        "url_consulta_dou": str(
            ocorrencia.get("url_consulta_dou") or ""
        ).strip(),
        "url_item": str(
            ocorrencia.get("url_item") or ""
        ).strip(),
        "url_pdf": str(
            ocorrencia.get("url_pdf") or ""
        ).strip(),
        "link": str(
            ocorrencia.get("link") or ""
        ).strip(),
        "href": str(
            ocorrencia.get("href") or ""
        ).strip(),
        "data_publicacao": data_publicacao,
        "secao": secao,
        "pagina": pagina,
        "jornal": str(
            ocorrencia.get("jornal") or ""
        ).strip(),
        "arquivo_xml": str(
            ocorrencia.get("arquivo_xml") or ""
        ).strip(),
        "zip": str(
            ocorrencia.get("zip") or ""
        ).strip(),
        "termos": [processo] if processo else [],
        "processos_detectados": [processo] if processo else [],
        "texto_referencia": trecho,
        "trecho_relevante": trecho,
        "trecho_relevante_html": destacar_termos_no_trecho_html(
            trecho=trecho,
            termos=[processo] if processo else [],
        ),
        "registro_original": registro_original,
        "ocorrencia_processo_incremental": True,
        "chave_email_ocorrencia": chave_email,
        "fonte_monitoramento": fonte,
    }


def carregar_publicacoes_processos_pendentes() -> tuple[list[dict], list[str]]:
    ocorrencias = obter_ocorrencias_pendentes()

    publicacoes: list[dict] = []
    chaves: list[str] = []

    for ocorrencia in ocorrencias:
        if not isinstance(ocorrencia, dict):
            continue

        publicacao = normalizar_ocorrencia_processo_email(
            ocorrencia
        )
        publicacoes.append(publicacao)

        chave_email = str(
            ocorrencia.get("chave_email") or ""
        ).strip()

        if chave_email and chave_email not in chaves:
            chaves.append(chave_email)

    return publicacoes, chaves


def chave_deduplicacao_publicacao_processo(
    publicacao: dict,
) -> str:
    processos = remover_duplicados_preservando_ordem(
        publicacao.get("processos_detectados", []) or []
    )

    if not processos:
        processos = extrair_processos_publicacao(publicacao)

    processo = processos[0] if processos else ""

    titulo = normalizar_chave_comparacao(
        publicacao.get("titulo")
    )
    pagina = normalizar_chave_comparacao(
        publicacao.get("pagina")
    )
    data_publicacao = normalizar_chave_comparacao(
        publicacao.get("data_publicacao")
    )

    url = normalizar_chave_comparacao(
        selecionar_url_publicacao(publicacao)
        or publicacao.get("url_pdf")
        or publicacao.get("url_item")
    )

    return "|".join([
        normalizar_chave_comparacao(processo),
        data_publicacao,
        titulo,
        pagina,
        url,
    ])


def combinar_publicacoes_com_processos_pendentes(
    publicacoes_tradicionais: list[dict],
    publicacoes_processos: list[dict],
) -> list[dict]:
    combinadas = list(publicacoes_tradicionais)
    chaves_existentes = {
        chave_deduplicacao_publicacao_processo(publicacao)
        for publicacao in publicacoes_tradicionais
        if eh_processo_monitorado(publicacao)
    }

    for publicacao in publicacoes_processos:
        chave = chave_deduplicacao_publicacao_processo(
            publicacao
        )

        if chave and chave in chaves_existentes:
            continue

        combinadas.append(publicacao)

        if chave:
            chaves_existentes.add(chave)

    return combinadas


# ============================================================
# ÍNTEGRA HTML/TXT — E-MAIL
# ============================================================

def chave_integra_email(valor) -> str:
    return " ".join(str(valor or "").split()).casefold()


def caminho_integra_para_href_email(caminho) -> str:
    caminho_txt = str(caminho or "").strip()

    if not caminho_txt:
        return ""

    try:
        caminho_path = Path(caminho_txt).resolve()
        raiz_integras = (DATA_DOU_DIR / "integras").resolve()

        caminho_relativo = caminho_path.relative_to(raiz_integras).as_posix()

        base_url = str(
            os.getenv("DOU_INTEGRA_BASE_URL")
            or "http://127.0.0.1:8765"
        ).strip().rstrip("/")

        return f"{base_url}/{caminho_relativo}"
    except Exception:
        return ""


def anexar_links_integras_publicacoes(
    publicacoes: list[dict],
    data_execucao: datetime.date,
) -> list[dict]:
    """
    Gera os HTMLs/TXTs de íntegra e associa cada publicação do e-mail.

    Regra de associação:
    1. ocorrência incremental de processo: chave_email_ocorrencia;
    2. publicação tradicional: título normalizado como fallback.

    A chave da ocorrência evita associar a íntegra errada quando existem
    publicações com títulos iguais ou genéricos.
    """

    if gerar_integras_do_json is None:
        print(
            "[EMAIL DOU] Serviço de íntegra HTML indisponível. "
            "Mantendo links atuais."
        )
        return publicacoes

    try:
        arquivos_integras = gerar_integras_do_json(
            data_execucao=data_execucao,
            finalidade=FINALIDADE,
            abrir_primeiro_html=False,
        )
    except Exception as erro:
        print(
            "[EMAIL DOU] Erro ao gerar íntegra HTML/TXT: "
            f"{erro}"
        )
        return publicacoes

    indice_por_chave_email: dict[str, dict] = {}
    indice_por_titulo: dict[str, list[dict]] = {}

    for item in arquivos_integras:
        caminho_html = str(item.get("html") or "").strip()

        if not caminho_html:
            continue

        dados_integra = {
            "href": caminho_integra_para_href_email(caminho_html),
            "caminho_html": caminho_html,
            "caminho_txt": str(item.get("txt") or "").strip(),
            "origem_integra": str(
                item.get("origem_integra") or ""
            ).strip(),
            "data_publicacao": str(
                item.get("data_publicacao") or ""
            ).strip(),
            "processos": list(item.get("processos") or []),
        }

        for chave_email in (
            item.get("chaves_email_ocorrencias") or []
        ):
            chave_email = str(chave_email or "").strip()

            if chave_email:
                indice_por_chave_email[chave_email] = dados_integra

        titulo = chave_integra_email(item.get("titulo"))

        if titulo:
            indice_por_titulo.setdefault(titulo, []).append(
                dados_integra
            )

    total_associados = 0
    associados_por_chave = 0
    associados_por_titulo = 0
    sem_integra = 0

    for publicacao in publicacoes:
        dados_integra = None
        criterio_associacao = ""

        chave_email = str(
            publicacao.get("chave_email_ocorrencia") or ""
        ).strip()

        if chave_email:
            dados_integra = indice_por_chave_email.get(
                chave_email
            )

            if dados_integra:
                criterio_associacao = "CHAVE_OCORRENCIA"

        if dados_integra is None:
            titulo = chave_integra_email(
                publicacao.get("titulo")
            )
            candidatos_titulo = indice_por_titulo.get(
                titulo,
                [],
            )

            if len(candidatos_titulo) == 1:
                dados_integra = candidatos_titulo[0]
                criterio_associacao = "TITULO_UNICO"

            elif len(candidatos_titulo) > 1:
                # Em caso de título repetido, evita escolher uma íntegra
                # arbitrariamente. Publicações incrementais devem usar chave.
                processo_publicacao = normalizar_texto_busca(
                    (
                        publicacao.get("processos_detectados")
                        or [""]
                    )[0]
                )

                candidatos_processo = [
                    item
                    for item in candidatos_titulo
                    if processo_publicacao
                    and processo_publicacao
                    in {
                        normalizar_texto_busca(processo)
                        for processo in (
                            item.get("processos") or []
                        )
                    }
                ]

                if len(candidatos_processo) == 1:
                    dados_integra = candidatos_processo[0]
                    criterio_associacao = "TITULO_E_PROCESSO"

        if not dados_integra:
            sem_integra += 1
            continue

        publicacao["url_integra_html"] = dados_integra["href"]
        publicacao["caminho_integra_html"] = (
            dados_integra["caminho_html"]
        )
        publicacao["caminho_integra_txt"] = (
            dados_integra["caminho_txt"]
        )
        publicacao["criterio_associacao_integra"] = (
            criterio_associacao
        )
        publicacao["origem_integra"] = (
            dados_integra.get("origem_integra")
        )

        total_associados += 1

        if criterio_associacao == "CHAVE_OCORRENCIA":
            associados_por_chave += 1
        else:
            associados_por_titulo += 1

    print(
        "[EMAIL DOU] Íntegras HTML/TXT geradas para o e-mail."
    )
    print(
        "[EMAIL DOU] Associadas por chave da ocorrência: "
        f"{associados_por_chave}"
    )
    print(
        "[EMAIL DOU] Associadas por título/fallback: "
        f"{associados_por_titulo}"
    )
    print(
        "[EMAIL DOU] Sem íntegra própria; mantendo link oficial: "
        f"{sem_integra}"
    )
    print(
        "[EMAIL DOU] Total de publicações com link de íntegra: "
        f"{total_associados}"
    )

    return publicacoes


def _dou_env_bool(nome: str, padrao: bool = False) -> bool:
    valor = str(os.getenv(nome, "")).strip().lower()

    if not valor:
        return padrao

    if valor in {"1", "true", "t", "sim", "s", "yes", "y", "on"}:
        return True

    if valor in {"0", "false", "f", "nao", "não", "n", "no", "off"}:
        return False

    return padrao



def publicar_integras_cloudflare_se_habilitado() -> bool:
    publicar = _dou_env_bool("DOU_PUBLICAR_INTEGRAS_CLOUDFLARE", False)

    if not publicar:
        return False

    script_config = str(os.getenv("DOU_CLOUDFLARE_SCRIPT") or "").strip()
    bloquear_email = _dou_env_bool("DOU_PUBLICAR_INTEGRAS_BLOQUEAR_EMAIL_SE_FALHAR", True)

    if not script_config:
        mensagem = "[EMAIL DOU] DOU_CLOUDFLARE_SCRIPT não configurado no .env."

        if bloquear_email:
            raise RuntimeError(mensagem)

        print(f"[EMAIL DOU][AVISO] {mensagem}")
        return False

    script_path = Path(script_config)

    if not script_path.is_absolute():
        script_path = ROOT_DIR / script_path

    script_path = script_path.resolve()

    if not script_path.exists():
        mensagem = f"[EMAIL DOU] Script Cloudflare não encontrado: {script_path}"

        if bloquear_email:
            raise RuntimeError(mensagem)

        print(f"[EMAIL DOU][AVISO] {mensagem}")
        return False

    print("[EMAIL DOU] Publicando íntegras HTML/TXT no Cloudflare...")

    try:
        resultado = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            cwd=str(script_path.parent),
            check=False,
        )
    except Exception as exc:
        mensagem = f"[EMAIL DOU] Falha ao executar publicação Cloudflare: {exc}"

        if bloquear_email:
            raise RuntimeError(mensagem) from exc

        print(f"[EMAIL DOU][AVISO] {mensagem}")
        return False

    if resultado.returncode != 0:
        mensagem = f"[EMAIL DOU] Publicação Cloudflare falhou. Código de saída: {resultado.returncode}"

        if bloquear_email:
            raise RuntimeError(mensagem)

        print(f"[EMAIL DOU][AVISO] {mensagem}")
        return False

    print("[EMAIL DOU] Íntegras publicadas no Cloudflare com sucesso.")
    return True


# RESOLUÇÃO DE LINK MODERNO — E-MAIL
# ============================================================

def executar_async_em_contexto_sincrono(coro):
    """
    Executa uma coroutine a partir de função síncrona.
    Se já existir event loop ativo, executa em thread separada para evitar RuntimeError.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    resultado = {"valor": None, "erro": None}

    def _runner():
        novo_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(novo_loop)
            resultado["valor"] = novo_loop.run_until_complete(coro)
        except Exception as erro:
            resultado["erro"] = erro
        finally:
            novo_loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if resultado["erro"]:
        raise resultado["erro"]

    return resultado["valor"]


def carregar_cache_links_modernos(data_execucao: datetime.date) -> dict:
    caminho = montar_caminho_cache_links(data_execucao)

    if not caminho.exists():
        return {
            "data": data_execucao.isoformat(),
            "gerado_em": None,
            "itens": {},
        }

    try:
        payload = carregar_json_seguro(caminho)
        if isinstance(payload, dict) and isinstance(payload.get("itens"), dict):
            return payload
    except Exception:
        pass

    return {
        "data": data_execucao.isoformat(),
        "gerado_em": None,
        "itens": {},
    }


def salvar_cache_links_modernos(data_execucao: datetime.date, cache: dict) -> None:
    cache["data"] = data_execucao.isoformat()
    cache["gerado_em"] = datetime.datetime.now().isoformat(timespec="seconds")
    salvar_json_seguro(montar_caminho_cache_links(data_execucao), cache)


def chave_cache_publicacao(publicacao: dict) -> str:
    base = "|".join([
        str(publicacao.get("titulo") or ""),
        str(publicacao.get("data_publicacao") or ""),
        str(publicacao.get("secao") or ""),
        str(publicacao.get("pagina") or ""),
        str(publicacao.get("jornal") or ""),
    ])
    return normalizar_chave_comparacao(base)


def aplicar_resultado_resolvedor_na_publicacao(publicacao: dict, resultado: dict) -> dict:
    status = str(resultado.get("status_resolucao_link") or "").strip()
    url_web = str(resultado.get("url_publicacao_web") or "").strip()

    publicacao["status_resolucao_link"] = status
    publicacao["mensagem_resolucao_link"] = str(resultado.get("mensagem") or "").strip()
    publicacao["query_resolucao_link"] = str(resultado.get("query_usada") or "").strip()
    publicacao["score_resolucao_link"] = resultado.get("score")
    publicacao["texto_link_resolvido"] = str(resultado.get("texto_link") or "").strip()

    if url_web:
        publicacao["url_publicacao_web"] = url_web
        publicacao["url_web_dou"] = url_web
        publicacao["url"] = url_web
        publicacao["link"] = url_web
        publicacao["href"] = url_web
    else:
        publicacao["url"] = selecionar_url_publicacao(publicacao)

    return publicacao


def enriquecer_publicacoes_com_links_modernos(
    data_execucao: datetime.date,
    publicacoes: list[dict],
) -> list[dict]:
    """
    Enriquecimento em lote dos links modernos do DOU.

    Regra operacional:
    - Usa INLABS/base/match como fonte oficial da publicação.
    - Usa o resolvedor moderno apenas para publicações relevantes que irão ao e-mail.
    - Resolve em lote com uma única sessão Playwright.
    - Usa cache em backend/data/dou/links_resolvidos.
    - Se não encontrar link moderno validado, mantém fallback oficial INLABS/página DOU.
    - Não altera match, base, relatório nem auditoria.
    """

    if not RESOLVER_LINK_MODERNO_EMAIL:
        return publicacoes

    if resolver_links_modernos_dou_lote is None:
        print("[EMAIL DOU] Resolvedor de link moderno em lote indisponível. Usando links atuais/fallback.")
        return publicacoes

    if not publicacoes:
        return publicacoes

    total = len(publicacoes)
    ja_modernos = 0
    sem_titulo = 0
    para_resolver: list[dict] = []
    indices_para_resolver: list[int] = []

    print("=" * 80)
    print("RESOLVENDO LINKS MODERNOS DOU — E-MAIL")
    print("=" * 80)
    print(f"Data: {data_execucao.isoformat()}")
    print(f"Publicações relevantes: {total}")
    print(f"Modo: lote com cache e fallback INLABS")
    print(f"Cache: {montar_caminho_cache_links(data_execucao)}")
    print("=" * 80)

    for indice, publicacao in enumerate(publicacoes):
        titulo = str(publicacao.get("titulo") or "").strip()
        url_atual = selecionar_url_publicacao(publicacao)
        fonte_monitoramento = normalizar_texto_busca(
            publicacao.get("fonte_monitoramento")
        )

        if "anvisa" in fonte_monitoramento:
            publicacao["status_resolucao_link"] = "LINK_EXTERNO_ANVISA"
            publicacao["url"] = (
                str(publicacao.get("url_item") or "").strip()
                or str(publicacao.get("url_pdf") or "").strip()
                or url_atual
            )
            continue

        if url_eh_link_moderno_dou(url_atual):
            publicacao["url"] = url_atual
            publicacao["url_publicacao_web"] = url_atual
            publicacao["status_resolucao_link"] = "JA_MODERNO"
            ja_modernos += 1
            continue

        if not titulo:
            publicacao["status_resolucao_link"] = "SEM_TITULO"
            publicacao["mensagem_resolucao_link"] = "Publicação sem título; mantendo fallback."
            publicacao["url"] = url_atual
            sem_titulo += 1
            continue

        item_resolucao = {
            "titulo": titulo,
            "titulo_publicacao": titulo,
            "data_publicacao": publicacao.get("data_publicacao") or data_execucao.isoformat(),
            "secao": publicacao.get("secao") or "",
            "pagina": publicacao.get("pagina") or "",
            "jornal": publicacao.get("jornal") or "",
        }

        para_resolver.append(item_resolucao)
        indices_para_resolver.append(indice)

    resultados: list[dict] = []

    if para_resolver:
        for pos, item in enumerate(para_resolver, start=1):
            print(f"[EMAIL DOU] Aguardando resolução em lote {pos}/{len(para_resolver)}: {item.get('titulo')}")

        try:
            resultados = executar_async_em_contexto_sincrono(
                resolver_links_modernos_dou_lote(
                    publicacoes=para_resolver,
                    data_publicacao=data_execucao,
                    headless=RESOLVER_LINK_MODERNO_HEADLESS,
                    timeout_ms=60000,
                    espera_ms=RESOLVER_LINK_MODERNO_ESPERA_MS,
                    validar_pagina=True,
                    caminho_cache=montar_caminho_cache_links(data_execucao),
                    exigir_secao_pagina=False,
                )
            )
        except Exception as erro:
            print(f"[EMAIL DOU] Erro ao resolver links modernos em lote: {erro}")
            resultados = [
                {
                    "status_resolucao_link": "ERRO_EMAIL_SERVICE_LOTE",
                    "url_publicacao_web": "",
                    "mensagem": str(erro),
                    "candidatos": [],
                }
                for _ in para_resolver
            ]

    resolvidos = 0
    fallback = 0
    cache_usado = 0

    for indice_publicacao, resultado in zip(indices_para_resolver, resultados):
        publicacao = publicacoes[indice_publicacao]
        publicacao = aplicar_resultado_resolvedor_na_publicacao(publicacao, resultado)

        if resultado.get("origem_cache"):
            cache_usado += 1

        if publicacao.get("url_publicacao_web"):
            resolvidos += 1
        else:
            fallback += 1
            publicacao["url"] = selecionar_url_publicacao(publicacao)

        publicacoes[indice_publicacao] = publicacao

    # Qualquer item que não entrou no resolvedor também conta como fallback quando não tem link moderno.
    fallback_total = sum(
        1 for publicacao in publicacoes
        if not url_eh_link_moderno_dou(publicacao.get("url_publicacao_web") or publicacao.get("url"))
    )

    debug_payload = {
        "data": data_execucao.isoformat(),
        "total_publicacoes": total,
        "ja_modernos": ja_modernos,
        "sem_titulo": sem_titulo,
        "enviadas_para_resolver": len(para_resolver),
        "links_modernos_resolvidos_nesta_execucao": resolvidos,
        "resultados_com_cache": cache_usado,
        "fallback_total": fallback_total,
        "cache": str(montar_caminho_cache_links(data_execucao)),
        "publicacoes": [
            {
                "titulo": p.get("titulo"),
                "status_resolucao_link": p.get("status_resolucao_link"),
                "url_publicacao_web": p.get("url_publicacao_web"),
                "url_final_email": selecionar_url_publicacao(p),
                "mensagem_resolucao_link": p.get("mensagem_resolucao_link"),
                "texto_link_resolvido": p.get("texto_link_resolvido"),
                "secao": p.get("secao"),
                "pagina": p.get("pagina"),
                "arquivo_xml": p.get("arquivo_xml"),
                "zip": p.get("zip"),
            }
            for p in publicacoes
        ],
    }

    try:
        salvar_json_seguro(montar_caminho_debug_links_email(data_execucao), debug_payload)
    except Exception as erro:
        print(f"[EMAIL DOU] Aviso: falha ao salvar debug de links modernos: {erro}")

    print("=" * 80)
    print("RESULTADO LINKS MODERNOS DOU — E-MAIL")
    print("=" * 80)
    print(f"Total publicações: {total}")
    print(f"Enviadas para resolvedor: {len(para_resolver)}")
    print(f"Links modernos resolvidos: {sum(1 for p in publicacoes if url_eh_link_moderno_dou(p.get('url_publicacao_web') or ''))}")
    print(f"Já estavam modernos: {ja_modernos}")
    print(f"Resultados vindos do cache: {cache_usado}")
    print(f"Sem título: {sem_titulo}")
    print(f"Fallback página DOU/INLABS: {fallback_total}")
    print(f"Cache: {montar_caminho_cache_links(data_execucao)}")
    print(f"Debug: {montar_caminho_debug_links_email(data_execucao)}")
    print("=" * 80)

    return publicacoes


# ============================================================
# PROCESSOS / SEPARAÇÃO
# ============================================================

def remover_duplicados_preservando_ordem(valores: list[Any]) -> list[Any]:
    """
    Remove duplicidades mantendo a ordem original.

    Uso no e-mail:
    - evita repetir o mesmo processo na tabela;
    - evita repetir termos/palavras-chave;
    - não altera match, score, base ou relatório.
    """
    resultado = []
    vistos = set()

    for valor in valores:
        if valor in [None, ""]:
            continue

        valor_txt = str(valor).strip()

        if not valor_txt:
            continue

        chave = normalizar_texto_busca(valor_txt)

        if chave in vistos:
            continue

        vistos.add(chave)
        resultado.append(valor_txt)

    return resultado


def extrair_processos_texto(texto: Any) -> list[str]:
    """
    Extrai números de processo em formatos administrativos comuns.

    Exemplo principal:
    - 02001.035676/2023-34

    Esta função não altera match nem cria relevância.
    Ela apenas identifica processo já presente no conteúdo retornado pelo match/base.
    """
    texto_normalizado = normalizar_texto(texto)

    if not texto_normalizado:
        return []

    padroes = [
        r"\b\d{5}\.\d{6}/\d{4}-\d{2}\b",
        r"\b\d{5}\s+\d{6}\s+\d{4}\s+\d{2}\b",
        r"\b\d{5}\.\d{6}\s*/\s*\d{4}\s*-\s*\d{2}\b",
    ]

    processos: list[str] = []

    for padrao in padroes:
        for encontrado in re.findall(padrao, texto_normalizado):
            processo = re.sub(r"\s+", "", str(encontrado)).strip()

            # Recompõe formato quando veio do texto_normalizado com separadores removidos por espaços.
            if re.fullmatch(r"\d{17}", processo):
                processo = (
                    f"{processo[0:5]}.{processo[5:11]}/"
                    f"{processo[11:15]}-{processo[15:17]}"
                )

            if processo and processo not in processos:
                processos.append(processo)

    return remover_duplicados_preservando_ordem(processos)


def extrair_processos_publicacao(publicacao: dict) -> list[str]:
    """
    Extrai SOMENTE os processos que já vieram prontos do match.

    Regra arquitetural:
    - o e-mail NÃO decide match;
    - o e-mail NÃO varre o texto completo para descobrir processos;
    - o e-mail apenas apresenta processos que o match_service gravou como:
        categoria = "processo"
        tipo = "match_processo"

    Isso evita listar todos os processos citados dentro da publicação e mantém
    o bloco PROCESSOS MONITORADOS restrito aos processos cadastrados na planilha
    que realmente deram match.
    """
    registro_original = publicacao.get("registro_original", {}) or {}

    processos: list[str] = []

    processos_diagnosticados = registro_original.get("processos_monitorados_detectados", [])

    if isinstance(processos_diagnosticados, list):
        for processo in processos_diagnosticados:
            if processo:
                processos.append(str(processo).strip())

    for campo in ("matchs", "matches", "matchs_detectados", "termos_detectados"):
        itens = registro_original.get(campo, [])

        if not isinstance(itens, list):
            continue

        for item in itens:
            if not isinstance(item, dict):
                continue

            categoria = str(item.get("categoria", "") or "").strip().lower()
            tipo = str(item.get("tipo", "") or "").strip().lower()

            if categoria != "processo" and tipo != "match_processo":
                continue

            termo = item.get("termo") or item.get("palavra") or item.get("valor")

            if termo:
                processos.append(str(termo).strip())

    return remover_duplicados_preservando_ordem(processos)


def eh_processo_monitorado(publicacao: dict) -> bool:
    """
    Define se a publicação deve aparecer no bloco PROCESSOS MONITORADOS.

    Regra profissional:
    - usa somente processos que já vieram do match_service;
    - não procura processos no texto completo da publicação;
    - não altera match, score, relevância ou arquivo de origem.
    """
    processos_detectados = remover_duplicados_preservando_ordem(
        extrair_processos_publicacao(publicacao)
    )

    if processos_detectados:
        publicacao["processos_detectados"] = processos_detectados
        return True

    return False


def separar_publicacoes(publicacoes: list[dict]) -> tuple[list[dict], list[dict]]:
    processos = []
    outros = []

    for publicacao in publicacoes:
        if eh_processo_monitorado(publicacao):
            processos.append(publicacao)
        else:
            outros.append(publicacao)

    return processos, outros


# ============================================================
# HTML
# ============================================================

def montar_linhas_tabela(
    publicacoes: list[dict],
    titulo_primeira_coluna: str = "Palavras-chave",
) -> str:
    """
    Monta as linhas da tabela do e-mail.

    Regras:
    - Para PROCESSOS MONITORADOS: gera 1 linha por processo detectado.
    - Remove processos duplicados mantendo a ordem.
    - Para OUTRAS PUBLICAÇÕES: mantém 1 linha por publicação.
    - Não altera match, score, base, relatório ou envio.
    """
    linhas = []

    for publicacao in publicacoes:
        termos = remover_duplicados_preservando_ordem(
            publicacao.get("termos", []) or []
        )

        titulo = html.escape(publicacao.get("titulo", ""))
        orgao = html.escape(publicacao.get("orgao", ""))
        secao = html.escape(publicacao.get("secao", ""))
        pagina = html.escape(publicacao.get("pagina", ""))
        url = html.escape(selecionar_url_publicacao(publicacao))

        localizacao = " / ".join(
            item for item in [secao, f"pág. {pagina}" if pagina else ""]
            if item
        )

        trecho_relevante_html = publicacao.get("trecho_relevante_html", "")

        if not trecho_relevante_html and publicacao.get("trecho_relevante"):
            trecho_relevante_html = html.escape(publicacao.get("trecho_relevante", ""))

        detalhes_publicacao = titulo

        if trecho_relevante_html:
            detalhes_publicacao += (
                '<br><span style="color:#444; font-size:12px;">'
                f'<em>(Trecho: {trecho_relevante_html})</em>'
                '</span>'
            )

        fonte_monitoramento = html.escape(
            str(publicacao.get("fonte_monitoramento") or "").strip()
        )
        data_publicacao = html.escape(
            str(publicacao.get("data_publicacao") or "").strip()
        )

        if orgao:
            detalhes_publicacao += f'<br><span style="color:#555;">{orgao}</span>'

        if fonte_monitoramento:
            detalhes_publicacao += (
                '<br><span style="color:#666; font-size:12px;">'
                f'Fonte: {fonte_monitoramento}'
                '</span>'
            )

        if data_publicacao:
            detalhes_publicacao += (
                '<br><span style="color:#777; font-size:12px;">'
                f'Data: {data_publicacao}'
                '</span>'
            )

        if localizacao:
            detalhes_publicacao += f'<br><span style="color:#777;">{html.escape(localizacao)}</span>'

        url_integra = html.escape(str(publicacao.get("url_integra_html") or "").strip())

        if url_integra:
            link_html = f'<a href="{url_integra}" target="_blank" rel="noopener noreferrer">Ver íntegra</a>'
        elif url:
            link_html = f'<a href="{url}" target="_blank" rel="noopener noreferrer">Abrir</a>'
        else:
            link_html = "-"

        if titulo_primeira_coluna == "Processo":
            processos_detectados = remover_duplicados_preservando_ordem(
                publicacao.get("processos_detectados", []) or []
            )

            if not processos_detectados:
                processos_detectados = remover_duplicados_preservando_ordem(
                    extrair_processos_publicacao(publicacao)
                )

            if not processos_detectados:
                processos_detectados = ["-"]

            for processo in processos_detectados:
                processo_html = html.escape(str(processo))

                linhas.append(f"""
        <tr>
          <td style="vertical-align:top;"><strong>{processo_html}</strong></td>
          <td style="vertical-align:top;">{detalhes_publicacao}</td>
          <td style="vertical-align:top; text-align:center;">{link_html}</td>
        </tr>
        """)

            continue

        termos_html = "<br>".join(
            html.escape(str(termo))
            for termo in termos
        )

        linhas.append(f"""
        <tr>
          <td style="vertical-align:top;">{termos_html or "-"}</td>
          <td style="vertical-align:top;">{detalhes_publicacao}</td>
          <td style="vertical-align:top; text-align:center;">{link_html}</td>
        </tr>
        """)

    if not linhas:
        return """
        <tr>
          <td colspan="3" style="text-align:center; color:#777;">
            Nenhum registro nesta seção.
          </td>
        </tr>
        """

    return "".join(linhas)


def montar_corpo_email_dou_diario(
    data_execucao: datetime.date,
    resumo: dict,
    publicacoes: list[dict],
) -> str:
    processos, outros = separar_publicacoes(publicacoes)

    data_iso = data_execucao.isoformat()

    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; font-size: 14px; color:#333;">

        <h2 style="margin-bottom: 22px;">DOU Diário – {data_iso}</h2>

        <div style="
            background-color: #f8f9fa;
            border-left: 4px solid #0d6efd;
            padding: 16px 18px;
            margin: 10px 0 24px 0;
            font-size: 13px;
            line-height: 1.55;
        ">
          <strong>Aviso sobre o processo de monitoramento</strong><br><br>

          Prezados, Este e-mail foi gerado por um
          <strong>processo automatizado de monitoramento do Diário Oficial da União (DOU)</strong>.
          <br><br>

          O sistema realiza a leitura diária das publicações oficiais e identifica conteúdos
          relevantes com base em <strong>palavras-chave previamente definidas</strong>.
          <br><br>

          Ressaltamos que este processo encontra-se em
          <strong>fase de validação e aprimoramento</strong>, podendo sofrer ajustes nas
          regras de busca, palavras-chave, critérios de exclusão e no formato de apresentação
          das informações.
          <br><br>

          Caso seja identificada qualquer necessidade de correção, ajuste ou melhoria,
          a solicitação deverá ser encaminhada para a <strong>área de projetos</strong>,
          responsável pela análise e evolução do processo.
        </div>

        <h3 style="margin-top:26px;">PROCESSOS MONITORADOS (PRIORIDADE)</h3>

        <table border="1" cellpadding="6" cellspacing="0"
              style="border-collapse: collapse; font-size: 13px; margin-bottom:30px;">
          <tr style="background-color:#f0f0f0;">
            <th>Processo</th>
            <th>Publicação</th>
            <th>Link</th>
          </tr>
          {montar_linhas_tabela(processos, titulo_primeira_coluna="Processo")}
        </table>

        <h3>OUTRAS PUBLICAÇÕES RELEVANTES</h3>

        <table border="1" cellpadding="6" cellspacing="0"
              style="border-collapse: collapse; font-size: 13px;">
          <tr style="background-color:#f0f0f0;">
            <th>Palavras-chave</th>
            <th>Publicação</th>
            <th>Link</th>
          </tr>
          {montar_linhas_tabela(outros, titulo_primeira_coluna="Palavras-chave")}
        </table>

      </body>
    </html>
    """


# ============================================================
# ASSUNTO / TEXTO
# ============================================================

def montar_assunto_email(
    data_execucao: datetime.date,
    quantidade_publicacoes: int,
) -> str:
    return f"{ASSUNTO_PREFIXO} – {data_execucao.isoformat()}"


def montar_corpo_texto_fallback(
    data_execucao: datetime.date,
    quantidade_publicacoes: int,
) -> str:
    return (
        f"DOU Diário – {data_execucao.isoformat()}\n"
        f"Publicações relevantes: {quantidade_publicacoes}\n\n"
        "Seu cliente de e-mail não exibiu o conteúdo HTML.\n"
        "Consulte o relatório TXT anexado."
    )


# ============================================================
# FUNÇÃO PRINCIPAL
# ============================================================

def enviar_email_dou_diario(
    data_execucao: datetime.date,
    modo_simulacao: bool | None = None,
    destinatarios=None,
) -> dict:
    """
    Prepara e envia/simula o e-mail diário da finalidade dou_diario.
    """

    caminho_modelo_json = montar_caminho_modelo_json(data_execucao)
    caminho_relatorio_txt = montar_caminho_relatorio_txt(data_execucao)

    if not caminho_modelo_json.exists():
        raise FileNotFoundError(
            f"Modelo JSON do relatório dou_diario não encontrado: {caminho_modelo_json}"
        )

    if not caminho_relatorio_txt.exists():
        raise FileNotFoundError(
            f"Relatório TXT do dou_diario não encontrado: {caminho_relatorio_txt}"
        )

    modelo_json = carregar_json_seguro(caminho_modelo_json)
    resumo = extrair_resumo_modelo(modelo_json)

    publicacoes_tradicionais = carregar_publicacoes_relevantes(
        data_execucao
    )
    (
        publicacoes_processos_pendentes,
        chaves_ocorrencias_processos_incluidas,
    ) = carregar_publicacoes_processos_pendentes()

    publicacoes = combinar_publicacoes_com_processos_pendentes(
        publicacoes_tradicionais=publicacoes_tradicionais,
        publicacoes_processos=publicacoes_processos_pendentes,
    )

    if not publicacoes and not ENVIAR_EMAIL_SEM_PUBLICACOES:
        return {
            "status": "IGNORADO_SEM_PUBLICACOES",
            "data": data_execucao.isoformat(),
            "finalidade": FINALIDADE,
            "mensagem": "Nenhuma publicação relevante ou ocorrência pendente de processo encontrada. E-mail não enviado.",
            "quantidade_publicacoes_tradicionais": len(publicacoes_tradicionais),
            "quantidade_ocorrencias_processos": len(publicacoes_processos_pendentes),
            "chaves_ocorrencias_processos_incluidas": [],
            "caminho_modelo_json": str(caminho_modelo_json),
            "caminho_relatorio_txt": str(caminho_relatorio_txt),
        }

    publicacoes = enriquecer_publicacoes_com_links_modernos(
        data_execucao=data_execucao,
        publicacoes=publicacoes,
    )

    assunto = montar_assunto_email(
        data_execucao=data_execucao,
        quantidade_publicacoes=len(publicacoes),
    )

    publicacoes = anexar_links_integras_publicacoes(
        publicacoes=publicacoes,
        data_execucao=data_execucao,
    )

    publicar_integras_cloudflare_se_habilitado()

    corpo_html = montar_corpo_email_dou_diario(
        data_execucao=data_execucao,
        resumo=resumo,
        publicacoes=publicacoes,
    )

    corpo_texto = montar_corpo_texto_fallback(
        data_execucao=data_execucao,
        quantidade_publicacoes=len(publicacoes),
    )

    resultado_envio = enviar_email(
        assunto=assunto,
        corpo_html=corpo_html,
        corpo_texto=corpo_texto,
        anexo=caminho_relatorio_txt,
        destinatarios=destinatarios,
        modo_simulacao=modo_simulacao,
    )

    return {
        "status": resultado_envio.get("status"),
        "data": data_execucao.isoformat(),
        "finalidade": FINALIDADE,
        "quantidade_publicacoes": len(publicacoes),
        "quantidade_publicacoes_tradicionais": len(
            publicacoes_tradicionais
        ),
        "quantidade_ocorrencias_processos": len(
            publicacoes_processos_pendentes
        ),
        "chaves_ocorrencias_processos_incluidas": (
            chaves_ocorrencias_processos_incluidas
        ),
        "links_modernos_resolvidos": sum(
            1 for publicacao in publicacoes
            if url_eh_link_moderno_dou(publicacao.get("url_publicacao_web") or publicacao.get("url"))
        ),
        "caminho_cache_links_modernos": str(montar_caminho_cache_links(data_execucao)),
        "caminho_modelo_json": str(caminho_modelo_json),
        "caminho_relatorio_txt": str(caminho_relatorio_txt),
        "resultado_envio": resultado_envio,
    }
