# ============================================================
# DRIVER COMUM — Busca Diária DOU
# Fonte oficial: INLABS / Imprensa Nacional
# Projeto Informativos
#
# Contrato oficial INLABS:
# - baixa ZIPs/XMLs do DOU por data;
# - extrai título, texto integral, link oficial, jornal, página e rastreabilidade;
# - salva backend/data/dou/bruto/publicacoes_YYYY-MM-DD.json;
# - mantém a função pública coletar_links_dou_diario(page, data_alvo, max_paginas=None)
#   para não quebrar o orquestrador atual.
# ============================================================

import datetime
import hashlib
import html
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError as exc:
    raise RuntimeError(
        "Biblioteca 'requests' não encontrada. Rode: pip install requests"
    ) from exc


# ============================================================
# CONFIGURAÇÕES
# ============================================================

TIPOS_DOU = ["DO1", "DO2", "DO3", "DO1E", "DO2E", "DO3E"]

URL_LOGIN = "https://inlabs.in.gov.br/logar.php"
URL_DOWNLOAD = "https://inlabs.in.gov.br/index.php"

ROOT_DIR = Path(__file__).resolve().parents[4]

BRUTO_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"
DEBUG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug"
INLABS_DIR = ROOT_DIR / "backend" / "data" / "dou" / "inlabs"

BRUTO_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
INLABS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILITÁRIOS
# ============================================================

def _agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _data_str(data_alvo: datetime.date) -> str:
    return data_alvo.isoformat()


def _pasta_inlabs_data(data_alvo: datetime.date) -> Path:
    pasta = INLABS_DIR / _data_str(data_alvo)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _zip_dir(data_alvo: datetime.date) -> Path:
    pasta = _pasta_inlabs_data(data_alvo) / "zips"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _publicacoes_path(data_alvo: datetime.date) -> Path:
    return BRUTO_DIR / f"publicacoes_{_data_str(data_alvo)}.json"


def _resumo_inlabs_path(data_alvo: datetime.date) -> Path:
    return _pasta_inlabs_data(data_alvo) / f"resumo_inlabs_{_data_str(data_alvo)}.json"


def _erro_debug_path(data_alvo: datetime.date) -> Path:
    return DEBUG_DIR / f"erro_busca_inlabs_dou_{_data_str(data_alvo)}.txt"


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


def obter_credenciais_inlabs() -> tuple[str, str]:
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
            "Credenciais INLABS não configuradas. "
            "Configure no PowerShell: "
            "$env:INLABS_EMAIL='seu_email'; "
            "$env:INLABS_PASSWORD='sua_senha'. "
            "Ou coloque INLABS_EMAIL e INLABS_PASSWORD no arquivo .env local."
        )

    return email, senha


def limpar_texto(valor: str | None, limite: int | None = None) -> str:
    if not valor:
        return ""

    texto = html.unescape(str(valor))
    texto = re.sub(r"\s+", " ", texto).strip()

    if limite is not None and len(texto) > limite:
        return texto[:limite].rstrip() + "..."

    return texto


def limpar_html_para_texto(valor: str | None) -> str:
    """
    Converte o HTML interno da tag Texto do INLABS em texto limpo.
    """
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


def nome_tag(elem: ET.Element) -> str:
    tag = str(elem.tag or "")
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return tag


def texto_tag_exata(root: ET.Element, tag_procurada: str) -> str:
    tag_procurada_norm = tag_procurada.lower()

    for elem in root.iter():
        if nome_tag(elem).lower() == tag_procurada_norm:
            partes = []
            for txt in elem.itertext():
                txt = str(txt or "")
                if txt.strip():
                    partes.append(txt)
            return "".join(partes).strip()

    return ""


def primeira_linha(texto: str, limite: int = 300) -> str:
    if not texto:
        return ""

    for linha in texto.splitlines():
        linha = limpar_texto(linha, limite=limite)
        if linha:
            return linha

    return limpar_texto(texto, limite=limite)


def montar_titulo(
    identifica: str,
    ementa: str,
    titulo: str,
    sub_titulo: str,
    texto_integral: str,
) -> str:
    for valor in [identifica, ementa, titulo, sub_titulo]:
        valor_limpo = limpar_texto(valor, limite=500)
        if valor_limpo:
            return valor_limpo

    fallback = primeira_linha(texto_integral, limite=300)
    if fallback:
        return fallback

    return "Publicação sem título detectado"


def gerar_id_publicacao(
    data_alvo: datetime.date,
    secao: str,
    nome_xml: str,
    texto_integral: str,
) -> str:
    base = f"{data_alvo.isoformat()}|{secao}|{Path(nome_xml).stem}"

    if texto_integral:
        h = hashlib.sha256(
            texto_integral.encode("utf-8", errors="ignore")
        ).hexdigest()[:12]
        return f"INLABS|{base}|{h}"

    return f"INLABS|{base}"


# ============================================================
# URL OFICIAL / JORNAL / PÁGINA
# ============================================================

def normalizar_url_xml(url: str) -> str:
    url = html.unescape(str(url or "")).strip().strip('"').strip("'")
    url = url.rstrip(".,;)]") if url else url
    return url


def extrair_urls_xml(xml_raw: str) -> list[str]:
    """
    Extrai URLs do XML bruto do INLABS.

    O mapeamento validado em 15/05/2026 mostrou URL oficial em 100% dos XMLs,
    principalmente no formato:
    http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=...&jornal=...&pagina=...
    """
    texto = html.unescape(str(xml_raw or ""))

    candidatos = re.findall(
        r"(https?://[^\s\"'<>]+|www\.[^\s\"'<>]+)",
        texto,
        flags=re.IGNORECASE,
    )

    urls: list[str] = []

    for candidato in candidatos:
        url = normalizar_url_xml(candidato)
        if not url:
            continue

        lower = url.lower()
        if (
            "pesquisa.in.gov.br/imprensa/jsp/visualiza" in lower
            or "in.gov.br/web/dou" in lower
            or "in.gov.br/consulta" in lower
            or "in.gov.br" in lower
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


def extrair_parametros_url_oficial(url: str) -> dict[str, str]:
    if not url:
        return {
            "data_url": "",
            "jornal": "",
            "pagina": "",
            "url_host": "",
            "url_path": "",
        }

    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return {
            "data_url": (query.get("data") or [""])[0],
            "jornal": (query.get("jornal") or [""])[0],
            "pagina": (query.get("pagina") or [""])[0],
            "url_host": parsed.netloc or "",
            "url_path": parsed.path or "",
        }
    except Exception:
        return {
            "data_url": "",
            "jornal": "",
            "pagina": "",
            "url_host": "",
            "url_path": "",
        }


def contar_atos_internos(texto_html: str) -> int:
    if not texto_html:
        return 0

    texto = html.unescape(str(texto_html))
    return len(
        re.findall(
            r'<p[^>]*class=["\'][^"\']*identifica[^"\']*["\'][^>]*>',
            texto,
            flags=re.IGNORECASE,
        )
    )



def extrair_grupo_xml_inlabs(nome_xml: str) -> str:
    """
    Agrupa XMLs que pertencem à mesma publicação paginada do INLABS.

    Exemplo real validado:
    - 530_20260515_23939787-1.xml -> grupo 530_20260515_23939787
    - 530_20260515_23939787-7.xml -> grupo 530_20260515_23939787

    O XML -1 traz o título oficial do edital; os XMLs seguintes podem ser
    continuação da tabela, sem Identifica/Titulo próprios.
    """
    stem = Path(str(nome_xml or "")).stem
    return re.sub(r"-\d+$", "", stem)


def extrair_indice_xml_inlabs(nome_xml: str) -> int:
    """
    Retorna o índice sequencial do XML dentro de um grupo paginado.
    Arquivos sem sufixo numérico recebem 0.
    """
    stem = Path(str(nome_xml or "")).stem
    m = re.search(r"-(\d+)$", stem)

    if not m:
        return 0

    try:
        return int(m.group(1))
    except Exception:
        return 0


def chave_ordenacao_xml_inlabs(nome_xml: str) -> tuple[str, int, str]:
    """
    Ordenação natural para evitar que -10 venha antes de -2.
    """
    grupo = extrair_grupo_xml_inlabs(nome_xml)
    indice = extrair_indice_xml_inlabs(nome_xml)
    return (grupo, indice, str(nome_xml or ""))


def tem_titulo_oficial_inlabs(
    identifica: str,
    ementa: str,
    titulo_xml: str,
    sub_titulo: str,
) -> bool:
    """
    Indica se o XML tem campo oficial de título próprio.
    Não confundir com primeira célula de tabela.
    """
    return any(
        limpar_texto(valor, limite=None)
        for valor in [identifica, ementa, titulo_xml, sub_titulo]
    )


def texto_tem_tabela_html(texto_html: str) -> bool:
    texto = str(texto_html or "").lower()
    return "<table" in texto or "<tr" in texto or "<td" in texto


def montar_resumo_listagem_inlabs(
    texto_preview: str,
    item_interno_tabela: str,
    eh_continuacao_tabela: bool,
) -> str:
    """
    Para continuação de tabela, preserva o item interno no resumo sem usá-lo
    como título principal.
    """
    if eh_continuacao_tabela and item_interno_tabela:
        return limpar_texto(
            f"Item interno: {item_interno_tabela}. {texto_preview}",
            limite=500,
        )

    return texto_preview

# ============================================================
# INLABS — LOGIN E DOWNLOAD
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
    caminho_zip = _zip_dir(data_alvo) / nome_zip

    cookie = session.cookies.get("inlabs_session_cookie")

    headers = {
        "Cookie": f"inlabs_session_cookie={cookie}",
        "origem": "736372697074",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python requests INLABS",
    }

    url = f"{URL_DOWNLOAD}?p={data_str}&dl={nome_zip}"

    print(f"[INLABS] Baixando {nome_zip}...")

    response = session.get(
        url,
        headers=headers,
        timeout=120,
    )

    resultado: dict[str, Any] = {
        "secao": secao,
        "nome_zip": nome_zip,
        "url": url,
        "http_status": response.status_code,
        "salvo": False,
        "caminho_zip": str(caminho_zip),
        "tamanho_zip_bytes": 0,
        "xml_total": 0,
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
        nomes_xml = [
            nome for nome in zf.namelist()
            if nome.lower().endswith(".xml")
        ]
        resultado["xml_total"] = len(nomes_xml)

    print(
        f"[INLABS] {nome_zip}: OK | "
        f"zip_bytes={resultado['tamanho_zip_bytes']} | "
        f"xml_total={resultado['xml_total']}"
    )

    return resultado


def baixar_zips_inlabs(data_alvo: datetime.date) -> dict[str, Any]:
    email, senha = obter_credenciais_inlabs()
    session = criar_sessao_inlabs(email=email, senha=senha)

    resultados = []

    for secao in TIPOS_DOU:
        resultado = baixar_zip_secao(
            session=session,
            data_alvo=data_alvo,
            secao=secao,
        )
        resultados.append(resultado)

    total_zips_salvos = sum(1 for r in resultados if r.get("salvo"))
    total_xml = sum(int(r.get("xml_total") or 0) for r in resultados)

    resumo = {
        "data": data_alvo.isoformat(),
        "fonte": "INLABS",
        "coletado_em": _agora_iso(),
        "total_zips_salvos": total_zips_salvos,
        "total_xml": total_xml,
        "resultados": resultados,
    }

    _resumo_inlabs_path(data_alvo).write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return resumo


# ============================================================
# PARSER XML INLABS
# ============================================================

def extrair_publicacao_xml(
    conteudo: bytes,
    nome_xml: str,
    secao: str,
    zip_nome: str,
    data_alvo: datetime.date,
    publicacao_pai: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        texto_bruto = conteudo.decode("utf-8", errors="ignore")
        root = ET.fromstring(texto_bruto)
    except Exception as erro:
        return {
            "fonte": "INLABS",
            "origem": "INLABS",
            "data_publicacao": data_alvo.isoformat(),
            "secao": secao,
            "zip": zip_nome,
            "arquivo_xml": nome_xml,
            "erro_parse_xml": str(erro),
            "texto_integral": "",
            "texto_html": "",
            "titulo": "XML inválido",
            "titulo_listagem": "XML inválido",
            "resumo_listagem": "",
            "url": "",
            "url_publicacao": "",
            "link": "",
            "href": "",
            "url_consulta_dou": "",
            "pagina": "",
            "jornal": "",
            "xml_grupo_inlabs": extrair_grupo_xml_inlabs(nome_xml),
            "xml_indice_grupo": extrair_indice_xml_inlabs(nome_xml),
            "eh_continuacao_inlabs": False,
            "tipo_publicacao_inlabs": "XML_INVALIDO",
        }

    identifica = texto_tag_exata(root, "Identifica")
    data_xml = texto_tag_exata(root, "Data")
    ementa = texto_tag_exata(root, "Ementa")
    titulo_xml = texto_tag_exata(root, "Titulo")
    sub_titulo = texto_tag_exata(root, "SubTitulo")
    texto_html = texto_tag_exata(root, "Texto")

    texto_integral = limpar_html_para_texto(texto_html)
    if not texto_integral:
        texto_integral = limpar_texto(" ".join(root.itertext()), limite=None)

    titulo_extraido_original = montar_titulo(
        identifica=identifica,
        ementa=ementa,
        titulo=titulo_xml,
        sub_titulo=sub_titulo,
        texto_integral=texto_integral,
    )

    tem_titulo_oficial = tem_titulo_oficial_inlabs(
        identifica=identifica,
        ementa=ementa,
        titulo_xml=titulo_xml,
        sub_titulo=sub_titulo,
    )

    xml_grupo = extrair_grupo_xml_inlabs(nome_xml)
    xml_indice_grupo = extrair_indice_xml_inlabs(nome_xml)

    titulo_publicacao_pai = ""
    id_publicacao_pai = ""
    arquivo_xml_pai = ""
    url_publicacao_pai = ""
    pagina_publicacao_pai = ""
    item_interno_tabela = ""
    eh_continuacao_inlabs = False
    tipo_publicacao_inlabs = "PUBLICACAO_PRINCIPAL"

    # Regra validada no caso 2026-05-15 / DO3:
    # XMLs 530_20260515_23939787-2.xml ... -9.xml eram continuação
    # de tabela do "Edital de Notificação nº 9/2026 - Dipro".
    #
    # Antes, quando Identifica/Titulo vinham vazios, o driver usava a
    # primeira célula da tabela como título. Isso gerou casos como
    # "Giselle Cristina Gonçalves Oliveira" como se fossem publicações
    # independentes. Agora o título principal é herdado do XML pai do grupo.
    if (
        not tem_titulo_oficial
        and publicacao_pai
        and publicacao_pai.get("xml_grupo_inlabs") == xml_grupo
    ):
        titulo_publicacao_pai = str(
            publicacao_pai.get("titulo_publicacao_pai")
            or publicacao_pai.get("titulo")
            or ""
        ).strip()

        if titulo_publicacao_pai:
            eh_continuacao_inlabs = True
            tipo_publicacao_inlabs = "CONTINUACAO_TABELA"
            id_publicacao_pai = str(publicacao_pai.get("id_publicacao") or "").strip()
            arquivo_xml_pai = str(publicacao_pai.get("arquivo_xml") or "").strip()
            url_publicacao_pai = str(publicacao_pai.get("url_publicacao") or "").strip()
            pagina_publicacao_pai = str(publicacao_pai.get("pagina") or "").strip()
            item_interno_tabela = titulo_extraido_original
            titulo = titulo_publicacao_pai
        else:
            titulo = titulo_extraido_original
            tipo_publicacao_inlabs = "SEM_TITULO_OFICIAL"
    else:
        titulo = titulo_extraido_original
        titulo_publicacao_pai = titulo if tem_titulo_oficial else ""
        if not tem_titulo_oficial:
            tipo_publicacao_inlabs = "SEM_TITULO_OFICIAL"

    id_publicacao = gerar_id_publicacao(
        data_alvo=data_alvo,
        secao=secao,
        nome_xml=nome_xml,
        texto_integral=texto_integral,
    )

    urls_encontradas = extrair_urls_xml(texto_bruto)
    url_oficial = escolher_url_oficial(urls_encontradas)
    parametros_url = extrair_parametros_url_oficial(url_oficial)

    pagina = parametros_url.get("pagina", "")
    jornal = parametros_url.get("jornal", "")
    data_url = parametros_url.get("data_url", "")
    texto_preview = limpar_texto(texto_integral, limite=500)
    atos_internos = contar_atos_internos(texto_html)
    tem_tabela = texto_tem_tabela_html(texto_html)

    resumo_listagem = montar_resumo_listagem_inlabs(
        texto_preview=texto_preview,
        item_interno_tabela=item_interno_tabela,
        eh_continuacao_tabela=eh_continuacao_inlabs,
    )

    return {
        "id_publicacao": id_publicacao,
        "fonte": "INLABS",
        "origem": "INLABS",
        "data_publicacao": data_alvo.isoformat(),
        "data_xml": limpar_texto(data_xml, limite=None),
        "data_url": data_url,
        "secao": secao,
        "zip": zip_nome,
        "arquivo_xml": nome_xml,

        # Título principal usado por base/match/e-mail.
        "titulo": titulo,
        "titulo_listagem": titulo,

        # Campos adicionais para rastreabilidade e apresentação correta.
        "titulo_extraido_original": titulo_extraido_original,
        "titulo_original_inlabs": titulo_extraido_original,
        "titulo_publicacao_pai": titulo_publicacao_pai,
        "id_publicacao_pai": id_publicacao_pai,
        "arquivo_xml_pai": arquivo_xml_pai,
        "url_publicacao_pai": url_publicacao_pai,
        "pagina_publicacao_pai": pagina_publicacao_pai,
        "item_interno_tabela": item_interno_tabela,
        "eh_continuacao_inlabs": eh_continuacao_inlabs,
        "tipo_publicacao_inlabs": tipo_publicacao_inlabs,
        "tem_titulo_oficial_inlabs": tem_titulo_oficial,
        "xml_grupo_inlabs": xml_grupo,
        "xml_indice_grupo": xml_indice_grupo,

        "resumo_listagem": resumo_listagem,
        "identifica": limpar_texto(identifica, limite=None),
        "ementa": limpar_texto(ementa, limite=None),
        "titulo_xml": limpar_texto(titulo_xml, limite=None),
        "sub_titulo": limpar_texto(sub_titulo, limite=None),
        "texto_html": texto_html,
        "texto_integral": texto_integral,
        "texto": texto_integral,
        "texto_tamanho": len(texto_integral),
        "url": url_oficial,
        "url_publicacao": url_oficial,
        "link": url_oficial,
        "href": url_oficial,
        "url_consulta_dou": url_oficial,
        "urls_encontradas_xml": urls_encontradas,
        "pagina": pagina,
        "jornal": jornal,
        "url_host": parametros_url.get("url_host", ""),
        "url_path": parametros_url.get("url_path", ""),
        "tem_url_oficial": bool(url_oficial),
        "atos_internos_estimados": atos_internos,
        "tem_multiplos_atos": atos_internos > 1,
        "tem_tabela_html": tem_tabela,
        "arquivo_origem": zip_nome,
    }


def carregar_publicacoes_dos_zips(data_alvo: datetime.date) -> list[dict[str, Any]]:
    zips = sorted(_zip_dir(data_alvo).glob("*.zip"))
    publicacoes: list[dict[str, Any]] = []

    for zip_path in zips:
        if not zipfile.is_zipfile(zip_path):
            print(f"[INLABS] Ignorando ZIP inválido: {zip_path}")
            continue

        secao = zip_path.stem.split("-")[-1]
        print(f"[INLABS] Lendo XMLs de {zip_path.name}...")

        # Guarda a publicação principal de cada grupo paginado.
        # Ex.: 530_20260515_23939787-1.xml é pai de 530_20260515_23939787-7.xml.
        publicacoes_pai_por_grupo: dict[str, dict[str, Any]] = {}
        total_continuacoes_zip = 0

        with zipfile.ZipFile(zip_path, "r") as zf:
            nomes_xml = sorted(
                [
                    nome for nome in zf.namelist()
                    if nome.lower().endswith(".xml")
                ],
                key=chave_ordenacao_xml_inlabs,
            )

            for nome_xml in nomes_xml:
                conteudo = zf.read(nome_xml)
                grupo_xml = extrair_grupo_xml_inlabs(nome_xml)
                publicacao_pai = publicacoes_pai_por_grupo.get(grupo_xml)

                item = extrair_publicacao_xml(
                    conteudo=conteudo,
                    nome_xml=nome_xml,
                    secao=secao,
                    zip_nome=zip_path.name,
                    data_alvo=data_alvo,
                    publicacao_pai=publicacao_pai,
                )

                if item is not None:
                    publicacoes.append(item)

                    if item.get("eh_continuacao_inlabs"):
                        total_continuacoes_zip += 1

                    # Atualiza pai apenas quando o XML tem título oficial próprio.
                    # Continuação de tabela não pode sobrescrever o pai.
                    if item.get("tem_titulo_oficial_inlabs"):
                        publicacoes_pai_por_grupo[grupo_xml] = item

        if total_continuacoes_zip:
            print(
                f"[INLABS] {zip_path.name}: continuações/tabelas herdadas="
                f"{total_continuacoes_zip}"
            )

    return publicacoes



# ============================================================
# FUNÇÕES PÚBLICAS PRESERVADAS
# ============================================================

async def realizar_busca_dou(page, data_alvo: datetime.date) -> dict:
    print(f"[DOU/INLABS] Iniciando busca diária: {data_alvo.isoformat()}")

    resumo = baixar_zips_inlabs(data_alvo)
    total_xml = int(resumo.get("total_xml") or 0)

    if total_xml <= 0:
        return {
            "status_busca": "SEM_PUBLICACOES",
            "mensagem": "Nenhum XML encontrado no INLABS para a data",
            "total_xml": 0,
            "resumo_inlabs": resumo,
        }

    return {
        "status_busca": "COM_PUBLICACOES",
        "mensagem": f"{total_xml} XMLs encontrados no INLABS",
        "total_xml": total_xml,
        "resumo_inlabs": resumo,
    }


async def coletar_links_dou_diario(
    page,
    data_alvo: datetime.date,
    max_paginas: int | None = None,
) -> dict:
    print("=" * 80)
    print("DRIVER DOU — INLABS OFICIAL")
    print("=" * 80)
    print(f"Data: {data_alvo.isoformat()}")
    print("Fonte: INLABS / Imprensa Nacional")
    print("Playwright: DESATIVADO")
    print("Scraping visual: DESATIVADO")
    print("Contrato: título + texto + link oficial + jornal + página")
    print("=" * 80)

    try:
        status_busca = await realizar_busca_dou(page, data_alvo)

        if status_busca["status_busca"] == "SEM_PUBLICACOES":
            payload_sem_publicacoes = {
                "data": data_alvo.isoformat(),
                "fonte": "INLABS",
                "origem": "INLABS",
                "gerado_em": _agora_iso(),
                "status_busca": "SEM_PUBLICACOES",
                "mensagem": status_busca["mensagem"],
                "total_publicacoes": 0,
                "total_links": 0,
                "total_com_url": 0,
                "total_sem_url": 0,
                "publicacoes": [],
                "links": [],
            }

            _publicacoes_path(data_alvo).write_text(
                json.dumps(payload_sem_publicacoes, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            return {
                "data": data_alvo.isoformat(),
                "status_busca": "SEM_PUBLICACOES",
                "mensagem": status_busca["mensagem"],
                "total_paginas_detectadas": 0,
                "paginas_visitadas": [],
                "total_links": 0,
                "total_publicacoes": 0,
                "links": [],
                "publicacoes": [],
                "fonte": "INLABS",
            }

        publicacoes = carregar_publicacoes_dos_zips(data_alvo)
        publicacoes_validas = [p for p in publicacoes if p.get("texto_integral")]

        total_com_url = sum(1 for p in publicacoes_validas if p.get("url"))
        total_sem_url = len(publicacoes_validas) - total_com_url
        total_multiplos_atos = sum(
            1 for p in publicacoes_validas if p.get("tem_multiplos_atos")
        )
        total_continuacoes_inlabs = sum(
            1 for p in publicacoes_validas if p.get("eh_continuacao_inlabs")
        )

        caminho_publicacoes = _publicacoes_path(data_alvo)

        payload_publicacoes = {
            "data": data_alvo.isoformat(),
            "fonte": "INLABS",
            "origem": "INLABS",
            "gerado_em": _agora_iso(),
            "status_busca": "COM_PUBLICACOES",
            "mensagem": "Busca concluída com publicações via INLABS",
            "total_publicacoes": len(publicacoes_validas),
            "total_links": len(publicacoes_validas),
            "total_com_url": total_com_url,
            "total_sem_url": total_sem_url,
            "total_multiplos_atos": total_multiplos_atos,
            "total_continuacoes_inlabs": total_continuacoes_inlabs,
            "publicacoes": publicacoes_validas,
            "links": publicacoes_validas,
            "resumo_inlabs": status_busca.get("resumo_inlabs"),
        }

        caminho_publicacoes.write_text(
            json.dumps(payload_publicacoes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("=" * 80)
        print("BUSCA DOU INLABS CONCLUÍDA")
        print("=" * 80)
        print(f"Publicações extraídas: {len(publicacoes_validas)}")
        print(f"Publicações com link oficial: {total_com_url}")
        print(f"Publicações sem link oficial: {total_sem_url}")
        print(f"Publicações com múltiplos atos internos: {total_multiplos_atos}")
        print(f"Continuações/tabelas com título herdado: {total_continuacoes_inlabs}")
        print(f"Arquivo bruto salvo: {caminho_publicacoes}")
        print("=" * 80)

        return {
            "data": data_alvo.isoformat(),
            "status_busca": "COM_PUBLICACOES",
            "mensagem": "Busca concluída com publicações via INLABS",
            "fonte": "INLABS",
            "total_paginas_detectadas": 0,
            "paginas_visitadas": [],
            "total_links": len(publicacoes_validas),
            "total_publicacoes": len(publicacoes_validas),
            "total_com_url": total_com_url,
            "total_sem_url": total_sem_url,
            "total_continuacoes_inlabs": total_continuacoes_inlabs,
            "links": publicacoes_validas,
            "publicacoes": publicacoes_validas,
            "arquivo_publicacoes": str(caminho_publicacoes),
            "resumo_inlabs": status_busca.get("resumo_inlabs"),
        }

    except Exception as erro:
        caminho_erro = _erro_debug_path(data_alvo)
        caminho_erro.write_text(
            "\n".join([
                "=" * 80,
                "ERRO NO DRIVER DOU INLABS",
                "=" * 80,
                f"Data: {data_alvo.isoformat()}",
                f"Erro: {erro}",
                "=" * 80,
            ]),
            encoding="utf-8",
        )

        print("=" * 80)
        print("ERRO NO DRIVER DOU INLABS")
        print("=" * 80)
        print(f"Data: {data_alvo.isoformat()}")
        print(f"Erro: {erro}")
        print(f"Debug: {caminho_erro}")
        print("=" * 80)
        raise
