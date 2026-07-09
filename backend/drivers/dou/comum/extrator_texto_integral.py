# ============================================================
# DRIVER COMUM — Extrator Texto Integral DOU
# Extrai conteúdo completo das publicações
# ============================================================

import asyncio
import datetime
import traceback

import httpx

from backend.services.parser_html_dou import extrair_publicacao_html


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0 Safari/537.36"
    )
}


DEFAULT_TIMEOUT = 60
DEFAULT_MAX_CONCORRENCIA = 5


async def baixar_html(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> str:
    """
    Faz download do HTML da publicação.

    Mantém compatibilidade:
    - Se receber um client externo, reutiliza a sessão HTTP.
    - Se não receber, cria um client próprio, como antes.
    """

    if client is not None:
        response = await client.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=timeout,
    ) as client_local:
        response = await client_local.get(url)
        response.raise_for_status()
        return response.text


async def extrair_publicacao(
    url: str,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """
    Extrai integralmente uma publicação do DOU.
    """
    inicio = datetime.datetime.now()

    try:
        html = await baixar_html(url, client=client)

        estruturado = extrair_publicacao_html(html)

        texto_integral = estruturado.get("texto_completo", "")
        tabelas = estruturado.get("tabelas", [])

        fim = datetime.datetime.now()
        duracao = (fim - inicio).total_seconds()

        return {
            "url": url,
            "titulo": estruturado.get("titulo", ""),
            "orgao": estruturado.get("orgao", ""),
            "publicado_em": estruturado.get("publicado_em", ""),
            "secao": estruturado.get("secao", ""),
            "pagina": estruturado.get("pagina", ""),
            "edicao": estruturado.get("edicao", ""),
            "publicacao": estruturado.get("publicado_em", ""),
            "texto_integral": texto_integral,
            "texto_normalizado": estruturado.get("texto_normalizado", ""),
            "texto_html": html,
            "blocos": estruturado.get("blocos", []),
            "assinaturas": estruturado.get("assinaturas", []),
            "tabelas": tabelas,
            "tabelas_html": [
                tabela.get("html", "")
                for tabela in tabelas
                if tabela.get("html")
            ],
            "status_parser": estruturado.get("status_parser", ""),
            "status_extracao": "SUCESSO",
            "erro": None,
            "traceback": None,
            "duracao_segundos": duracao,
            "tamanho_texto": len(texto_integral),
            "quantidade_blocos": len(estruturado.get("blocos", [])),
            "quantidade_tabelas": len(tabelas),
            "quantidade_assinaturas": len(estruturado.get("assinaturas", [])),
        }

    except Exception as e:
        fim = datetime.datetime.now()
        duracao = (fim - inicio).total_seconds()

        return {
            "url": url,
            "titulo": "",
            "orgao": "",
            "publicado_em": "",
            "secao": "",
            "pagina": "",
            "edicao": "",
            "publicacao": "",
            "texto_integral": "",
            "texto_normalizado": "",
            "texto_html": "",
            "blocos": [],
            "assinaturas": [],
            "tabelas": [],
            "tabelas_html": [],
            "status_parser": "ERRO",
            "status_extracao": "ERRO",
            "erro": str(e),
            "traceback": traceback.format_exc(),
            "duracao_segundos": duracao,
            "tamanho_texto": 0,
            "quantidade_blocos": 0,
            "quantidade_tabelas": 0,
            "quantidade_assinaturas": 0,
        }


async def _extrair_publicacao_com_limite(
    indice: int,
    total: int,
    url: str,
    semaphore: asyncio.Semaphore,
    client: httpx.AsyncClient,
) -> tuple[int, dict]:
    """
    Executa a extração de uma publicação respeitando o limite de concorrência.

    Retorna o índice original junto com o resultado para preservar a ordem
    final dos links no JSON.
    """

    async with semaphore:
        print(f"[EXTRACAO] {indice + 1}/{total} | INICIANDO")

        resultado = await extrair_publicacao(
            url=url,
            client=client,
        )

        print(
            f"[EXTRACAO] {indice + 1}/{total} | "
            f"status={resultado['status_extracao']} | "
            f"parser={resultado.get('status_parser')} | "
            f"titulo={resultado.get('titulo', '')[:80]} | "
            f"orgao={resultado.get('orgao', '')[:80]}"
        )

        return indice, resultado


async def extrair_multiplas_publicacoes(
    urls: list[str],
    limite: int | None = None,
    max_concorrencia: int = DEFAULT_MAX_CONCORRENCIA,
) -> list[dict]:
    """
    Extrai múltiplas publicações em paralelo com limite de concorrência.

    Mantém compatibilidade com chamadas antigas:

        await extrair_multiplas_publicacoes(urls=urls, limite=limite)

    Nova opção:

        await extrair_multiplas_publicacoes(
            urls=urls,
            limite=limite,
            max_concorrencia=3,
        )

    Regras preservadas:
    - mantém a ordem original dos links no resultado final;
    - não derruba a execução inteira se uma publicação falhar;
    - cada publicação continua retornando status_extracao SUCESSO ou ERRO;
    - mantém o mesmo formato de saída usado pelo restante do pipeline.
    """

    if limite:
        urls = urls[:limite]

    total = len(urls)

    if total == 0:
        return []

    if max_concorrencia is None or max_concorrencia < 1:
        max_concorrencia = 1

    print(
        f"[EXTRACAO] Total de publicações: {total} | "
        f"Concorrência máxima: {max_concorrencia}"
    )

    semaphore = asyncio.Semaphore(max_concorrencia)

    limites_http = httpx.Limits(
        max_connections=max_concorrencia,
        max_keepalive_connections=max_concorrencia,
    )

    timeout = httpx.Timeout(DEFAULT_TIMEOUT)

    resultados_ordenados: list[dict | None] = [None] * total

    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=timeout,
        limits=limites_http,
    ) as client:

        tarefas = [
            _extrair_publicacao_com_limite(
                indice=indice,
                total=total,
                url=url,
                semaphore=semaphore,
                client=client,
            )
            for indice, url in enumerate(urls)
        ]

        resultados = await asyncio.gather(
            *tarefas,
            return_exceptions=True,
        )

    for item in resultados:
        if isinstance(item, Exception):
            resultado_erro = {
                "url": "",
                "titulo": "",
                "orgao": "",
                "publicado_em": "",
                "secao": "",
                "pagina": "",
                "edicao": "",
                "publicacao": "",
                "texto_integral": "",
                "texto_normalizado": "",
                "texto_html": "",
                "blocos": [],
                "assinaturas": [],
                "tabelas": [],
                "tabelas_html": [],
                "status_parser": "ERRO",
                "status_extracao": "ERRO",
                "erro": str(item),
                "traceback": traceback.format_exc(),
                "duracao_segundos": 0,
                "tamanho_texto": 0,
                "quantidade_blocos": 0,
                "quantidade_tabelas": 0,
                "quantidade_assinaturas": 0,
            }

            for posicao, valor in enumerate(resultados_ordenados):
                if valor is None:
                    resultados_ordenados[posicao] = resultado_erro
                    break

            continue

        indice, resultado = item
        resultados_ordenados[indice] = resultado

    return [
        resultado
        for resultado in resultados_ordenados
        if resultado is not None
    ]