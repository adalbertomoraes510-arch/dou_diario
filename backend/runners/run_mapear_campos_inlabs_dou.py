# ============================================================
# RUNNER — Mapear Campos INLABS DOU
# Projeto Informativos
#
# Objetivo:
# - Ler XMLs já baixados do INLABS.
# - Mapear tags, atributos, links, campos e qualidade dos dados.
# - Não altera base, match, e-mail, relatório ou orquestrador.
# ============================================================

import datetime
import html
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET


# ============================================================
# CONFIGURAÇÃO
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 15)

LIMITE_AMOSTRAS = 30

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
    / "mapeamentos"
    / "inlabs"
)

SAIDA_DIR.mkdir(parents=True, exist_ok=True)

SAIDA_JSON = SAIDA_DIR / f"mapeamento_campos_inlabs_{DATA_EXECUCAO.isoformat()}.json"
SAIDA_TXT = SAIDA_DIR / f"mapeamento_campos_inlabs_{DATA_EXECUCAO.isoformat()}.txt"
SAIDA_AMOSTRAS_TXT = SAIDA_DIR / f"amostras_publicacoes_inlabs_{DATA_EXECUCAO.isoformat()}.txt"


# ============================================================
# UTILITÁRIOS
# ============================================================

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


def limpar_html_para_texto(valor: str) -> str:
    if not valor:
        return ""

    texto = html.unescape(str(valor))

    texto = re.sub(r"</p\s*>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", " ", texto, flags=re.IGNORECASE)

    linhas = []

    for linha in texto.splitlines():
        linha = re.sub(r"\s+", " ", linha).strip()

        if linha:
            linhas.append(linha)

    return "\n".join(linhas).strip()


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

        url_lower = url.lower()

        if (
            "in.gov.br" in url_lower
            or "pesquisa.in.gov.br" in url_lower
            or "/consulta/" in url_lower
            or "/imprensa/jsp/visualiza" in url_lower
            or url_lower.startswith("http")
            or url_lower.startswith("www.")
        ):
            if url not in urls:
                urls.append(url)

    return urls


def escolher_url_oficial(urls: list[str]) -> str:
    if not urls:
        return ""

    prioridades = [
        "pesquisa.in.gov.br/imprensa/jsp/visualiza",
        "in.gov.br/web/dou",
        "in.gov.br/consulta",
        "in.gov.br",
    ]

    for prioridade in prioridades:
        for url in urls:
            if prioridade in url.lower():
                return url

    return urls[0]


def extrair_parametros_url(url: str) -> dict:
    if not url:
        return {}

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        return {
            "data": (query.get("data") or [""])[0],
            "jornal": (query.get("jornal") or [""])[0],
            "pagina": (query.get("pagina") or [""])[0],
            "url_host": parsed.netloc,
            "url_path": parsed.path,
        }

    except Exception:
        return {}


def contar_atos_internos(texto_html: str) -> int:
    if not texto_html:
        return 0

    texto = html.unescape(str(texto_html))

    identificas = re.findall(
        r'<p[^>]*class=["\'][^"\']*identifica[^"\']*["\'][^>]*>',
        texto,
        flags=re.IGNORECASE,
    )

    return len(identificas)


def montar_titulo(
    identifica: str,
    ementa: str,
    titulo: str,
    subtitulo: str,
    texto_integral: str,
) -> str:
    for valor in [identifica, ementa, titulo, subtitulo]:
        valor = re.sub(r"\s+", " ", str(valor or "")).strip()

        if valor:
            return valor

    for linha in texto_integral.splitlines():
        linha = re.sub(r"\s+", " ", linha).strip()

        if linha:
            return linha[:300]

    return ""


# ============================================================
# PROCESSAMENTO
# ============================================================

def analisar_xml(xml_bytes: bytes, nome_xml: str, nome_zip: str, secao: str) -> dict:
    xml_raw = xml_bytes.decode("utf-8", errors="ignore")
    xml_unescape = html.unescape(xml_raw)

    try:
        root = ET.fromstring(xml_raw)
    except Exception as erro:
        return {
            "xml_valido": False,
            "erro_parse": str(erro),
            "zip": nome_zip,
            "secao": secao,
            "arquivo_xml": nome_xml,
        }

    tags = Counter()
    tags_com_texto = Counter()
    atributos = Counter()
    atributos_relevantes = []

    for el in root.iter():
        tag = limpar_tag(el.tag)
        tags[tag] += 1

        texto = texto_elemento(el)

        if texto:
            tags_com_texto[tag] += 1

        for attr_nome, attr_valor in (el.attrib or {}).items():
            atributos[attr_nome] += 1

            texto_attr = f"{attr_nome}={attr_valor}".lower()

            if any(
                chave in texto_attr
                for chave in ["href", "url", "link", "src", "uri", "id", "dou", "materia"]
            ):
                atributos_relevantes.append({
                    "tag": tag,
                    "atributo": attr_nome,
                    "valor": attr_valor,
                })

    identifica = extrair_tag_exata(root, "Identifica")
    data_xml = extrair_tag_exata(root, "Data")
    ementa = extrair_tag_exata(root, "Ementa")
    titulo_xml = extrair_tag_exata(root, "Titulo")
    subtitulo = extrair_tag_exata(root, "SubTitulo")
    texto_html = extrair_tag_exata(root, "Texto")
    texto_integral = limpar_html_para_texto(texto_html)

    if not texto_integral:
        texto_integral = texto_elemento(root)

    urls = extrair_urls(xml_unescape)
    url_oficial = escolher_url_oficial(urls)
    params_url = extrair_parametros_url(url_oficial)

    atos_internos = contar_atos_internos(texto_html)

    titulo_final = montar_titulo(
        identifica=identifica,
        ementa=ementa,
        titulo=titulo_xml,
        subtitulo=subtitulo,
        texto_integral=texto_integral,
    )

    return {
        "xml_valido": True,
        "zip": nome_zip,
        "secao": secao,
        "arquivo_xml": nome_xml,
        "root_tag": limpar_tag(root.tag),
        "root_atributos": dict(root.attrib or {}),
        "tags": dict(tags),
        "tags_com_texto": dict(tags_com_texto),
        "atributos": dict(atributos),
        "atributos_relevantes": atributos_relevantes,
        "identifica": identifica,
        "data_xml": data_xml,
        "ementa": ementa,
        "titulo_xml": titulo_xml,
        "subtitulo": subtitulo,
        "titulo_final": titulo_final,
        "texto_tamanho": len(texto_integral),
        "texto_preview": texto_integral[:1000],
        "urls_encontradas": urls,
        "url_oficial": url_oficial,
        "url_parametros": params_url,
        "tem_url": bool(url_oficial),
        "pagina": params_url.get("pagina", ""),
        "jornal": params_url.get("jornal", ""),
        "atos_internos_estimados": atos_internos,
        "tem_multiplos_atos": atos_internos > 1,
    }


def main():
    print("=" * 80)
    print("MAPEAMENTO CAMPOS INLABS DOU")
    print("=" * 80)
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"ZIP_DIR: {ZIP_DIR}")
    print("=" * 80)

    if not ZIP_DIR.exists():
        raise FileNotFoundError(f"Pasta de ZIPs não encontrada: {ZIP_DIR}")

    zips = sorted(ZIP_DIR.glob("*.zip"))

    if not zips:
        raise FileNotFoundError(f"Nenhum ZIP encontrado em: {ZIP_DIR}")

    total_xml = 0
    total_validos = 0
    total_invalidos = 0

    total_com_url = 0
    total_sem_url = 0
    total_com_identifica = 0
    total_sem_identifica = 0
    total_com_data_xml = 0
    total_com_texto = 0
    total_multiplos_atos = 0

    tags_gerais = Counter()
    tags_com_texto_gerais = Counter()
    atributos_gerais = Counter()
    hosts_url = Counter()
    jornais = Counter()
    secoes = Counter()
    zips_resumo = []

    amostras = []
    erros = []

    for zip_path in zips:
        secao = zip_path.stem.split("-")[-1]

        print(f"[MAPEAMENTO] Lendo {zip_path.name}")

        resumo_zip = {
            "zip": zip_path.name,
            "secao": secao,
            "xml_total": 0,
            "xml_validos": 0,
            "xml_invalidos": 0,
            "com_url": 0,
            "sem_url": 0,
            "com_identifica": 0,
            "sem_identifica": 0,
            "multiplos_atos": 0,
        }

        with zipfile.ZipFile(zip_path, "r") as zf:
            nomes_xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]

            resumo_zip["xml_total"] = len(nomes_xml)
            total_xml += len(nomes_xml)

            for nome_xml in nomes_xml:
                xml_bytes = zf.read(nome_xml)

                item = analisar_xml(
                    xml_bytes=xml_bytes,
                    nome_xml=nome_xml,
                    nome_zip=zip_path.name,
                    secao=secao,
                )

                if not item.get("xml_valido"):
                    total_invalidos += 1
                    resumo_zip["xml_invalidos"] += 1
                    erros.append(item)
                    continue

                total_validos += 1
                resumo_zip["xml_validos"] += 1

                secoes[secao] += 1

                for tag, qtd in item.get("tags", {}).items():
                    tags_gerais[tag] += int(qtd)

                for tag, qtd in item.get("tags_com_texto", {}).items():
                    tags_com_texto_gerais[tag] += int(qtd)

                for attr, qtd in item.get("atributos", {}).items():
                    atributos_gerais[attr] += int(qtd)

                if item.get("tem_url"):
                    total_com_url += 1
                    resumo_zip["com_url"] += 1

                    params = item.get("url_parametros") or {}

                    if params.get("url_host"):
                        hosts_url[params.get("url_host")] += 1

                    if item.get("jornal"):
                        jornais[item.get("jornal")] += 1

                else:
                    total_sem_url += 1
                    resumo_zip["sem_url"] += 1

                if item.get("identifica"):
                    total_com_identifica += 1
                    resumo_zip["com_identifica"] += 1
                else:
                    total_sem_identifica += 1
                    resumo_zip["sem_identifica"] += 1

                if item.get("data_xml"):
                    total_com_data_xml += 1

                if item.get("texto_tamanho", 0) > 0:
                    total_com_texto += 1

                if item.get("tem_multiplos_atos"):
                    total_multiplos_atos += 1
                    resumo_zip["multiplos_atos"] += 1

                if len(amostras) < LIMITE_AMOSTRAS:
                    amostras.append(item)

        zips_resumo.append(resumo_zip)

        print(
            f"[MAPEAMENTO] {zip_path.name}: "
            f"xmls={resumo_zip['xml_total']} | "
            f"validos={resumo_zip['xml_validos']} | "
            f"com_url={resumo_zip['com_url']} | "
            f"multiplos_atos={resumo_zip['multiplos_atos']}"
        )

    percentual_url = round((total_com_url / total_validos) * 100, 2) if total_validos else 0
    percentual_identifica = round((total_com_identifica / total_validos) * 100, 2) if total_validos else 0
    percentual_texto = round((total_com_texto / total_validos) * 100, 2) if total_validos else 0
    percentual_multiplos_atos = round((total_multiplos_atos / total_validos) * 100, 2) if total_validos else 0

    contrato_sugerido = [
        {
            "campo_final": "id_publicacao",
            "origem_inlabs": "gerado pelo sistema",
            "fallback": "data + secao + arquivo_xml + hash texto",
            "obrigatorio": True,
            "uso": ["base", "match", "auditoria", "deduplicacao"],
        },
        {
            "campo_final": "data_publicacao",
            "origem_inlabs": "data do ZIP / data da execução",
            "fallback": "Data XML se necessário",
            "obrigatorio": True,
            "uso": ["base", "match", "relatorio", "email"],
        },
        {
            "campo_final": "secao",
            "origem_inlabs": "nome do ZIP: DO1, DO2, DO3, DO1E, DO2E, DO3E",
            "fallback": "",
            "obrigatorio": True,
            "uso": ["base", "relatorio", "email"],
        },
        {
            "campo_final": "titulo",
            "origem_inlabs": "Identifica",
            "fallback": "Ementa > Titulo > SubTitulo > primeira linha de Texto",
            "obrigatorio": True,
            "uso": ["base", "match", "relatorio", "email"],
        },
        {
            "campo_final": "texto_html",
            "origem_inlabs": "Texto",
            "fallback": "",
            "obrigatorio": False,
            "uso": ["auditoria", "debug"],
        },
        {
            "campo_final": "texto_integral",
            "origem_inlabs": "Texto limpo",
            "fallback": "root.itertext()",
            "obrigatorio": True,
            "uso": ["match", "auditoria", "relatorio", "email"],
        },
        {
            "campo_final": "url_publicacao",
            "origem_inlabs": "URL encontrada no XML bruto",
            "fallback": "futuro: busca oficial por título/data",
            "obrigatorio": False,
            "uso": ["email", "auditoria", "front"],
        },
        {
            "campo_final": "pagina",
            "origem_inlabs": "parâmetro pagina da URL oficial",
            "fallback": "",
            "obrigatorio": False,
            "uso": ["email", "relatorio", "auditoria"],
        },
        {
            "campo_final": "jornal",
            "origem_inlabs": "parâmetro jornal da URL oficial",
            "fallback": "",
            "obrigatorio": False,
            "uso": ["auditoria"],
        },
        {
            "campo_final": "arquivo_xml",
            "origem_inlabs": "nome do XML dentro do ZIP",
            "fallback": "",
            "obrigatorio": True,
            "uso": ["auditoria", "debug"],
        },
        {
            "campo_final": "zip",
            "origem_inlabs": "nome do ZIP",
            "fallback": "",
            "obrigatorio": True,
            "uso": ["auditoria", "debug"],
        },
    ]

    resultado = {
        "data": DATA_EXECUCAO.isoformat(),
        "zip_dir": str(ZIP_DIR),
        "saida_json": str(SAIDA_JSON),
        "saida_txt": str(SAIDA_TXT),
        "totais": {
            "zips": len(zips),
            "xml_total": total_xml,
            "xml_validos": total_validos,
            "xml_invalidos": total_invalidos,
            "com_url": total_com_url,
            "sem_url": total_sem_url,
            "percentual_com_url": percentual_url,
            "com_identifica": total_com_identifica,
            "sem_identifica": total_sem_identifica,
            "percentual_com_identifica": percentual_identifica,
            "com_data_xml": total_com_data_xml,
            "com_texto": total_com_texto,
            "percentual_com_texto": percentual_texto,
            "multiplos_atos": total_multiplos_atos,
            "percentual_multiplos_atos": percentual_multiplos_atos,
        },
        "zips": zips_resumo,
        "secoes": dict(secoes.most_common()),
        "tags_gerais": dict(tags_gerais.most_common(150)),
        "tags_com_texto_gerais": dict(tags_com_texto_gerais.most_common(150)),
        "atributos_gerais": dict(atributos_gerais.most_common(150)),
        "hosts_url": dict(hosts_url.most_common()),
        "jornais": dict(jornais.most_common()),
        "contrato_sugerido": contrato_sugerido,
        "amostras": amostras,
        "erros": erros[:50],
    }

    SAIDA_JSON.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = []
    linhas.append("=" * 80)
    linhas.append("MAPEAMENTO CAMPOS INLABS DOU")
    linhas.append("=" * 80)
    linhas.append(f"Data: {DATA_EXECUCAO.isoformat()}")
    linhas.append(f"ZIP_DIR: {ZIP_DIR}")
    linhas.append("")
    linhas.append("TOTAIS")
    linhas.append("-" * 80)
    linhas.append(f"Zips: {len(zips)}")
    linhas.append(f"XML total: {total_xml}")
    linhas.append(f"XML válidos: {total_validos}")
    linhas.append(f"XML inválidos: {total_invalidos}")
    linhas.append(f"Com URL/link oficial: {total_com_url} ({percentual_url}%)")
    linhas.append(f"Sem URL/link oficial: {total_sem_url}")
    linhas.append(f"Com Identifica: {total_com_identifica} ({percentual_identifica}%)")
    linhas.append(f"Sem Identifica: {total_sem_identifica}")
    linhas.append(f"Com Data XML: {total_com_data_xml}")
    linhas.append(f"Com Texto: {total_com_texto} ({percentual_texto}%)")
    linhas.append(f"Com múltiplos atos internos: {total_multiplos_atos} ({percentual_multiplos_atos}%)")
    linhas.append("")

    linhas.append("RESUMO POR ZIP")
    linhas.append("-" * 80)
    for z in zips_resumo:
        linhas.append(
            f"{z['zip']} | secao={z['secao']} | xmls={z['xml_total']} | "
            f"validos={z['xml_validos']} | com_url={z['com_url']} | "
            f"sem_url={z['sem_url']} | com_identifica={z['com_identifica']} | "
            f"sem_identifica={z['sem_identifica']} | multiplos_atos={z['multiplos_atos']}"
        )

    linhas.append("")
    linhas.append("TAGS MAIS COMUNS")
    linhas.append("-" * 80)
    for tag, qtd in tags_gerais.most_common(50):
        linhas.append(f"{tag}: {qtd}")

    linhas.append("")
    linhas.append("TAGS COM TEXTO MAIS COMUNS")
    linhas.append("-" * 80)
    for tag, qtd in tags_com_texto_gerais.most_common(50):
        linhas.append(f"{tag}: {qtd}")

    linhas.append("")
    linhas.append("ATRIBUTOS MAIS COMUNS")
    linhas.append("-" * 80)
    for attr, qtd in atributos_gerais.most_common(50):
        linhas.append(f"{attr}: {qtd}")

    linhas.append("")
    linhas.append("HOSTS DE URL")
    linhas.append("-" * 80)
    for host, qtd in hosts_url.most_common():
        linhas.append(f"{host}: {qtd}")

    linhas.append("")
    linhas.append("JORNAIS")
    linhas.append("-" * 80)
    for jornal, qtd in jornais.most_common():
        linhas.append(f"jornal={jornal}: {qtd}")

    linhas.append("")
    linhas.append("CONTRATO SUGERIDO")
    linhas.append("-" * 80)
    for campo in contrato_sugerido:
        linhas.append(
            f"{campo['campo_final']} <- {campo['origem_inlabs']} | "
            f"fallback={campo['fallback']} | obrigatorio={campo['obrigatorio']} | "
            f"uso={', '.join(campo['uso'])}"
        )

    linhas.append("")
    linhas.append("AMOSTRAS")
    linhas.append("=" * 80)

    for i, item in enumerate(amostras, start=1):
        linhas.append(f"Amostra {i}")
        linhas.append("-" * 80)
        linhas.append(f"ZIP: {item.get('zip')}")
        linhas.append(f"XML: {item.get('arquivo_xml')}")
        linhas.append(f"Seção: {item.get('secao')}")
        linhas.append(f"Título final: {item.get('titulo_final')}")
        linhas.append(f"Identifica: {item.get('identifica')}")
        linhas.append(f"Ementa: {item.get('ementa')}")
        linhas.append(f"Data XML: {item.get('data_xml')}")
        linhas.append(f"URL oficial: {item.get('url_oficial')}")
        linhas.append(f"Jornal: {item.get('jornal')}")
        linhas.append(f"Página: {item.get('pagina')}")
        linhas.append(f"Texto tamanho: {item.get('texto_tamanho')}")
        linhas.append(f"Atos internos estimados: {item.get('atos_internos_estimados')}")
        linhas.append("Texto preview:")
        linhas.append(str(item.get("texto_preview") or "")[:1000])
        linhas.append("")

    SAIDA_TXT.write_text("\n".join(linhas), encoding="utf-8")

    linhas_amostras = []
    linhas_amostras.append("=" * 80)
    linhas_amostras.append("AMOSTRAS PUBLICAÇÕES INLABS")
    linhas_amostras.append("=" * 80)

    for i, item in enumerate(amostras, start=1):
        linhas_amostras.append(f"\nAMOSTRA {i}")
        linhas_amostras.append("-" * 80)
        linhas_amostras.append(f"ZIP: {item.get('zip')}")
        linhas_amostras.append(f"XML: {item.get('arquivo_xml')}")
        linhas_amostras.append(f"SEÇÃO: {item.get('secao')}")
        linhas_amostras.append(f"TÍTULO: {item.get('titulo_final')}")
        linhas_amostras.append(f"URL: {item.get('url_oficial')}")
        linhas_amostras.append(f"JORNAL: {item.get('jornal')}")
        linhas_amostras.append(f"PÁGINA: {item.get('pagina')}")
        linhas_amostras.append(f"ATOS INTERNOS: {item.get('atos_internos_estimados')}")
        linhas_amostras.append("")
        linhas_amostras.append(str(item.get("texto_preview") or "")[:3000])

    SAIDA_AMOSTRAS_TXT.write_text("\n".join(linhas_amostras), encoding="utf-8")

    print("=" * 80)
    print("MAPEAMENTO CONCLUÍDO")
    print("=" * 80)
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Zips: {len(zips)}")
    print(f"XML total: {total_xml}")
    print(f"XML válidos: {total_validos}")
    print(f"Com URL/link oficial: {total_com_url} ({percentual_url}%)")
    print(f"Sem URL/link oficial: {total_sem_url}")
    print(f"Com Identifica: {total_com_identifica} ({percentual_identifica}%)")
    print(f"Com Texto: {total_com_texto} ({percentual_texto}%)")
    print(f"Com múltiplos atos internos: {total_multiplos_atos} ({percentual_multiplos_atos}%)")
    print(f"JSON: {SAIDA_JSON}")
    print(f"TXT: {SAIDA_TXT}")
    print(f"AMOSTRAS: {SAIDA_AMOSTRAS_TXT}")
    print("=" * 80)


if __name__ == "__main__":
    main()
