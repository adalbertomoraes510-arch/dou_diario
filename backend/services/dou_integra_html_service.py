# -*- coding: utf-8 -*-
"""
Serviço para geração de páginas HTML/TXT de íntegra das publicações do DOU
com palavras-chave localizadas.

Este serviço não envia e-mail e não altera regra de match. Ele apenas consome
os JSONs já gerados em backend/data/dou/match/<finalidade>/ e cria arquivos em
backend/data/dou/integras/<finalidade>/<AAAA-MM-DD>/.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "backend" / "data" / "dou"


HTML_PADRAO_TITULO = "DIÁRIO OFICIAL DA UNIÃO"
AVISO_CERTIFICADO = "Este conteúdo não substitui o publicado na versão certificada."


# -----------------------------------------------------------------------------
# Utilitários básicos
# -----------------------------------------------------------------------------


def normalizar(txt: Any) -> str:
    txt = "" if txt is None else str(txt)
    txt = unicodedata.normalize("NFKD", txt)
    txt = txt.encode("ASCII", "ignore").decode("ASCII")
    return txt.lower()


def normalizar_com_mapa(txt: Any) -> Tuple[str, List[int]]:
    txt = "" if txt is None else str(txt)

    norm_chars: List[str] = []
    mapa: List[int] = []

    for idx, ch in enumerate(txt):
        decomposed = unicodedata.normalize("NFKD", ch)

        for d in decomposed:
            if unicodedata.combining(d):
                continue

            ascii_ch = d.encode("ASCII", "ignore").decode("ASCII").lower()

            if ascii_ch:
                norm_chars.append(ascii_ch)
                mapa.append(idx)

    return "".join(norm_chars), mapa


def slugify(txt: Any, limite: int = 140) -> str:
    txt = normalizar(txt)
    txt = re.sub(r"[^a-z0-9]+", "-", txt)
    txt = txt.strip("-")

    if not txt:
        txt = "publicacao"

    return txt[:limite].strip("-") or "publicacao"


def data_para_iso(data_execucao: Any) -> str:
    if isinstance(data_execucao, _dt.date):
        return data_execucao.isoformat()

    texto = str(data_execucao).strip()

    if re.match(r"^\d{4}-\d{2}-\d{2}$", texto):
        return texto

    if re.match(r"^\d{2}/\d{2}/\d{4}$", texto):
        d, m, a = texto.split("/")
        return f"{a}-{m}-{d}"

    raise ValueError(f"Data inválida para geração de íntegra: {data_execucao!r}")


def data_para_br(data_iso: str) -> str:
    a, m, d = data_iso.split("-")
    return f"{d}/{m}/{a}"


def primeiro_valor(dados: Dict[str, Any], chaves: Iterable[str], padrao: str = "") -> str:
    for chave in chaves:
        valor = dados.get(chave)

        if valor is None:
            continue

        valor_txt = str(valor).strip()

        if valor_txt:
            return valor_txt

    return padrao


def coletar_urls(obj: Any) -> List[str]:
    urls: List[str] = []

    if isinstance(obj, dict):
        for valor in obj.values():
            urls.extend(coletar_urls(valor))
    elif isinstance(obj, list):
        for item in obj:
            urls.extend(coletar_urls(item))
    elif isinstance(obj, str):
        urls.extend(re.findall(r"https?://[^\s\"'<>]+", obj))

    # Mantém ordem e remove duplicados.
    vistos = set()
    saida = []

    for url in urls:
        url_limpa = url.strip().rstrip(".,;)")

        if url_limpa and url_limpa not in vistos:
            vistos.add(url_limpa)
            saida.append(url_limpa)

    return saida


def rotulo_url(url: str) -> str:
    m = re.search(r"pagina=(\d+)", url)

    if m:
        return f"Abrir DOU página {m.group(1)}"

    return "Abrir página oficial do DOU"


# -----------------------------------------------------------------------------
# Extração dos dados do JSON de match
# -----------------------------------------------------------------------------


def carregar_json_match(data_execucao: Any, finalidade: str = "dou_diario") -> Dict[str, Any]:
    data_iso = data_para_iso(data_execucao)
    caminho = DATA_DIR / "match" / finalidade / f"match_publicacoes_{data_iso}.json"

    if not caminho.exists():
        raise FileNotFoundError(f"JSON de match não encontrado: {caminho}")

    return json.loads(caminho.read_text(encoding="utf-8"))


def obter_registros(dados_json: Any) -> List[Dict[str, Any]]:
    if isinstance(dados_json, list):
        return [x for x in dados_json if isinstance(x, dict)]

    if isinstance(dados_json, dict):
        for chave in ("registros", "publicacoes", "itens", "resultados"):
            valor = dados_json.get(chave)

            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]

    return []


def extrair_termos_match(registro: Dict[str, Any]) -> List[str]:
    termos: List[str] = []

    candidatos = []

    for chave in (
        "matchs",
        "matches",
        "palavras_chave",
        "palavras_chave_localizadas",
        "palavras_localizadas",
        "keywords",
    ):
        valor = registro.get(chave)

        if valor:
            candidatos.append(valor)

    def adicionar(valor: Any) -> None:
        if valor is None:
            return

        if isinstance(valor, str):
            termo = valor.strip()

            if termo and termo not in termos:
                termos.append(termo)

            return

        if isinstance(valor, dict):
            for k in ("termo", "palavra", "palavra_chave", "keyword", "valor", "texto"):
                if valor.get(k):
                    adicionar(valor.get(k))
                    return

            return

        if isinstance(valor, list):
            for item in valor:
                adicionar(item)

    for candidato in candidatos:
        adicionar(candidato)

    return termos


def registro_tem_match(registro: Dict[str, Any]) -> bool:
    if extrair_termos_match(registro):
        return True

    for chave in ("tem_match", "com_match", "match", "encontrado"):
        valor = registro.get(chave)

        if isinstance(valor, bool) and valor:
            return True

        if isinstance(valor, str) and valor.strip().lower() in {"sim", "true", "1", "s", "com_match"}:
            return True

    return False


def extrair_texto_publicacao(registro: Dict[str, Any]) -> str:
    return primeiro_valor(
        registro,
        (
            "texto_integral",
            "texto_publicacao",
            "texto",
            "conteudo",
            "corpo",
            "ementa_texto",
        ),
    )


def extrair_titulo(registro: Dict[str, Any]) -> str:
    return primeiro_valor(
        registro,
        (
            "titulo",
            "titulo_publicacao",
            "identificacao",
            "nome_publicacao",
            "ato",
        ),
        "Publicação sem título",
    )


def extrair_orgao(registro: Dict[str, Any]) -> str:
    return primeiro_valor(
        registro,
        (
            "orgao",
            "órgão",
            "hierarquia",
            "nome_orgao",
            "orgao_publicador",
            "departamento",
        ),
        "Órgão não informado",
    )


def limpar_inicio_texto(texto: str, titulo: str) -> str:
    texto = str(texto or "").strip()
    titulo_norm = normalizar(titulo).strip()

    if not texto or not titulo_norm:
        return texto

    linhas = texto.splitlines()

    # Remove repetições exatas do título no começo do bloco.
    while linhas and normalizar(linhas[0]).strip() == titulo_norm:
        linhas.pop(0)

    return "\n".join(linhas).strip()


def chave_publicacao(registro: Dict[str, Any]) -> str:
    """
    Agrupa partes de uma mesma publicação.

    Usamos título + órgão porque, no INLABS, uma publicação longa pode aparecer
    em mais de uma página/bloco, mas mantendo o mesmo título e órgão.
    """

    titulo = extrair_titulo(registro)
    orgao = extrair_orgao(registro)
    return f"{slugify(titulo, 180)}__{slugify(orgao, 80)}"


def consolidar_publicacoes(registros: List[Dict[str, Any]], data_iso: str) -> List[Dict[str, Any]]:
    grupos: Dict[str, Dict[str, Any]] = {}

    for registro in registros:
        if not registro_tem_match(registro):
            continue

        texto = extrair_texto_publicacao(registro)

        if not texto:
            continue

        titulo = extrair_titulo(registro)
        orgao = extrair_orgao(registro)
        chave = chave_publicacao(registro)

        pagina = primeiro_valor(registro, ("pagina", "pagina_publicacao", "page"))
        edicao = primeiro_valor(registro, ("edicao", "edição", "numero_edicao", "edicao_dou"))
        secao = primeiro_valor(registro, ("secao", "seção", "jornal", "secao_dou"))

        if chave not in grupos:
            grupos[chave] = {
                "titulo": titulo,
                "orgao": orgao,
                "data_iso": data_iso,
                "data_br": data_para_br(data_iso),
                "edicao": edicao,
                "secao": secao,
                "paginas": [],
                "urls": [],
                "termos": [],
                "partes": [],
            }

        grupo = grupos[chave]

        if edicao and not grupo.get("edicao"):
            grupo["edicao"] = edicao

        if secao and not grupo.get("secao"):
            grupo["secao"] = secao

        if pagina and str(pagina) not in grupo["paginas"]:
            grupo["paginas"].append(str(pagina))

        for url in coletar_urls(registro):
            if url not in grupo["urls"]:
                grupo["urls"].append(url)

        for termo in extrair_termos_match(registro):
            if termo not in grupo["termos"]:
                grupo["termos"].append(termo)

        grupo["partes"].append({
            "pagina": pagina,
            "texto": limpar_inicio_texto(texto, titulo),
        })

    saida = []

    for grupo in grupos.values():
        grupo["partes"].sort(
            key=lambda p: int(str(p.get("pagina") or "999999"))
            if str(p.get("pagina") or "").isdigit()
            else 999999
        )

        textos = []
        vistos_texto = set()

        for parte in grupo["partes"]:
            texto = str(parte.get("texto") or "").strip()

            if not texto:
                continue

            chave_texto = normalizar(texto)[:3000]

            if chave_texto in vistos_texto:
                continue

            vistos_texto.add(chave_texto)
            textos.append(texto)

        grupo["texto_integral_consolidado"] = "\n\n".join(textos).strip()
        saida.append(grupo)

    saida.sort(key=lambda g: (g.get("paginas") or ["999999"])[0])
    return saida


# -----------------------------------------------------------------------------
# Destaques e navegação de palavras-chave
# -----------------------------------------------------------------------------


def termo_para_regex_flexivel(termo: str) -> Optional[str]:
    partes = re.findall(r"[a-z0-9]+", normalizar(termo))

    if not partes:
        return None

    return r"[\s\-\–\—_/.,;:()]*".join(re.escape(p) for p in partes)


def localizar_ocorrencias_flexiveis(texto: str, termos: Iterable[str]) -> List[Dict[str, Any]]:
    texto_norm, mapa = normalizar_com_mapa(texto)
    ocorrencias: List[Dict[str, Any]] = []

    termos_unicos = []

    for termo in termos:
        termo = str(termo).strip()

        if termo and termo not in termos_unicos:
            termos_unicos.append(termo)

    for termo in sorted(termos_unicos, key=len, reverse=True):
        padrao = termo_para_regex_flexivel(termo)

        if not padrao:
            continue

        padrao_final = r"(?<![a-z0-9])" + padrao + r"(?![a-z0-9])"

        for match in re.finditer(padrao_final, texto_norm, flags=re.IGNORECASE):
            ini_norm = match.start()
            fim_norm = match.end()

            if ini_norm >= len(mapa) or fim_norm - 1 >= len(mapa):
                continue

            ini_original = mapa[ini_norm]
            fim_original = mapa[fim_norm - 1] + 1

            if fim_original <= ini_original:
                continue

            ocorrencias.append({
                "termo": termo,
                "ini": ini_original,
                "fim": fim_original,
            })

    # Prioriza ocorrência mais longa quando houver sobreposição.
    ocorrencias.sort(key=lambda x: (x["ini"], -(x["fim"] - x["ini"])))

    filtradas: List[Dict[str, Any]] = []

    for oc in ocorrencias:
        tem_sobreposicao = False

        for existente in filtradas:
            if not (oc["fim"] <= existente["ini"] or oc["ini"] >= existente["fim"]):
                tem_sobreposicao = True
                break

        if not tem_sobreposicao:
            filtradas.append(oc)

    filtradas.sort(key=lambda x: x["ini"])
    return filtradas


def renderizar_texto_com_destaques(texto: str, termos: Iterable[str]) -> Tuple[str, Dict[str, int]]:
    ocorrencias = localizar_ocorrencias_flexiveis(texto, termos)

    contagem_por_termo: Dict[str, int] = {}
    partes_html: List[str] = []
    cursor = 0

    for oc in ocorrencias:
        termo = oc["termo"]
        contagem_por_termo[termo] = contagem_por_termo.get(termo, 0) + 1

        numero = contagem_por_termo[termo]
        termo_id = slugify(termo, 80)
        sid = f"kw-{termo_id}-{numero}"

        partes_html.append(_html.escape(texto[cursor:oc["ini"]]))

        trecho = texto[oc["ini"]:oc["fim"]]

        partes_html.append(
            f'<mark id="{sid}" '
            f'class="kw-mark" '
            f'data-termo-id="{_html.escape(termo_id)}" '
            f'data-termo="{_html.escape(termo)}" '
            f'title="{_html.escape(termo)}">'
            f'{_html.escape(trecho)}'
            f'</mark>'
        )

        cursor = oc["fim"]

    partes_html.append(_html.escape(texto[cursor:]))
    return "".join(partes_html), contagem_por_termo


# -----------------------------------------------------------------------------
# Geração TXT/HTML
# -----------------------------------------------------------------------------


def montar_txt(publicacao: Dict[str, Any], termos_visiveis: List[str], contagem: Dict[str, int]) -> str:
    titulo = publicacao.get("titulo") or "Publicação sem título"
    linhas: List[str] = []

    linhas.append(titulo)
    linhas.append("=" * len(titulo))
    linhas.append("")
    linhas.append(f"Publicado em: {publicacao.get('data_br') or ''}")
    linhas.append(f"Edição: {publicacao.get('edicao') or ''}")
    linhas.append(f"Seção: {publicacao.get('secao') or ''}")
    linhas.append(f"Páginas-base INLABS: {', '.join(publicacao.get('paginas') or [])}")
    linhas.append(f"Órgão: {publicacao.get('orgao') or ''}")
    linhas.append("")
    linhas.append("PALAVRAS-CHAVE LOCALIZADAS")
    linhas.append("-" * 80)

    for termo in termos_visiveis:
        linhas.append(f"- {termo}: {contagem.get(termo, 0)} ocorrência(s)")

    linhas.append("")
    linhas.append("LINKS OFICIAIS")
    linhas.append("-" * 80)

    for url in publicacao.get("urls") or []:
        linhas.append(url)

    linhas.append("")
    linhas.append("TEXTO INTEGRAL")
    linhas.append("-" * 80)
    linhas.append(titulo)
    linhas.append("")
    linhas.append(publicacao.get("texto_integral_consolidado") or "")

    return "\n".join(linhas)


def montar_html(
    publicacao: Dict[str, Any],
    texto_html: str,
    termos_visiveis: List[str],
    contagem: Dict[str, int],
    nome_txt: str,
) -> str:
    titulo = publicacao.get("titulo") or "Publicação sem título"
    data_br = publicacao.get("data_br") or ""
    edicao = publicacao.get("edicao") or ""
    secao = publicacao.get("secao") or ""
    paginas = ", ".join(publicacao.get("paginas") or [])
    orgao = publicacao.get("orgao") or "Órgão não informado"

    chips_html = ""

    for termo in termos_visiveis:
        qtd = contagem.get(termo, 0)
        termo_id = slugify(termo, 80)

        chips_html += f'''
    <a href="#" class="chip" data-termo-id="{_html.escape(termo_id)}" onclick="return selecionarTermo('{_html.escape(termo_id)}');">
        {_html.escape(termo)}
        <span>{qtd}</span>
    </a>'''

    links_html = ""

    for url in publicacao.get("urls") or []:
        links_html += f'''
    <a href="{_html.escape(url)}" target="_blank" class="btn secondary">
        {_html.escape(rotulo_url(url))}
    </a>'''

    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>{_html.escape(titulo)}</title>

<style>
    html {{ scroll-behavior: smooth; }}

    body {{
        margin: 0;
        background: #ffffff;
        color: #061b33;
        font-family: Arial, Helvetica, sans-serif;
    }}

    .pagina {{
        max-width: 1240px;
        margin: 0 auto;
        padding: 34px 70px 90px 70px;
    }}

    .dou-titulo {{
        text-align: center;
        font-family: Georgia, "Times New Roman", serif;
        font-size: 42px;
        letter-spacing: 1px;
        font-weight: bold;
        color: #4b5563;
        margin-bottom: 8px;
    }}

    .meta {{
        text-align: center;
        font-size: 17px;
        color: #4b5563;
        margin-bottom: 8px;
    }}

    .meta small {{ font-size: 12px; }}

    .orgao {{
        text-align: center;
        font-size: 17px;
        color: #4b5563;
        font-weight: bold;
        margin-bottom: 34px;
    }}

    .titulo-publicacao {{
        text-align: center;
        font-size: 24px;
        font-weight: bold;
        color: #061b33;
        margin-bottom: 24px;
        text-transform: uppercase;
    }}

    .keywords-box {{
        border: 1px solid #d7dde5;
        background: #f8fafc;
        border-radius: 10px;
        padding: 16px 18px;
        margin: 0 auto 22px auto;
    }}

    .keywords-title {{
        font-size: 16px;
        font-weight: bold;
        color: #111827;
        margin-bottom: 10px;
    }}

    .chip {{
        display: inline-block;
        text-decoration: none;
        color: #073763;
        background: #e8f1ff;
        border: 1px solid #b9d4ff;
        border-radius: 999px;
        padding: 7px 11px;
        margin: 4px 5px 4px 0;
        font-size: 14px;
        font-weight: bold;
    }}

    .chip:hover {{
        background: #d7e8ff;
        border-color: #7db1ff;
    }}

    .chip.ativo {{
        background: #bfdbfe;
        border-color: #2563eb;
        outline: 2px solid #2563eb;
    }}

    .chip span {{
        display: inline-block;
        margin-left: 6px;
        background: #073763;
        color: white;
        border-radius: 999px;
        padding: 1px 7px;
        font-size: 12px;
    }}

    .nota {{
        border: 1px solid #fde68a;
        background: #fffbeb;
        color: #92400e;
        padding: 12px 14px;
        border-radius: 8px;
        font-size: 14px;
        margin-bottom: 30px;
    }}

    .texto {{
        font-size: 22px;
        line-height: 1.52;
        text-align: justify;
        color: #061b33;
        white-space: pre-wrap;
        word-break: normal;
    }}

    .kw-mark {{
        background: #fff2a8;
        color: #061b33;
        padding: 1px 3px;
        border-radius: 4px;
        scroll-margin-top: 120px;
        scroll-margin-bottom: 150px;
    }}

    .kw-mark.active {{
        background: #ffb703 !important;
        outline: 3px solid #fb8500;
    }}

    .aviso {{
        margin-top: 28px;
        color: red;
        font-size: 15px;
    }}

    .links {{
        margin-top: 24px;
        text-align: center;
    }}

    .btn {{
        display: inline-block;
        background: #2563eb;
        color: white;
        text-decoration: none;
        padding: 10px 16px;
        border-radius: 6px;
        margin: 4px;
        font-size: 14px;
        font-weight: bold;
    }}

    .btn.secondary {{ background: #1f2937; }}
    .btn.txt {{ background: #047857; }}

    .rodape {{
        margin-top: 60px;
        border-top: 1px solid #d1d5db;
        text-align: center;
        color: #6b7280;
        font-size: 12px;
        padding-top: 16px;
    }}

    .floating-keyword-nav {{
        position: fixed;
        left: 50%;
        bottom: 18px;
        transform: translateX(-50%);
        z-index: 9999;
        background: rgba(17, 24, 39, 0.96);
        color: #ffffff;
        border-radius: 14px;
        padding: 12px 14px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.28);
        display: none;
        align-items: center;
        gap: 10px;
        max-width: calc(100vw - 32px);
        flex-wrap: wrap;
    }}

    .floating-keyword-nav.show {{ display: flex; }}

    .floating-keyword-nav .floating-status {{
        font-size: 14px;
        font-weight: bold;
        white-space: nowrap;
        color: #ffffff;
    }}

    .floating-keyword-nav .floating-hint {{
        font-size: 12px;
        color: #d1d5db;
        white-space: nowrap;
    }}

    .floating-keyword-nav button {{
        border: 1px solid #9ca3af;
        background: #ffffff;
        color: #111827;
        border-radius: 9px;
        padding: 8px 11px;
        font-weight: bold;
        cursor: pointer;
    }}

    .floating-keyword-nav button:hover {{ background: #e5e7eb; }}

    .floating-keyword-nav button:disabled {{
        color: #9ca3af;
        background: #f3f4f6;
        cursor: not-allowed;
    }}

    .floating-keyword-nav .btn-topo {{
        background: #2563eb;
        color: white;
        border-color: #2563eb;
    }}

    @media print {{
        .links, .keywords-box, .nota, .floating-keyword-nav {{ display: none !important; }}
        body {{ background: white; }}
        .pagina {{ padding: 20px 50px; }}
    }}
</style>
</head>

<body>
    <main class="pagina">
        <div id="inicio-publicacao" class="dou-titulo">{_html.escape(HTML_PADRAO_TITULO)}</div>

        <div class="meta">
            Publicado em: {_html.escape(data_br)} |
            Edição: {_html.escape(edicao)} |
            Seção: {_html.escape(secao)} |
            <small>Página: {_html.escape(paginas)}</small>
        </div>

        <div class="orgao">
            Órgão: {_html.escape(orgao)}
        </div>

        <div class="titulo-publicacao">
            {_html.escape(titulo)}
        </div>

        <section class="keywords-box" id="box-palavras-chave">
            <div class="keywords-title">Palavras-chave localizadas</div>
            {chips_html}

            <div class="links">
                <a href="{_html.escape(nome_txt)}" download class="btn txt">Baixar TXT</a>
                <a href="{_html.escape(nome_txt)}" target="_blank" class="btn">Abrir TXT</a>
                {links_html}
            </div>
        </section>

        <div class="nota">
            Ao clicar em uma palavra-chave, a tela será posicionada na primeira ocorrência encontrada no texto.
            Use a barra flutuante para navegar entre as ocorrências.
        </div>

        <section class="texto">{texto_html}</section>

        <div class="aviso">
            {_html.escape(AVISO_CERTIFICADO)}
        </div>

        <div class="rodape">
            Visualização gerada localmente a partir do texto integral extraído do INLABS.
        </div>
    </main>

    <div class="floating-keyword-nav" id="floating-keyword-nav">
        <button type="button" id="floating-anterior">← Anterior</button>
        <button type="button" id="floating-proxima">Próxima →</button>
        <span class="floating-status" id="floating-status">Nenhuma palavra selecionada</span>
        <span class="floating-hint">Atalhos: N próxima | P anterior</span>
        <button type="button" class="btn-topo" id="floating-topo">Retornar ao topo</button>
    </div>

<script>
let termoAtual = null;
let indiceAtual = -1;

function marcasDoTermo(termoId) {{
    return Array.from(document.querySelectorAll('.kw-mark[data-termo-id="' + termoId + '"]'));
}}

function limparAtivos() {{
    document.querySelectorAll('.kw-mark.active').forEach(function(el) {{
        el.classList.remove('active');
    }});

    document.querySelectorAll('.chip.ativo').forEach(function(el) {{
        el.classList.remove('ativo');
    }});
}}

function marcarChipAtivo(termoId) {{
    document.querySelectorAll('.chip[data-termo-id="' + termoId + '"]').forEach(function(el) {{
        el.classList.add('ativo');
    }});
}}

function focarMarca(marca) {{
    limparAtivos();
    marca.classList.add('active');

    if (termoAtual) {{
        marcarChipAtivo(termoAtual);
    }}

    marca.scrollIntoView({{
        behavior: 'smooth',
        block: 'center'
    }});

    history.replaceState(null, '', '#' + marca.id);
}}

function atualizarBarraFlutuante() {{
    const barra = document.getElementById('floating-keyword-nav');
    const status = document.getElementById('floating-status');
    const btnAnterior = document.getElementById('floating-anterior');
    const btnProxima = document.getElementById('floating-proxima');

    if (!termoAtual) {{
        barra.classList.remove('show');
        return;
    }}

    const marcas = marcasDoTermo(termoAtual);

    if (!marcas.length) {{
        barra.classList.remove('show');
        return;
    }}

    const nome = marcas[0].getAttribute('data-termo') || termoAtual;

    barra.classList.add('show');
    status.textContent = nome + ': ocorrência ' + (indiceAtual + 1) + ' de ' + marcas.length;

    btnAnterior.disabled = marcas.length <= 1;
    btnProxima.disabled = marcas.length <= 1;
}}

function selecionarTermo(termoId) {{
    const marcas = marcasDoTermo(termoId);

    if (!marcas.length) {{
        return false;
    }}

    termoAtual = termoId;
    indiceAtual = 0;

    focarMarca(marcas[indiceAtual]);
    atualizarBarraFlutuante();

    return false;
}}

function proximaOcorrencia() {{
    if (!termoAtual) {{ return false; }}

    const marcas = marcasDoTermo(termoAtual);

    if (!marcas.length) {{ return false; }}

    indiceAtual = (indiceAtual + 1) % marcas.length;

    focarMarca(marcas[indiceAtual]);
    atualizarBarraFlutuante();

    return false;
}}

function ocorrenciaAnterior() {{
    if (!termoAtual) {{ return false; }}

    const marcas = marcasDoTermo(termoAtual);

    if (!marcas.length) {{ return false; }}

    indiceAtual = (indiceAtual - 1 + marcas.length) % marcas.length;

    focarMarca(marcas[indiceAtual]);
    atualizarBarraFlutuante();

    return false;
}}

function voltarTopo() {{
    const inicio = document.getElementById('inicio-publicacao');

    if (inicio) {{
        inicio.scrollIntoView({{
            behavior: 'smooth',
            block: 'start'
        }});
    }}

    return false;
}}

document.getElementById('floating-anterior').addEventListener('click', ocorrenciaAnterior);
document.getElementById('floating-proxima').addEventListener('click', proximaOcorrencia);
document.getElementById('floating-topo').addEventListener('click', voltarTopo);

document.addEventListener('keydown', function(event) {{
    const tag = (event.target && event.target.tagName || '').toLowerCase();

    if (tag === 'input' || tag === 'textarea' || event.ctrlKey || event.metaKey || event.altKey) {{
        return;
    }}

    if (!termoAtual) {{ return; }}

    if (event.key.toLowerCase() === 'n') {{
        event.preventDefault();
        proximaOcorrencia();
    }}

    if (event.key.toLowerCase() === 'p') {{
        event.preventDefault();
        ocorrenciaAnterior();
    }}
}});
</script>

</body>
</html>'''


def gerar_integras_do_json(
    data_execucao: Any,
    finalidade: str = "dou_diario",
    abrir_primeiro_html: bool = False,
) -> List[Dict[str, str]]:
    """
    Gera HTML/TXT para todas as publicações com match de uma data/finalidade.

    Retorna lista com caminhos dos arquivos gerados.
    """

    data_iso = data_para_iso(data_execucao)
    dados_json = carregar_json_match(data_iso, finalidade=finalidade)
    registros = obter_registros(dados_json)
    publicacoes = consolidar_publicacoes(registros, data_iso=data_iso)

    pasta_saida = DATA_DIR / "integras" / finalidade / data_iso
    pasta_saida.mkdir(parents=True, exist_ok=True)

    saida: List[Dict[str, str]] = []
    slugs_usados: Dict[str, int] = {}

    for publicacao in publicacoes:
        titulo = publicacao.get("titulo") or "publicacao"
        slug_base = slugify(titulo)
        contador = slugs_usados.get(slug_base, 0) + 1
        slugs_usados[slug_base] = contador

        slug_final = slug_base if contador == 1 else f"{slug_base}-{contador}"

        caminho_html = pasta_saida / f"{slug_final}.html"
        caminho_txt = pasta_saida / f"{slug_final}.txt"

        texto_integral = publicacao.get("texto_integral_consolidado") or ""
        texto_html, contagem = renderizar_texto_com_destaques(texto_integral, publicacao.get("termos") or [])

        termos_visiveis = [
            termo for termo in (publicacao.get("termos") or [])
            if contagem.get(termo, 0) > 0
        ]

        txt = montar_txt(publicacao, termos_visiveis, contagem)
        caminho_txt.write_text(txt, encoding="utf-8")

        html_doc = montar_html(
            publicacao=publicacao,
            texto_html=texto_html,
            termos_visiveis=termos_visiveis,
            contagem=contagem,
            nome_txt=caminho_txt.name,
        )
        caminho_html.write_text(html_doc, encoding="utf-8")

        saida.append({
            "titulo": titulo,
            "html": str(caminho_html),
            "txt": str(caminho_txt),
            "arquivo_html": caminho_html.name,
            "arquivo_txt": caminho_txt.name,
        })

    if abrir_primeiro_html and saida:
        import webbrowser
        webbrowser.open(Path(saida[0]["html"]).resolve().as_uri())

    return saida


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gerar HTML/TXT de íntegra do DOU para publicações com match.")
    parser.add_argument("--data", required=True, help="Data no formato AAAA-MM-DD ou DD/MM/AAAA")
    parser.add_argument("--finalidade", default="dou_diario", help="Finalidade do match. Padrão: dou_diario")
    parser.add_argument("--abrir", action="store_true", help="Abrir o primeiro HTML gerado no navegador")

    args = parser.parse_args()

    arquivos = gerar_integras_do_json(
        data_execucao=args.data,
        finalidade=args.finalidade,
        abrir_primeiro_html=args.abrir,
    )

    print("=" * 80)
    print("Geração de íntegra HTML/TXT concluída")
    print("=" * 80)
    print(f"Total de publicações com íntegra gerada: {len(arquivos)}")

    for item in arquivos:
        print("-" * 80)
        print(item["titulo"])
        print(f"HTML: {item['html']}")
        print(f"TXT : {item['txt']}")

    print("=" * 80)
