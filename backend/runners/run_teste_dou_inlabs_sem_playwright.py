# ============================================================
# RUNNER ISOLADO — Teste DOU sem Playwright + Inspeção XML
# Fonte: INLABS / Imprensa Nacional
# Projeto Informativos — prova técnica de coleta estruturada
# ============================================================

import datetime
import html
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "ERRO: biblioteca 'requests' não encontrada. Rode: pip install requests"
    ) from exc


# ============================================================
# CONFIGURAÇÃO DO TESTE
# ============================================================

DATA_TESTE = datetime.date(2026, 4, 1)

# Seções do DOU em XML no INLABS.
# DO1/DO2/DO3 = edições normais.
# DO1E/DO2E/DO3E = edições extras/suplementares, quando existirem.
TIPOS_DOU = ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"]

URL_LOGIN = "https://inlabs.in.gov.br/logar.php"
URL_DOWNLOAD = "https://inlabs.in.gov.br/index.php"

ROOT_DIR = Path(__file__).resolve().parents[2]
SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "testes_inlabs" / DATA_TESTE.isoformat()
ZIP_DIR = SAIDA_DIR / "zips"
EXTRACAO_DIR = SAIDA_DIR / "amostras_xml"

SAIDA_DIR.mkdir(parents=True, exist_ok=True)
ZIP_DIR.mkdir(parents=True, exist_ok=True)
EXTRACAO_DIR.mkdir(parents=True, exist_ok=True)

MAX_AMOSTRAS_XML_SALVAS = 30
MAX_AMOSTRAS_RELATORIO = 15


# ============================================================
# UTILITÁRIOS
# ============================================================

def carregar_env_local() -> None:
    """
    Carrega variáveis simples de .env sem depender de python-dotenv.
    Não sobrescreve variáveis já existentes no ambiente.
    """
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return

    for linha in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")

        if chave and chave not in os.environ:
            os.environ[chave] = valor


def obter_credenciais() -> tuple[str, str]:
    carregar_env_local()

    email = (
        os.getenv("INLABS_EMAIL")
        or os.getenv("INLABS_LOGIN")
        or os.getenv("DOU_INLABS_EMAIL")
        or ""
    ).strip()

    senha = (
        os.getenv("INLABS_PASSWORD")
        or os.getenv("INLABS_SENHA")
        or os.getenv("DOU_INLABS_PASSWORD")
        or ""
    ).strip()

    if not email or not senha:
        raise RuntimeError(
            "Credenciais INLABS não configuradas.\n"
            "Configure no PowerShell, sem colar senha no chat:\n"
            "  $env:INLABS_EMAIL='seu_email'\n"
            "  $env:INLABS_PASSWORD='sua_senha'\n"
            "Ou coloque essas chaves no arquivo .env local do projeto."
        )

    return email, senha


def limpar_texto(valor: str | None, limite: int | None = 600) -> str:
    if not valor:
        return ""

    texto = html.unescape(str(valor))
    texto = re.sub(r"\s+", " ", texto).strip()

    if limite is not None and len(texto) > limite:
        return texto[:limite].rstrip() + "..."

    return texto


def nome_tag(elem: ET.Element) -> str:
    tag = str(elem.tag or "")
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return tag.lower()


def nome_tag_original(tag: str) -> str:
    tag = str(tag or "")
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def texto_no(elemento: ET.Element | None, limite: int | None = None) -> str:
    if elemento is None:
        return ""

    partes = []
    for txt in elemento.itertext():
        txt = limpar_texto(txt, limite=None)
        if txt:
            partes.append(txt)

    return limpar_texto(" ".join(partes), limite=limite)


def extrair_primeiro_por_tags(root: ET.Element, candidatos: list[str], limite: int = 800) -> str:
    candidatos_norm = [c.lower() for c in candidatos]

    for elem in root.iter():
        tag = nome_tag(elem)
        if any(c in tag for c in candidatos_norm):
            texto = texto_no(elem, limite=limite)
            if texto:
                return texto

    return ""


def extrair_tag_exata(root: ET.Element, tag_procurada: str, limite: int | None = None) -> str:
    tag_procurada_norm = tag_procurada.lower()

    for elem in root.iter():
        if nome_tag(elem) == tag_procurada_norm:
            return texto_no(elem, limite=limite)

    return ""


def montar_titulo_final(campos: dict[str, str], texto_integral: str) -> str:
    """
    Define o título mais adequado para o parser oficial.
    """
    for chave in ["identifica", "ementa", "titulo", "sub_titulo"]:
        valor = limpar_texto(campos.get(chave), limite=500)
        if valor:
            return valor

    if texto_integral:
        return limpar_texto(texto_integral, limite=300)

    return "Publicação sem título detectado"


def resumir_xml(conteudo: bytes, nome_arquivo: str) -> dict[str, Any]:
    """
    Extrai uma amostra de um XML sem depender rigidamente do schema.
    O objetivo aqui é provar que temos XML estruturado e texto de publicação.
    """
    try:
        texto_bruto = conteudo.decode("utf-8", errors="ignore")
        root = ET.fromstring(texto_bruto)
    except Exception as erro:
        return {
            "arquivo": nome_arquivo,
            "xml_valido": False,
            "erro": str(erro),
            "tamanho_bytes": len(conteudo),
        }

    texto_total = texto_no(root, limite=1200)

    return {
        "arquivo": nome_arquivo,
        "xml_valido": True,
        "tag_raiz": nome_tag(root),
        "atributos_raiz": dict(root.attrib or {}),
        "tamanho_bytes": len(conteudo),
        "identifica": extrair_primeiro_por_tags(root, ["identifica", "identificacao"]),
        "titulo": extrair_primeiro_por_tags(root, ["titulo", "title"]),
        "sub_titulo": extrair_primeiro_por_tags(root, ["sub_titulo", "subtitulo", "subtitle"]),
        "texto_amostra": texto_total,
    }


def inspecionar_xml_completo(conteudo: bytes, nome_arquivo: str, secao: str, zip_nome: str) -> dict[str, Any]:
    """
    Inspeção estrutural mais completa do XML.
    Retorna tags existentes, atributos, campos prováveis e tamanho do texto.
    """
    try:
        texto_bruto = conteudo.decode("utf-8", errors="ignore")
        root = ET.fromstring(texto_bruto)
    except Exception as erro:
        return {
            "arquivo": nome_arquivo,
            "secao": secao,
            "zip": zip_nome,
            "xml_valido": False,
            "erro_parse": str(erro),
            "tamanho_bytes": len(conteudo),
        }

    tags_counter = Counter()
    campos_por_tag: dict[str, list[str]] = defaultdict(list)

    for el in root.iter():
        tag = nome_tag_original(el.tag)
        tags_counter[tag] += 1

        conteudo_texto = texto_no(el, limite=1000)
        if conteudo_texto:
            campos_por_tag[tag].append(conteudo_texto)

    texto_integral = texto_no(root, limite=None)

    candidatos = {
        "identifica": ["Identifica", "identifica", "Identificacao", "identificacao"],
        "titulo": ["Titulo", "titulo", "title", "Title"],
        "sub_titulo": ["SubTitulo", "subTitulo", "sub_titulo", "subtitulo", "Subtitulo"],
        "ementa": ["Ementa", "ementa"],
        "texto": ["Texto", "texto", "text", "Text", "body", "Body"],
        "orgao": ["ArtCategory", "artCategory", "Orgao", "Órgão", "orgao"],
        "data": ["Data", "data", "DtPublicacao", "dtPublicacao"],
    }

    campos_detectados: dict[str, str] = {}
    for nome_campo, tags in candidatos.items():
        valor = ""
        for tag in tags:
            if campos_por_tag.get(tag):
                valor = campos_por_tag[tag][0]
                break

        if not valor:
            tags_norm = [t.lower() for t in tags]
            for tag_existente, textos in campos_por_tag.items():
                tag_norm = tag_existente.lower()
                if any(t in tag_norm for t in tags_norm) and textos:
                    valor = textos[0]
                    break

        campos_detectados[nome_campo] = limpar_texto(valor, limite=1200)

    return {
        "arquivo": nome_arquivo,
        "secao": secao,
        "zip": zip_nome,
        "xml_valido": True,
        "tag_raiz": nome_tag_original(root.tag),
        "atributos_raiz": dict(root.attrib or {}),
        "tamanho_bytes": len(conteudo),
        "texto_tamanho": len(texto_integral),
        "texto_preview": limpar_texto(texto_integral, limite=1500),
        "tags": dict(tags_counter),
        "tags_com_texto": sorted(campos_por_tag.keys()),
        "campos_detectados": campos_detectados,
    }


def extrair_publicacao_real_xml(conteudo: bytes, nome_arquivo: str, secao: str, zip_nome: str) -> dict[str, Any]:
    """
    Extrai uma publicação real em formato próximo ao futuro parser oficial.
    """
    texto_bruto = conteudo.decode("utf-8", errors="ignore")
    root = ET.fromstring(texto_bruto)

    campos = {
        "identifica": extrair_tag_exata(root, "Identifica", limite=None),
        "data": extrair_tag_exata(root, "Data", limite=None),
        "ementa": extrair_tag_exata(root, "Ementa", limite=None),
        "titulo": extrair_tag_exata(root, "Titulo", limite=None),
        "sub_titulo": extrair_tag_exata(root, "SubTitulo", limite=None),
        "texto": extrair_tag_exata(root, "Texto", limite=None),
    }

    texto_integral = campos.get("texto") or texto_no(root, limite=None)
    titulo_final = montar_titulo_final(campos, texto_integral)

    atributos_raiz = dict(root.attrib or {})

    id_publicacao_teste = (
        f"INLABS|{DATA_TESTE.isoformat()}|{secao}|{Path(nome_arquivo).stem}"
    )

    return {
        "id_publicacao_teste": id_publicacao_teste,
        "fonte": "INLABS",
        "data_publicacao": DATA_TESTE.isoformat(),
        "secao": secao,
        "zip": zip_nome,
        "arquivo_xml": nome_arquivo,
        "tag_raiz": nome_tag_original(root.tag),
        "atributos_raiz": atributos_raiz,
        "titulo_final": titulo_final,
        "identifica": limpar_texto(campos.get("identifica"), limite=None),
        "data_xml": limpar_texto(campos.get("data"), limite=None),
        "ementa": limpar_texto(campos.get("ementa"), limite=None),
        "titulo": limpar_texto(campos.get("titulo"), limite=None),
        "sub_titulo": limpar_texto(campos.get("sub_titulo"), limite=None),
        "texto_integral": limpar_texto(texto_integral, limite=None),
        "texto_tamanho": len(limpar_texto(texto_integral, limite=None)),
    }


# ============================================================
# INLABS
# ============================================================

def criar_sessao_inlabs(email: str, senha: str) -> requests.Session:
    session = requests.Session()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests INLABS",
    }

    payload = {
        "email": email,
        "password": senha,
    }

    print("[INLABS] Realizando login...")

    response = session.post(
        URL_LOGIN,
        data=payload,
        headers=headers,
        timeout=60,
    )

    cookie = session.cookies.get("inlabs_session_cookie")

    if not cookie:
        raise RuntimeError(
            "Falha ao obter cookie INLABS. "
            f"HTTP={response.status_code}. Verifique credenciais e acesso ao INLABS."
        )

    print("[INLABS] Login OK — cookie obtido.")
    return session


def baixar_zip_secao(
    session: requests.Session,
    data_alvo: datetime.date,
    secao: str,
) -> dict[str, Any]:
    data_str = data_alvo.isoformat()
    nome_zip = f"{data_str}-{secao}.zip"
    caminho_zip = ZIP_DIR / nome_zip

    cookie = session.cookies.get("inlabs_session_cookie")
    headers = {
        "Cookie": f"inlabs_session_cookie={cookie}",
        "origem": "736372697074",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests INLABS",
    }

    url = f"{URL_DOWNLOAD}?p={data_str}&dl={nome_zip}"

    print(f"[INLABS] Baixando {nome_zip}...")

    response = session.get(url, headers=headers, timeout=120)

    resultado: dict[str, Any] = {
        "secao": secao,
        "nome_zip": nome_zip,
        "url": url,
        "http_status": response.status_code,
        "salvo": False,
        "caminho_zip": str(caminho_zip),
        "tamanho_zip_bytes": 0,
        "xml_total": 0,
        "xml_validos_amostra": 0,
        "amostras": [],
        "erro": "",
    }

    if response.status_code == 404:
        resultado["erro"] = "Arquivo não encontrado para esta seção/data."
        print(f"[INLABS] {nome_zip}: não encontrado (404).")
        return resultado

    if response.status_code != 200:
        resultado["erro"] = f"HTTP inesperado: {response.status_code}"
        print(f"[INLABS] {nome_zip}: erro HTTP {response.status_code}.")
        return resultado

    caminho_zip.write_bytes(response.content)
    resultado["salvo"] = True
    resultado["tamanho_zip_bytes"] = caminho_zip.stat().st_size

    if not zipfile.is_zipfile(caminho_zip):
        resultado["erro"] = "Arquivo baixado não é ZIP válido."
        print(f"[INLABS] {nome_zip}: baixado, mas não é ZIP válido.")
        return resultado

    with zipfile.ZipFile(caminho_zip, "r") as zf:
        nomes_xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        resultado["xml_total"] = len(nomes_xml)

        for nome_xml in nomes_xml[:5]:
            conteudo = zf.read(nome_xml)
            amostra = resumir_xml(conteudo, nome_xml)
            resultado["amostras"].append(amostra)

            if amostra.get("xml_valido"):
                resultado["xml_validos_amostra"] += 1

            caminho_amostra = EXTRACAO_DIR / f"{secao}_{Path(nome_xml).name}"
            try:
                caminho_amostra.write_bytes(conteudo)
            except Exception:
                pass

    print(
        f"[INLABS] {nome_zip}: OK | "
        f"zip_bytes={resultado['tamanho_zip_bytes']} | "
        f"xml_total={resultado['xml_total']}"
    )

    return resultado


# ============================================================
# INSPEÇÃO DO CONTEÚDO BAIXADO
# ============================================================

def inspecionar_conteudo_inlabs(data_alvo: datetime.date) -> dict[str, Any]:
    """
    Inspeciona todos os ZIPs baixados no teste atual.
    """
    data_str = data_alvo.isoformat()
    zips = sorted(ZIP_DIR.glob("*.zip"))

    if not zips:
        raise FileNotFoundError(f"Nenhum ZIP encontrado em: {ZIP_DIR}")

    print("=" * 80)
    print("INSPEÇÃO DO CONTEÚDO INLABS")
    print("=" * 80)
    print(f"Data: {data_str}")
    print(f"ZIP_DIR: {ZIP_DIR}")
    print(f"Zips encontrados: {len(zips)}")
    print("=" * 80)

    tags_gerais = Counter()
    root_tags = Counter()
    atributos_raiz_gerais = Counter()
    tags_com_texto_gerais = Counter()
    tamanhos_texto: list[int] = []

    zips_info: list[dict[str, Any]] = []
    amostras: list[dict[str, Any]] = []
    erros_parse: list[dict[str, Any]] = []

    total_xml = 0
    total_xml_validos = 0
    total_xml_invalidos = 0
    amostras_salvas = 0

    for zip_path in zips:
        print(f"[INSPEÇÃO] Lendo {zip_path.name}")

        zip_info: dict[str, Any] = {
            "arquivo": zip_path.name,
            "tamanho_bytes": zip_path.stat().st_size,
            "xml_total": 0,
            "xml_validos": 0,
            "xml_invalidos": 0,
            "xml_exemplos": [],
        }

        secao = zip_path.stem.split("-")[-1]

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                nomes_xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                zip_info["xml_total"] = len(nomes_xml)
                zip_info["xml_exemplos"] = nomes_xml[:10]

                total_xml += len(nomes_xml)

                for nome_xml in nomes_xml:
                    conteudo = zf.read(nome_xml)
                    item = inspecionar_xml_completo(
                        conteudo=conteudo,
                        nome_arquivo=nome_xml,
                        secao=secao,
                        zip_nome=zip_path.name,
                    )

                    if not item.get("xml_valido"):
                        total_xml_invalidos += 1
                        zip_info["xml_invalidos"] += 1
                        erros_parse.append(item)
                        continue

                    total_xml_validos += 1
                    zip_info["xml_validos"] += 1

                    root_tags[item.get("tag_raiz") or ""] += 1

                    for attr in (item.get("atributos_raiz") or {}).keys():
                        atributos_raiz_gerais[attr] += 1

                    for tag, qtd in (item.get("tags") or {}).items():
                        tags_gerais[tag] += int(qtd)

                    for tag in item.get("tags_com_texto") or []:
                        tags_com_texto_gerais[tag] += 1

                    tamanhos_texto.append(int(item.get("texto_tamanho") or 0))

                    if len(amostras) < MAX_AMOSTRAS_RELATORIO:
                        amostras.append(item)

                    if amostras_salvas < MAX_AMOSTRAS_XML_SALVAS:
                        caminho_amostra = EXTRACAO_DIR / f"amostra_{amostras_salvas + 1:03d}_{secao}_{Path(nome_xml).name}"
                        try:
                            caminho_amostra.write_bytes(conteudo)
                            amostras_salvas += 1
                        except Exception:
                            pass

        except Exception as erro:
            zip_info["erro"] = str(erro)

        zips_info.append(zip_info)

        print(
            f"[INSPEÇÃO] {zip_path.name}: "
            f"xml_total={zip_info['xml_total']} | "
            f"validos={zip_info['xml_validos']} | "
            f"invalidos={zip_info['xml_invalidos']}"
        )

    if tamanhos_texto:
        texto_tamanho = {
            "min": min(tamanhos_texto),
            "max": max(tamanhos_texto),
            "media": round(sum(tamanhos_texto) / len(tamanhos_texto), 2),
        }
    else:
        texto_tamanho = {
            "min": None,
            "max": None,
            "media": None,
        }

    resumo = {
        "data": data_str,
        "fonte": "INLABS",
        "pasta": str(SAIDA_DIR),
        "zip_dir": str(ZIP_DIR),
        "zips_total": len(zips),
        "xml_total": total_xml,
        "xml_validos": total_xml_validos,
        "xml_invalidos": total_xml_invalidos,
        "texto_tamanho": texto_tamanho,
        "root_tags": dict(root_tags.most_common(50)),
        "tags_gerais": dict(tags_gerais.most_common(150)),
        "tags_com_texto_gerais": dict(tags_com_texto_gerais.most_common(150)),
        "atributos_raiz_gerais": dict(atributos_raiz_gerais.most_common(100)),
        "zips": zips_info,
        "amostras": amostras,
        "erros_parse": erros_parse[:100],
    }

    caminho_json = SAIDA_DIR / f"inspecao_conteudo_inlabs_{data_str}.json"
    caminho_txt = SAIDA_DIR / f"inspecao_conteudo_inlabs_{data_str}.txt"

    caminho_json.write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas: list[str] = []
    linhas.append("=" * 80)
    linhas.append("INSPEÇÃO DE CONTEÚDO INLABS")
    linhas.append("=" * 80)
    linhas.append(f"Data: {data_str}")
    linhas.append(f"Pasta: {SAIDA_DIR}")
    linhas.append(f"Zips encontrados: {len(zips)}")
    linhas.append(f"XMLs encontrados: {total_xml}")
    linhas.append(f"XMLs válidos: {total_xml_validos}")
    linhas.append(f"XMLs inválidos: {total_xml_invalidos}")
    linhas.append("")

    linhas.append("ZIPs:")
    for z in zips_info:
        linhas.append(
            f"- {z.get('arquivo')} | xmls={z.get('xml_total')} | "
            f"validos={z.get('xml_validos')} | invalidos={z.get('xml_invalidos')} | "
            f"bytes={z.get('tamanho_bytes')}"
        )

    linhas.append("")
    linhas.append("Root tags mais comuns:")
    for tag, qtd in root_tags.most_common(30):
        linhas.append(f"- {tag}: {qtd}")

    linhas.append("")
    linhas.append("Tags mais comuns:")
    for tag, qtd in tags_gerais.most_common(80):
        linhas.append(f"- {tag}: {qtd}")

    linhas.append("")
    linhas.append("Tags com texto mais comuns:")
    for tag, qtd in tags_com_texto_gerais.most_common(80):
        linhas.append(f"- {tag}: {qtd}")

    linhas.append("")
    linhas.append("Atributos no root mais comuns:")
    for attr, qtd in atributos_raiz_gerais.most_common(80):
        linhas.append(f"- {attr}: {qtd}")

    linhas.append("")
    linhas.append("Tamanho do texto integral estimado:")
    linhas.append(f"- mínimo: {texto_tamanho['min']}")
    linhas.append(f"- máximo: {texto_tamanho['max']}")
    linhas.append(f"- média: {texto_tamanho['media']}")

    linhas.append("")
    linhas.append("AMOSTRAS:")
    linhas.append("=" * 80)

    for i, item in enumerate(amostras, start=1):
        campos = item.get("campos_detectados") or {}
        linhas.append(f"Amostra {i}")
        linhas.append("-" * 80)
        linhas.append(f"Arquivo: {item.get('arquivo')}")
        linhas.append(f"ZIP: {item.get('zip')}")
        linhas.append(f"Seção: {item.get('secao')}")
        linhas.append(f"Root tag: {item.get('tag_raiz')}")
        linhas.append(f"Atributos raiz: {item.get('atributos_raiz')}")
        linhas.append(f"Texto tamanho: {item.get('texto_tamanho')}")
        linhas.append(f"Identifica: {campos.get('identifica')}")
        linhas.append(f"Título: {campos.get('titulo')}")
        linhas.append(f"Subtítulo: {campos.get('sub_titulo')}")
        linhas.append(f"Ementa: {campos.get('ementa')}")
        linhas.append(f"Órgão: {campos.get('orgao')}")
        linhas.append("Preview texto:")
        linhas.append(str(item.get("texto_preview") or "")[:1500])
        linhas.append("")

    if erros_parse:
        linhas.append("")
        linhas.append("ERROS DE PARSE:")
        for erro in erros_parse[:30]:
            linhas.append(f"- {erro}")

    caminho_txt.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 80)
    print("RESULTADO DA INSPEÇÃO")
    print("=" * 80)
    print(f"Zips encontrados: {len(zips)}")
    print(f"XMLs encontrados: {total_xml}")
    print(f"XMLs válidos: {total_xml_validos}")
    print(f"XMLs inválidos: {total_xml_invalidos}")
    print(f"Root tags: {dict(root_tags.most_common(10))}")
    print(f"Tags principais: {dict(tags_gerais.most_common(15))}")
    print(f"Tags com texto principais: {dict(tags_com_texto_gerais.most_common(15))}")
    print(f"Tamanho médio do texto: {texto_tamanho['media']}")
    print(f"JSON inspeção: {caminho_json}")
    print(f"TXT inspeção: {caminho_txt}")
    print("=" * 80)

    return resumo


# ============================================================
# AMOSTRA DE PUBLICAÇÃO REAL
# ============================================================

def escolher_publicacao_real(data_alvo: datetime.date) -> dict[str, Any]:
    """
    Escolhe uma publicação real dos XMLs já baixados.

    Critério:
    - XML válido;
    - tag Texto preenchida;
    - texto com tamanho mínimo razoável;
    - preferência por publicação com Identifica.
    """
    zips = sorted(ZIP_DIR.glob("*.zip"))

    if not zips:
        raise FileNotFoundError(f"Nenhum ZIP encontrado em: {ZIP_DIR}")

    melhor_item: dict[str, Any] | None = None

    for zip_path in zips:
        secao = zip_path.stem.split("-")[-1]

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                nomes_xml = [n for n in zf.namelist() if n.lower().endswith(".xml")]

                for nome_xml in nomes_xml:
                    conteudo = zf.read(nome_xml)

                    try:
                        item = extrair_publicacao_real_xml(
                            conteudo=conteudo,
                            nome_arquivo=nome_xml,
                            secao=secao,
                            zip_nome=zip_path.name,
                        )
                    except Exception:
                        continue

                    texto = item.get("texto_integral") or ""
                    identifica = item.get("identifica") or ""

                    if len(texto) < 500:
                        continue

                    if identifica:
                        return item

                    if melhor_item is None:
                        melhor_item = item

        except Exception:
            continue

    if melhor_item:
        return melhor_item

    raise RuntimeError("Nenhuma publicação real adequada encontrada nos XMLs baixados.")


def salvar_e_mostrar_publicacao_real(data_alvo: datetime.date) -> dict[str, Any]:
    """
    Mostra uma publicação real no terminal e salva JSON/TXT.
    """
    data_str = data_alvo.isoformat()
    item = escolher_publicacao_real(data_alvo)

    caminho_json = SAIDA_DIR / f"amostra_publicacao_real_inlabs_{data_str}.json"
    caminho_txt = SAIDA_DIR / f"amostra_publicacao_real_inlabs_{data_str}.txt"

    caminho_json.write_text(
        json.dumps(item, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    linhas = []
    linhas.append("=" * 80)
    linhas.append("AMOSTRA REAL DE PUBLICAÇÃO INLABS")
    linhas.append("=" * 80)
    linhas.append(f"Data teste: {data_str}")
    linhas.append(f"ID teste: {item.get('id_publicacao_teste')}")
    linhas.append(f"Fonte: {item.get('fonte')}")
    linhas.append(f"Seção: {item.get('secao')}")
    linhas.append(f"ZIP: {item.get('zip')}")
    linhas.append(f"Arquivo XML: {item.get('arquivo_xml')}")
    linhas.append(f"Tag raiz: {item.get('tag_raiz')}")
    linhas.append(f"Texto tamanho: {item.get('texto_tamanho')}")
    linhas.append("")
    linhas.append("CAMPOS EXTRAÍDOS")
    linhas.append("-" * 80)
    linhas.append(f"Título final: {item.get('titulo_final')}")
    linhas.append(f"Identifica: {item.get('identifica')}")
    linhas.append(f"Data XML: {item.get('data_xml')}")
    linhas.append(f"Ementa: {item.get('ementa')}")
    linhas.append(f"Título: {item.get('titulo')}")
    linhas.append(f"Subtítulo: {item.get('sub_titulo')}")
    linhas.append("")
    linhas.append("TEXTO INTEGRAL")
    linhas.append("-" * 80)
    linhas.append(item.get("texto_integral") or "")

    caminho_txt.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 80)
    print("AMOSTRA REAL DE PUBLICAÇÃO INLABS")
    print("=" * 80)
    print(f"Data teste: {data_str}")
    print(f"ID teste: {item.get('id_publicacao_teste')}")
    print(f"Fonte: {item.get('fonte')}")
    print(f"Seção: {item.get('secao')}")
    print(f"ZIP: {item.get('zip')}")
    print(f"Arquivo XML: {item.get('arquivo_xml')}")
    print(f"Tag raiz: {item.get('tag_raiz')}")
    print(f"Texto tamanho: {item.get('texto_tamanho')}")
    print("-" * 80)
    print(f"Título final: {item.get('titulo_final')}")
    print(f"Identifica: {item.get('identifica')}")
    print(f"Data XML: {item.get('data_xml')}")
    print(f"Ementa: {item.get('ementa')}")
    print(f"Título: {item.get('titulo')}")
    print(f"Subtítulo: {item.get('sub_titulo')}")
    print("-" * 80)
    print("Prévia do texto integral:")
    print((item.get("texto_integral") or "")[:3000])
    print("-" * 80)
    print(f"JSON amostra real: {caminho_json}")
    print(f"TXT amostra real: {caminho_txt}")
    print("=" * 80)

    return item


# ============================================================
# RUNNER
# ============================================================

def main() -> None:
    print("=" * 80)
    print("TESTE ISOLADO — DOU SEM PLAYWRIGHT / SEM NAVEGADOR")
    print("Fonte: INLABS / Imprensa Nacional")
    print("Data:", DATA_TESTE.isoformat())
    print("Seções:", ", ".join(TIPOS_DOU))
    print("Saída:", SAIDA_DIR)
    print("=" * 80)

    email, senha = obter_credenciais()
    session = criar_sessao_inlabs(email=email, senha=senha)

    resultados = []

    for secao in TIPOS_DOU:
        resultados.append(
            baixar_zip_secao(
                session=session,
                data_alvo=DATA_TESTE,
                secao=secao,
            )
        )

    total_zips_salvos = sum(1 for r in resultados if r.get("salvo"))
    total_xml = sum(int(r.get("xml_total") or 0) for r in resultados)

    resumo = {
        "data": DATA_TESTE.isoformat(),
        "fonte": "INLABS",
        "sem_playwright": True,
        "status_teste": "OK" if total_xml > 0 else "SEM_XML_CONFIRMADO",
        "total_zips_salvos": total_zips_salvos,
        "total_xml": total_xml,
        "saida_dir": str(SAIDA_DIR),
        "resultados": resultados,
    }

    caminho_resumo = SAIDA_DIR / f"resumo_teste_inlabs_{DATA_TESTE.isoformat()}.json"
    caminho_resumo.write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 80)
    print("RESULTADO DO TESTE")
    print("=" * 80)
    print("Zips salvos:", total_zips_salvos)
    print("XMLs encontrados:", total_xml)
    print("Resumo:", caminho_resumo)

    if total_xml > 0:
        print("STATUS: OK — foi possível obter dados estruturados do DOU sem Playwright.")
    else:
        print("STATUS: ATENÇÃO — nenhum XML confirmado. Verifique credenciais/data/seções.")

    print("=" * 80)

    if total_xml > 0:
        inspecionar_conteudo_inlabs(DATA_TESTE)
        salvar_e_mostrar_publicacao_real(DATA_TESTE)


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print("=" * 80)
        print("ERRO NO TESTE INLABS SEM PLAYWRIGHT")
        print("=" * 80)
        print(str(erro))
        print("=" * 80)
        sys.exit(1)