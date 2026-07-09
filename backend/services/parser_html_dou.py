# ============================================================
# SERVICE — Parser HTML DOU
# Extrai publicação estruturada a partir do HTML bruto
# ============================================================

import re
import unicodedata
from bs4 import BeautifulSoup


def limpar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)

    linhas = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if linha:
            linhas.append(linha)

    return "\n".join(linhas).strip()


def limpar_texto_linha(texto: str) -> str:
    if not texto:
        return ""

    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ASCII", "ignore").decode("utf-8")
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def texto_de(soup, seletor: str) -> str:
    el = soup.select_one(seletor)
    if not el:
        return ""

    return limpar_texto_linha(el.get_text(" ", strip=True))


def extrair_titulo(article) -> str:
    candidatos = [
        ".texto-dou p.identifica",
        ".portlet-title-text.border-bottom-0",
        ".dou-modelo h2.portlet-title-text",
        "h2.portlet-title-text",
    ]

    for seletor in candidatos:
        el = article.select_one(seletor)
        if el:
            texto = limpar_texto_linha(el.get_text(" ", strip=True))
            if texto and texto.lower() not in {
                "diário oficial da união",
                "diario oficial da uniao",
            }:
                return texto

    return ""


def extrair_metadados(article) -> dict:
    publicado_em = texto_de(article, ".publicado-dou-data")
    edicao = texto_de(article, ".edicao-dou-data")
    pagina = texto_de(article, ".secao-dou-data")
    orgao = texto_de(article, ".orgao-dou-data")

    secao = ""

    for span in article.select(".secao-dou"):
        texto = limpar_texto_linha(span.get_text(" ", strip=True))

        if texto.startswith("Seção:"):
            secao = texto.replace("Seção:", "").strip()
            break

    return {
        "publicado_em": publicado_em,
        "edicao": edicao,
        "secao": secao,
        "pagina": pagina,
        "orgao": orgao,
    }


def extrair_blocos_texto(article) -> list[dict]:
    blocos = []

    texto_dou = article.select_one(".texto-dou")

    if not texto_dou:
        return blocos

    for tag in texto_dou.find_all(["p", "div", "li", "blockquote"], recursive=True):
        texto = limpar_texto_linha(tag.get_text(" ", strip=True))

        if not texto:
            continue

        if len(texto) < 2:
            continue

        classe = " ".join(tag.get("class", []))

        tipo = "texto"

        if "identifica" in classe:
            tipo = "titulo"
        elif "assina" in classe:
            tipo = "assinatura"
        elif "cargo" in classe:
            tipo = "cargo"
        elif "dou-paragraph" in classe:
            tipo = "paragrafo"

        blocos.append({
            "tipo": tipo,
            "tag": tag.name,
            "classe": classe,
            "texto": texto,
        })

    return blocos


def extrair_assinaturas(blocos: list[dict]) -> list[str]:
    assinaturas = []

    for bloco in blocos:
        if bloco.get("tipo") == "assinatura":
            texto = bloco.get("texto", "").strip()
            if texto:
                assinaturas.append(texto)

    return assinaturas


def extrair_tabelas(article) -> list[dict]:
    tabelas = []

    texto_dou = article.select_one(".texto-dou")

    if not texto_dou:
        return tabelas

    for idx, table in enumerate(texto_dou.find_all("table"), start=1):
        linhas = []

        for tr in table.find_all("tr"):
            colunas = []

            for celula in tr.find_all(["td", "th"]):
                colunas.append(
                    limpar_texto_linha(celula.get_text(" ", strip=True))
                )

            if colunas:
                linhas.append(colunas)

        if linhas:
            tabelas.append({
                "indice": idx,
                "linhas": linhas,
                "html": str(table),
            })

    return tabelas


def montar_texto_completo(titulo: str, metadados: dict, blocos: list[dict]) -> str:
    partes = []

    if titulo:
        partes.append(titulo)

    if metadados.get("orgao"):
        partes.append(metadados["orgao"])

    for bloco in blocos:
        texto = bloco.get("texto", "")
        if texto:
            partes.append(texto)

    return limpar_texto("\n".join(partes))


def extrair_publicacao_html(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")

    article = soup.select_one("article#materia")

    if not article:
        article = soup.find("article")

    if not article:
        return {
            "titulo": "",
            "orgao": "",
            "publicado_em": "",
            "edicao": "",
            "secao": "",
            "pagina": "",
            "texto_completo": "",
            "texto_normalizado": "",
            "blocos": [],
            "tabelas": [],
            "assinaturas": [],
            "status_parser": "SEM_ARTICLE",
        }

    titulo = extrair_titulo(article)
    metadados = extrair_metadados(article)
    blocos = extrair_blocos_texto(article)
    tabelas = extrair_tabelas(article)
    assinaturas = extrair_assinaturas(blocos)
    texto_completo = montar_texto_completo(titulo, metadados, blocos)

    return {
        "titulo": titulo,
        "orgao": metadados.get("orgao", ""),
        "publicado_em": metadados.get("publicado_em", ""),
        "edicao": metadados.get("edicao", ""),
        "secao": metadados.get("secao", ""),
        "pagina": metadados.get("pagina", ""),
        "texto_completo": texto_completo,
        "texto_normalizado": normalizar_texto(texto_completo),
        "blocos": blocos,
        "tabelas": tabelas,
        "assinaturas": assinaturas,
        "status_parser": "SUCESSO",
    }