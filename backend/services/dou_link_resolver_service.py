# ============================================================
# SERVICE — Resolvedor de Link Moderno do DOU
# Projeto Informativos / DOU
# ============================================================
#
# Responsabilidade:
# - Resolver o link moderno individual do portal do DOU:
#   https://www.in.gov.br/web/dou/-/...
#
# Regra oficial validada no mapeamento:
# - INLABS continua sendo a fonte oficial para coleta/texto/base/match.
# - INLABS não traz o link moderno /web/dou/-/.
# - Este service usa Playwright apenas para enriquecer links das publicações relevantes.
#
# Estratégia segura:
# 1. Usa o título oficial da publicação.
# 2. Monta a busca avançada com o título ENTRE ASPAS.
# 3. Usa data exata: publishFrom = publishTo.
# 4. Captura somente links reais /web/dou/-/.
# 5. Aceita somente candidato cujo texto do resultado bate com o título oficial.
# 6. Abre a página candidata e valida título + data.
# 7. Se seção/página forem informadas, registra a conferência, mas por padrão
#    não bloqueia o link, porque a página do visualizador INLABS pode não ser
#    igual à página moderna exibida no portal.
# 8. Se não validar título/data, não usa link moderno; o chamador deve manter
#    fallback INLABS.
#
# Este service NÃO:
# - coleta o DOU inteiro;
# - altera match;
# - altera base;
# - altera auditoria;
# - envia e-mail.
# ============================================================

import asyncio
import datetime
import html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


# ============================================================
# CONSTANTES
# ============================================================

BASE_BUSCA_DOU = "https://www.in.gov.br/consulta/-/buscar/dou"
BASE_IN_GOV = "https://www.in.gov.br"

DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
DEFAULT_LOCALE = "pt-BR"
DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

STATUS_ENCONTRADO = "ENCONTRADO"
STATUS_NAO_ENCONTRADO = "NAO_ENCONTRADO"
STATUS_SEM_TITULO = "SEM_TITULO"
STATUS_LOGIN_LIFERAY = "LOGIN_LIFERAY"
STATUS_ERRO_TIMEOUT = "ERRO_TIMEOUT"
STATUS_ERRO = "ERRO"

STOPWORDS_TITULO = {
    "a", "as", "ao", "aos",
    "o", "os",
    "de", "da", "das", "do", "dos",
    "e", "em", "no", "na", "nos", "nas",
    "por", "para", "com", "sem",
    "n", "nº", "n°", "numero", "número",
}


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def normalizar_texto(valor: Any) -> str:
    texto = str(valor or "")
    texto = html.unescape(texto)

    # Importante:
    # Faz substituições de "nº/n°" antes do NFKD, porque o NFKD pode
    # transformar o símbolo ordinal em "o" e atrapalhar a equivalência.
    texto = texto.replace("Nº", "N")
    texto = texto.replace("nº", "n")
    texto = texto.replace("N°", "N")
    texto = texto.replace("n°", "n")
    texto = texto.replace("º", "")
    texto = texto.replace("°", "")
    texto = texto.replace("ª", "")

    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()

    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_para_comparacao(valor: Any) -> str:
    texto = normalizar_texto(valor)
    texto = re.sub(r"[^a-z0-9/.-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def limpar_titulo(valor: Any) -> str:
    return re.sub(r"\s+", " ", str(valor or "").strip())


def formatar_data_dou_url(data_publicacao: datetime.date | str) -> str:
    """
    Retorna DD-MM-YYYY para URL da busca do DOU.
    Aceita:
    - datetime.date
    - YYYY-MM-DD
    - DD/MM/YYYY
    - DD-MM-YYYY
    """

    if isinstance(data_publicacao, datetime.date):
        return data_publicacao.strftime("%d-%m-%Y")

    texto = str(data_publicacao or "").strip()

    # YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        ano, mes, dia = m.groups()
        return f"{dia}-{mes}-{ano}"

    # DD/MM/YYYY
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if m:
        dia, mes, ano = m.groups()
        return f"{dia}-{mes}-{ano}"

    # DD-MM-YYYY
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", texto)
    if m:
        return texto

    raise ValueError(f"Data inválida para busca DOU: {data_publicacao}")


def formatar_data_dou_texto(data_publicacao: datetime.date | str) -> str:
    """
    Retorna DD/MM/YYYY para validação na página moderna.
    """

    if isinstance(data_publicacao, datetime.date):
        return data_publicacao.strftime("%d/%m/%Y")

    texto = str(data_publicacao or "").strip()

    # YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if m:
        ano, mes, dia = m.groups()
        return f"{dia}/{mes}/{ano}"

    # DD-MM-YYYY
    m = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", texto)
    if m:
        dia, mes, ano = m.groups()
        return f"{dia}/{mes}/{ano}"

    # DD/MM/YYYY
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if m:
        return texto

    return texto


def normalizar_secao(valor: Any) -> str:
    """
    Converte:
    - DO1 -> 1
    - DO2 -> 2
    - DO3 -> 3
    - Seção 1 -> 1
    """

    texto = normalizar_para_comparacao(valor)

    if not texto:
        return ""

    m = re.search(r"\bdo\s*([123])\b", texto)
    if m:
        return m.group(1)

    m = re.search(r"\bsecao\s*([123])\b", texto)
    if m:
        return m.group(1)

    m = re.fullmatch(r"[123]", texto)
    if m:
        return texto

    m = re.search(r"\b([123])\b", texto)
    if m:
        return m.group(1)

    return texto


# ============================================================
# COMPARAÇÃO DE TÍTULO
# ============================================================

def tokens_relevantes_titulo(titulo: str) -> list[str]:
    texto = normalizar_para_comparacao(titulo)
    tokens = []

    for token in texto.split():
        token = token.strip()

        if not token:
            continue

        if token in STOPWORDS_TITULO:
            continue

        # Mantém tokens curtos quando têm número, ex.: 71-e, 9/2026.
        if len(token) < 3 and not re.search(r"\d", token):
            continue

        if token not in tokens:
            tokens.append(token)

    return tokens


def extrair_numeros_distintivos(titulo: str) -> list[str]:
    texto = normalizar_para_comparacao(titulo)

    padroes = [
        r"\b\d{1,5}[-–—]?[a-z]\b",     # 71-E
        r"\b\d{1,5}/\d{4}\b",          # 9/2026
        r"\b\d{1,4}\.\d{1,4}\b",       # 1.397
        r"\b\d{4}\b",                  # 2026
        r"\b\d{1,5}\b",                # 71, 1397 etc.
    ]

    encontrados = []

    for padrao in padroes:
        for item in re.findall(padrao, texto, flags=re.IGNORECASE):
            item = item.strip()

            if item and item not in encontrados:
                encontrados.append(item)

    return encontrados


def titulo_bate_exato_ou_equivalente(titulo_esperado: str, texto_candidato: str) -> bool:
    """
    Validação rígida, porém direta.

    Regras:
    - Se o título normalizado for igual: OK.
    - Se o título esperado estiver contido no texto candidato: OK.
    - Caso contrário, exige todos os números distintivos e alta presença
      dos tokens relevantes.

    Isso evita aceitar:
    - "Despacho de 15 de maio de 2026"
      quando o esperado é:
    - "Despacho do Diretor Presidente nº 71-E, de 14 de maio de 2026"
    """

    esperado = normalizar_para_comparacao(titulo_esperado)
    candidato = normalizar_para_comparacao(texto_candidato)

    if not esperado or not candidato:
        return False

    if esperado == candidato:
        return True

    if esperado in candidato:
        return True

    tokens = tokens_relevantes_titulo(titulo_esperado)
    numeros = extrair_numeros_distintivos(titulo_esperado)

    if not tokens:
        return False

    # Todos os números distintivos precisam aparecer.
    for numero in numeros:
        if numero not in candidato:
            return False

    presentes = [token for token in tokens if token in candidato]
    proporcao = len(presentes) / len(tokens)

    return proporcao >= 0.85


def avaliar_candidato(titulo: str, texto_link: str, href: str) -> dict[str, Any]:
    """
    Avaliação informativa. Não deve bloquear sozinha o candidato.

    A aprovação principal acontece por:
    - título do resultado bate com o título oficial;
    - página moderna abre e valida título/data.
    """

    combinado = f"{texto_link} {href}"
    combinado_norm = normalizar_para_comparacao(combinado)
    tokens = tokens_relevantes_titulo(titulo)
    numeros = extrair_numeros_distintivos(titulo)

    tokens_presentes = [token for token in tokens if token in combinado_norm]
    tokens_ausentes = [token for token in tokens if token not in combinado_norm]
    numeros_presentes = [numero for numero in numeros if numero in combinado_norm]
    numeros_ausentes = [numero for numero in numeros if numero not in combinado_norm]

    bate_titulo = titulo_bate_exato_ou_equivalente(titulo, texto_link)

    score = 0

    if bate_titulo:
        score += 300

    if tokens:
        score += int((len(tokens_presentes) / len(tokens)) * 120)

    if numeros:
        score += int((len(numeros_presentes) / len(numeros)) * 160)

    if "/lei-" in normalizar_para_comparacao(href) and "lei" not in normalizar_para_comparacao(titulo):
        score -= 100

    return {
        "score": score,
        "bate_titulo": bate_titulo,
        "tokens": tokens,
        "tokens_presentes": tokens_presentes,
        "tokens_ausentes": tokens_ausentes,
        "numeros": numeros,
        "numeros_presentes": numeros_presentes,
        "numeros_ausentes": numeros_ausentes,
        "aprovado_preliminar": bate_titulo,
    }


# Compatibilidade com versões anteriores que chamavam pontuar_candidato.
def pontuar_candidato(titulo: str, texto_link: str, href: str) -> dict[str, Any]:
    return avaliar_candidato(titulo, texto_link, href)


# ============================================================
# URL DA BUSCA AVANÇADA
# ============================================================

def montar_url_busca_dou(
    titulo: str,
    data_publicacao: datetime.date | str,
    usar_resultado_exato: bool = True,
) -> str:
    data_br = formatar_data_dou_url(data_publicacao)
    titulo_limpo = limpar_titulo(titulo)

    # Mapeamento validado:
    # Resultado exato usa q entre aspas.
    query = f'"{titulo_limpo}"' if usar_resultado_exato else titulo_limpo
    q = quote_plus(query)

    return (
        f"{BASE_BUSCA_DOU}"
        f"?q={q}"
        f"&s=todos"
        f"&exactDate=personalizado"
        f"&sortType=0"
        f"&publishFrom={data_br}"
        f"&publishTo={data_br}"
    )


def gerar_urls_busca_resolucao(titulo: str, data_publicacao: datetime.date | str) -> list[dict[str, Any]]:
    titulo_limpo = limpar_titulo(titulo)

    urls = [
        {
            "tipo": "BUSCA_AVANCADA_EXATA_TITULO_OFICIAL",
            "query": f'"{titulo_limpo}"',
            "url": montar_url_busca_dou(
                titulo=titulo_limpo,
                data_publicacao=data_publicacao,
                usar_resultado_exato=True,
            ),
        },
        {
            "tipo": "BUSCA_AVANCADA_TITULO_OFICIAL_SEM_ASPAS_FALLBACK",
            "query": titulo_limpo,
            "url": montar_url_busca_dou(
                titulo=titulo_limpo,
                data_publicacao=data_publicacao,
                usar_resultado_exato=False,
            ),
        },
    ]

    saida = []
    vistos = set()

    for item in urls:
        if item["url"] in vistos:
            continue

        vistos.add(item["url"])
        saida.append(item)

    return saida


# ============================================================
# PLAYWRIGHT HELPERS
# ============================================================

async def criar_contexto(browser: Browser) -> BrowserContext:
    return await browser.new_context(
        viewport=DEFAULT_VIEWPORT,
        locale=DEFAULT_LOCALE,
        timezone_id=DEFAULT_TIMEZONE,
        user_agent=DEFAULT_USER_AGENT,
    )


async def extrair_links_modernos(page: Page) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
            texto: (a.innerText || a.textContent || '').trim(),
            href: a.href
        })).filter(x => x.href && x.href.includes('/web/dou/-/'))
        """
    )


async def validar_pagina_moderno(
    context: BrowserContext,
    titulo: str,
    data_publicacao: datetime.date | str,
    url: str,
    secao: str | None = None,
    pagina: str | int | None = None,
    timeout_ms: int = 30000,
    exigir_secao_pagina: bool = False,
) -> dict[str, Any]:
    """
    Valida a página moderna.

    Título e data são obrigatórios para aprovação.
    Seção/página são verificadas e registradas quando informadas, mas por
    padrão não bloqueiam a aprovação, porque a página do visualizador do INLABS
    nem sempre equivale à página moderna exibida no portal.
    """

    page = await context.new_page()

    resultado = {
        "url": url,
        "url_final": "",
        "http_ok": False,
        "titulo_pagina": "",
        "bate_titulo": False,
        "bate_data": False,
        "bate_secao": False,
        "bate_pagina": False,
        "secao_informada": str(secao or ""),
        "pagina_informada": str(pagina or ""),
        "exigir_secao_pagina": exigir_secao_pagina,
        "aprovado": False,
        "motivos": [],
        "avisos": [],
        "erro": "",
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_timeout(2500)

        resultado["url_final"] = page.url
        resultado["titulo_pagina"] = await page.title()

        body_text = await page.locator("body").inner_text(timeout=10000)
        body_norm = normalizar_para_comparacao(body_text)

        titulo_ok = (
            titulo_bate_exato_ou_equivalente(titulo, resultado["titulo_pagina"])
            or titulo_bate_exato_ou_equivalente(titulo, body_text)
        )
        resultado["bate_titulo"] = titulo_ok

        if titulo_ok:
            resultado["motivos"].append("titulo_confirmado_na_pagina")

        data_texto = formatar_data_dou_texto(data_publicacao)
        data_ok = bool(data_texto and data_texto in body_text)
        resultado["bate_data"] = data_ok

        if data_ok:
            resultado["motivos"].append("data_publicacao_confirmada")

        secao_ok = True
        if secao not in [None, ""]:
            secao_txt = normalizar_secao(secao)
            padroes_secao = [
                f"seção: {secao_txt}",
                f"secao: {secao_txt}",
                f"seção {secao_txt}",
                f"secao {secao_txt}",
            ]
            secao_ok = any(
                normalizar_para_comparacao(padrao) in body_norm
                for padrao in padroes_secao
            )
            resultado["bate_secao"] = secao_ok

            if secao_ok:
                resultado["motivos"].append("secao_confirmada")
            else:
                resultado["avisos"].append("secao_nao_confirmada")
        else:
            resultado["bate_secao"] = True

        pagina_ok = True
        if pagina not in [None, ""]:
            pagina_txt = str(pagina).strip()
            padroes_pagina = [
                f"página: {pagina_txt}",
                f"pagina: {pagina_txt}",
                f"página {pagina_txt}",
                f"pagina {pagina_txt}",
            ]
            pagina_ok = any(
                normalizar_para_comparacao(padrao) in body_norm
                for padrao in padroes_pagina
            )
            resultado["bate_pagina"] = pagina_ok

            if pagina_ok:
                resultado["motivos"].append("pagina_confirmada")
            else:
                resultado["avisos"].append("pagina_nao_confirmada")
        else:
            resultado["bate_pagina"] = True

        resultado["http_ok"] = True

        if exigir_secao_pagina:
            resultado["aprovado"] = bool(
                resultado["http_ok"]
                and resultado["bate_titulo"]
                and resultado["bate_data"]
                and secao_ok
                and pagina_ok
            )
        else:
            resultado["aprovado"] = bool(
                resultado["http_ok"]
                and resultado["bate_titulo"]
                and resultado["bate_data"]
            )

        if resultado["aprovado"]:
            resultado["motivos"].append("link_moderno_validado")

    except Exception as erro:
        resultado["erro"] = str(erro)

    try:
        await page.close()
    except Exception:
        pass

    return resultado


# ============================================================
# RESOLUÇÃO UNITÁRIA
# ============================================================

async def resolver_link_moderno_dou_com_contexto(
    context: BrowserContext,
    page: Page,
    titulo: str,
    data_publicacao: datetime.date | str,
    secao: str | None = None,
    pagina: str | int | None = None,
    timeout_ms: int = 60000,
    espera_ms: int = 5000,
    validar_pagina: bool = True,
    exigir_secao_pagina: bool = False,
) -> dict[str, Any]:
    """
    Resolve usando um context/page já aberto.
    Use esta função para resolver em lote sem abrir/fechar navegador a cada publicação.
    """

    titulo = limpar_titulo(titulo)

    if not titulo:
        return {
            "status_resolucao_link": STATUS_SEM_TITULO,
            "url_publicacao_web": "",
            "mensagem": "Título vazio; não foi possível resolver link moderno.",
            "candidatos": [],
        }

    buscas = gerar_urls_busca_resolucao(titulo, data_publicacao)
    candidatos_globais: list[dict[str, Any]] = []

    try:
        for busca in buscas:
            url_busca = busca["url"]

            await page.goto(
                url_busca,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeoutError:
                pass

            await page.wait_for_timeout(espera_ms)

            url_final = page.url
            titulo_pagina = await page.title()

            if "LoginPortlet" in url_final or "liferay" in url_final.lower():
                return {
                    "status_resolucao_link": STATUS_LOGIN_LIFERAY,
                    "url_publicacao_web": "",
                    "mensagem": "Busca do DOU caiu em LoginPortlet/Liferay.",
                    "query_usada": busca["query"],
                    "tipo_busca": busca["tipo"],
                    "url_busca": url_busca,
                    "url_final": url_final,
                    "titulo_pagina": titulo_pagina,
                    "candidatos": candidatos_globais,
                }

            links = await extrair_links_modernos(page)
            candidatos_query = []

            for item in links:
                href = str(item.get("href") or "").strip()
                texto = str(item.get("texto") or "").strip()

                if not href:
                    continue

                avaliacao = avaliar_candidato(
                    titulo=titulo,
                    texto_link=texto,
                    href=href,
                )

                candidato = {
                    "query": busca["query"],
                    "tipo_busca": busca["tipo"],
                    "url_busca": url_busca,
                    "texto": texto,
                    "href": href,
                    "score": avaliacao["score"],
                    "bate_titulo": avaliacao["bate_titulo"],
                    "tokens_presentes": avaliacao["tokens_presentes"],
                    "tokens_ausentes": avaliacao["tokens_ausentes"],
                    "numeros_presentes": avaliacao["numeros_presentes"],
                    "numeros_ausentes": avaliacao["numeros_ausentes"],
                    "aprovado_preliminar": avaliacao["aprovado_preliminar"],
                }

                candidatos_query.append(candidato)
                candidatos_globais.append(candidato)

            # O filtro principal agora é "texto do resultado bate com o título".
            # Score é apenas informação/ordenação.
            candidatos_query.sort(key=lambda x: x.get("score", 0), reverse=True)

            for candidato in candidatos_query:
                if not candidato.get("bate_titulo"):
                    continue

                validacao = {}

                if validar_pagina:
                    validacao = await validar_pagina_moderno(
                        context=context,
                        titulo=titulo,
                        data_publicacao=data_publicacao,
                        url=candidato["href"],
                        secao=secao,
                        pagina=pagina,
                        timeout_ms=30000,
                        exigir_secao_pagina=exigir_secao_pagina,
                    )

                    candidato["validacao_pagina"] = validacao

                    if not validacao.get("aprovado"):
                        continue

                return {
                    "status_resolucao_link": STATUS_ENCONTRADO,
                    "url_publicacao_web": candidato["href"],
                    "mensagem": "Link moderno encontrado e validado pela busca avançada do DOU.",
                    "query_usada": candidato.get("query"),
                    "tipo_busca": candidato.get("tipo_busca"),
                    "url_busca": candidato.get("url_busca"),
                    "score": candidato.get("score"),
                    "texto_link": candidato.get("texto"),
                    "validacao_pagina": validacao,
                    "candidatos": candidatos_globais,
                }

    except PlaywrightTimeoutError as erro:
        return {
            "status_resolucao_link": STATUS_ERRO_TIMEOUT,
            "url_publicacao_web": "",
            "mensagem": str(erro),
            "candidatos": candidatos_globais,
        }

    except Exception as erro:
        return {
            "status_resolucao_link": STATUS_ERRO,
            "url_publicacao_web": "",
            "mensagem": str(erro),
            "candidatos": candidatos_globais,
        }

    candidatos_globais.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {
        "status_resolucao_link": STATUS_NAO_ENCONTRADO,
        "url_publicacao_web": "",
        "mensagem": "Nenhum link moderno validado com segurança.",
        "buscas_testadas": buscas,
        "candidatos": candidatos_globais,
    }


async def resolver_link_moderno_dou(
    titulo: str,
    data_publicacao: datetime.date | str,
    secao: str | None = None,
    pagina: str | int | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    espera_ms: int = 5000,
    validar_pagina: bool = True,
    exigir_secao_pagina: bool = False,
) -> dict[str, Any]:
    """
    Resolve o link moderno individual do DOU para uma publicação.

    Retorno principal:
    - status_resolucao_link: ENCONTRADO | NAO_ENCONTRADO | LOGIN_LIFERAY | ERRO_TIMEOUT | ERRO
    - url_publicacao_web: link moderno se encontrado e validado
    - candidatos: links analisados
    """

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)

            try:
                context = await criar_contexto(browser)
                page = await context.new_page()

                try:
                    return await resolver_link_moderno_dou_com_contexto(
                        context=context,
                        page=page,
                        titulo=titulo,
                        data_publicacao=data_publicacao,
                        secao=secao,
                        pagina=pagina,
                        timeout_ms=timeout_ms,
                        espera_ms=espera_ms,
                        validar_pagina=validar_pagina,
                        exigir_secao_pagina=exigir_secao_pagina,
                    )

                finally:
                    await context.close()

            finally:
                await browser.close()

    except PlaywrightTimeoutError as erro:
        return {
            "status_resolucao_link": STATUS_ERRO_TIMEOUT,
            "url_publicacao_web": "",
            "mensagem": str(erro),
            "candidatos": [],
        }

    except Exception as erro:
        return {
            "status_resolucao_link": STATUS_ERRO,
            "url_publicacao_web": "",
            "mensagem": str(erro),
            "candidatos": [],
        }


# ============================================================
# RESOLUÇÃO EM LOTE COM CACHE OPCIONAL
# ============================================================

def chave_cache_link(
    titulo: str,
    data_publicacao: datetime.date | str,
    secao: str | None = None,
    pagina: str | int | None = None,
) -> str:
    base = "|".join([
        normalizar_para_comparacao(titulo),
        formatar_data_dou_url(data_publicacao),
        normalizar_para_comparacao(secao or ""),
        normalizar_para_comparacao(pagina or ""),
    ])
    return base


def carregar_cache_links(caminho_cache: Path | None) -> dict[str, Any]:
    if not caminho_cache:
        return {}

    if not caminho_cache.exists():
        return {}

    try:
        return json.loads(caminho_cache.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_cache_links(caminho_cache: Path | None, cache: dict[str, Any]) -> None:
    if not caminho_cache:
        return

    caminho_cache.parent.mkdir(parents=True, exist_ok=True)
    caminho_cache.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def resolver_links_modernos_dou_lote(
    publicacoes: list[dict[str, Any]],
    data_publicacao: datetime.date | str,
    headless: bool = True,
    timeout_ms: int = 60000,
    espera_ms: int = 5000,
    validar_pagina: bool = True,
    caminho_cache: Path | None = None,
    exigir_secao_pagina: bool = False,
) -> list[dict[str, Any]]:
    """
    Resolve links em lote usando uma única sessão Playwright.

    Cada item de publicacoes pode conter:
    - titulo / titulo_publicacao
    - data_publicacao
    - secao
    - pagina

    Retorna lista de resultados na mesma ordem.
    """

    cache = carregar_cache_links(caminho_cache)
    resultados: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)

        try:
            context = await criar_contexto(browser)
            page = await context.new_page()

            try:
                for idx, publicacao in enumerate(publicacoes, start=1):
                    titulo = (
                        publicacao.get("titulo")
                        or publicacao.get("titulo_publicacao")
                        or publicacao.get("title")
                        or ""
                    )

                    data_item = (
                        publicacao.get("data_publicacao")
                        or publicacao.get("data")
                        or data_publicacao
                    )

                    secao = publicacao.get("secao") or publicacao.get("seção") or ""
                    pagina = publicacao.get("pagina") or publicacao.get("página") or ""

                    chave = chave_cache_link(
                        titulo=titulo,
                        data_publicacao=data_item,
                        secao=secao,
                        pagina=pagina,
                    )

                    if chave in cache:
                        resultado_cache = dict(cache[chave])
                        resultado_cache["origem_cache"] = True
                        resultado_cache["indice_lote"] = idx
                        resultados.append(resultado_cache)
                        continue

                    resultado = await resolver_link_moderno_dou_com_contexto(
                        context=context,
                        page=page,
                        titulo=titulo,
                        data_publicacao=data_item,
                        secao=secao,
                        pagina=pagina,
                        timeout_ms=timeout_ms,
                        espera_ms=espera_ms,
                        validar_pagina=validar_pagina,
                        exigir_secao_pagina=exigir_secao_pagina,
                    )

                    resultado["origem_cache"] = False
                    resultado["indice_lote"] = idx

                    resultados.append(resultado)

                    # Salva cache somente de resultado encontrado.
                    if resultado.get("status_resolucao_link") == STATUS_ENCONTRADO:
                        cache[chave] = resultado
                        salvar_cache_links(caminho_cache, cache)

            finally:
                await context.close()

        finally:
            await browser.close()

    salvar_cache_links(caminho_cache, cache)
    return resultados


# ============================================================
# WRAPPER SÍNCRONO OPCIONAL
# ============================================================

def resolver_link_moderno_dou_sync(
    titulo: str,
    data_publicacao: datetime.date | str,
    secao: str | None = None,
    pagina: str | int | None = None,
    headless: bool = True,
    timeout_ms: int = 60000,
    espera_ms: int = 5000,
    validar_pagina: bool = True,
    exigir_secao_pagina: bool = False,
) -> dict[str, Any]:
    """
    Wrapper síncrono para chamadas em código que ainda não usa async.
    """

    return asyncio.run(
        resolver_link_moderno_dou(
            titulo=titulo,
            data_publicacao=data_publicacao,
            secao=secao,
            pagina=pagina,
            headless=headless,
            timeout_ms=timeout_ms,
            espera_ms=espera_ms,
            validar_pagina=validar_pagina,
            exigir_secao_pagina=exigir_secao_pagina,
        )
    )
