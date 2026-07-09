# ============================================================
# RUNNER — Auditoria Profunda INLABS x Link Moderno DOU
# Projeto Informativos / DOU
#
# Objetivo:
# - Ler TODOS os ZIPs/XMLs do INLABS baixados para uma data.
# - Procurar uma publicação específica em todo o conteúdo bruto.
# - Verificar se existe:
#     1. link moderno /web/dou/-/
#     2. ID moderno do portal
#     3. URL antiga do visualizador pesquisa.in.gov.br
#     4. atributos/tags/metadados que ajudem a montar o link perfeito
#     5. agrupamento de XMLs relacionados pelo mesmo ID interno do INLABS
#
# Importante:
# - NÃO altera base, match, e-mail, relatório ou orquestrador.
# - Apenas gera diagnóstico JSON/TXT.
# ============================================================

import datetime
import html
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET


# ============================================================
# CONFIGURAÇÃO
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 15)

# Publicação que queremos auditar.
# Pode alterar para outro título depois.
TITULO_ALVO = "Edital de Notificação nº 9/2026 - Dipro"

# Link moderno esperado, se você tiver.
URL_MODERNA_ESPERADA = (
    "https://www.in.gov.br/web/dou/-/edital-de-notificacao-n-9/2026-dipro-705977328"
)

# ID moderno esperado, se você tiver.
ID_MODERNO_ESPERADO = "705977328"

# Termos simples e sem acento para localizar a publicação.
# Todos os termos devem existir no XML para ser considerado "match direto".
TERMOS_OBRIGATORIOS = ["edital", "dipro"]

# Termos complementares para ajudar no relatório.
TERMOS_COMPLEMENTARES = ["9/2026", "notificacao", "notificação", "dipro"]

ROOT_DIR = Path(__file__).resolve().parents[2]

ZIP_DIR = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "inlabs"
    / DATA_EXECUCAO.isoformat()
    / "zips"
)

SAIDA_DIR = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "debug"
    / "auditoria_inlabs_link_moderno"
)

SAIDA_DIR.mkdir(parents=True, exist_ok=True)

SAIDA_JSON = SAIDA_DIR / f"auditoria_inlabs_link_moderno_{DATA_EXECUCAO.isoformat()}.json"
SAIDA_TXT = SAIDA_DIR / f"auditoria_inlabs_link_moderno_{DATA_EXECUCAO.isoformat()}.txt"
SAIDA_XMLS_TXT = SAIDA_DIR / f"auditoria_inlabs_xmls_relacionados_{DATA_EXECUCAO.isoformat()}.txt"


# ============================================================
# NORMALIZAÇÃO / UTILITÁRIOS
# ============================================================

def normalizar_texto(valor) -> str:
    texto = str(valor or "")
    texto = html.unescape(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = texto.replace("º", "")
    texto = texto.replace("°", "")
    texto = texto.replace("ª", "")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpar_tag(tag: str) -> str:
    tag = str(tag or "")
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def texto_elemento(elemento) -> str:
    partes = []
    for txt in elemento.itertext():
        txt = str(txt or "").strip()
        if txt:
            partes.append(txt)
    return " ".join(partes).strip()


def extrair_tag_exata(root, nome_tag: str) -> str:
    nome_tag_norm = nome_tag.lower()
    for el in root.iter():
        if limpar_tag(el.tag).lower() == nome_tag_norm:
            return texto_elemento(el)
    return ""


def id_interno_por_nome_xml(nome_xml: str) -> str:
    """
    Exemplos:
    530_20260515_23939787-1.xml -> 23939787
    515_20260515_705704735.xml  -> 705704735
    """
    stem = Path(str(nome_xml or "")).stem

    # Prioriza o padrão final depois da data.
    m = re.search(r"_(\d{6,12})(?:-\d+)?$", stem)
    if m:
        return m.group(1)

    achados = re.findall(r"\d{6,12}", stem)
    return achados[-1] if achados else ""


def parte_por_nome_xml(nome_xml: str) -> str:
    stem = Path(str(nome_xml or "")).stem
    m = re.search(r"-(\d+)$", stem)
    return m.group(1) if m else ""


def extrair_urls(texto: str) -> list[str]:
    texto = html.unescape(str(texto or ""))

    candidatos = re.findall(
        r"(https?://[^\s\"'<>]+|www\.[^\s\"'<>]+|/[a-zA-Z0-9_\-/]+(?:\?[^\s\"'<>]+)?)",
        texto,
        flags=re.IGNORECASE,
    )

    urls = []

    for url in candidatos:
        url = html.unescape(url).strip()

        if not url:
            continue

        # Limpeza comum quando URL vem colada com pontuação HTML/texto.
        url = url.rstrip(").,;")

        if url not in urls:
            urls.append(url)

    return urls


def classificar_url(url: str) -> str:
    url_lower = str(url or "").lower()

    if "/web/dou/-/" in url_lower:
        return "LINK_MODERNO_WEB_DOU"

    if "pesquisa.in.gov.br/imprensa/jsp/visualiza" in url_lower:
        return "LINK_VISUALIZADOR_PAGINA_DOU"

    if "in.gov.br/consulta" in url_lower:
        return "LINK_BUSCA_DOU"

    if "in.gov.br" in url_lower:
        return "LINK_IN_GOV_BR_OUTRO"

    if "gov.br" in url_lower:
        return "LINK_GOV_BR_OUTRO"

    if url_lower.startswith("http"):
        return "LINK_EXTERNO_HTTP"

    if url_lower.startswith("/"):
        return "CAMINHO_RELATIVO"

    return "OUTRO"


def parametros_url(url: str) -> dict:
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return {
            "scheme": parsed.scheme,
            "host": parsed.netloc,
            "path": parsed.path,
            "data": (query.get("data") or [""])[0],
            "jornal": (query.get("jornal") or [""])[0],
            "pagina": (query.get("pagina") or [""])[0],
            "query": parsed.query,
        }
    except Exception:
        return {}


def extrair_ids_numericos(texto: str) -> list[str]:
    texto = str(texto or "")

    # IDs possíveis de matéria costumam ter 6 a 12 dígitos.
    ids = re.findall(r"\b\d{6,12}\b", texto)

    saida = []
    for item in ids:
        if item not in saida:
            saida.append(item)

    return saida


def snippets_ao_redor(texto: str, termos: list[str], margem: int = 350) -> list[dict]:
    texto_original = str(texto or "")
    texto_norm = normalizar_texto(texto_original)

    snippets = []

    for termo in termos:
        termo_norm = normalizar_texto(termo)

        if not termo_norm:
            continue

        pos = texto_norm.find(termo_norm)

        if pos < 0:
            continue

        inicio = max(0, pos - margem)
        fim = min(len(texto_original), pos + len(termo) + margem)

        snippets.append({
            "termo": termo,
            "inicio_aproximado": inicio,
            "fim_aproximado": fim,
            "snippet": texto_original[inicio:fim],
        })

    return snippets


def contem_termos_obrigatorios(texto: str) -> bool:
    texto_norm = normalizar_texto(texto)
    return all(normalizar_texto(t) in texto_norm for t in TERMOS_OBRIGATORIOS)


def contem_qualquer_identificador_alvo(texto: str) -> bool:
    texto_raw = str(texto or "")
    texto_norm = normalizar_texto(texto_raw)

    if URL_MODERNA_ESPERADA and URL_MODERNA_ESPERADA in texto_raw:
        return True

    if ID_MODERNO_ESPERADO and ID_MODERNO_ESPERADO in texto_raw:
        return True

    if normalizar_texto(TITULO_ALVO) and normalizar_texto(TITULO_ALVO) in texto_norm:
        return True

    return contem_termos_obrigatorios(texto_raw)


def tentar_parse_xml(xml_raw: str):
    try:
        return ET.fromstring(xml_raw), ""
    except Exception as erro:
        return None, str(erro)


def analisar_xml(nome_zip: str, nome_xml: str, xml_bytes: bytes) -> dict:
    xml_raw = xml_bytes.decode("utf-8", errors="ignore")
    xml_unescape = html.unescape(xml_raw)
    root, erro_parse = tentar_parse_xml(xml_raw)

    id_interno = id_interno_por_nome_xml(nome_xml)
    parte = parte_por_nome_xml(nome_xml)

    urls = extrair_urls(xml_unescape)
    urls_classificadas = [
        {
            "url": url,
            "tipo": classificar_url(url),
            "parametros": parametros_url(url),
        }
        for url in urls
    ]

    ids_no_xml = extrair_ids_numericos(xml_unescape)
    ids_no_nome = extrair_ids_numericos(nome_xml)

    tags = Counter()
    atributos = []
    atributos_relevantes = []

    campos = {
        "Identifica": "",
        "Data": "",
        "Ementa": "",
        "Titulo": "",
        "SubTitulo": "",
        "Texto_preview": "",
    }

    root_atributos = {}

    if root is not None:
        root_atributos = dict(root.attrib or {})

        for el in root.iter():
            tag = limpar_tag(el.tag)
            tags[tag] += 1

            for attr, valor in (el.attrib or {}).items():
                item = {
                    "tag": tag,
                    "atributo": attr,
                    "valor": valor,
                }
                atributos.append(item)

                texto_attr_norm = normalizar_texto(f"{attr}={valor}")

                if any(chave in texto_attr_norm for chave in [
                    "href", "url", "link", "src", "uri", "materia",
                    "article", "friendly", "dou", "id",
                ]):
                    atributos_relevantes.append(item)

        campos["Identifica"] = extrair_tag_exata(root, "Identifica")
        campos["Data"] = extrair_tag_exata(root, "Data")
        campos["Ementa"] = extrair_tag_exata(root, "Ementa")
        campos["Titulo"] = extrair_tag_exata(root, "Titulo")
        campos["SubTitulo"] = extrair_tag_exata(root, "SubTitulo")

        texto_tag = extrair_tag_exata(root, "Texto")
        campos["Texto_preview"] = html.unescape(texto_tag)[:2500]

    termos_snippet = [
        TITULO_ALVO,
        ID_MODERNO_ESPERADO,
        URL_MODERNA_ESPERADA,
        *TERMOS_COMPLEMENTARES,
        "web/dou",
        "visualiza/index.jsp",
        "article",
        "friendly",
        "url",
        "href",
    ]

    return {
        "zip": nome_zip,
        "xml": nome_xml,
        "id_interno_nome_xml": id_interno,
        "parte_nome_xml": parte,
        "xml_valido": root is not None,
        "erro_parse": erro_parse,
        "root_tag": limpar_tag(root.tag) if root is not None else "",
        "root_atributos": root_atributos,
        "tags": dict(tags),
        "campos": campos,
        "urls": urls_classificadas,
        "total_urls": len(urls_classificadas),
        "tem_url_moderna_web_dou": any(u["tipo"] == "LINK_MODERNO_WEB_DOU" for u in urls_classificadas),
        "tem_url_visualizador_pagina_dou": any(u["tipo"] == "LINK_VISUALIZADOR_PAGINA_DOU" for u in urls_classificadas),
        "atributos_total": len(atributos),
        "atributos_relevantes": atributos_relevantes,
        "ids_no_nome_xml": ids_no_nome,
        "ids_no_xml": ids_no_xml[:200],
        "tem_id_moderno_esperado": bool(ID_MODERNO_ESPERADO and ID_MODERNO_ESPERADO in xml_unescape),
        "tem_url_moderna_esperada": bool(URL_MODERNA_ESPERADA and URL_MODERNA_ESPERADA in xml_unescape),
        "tem_titulo_alvo": normalizar_texto(TITULO_ALVO) in normalizar_texto(xml_unescape),
        "tem_termos_obrigatorios": contem_termos_obrigatorios(xml_unescape),
        "snippets": snippets_ao_redor(xml_unescape, termos_snippet),
        "xml_raw_preview": xml_unescape[:5000],
    }


# ============================================================
# EXECUÇÃO
# ============================================================

def main():
    print("=" * 80)
    print("AUDITORIA PROFUNDA INLABS x LINK MODERNO DOU")
    print("=" * 80)
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Título alvo: {TITULO_ALVO}")
    print(f"URL moderna esperada: {URL_MODERNA_ESPERADA}")
    print(f"ID moderno esperado: {ID_MODERNO_ESPERADO}")
    print(f"ZIP_DIR: {ZIP_DIR}")
    print("=" * 80)

    if not ZIP_DIR.exists():
        raise FileNotFoundError(f"Pasta de ZIPs não encontrada: {ZIP_DIR}")

    zips = sorted(ZIP_DIR.glob("*.zip"))

    if not zips:
        raise FileNotFoundError(f"Nenhum ZIP encontrado em: {ZIP_DIR}")

    todos_xmls_resumo = []
    achados_diretos = []
    xmls_por_id_interno = defaultdict(list)

    total_xmls = 0
    total_com_url_moderna = 0
    total_com_url_visualizador = 0
    total_com_id_moderno_esperado = 0
    total_com_url_moderna_esperada = 0

    print("[1/3] Lendo todos os XMLs do INLABS...")

    for zip_path in zips:
        print(f"  - {zip_path.name}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            nomes_xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]

            for nome_xml in nomes_xml:
                total_xmls += 1
                xml_bytes = zf.read(nome_xml)
                item = analisar_xml(zip_path.name, nome_xml, xml_bytes)

                resumo = {
                    "zip": item["zip"],
                    "xml": item["xml"],
                    "id_interno_nome_xml": item["id_interno_nome_xml"],
                    "parte_nome_xml": item["parte_nome_xml"],
                    "xml_valido": item["xml_valido"],
                    "identifica": item["campos"].get("Identifica"),
                    "titulo": item["campos"].get("Titulo"),
                    "tem_url_moderna_web_dou": item["tem_url_moderna_web_dou"],
                    "tem_url_visualizador_pagina_dou": item["tem_url_visualizador_pagina_dou"],
                    "tem_id_moderno_esperado": item["tem_id_moderno_esperado"],
                    "tem_url_moderna_esperada": item["tem_url_moderna_esperada"],
                    "tem_titulo_alvo": item["tem_titulo_alvo"],
                    "tem_termos_obrigatorios": item["tem_termos_obrigatorios"],
                    "urls": item["urls"],
                    "ids_no_nome_xml": item["ids_no_nome_xml"],
                    "ids_no_xml_amostra": item["ids_no_xml"][:20],
                }
                todos_xmls_resumo.append(resumo)

                if item["tem_url_moderna_web_dou"]:
                    total_com_url_moderna += 1

                if item["tem_url_visualizador_pagina_dou"]:
                    total_com_url_visualizador += 1

                if item["tem_id_moderno_esperado"]:
                    total_com_id_moderno_esperado += 1

                if item["tem_url_moderna_esperada"]:
                    total_com_url_moderna_esperada += 1

                if item["id_interno_nome_xml"]:
                    xmls_por_id_interno[item["id_interno_nome_xml"]].append(item)

                if (
                    item["tem_titulo_alvo"]
                    or item["tem_termos_obrigatorios"]
                    or item["tem_id_moderno_esperado"]
                    or item["tem_url_moderna_esperada"]
                ):
                    achados_diretos.append(item)

    print("[2/3] Identificando grupos relacionados...")

    ids_achados = sorted({
        item["id_interno_nome_xml"]
        for item in achados_diretos
        if item.get("id_interno_nome_xml")
    })

    grupos_relacionados = {}

    for id_interno in ids_achados:
        grupo = xmls_por_id_interno.get(id_interno, [])

        grupos_relacionados[id_interno] = {
            "id_interno": id_interno,
            "total_xmls_grupo": len(grupo),
            "xmls": grupo,
        }

    # Também verifica se o ID moderno esperado aparece como ID interno de algum XML.
    grupo_id_moderno = xmls_por_id_interno.get(ID_MODERNO_ESPERADO, [])

    conclusao = {
        "url_moderna_esperada_existe_no_xml": total_com_url_moderna_esperada > 0,
        "id_moderno_esperado_existe_no_conteudo_xml": total_com_id_moderno_esperado > 0,
        "id_moderno_esperado_existe_como_id_interno_nome_xml": len(grupo_id_moderno) > 0,
        "algum_xml_tem_link_moderno_web_dou": total_com_url_moderna > 0,
        "xmls_da_publicacao_encontrados": len(achados_diretos),
        "ids_internos_relacionados_encontrados": ids_achados,
    }

    if conclusao["url_moderna_esperada_existe_no_xml"]:
        conclusao["resultado"] = "LINK_MODERNO_COMPLETO_EXISTE_NO_INLABS"
    elif conclusao["id_moderno_esperado_existe_no_conteudo_xml"]:
        conclusao["resultado"] = "ID_MODERNO_EXISTE_NO_CONTEUDO_XML_MAS_LINK_NAO"
    elif conclusao["id_moderno_esperado_existe_como_id_interno_nome_xml"]:
        conclusao["resultado"] = "ID_MODERNO_EXISTE_COMO_ID_INTERNO_DO_XML"
    elif achados_diretos:
        conclusao["resultado"] = "PUBLICACAO_EXISTE_NO_INLABS_MAS_SEM_ID_LINK_MODERNO"
    else:
        conclusao["resultado"] = "PUBLICACAO_NAO_LOCALIZADA_COM_CRITERIOS_ATUAIS"

    print("[3/3] Salvando diagnóstico...")

    payload = {
        "data": DATA_EXECUCAO.isoformat(),
        "titulo_alvo": TITULO_ALVO,
        "url_moderna_esperada": URL_MODERNA_ESPERADA,
        "id_moderno_esperado": ID_MODERNO_ESPERADO,
        "zip_dir": str(ZIP_DIR),
        "totais": {
            "zips": len(zips),
            "xmls_total": total_xmls,
            "xmls_com_url_moderna_web_dou": total_com_url_moderna,
            "xmls_com_url_visualizador_pagina_dou": total_com_url_visualizador,
            "xmls_com_id_moderno_esperado": total_com_id_moderno_esperado,
            "xmls_com_url_moderna_esperada": total_com_url_moderna_esperada,
            "achados_diretos": len(achados_diretos),
            "ids_internos_relacionados": ids_achados,
        },
        "conclusao": conclusao,
        "achados_diretos": achados_diretos,
        "grupos_relacionados": grupos_relacionados,
        "grupo_id_moderno_esperado_como_id_interno": grupo_id_moderno,
        "todos_xmls_resumo": todos_xmls_resumo,
    }

    SAIDA_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = []
    linhas.append("=" * 80)
    linhas.append("AUDITORIA PROFUNDA INLABS x LINK MODERNO DOU")
    linhas.append("=" * 80)
    linhas.append(f"Data: {DATA_EXECUCAO.isoformat()}")
    linhas.append(f"Título alvo: {TITULO_ALVO}")
    linhas.append(f"URL moderna esperada: {URL_MODERNA_ESPERADA}")
    linhas.append(f"ID moderno esperado: {ID_MODERNO_ESPERADO}")
    linhas.append(f"ZIP_DIR: {ZIP_DIR}")
    linhas.append("")
    linhas.append("TOTAIS")
    linhas.append("-" * 80)
    linhas.append(f"Zips: {len(zips)}")
    linhas.append(f"XMLs total: {total_xmls}")
    linhas.append(f"XMLs com link moderno /web/dou/-/: {total_com_url_moderna}")
    linhas.append(f"XMLs com link visualizador página DOU: {total_com_url_visualizador}")
    linhas.append(f"XMLs com ID moderno esperado no conteúdo: {total_com_id_moderno_esperado}")
    linhas.append(f"XMLs com URL moderna esperada no conteúdo: {total_com_url_moderna_esperada}")
    linhas.append(f"Achados diretos da publicação: {len(achados_diretos)}")
    linhas.append(f"IDs internos relacionados: {', '.join(ids_achados) if ids_achados else '-'}")
    linhas.append("")
    linhas.append("CONCLUSÃO")
    linhas.append("-" * 80)
    for chave, valor in conclusao.items():
        linhas.append(f"{chave}: {valor}")

    linhas.append("")
    linhas.append("ACHADOS DIRETOS")
    linhas.append("=" * 80)

    for i, item in enumerate(achados_diretos, start=1):
        linhas.append(f"ACHADO {i}")
        linhas.append("-" * 80)
        linhas.append(f"ZIP: {item.get('zip')}")
        linhas.append(f"XML: {item.get('xml')}")
        linhas.append(f"ID interno nome XML: {item.get('id_interno_nome_xml')}")
        linhas.append(f"Parte nome XML: {item.get('parte_nome_xml')}")
        linhas.append(f"Identifica: {item.get('campos', {}).get('Identifica')}")
        linhas.append(f"Titulo: {item.get('campos', {}).get('Titulo')}")
        linhas.append(f"Ementa: {item.get('campos', {}).get('Ementa')}")
        linhas.append(f"Data: {item.get('campos', {}).get('Data')}")
        linhas.append(f"Tem URL moderna esperada: {item.get('tem_url_moderna_esperada')}")
        linhas.append(f"Tem ID moderno esperado: {item.get('tem_id_moderno_esperado')}")
        linhas.append(f"Tem URL moderna /web/dou/-/: {item.get('tem_url_moderna_web_dou')}")
        linhas.append(f"Tem URL visualizador página DOU: {item.get('tem_url_visualizador_pagina_dou')}")
        linhas.append("URLs:")
        for u in item.get("urls", []):
            linhas.append(f"  - [{u.get('tipo')}] {u.get('url')} | params={u.get('parametros')}")
        linhas.append("Atributos relevantes:")
        if item.get("atributos_relevantes"):
            for attr in item.get("atributos_relevantes", []):
                linhas.append(f"  - tag={attr.get('tag')} | {attr.get('atributo')}={attr.get('valor')}")
        else:
            linhas.append("  - nenhum")
        linhas.append("IDs no nome XML:")
        linhas.append(f"  - {item.get('ids_no_nome_xml')}")
        linhas.append("IDs no XML, amostra:")
        linhas.append(f"  - {item.get('ids_no_xml', [])[:30]}")
        linhas.append("Snippets:")
        for snip in item.get("snippets", [])[:10]:
            linhas.append(f"  >>> termo={snip.get('termo')}")
            linhas.append(str(snip.get("snippet") or "")[:900])
        linhas.append("")

    SAIDA_TXT.write_text("\n".join(linhas), encoding="utf-8")

    linhas_xmls = []
    linhas_xmls.append("=" * 80)
    linhas_xmls.append("XMLs RELACIONADOS POR ID INTERNO")
    linhas_xmls.append("=" * 80)

    for id_interno, grupo in grupos_relacionados.items():
        linhas_xmls.append("")
        linhas_xmls.append(f"ID INTERNO: {id_interno} | total={grupo.get('total_xmls_grupo')}")
        linhas_xmls.append("-" * 80)

        for item in grupo.get("xmls", []):
            linhas_xmls.append(f"XML: {item.get('xml')}")
            linhas_xmls.append(f"ZIP: {item.get('zip')}")
            linhas_xmls.append(f"Parte: {item.get('parte_nome_xml')}")
            linhas_xmls.append(f"Identifica: {item.get('campos', {}).get('Identifica')}")
            linhas_xmls.append("URLs:")
            for u in item.get("urls", []):
                linhas_xmls.append(f"  - [{u.get('tipo')}] {u.get('url')} | params={u.get('parametros')}")
            linhas_xmls.append("Texto preview:")
            linhas_xmls.append(str(item.get("campos", {}).get("Texto_preview") or "")[:1600])
            linhas_xmls.append("")

    SAIDA_XMLS_TXT.write_text("\n".join(linhas_xmls), encoding="utf-8")

    print("=" * 80)
    print("AUDITORIA CONCLUÍDA")
    print("=" * 80)
    print(f"XMLs total: {total_xmls}")
    print(f"XMLs com link moderno /web/dou/-/: {total_com_url_moderna}")
    print(f"XMLs com link visualizador página DOU: {total_com_url_visualizador}")
    print(f"XMLs com ID moderno esperado no conteúdo: {total_com_id_moderno_esperado}")
    print(f"XMLs com URL moderna esperada no conteúdo: {total_com_url_moderna_esperada}")
    print(f"Achados diretos: {len(achados_diretos)}")
    print(f"IDs internos relacionados: {ids_achados}")
    print(f"Resultado: {conclusao['resultado']}")
    print(f"JSON: {SAIDA_JSON}")
    print(f"TXT: {SAIDA_TXT}")
    print(f"XMLs relacionados: {SAIDA_XMLS_TXT}")
    print("=" * 80)


if __name__ == "__main__":
    main()
