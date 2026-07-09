# ============================================================
# RUNNER — Comparar Caso Giselle x Aviso de Adjudicação
# Projeto Informativos / DOU
#
# Objetivo:
# - Mapear tecnicamente por que uma publicação saiu como
#   "Giselle Cristina Gonçalves Oliveira" e outra saiu como
#   "AVISO DE ADJUDICAÇÃO E HOMOLOGAÇÃO".
#
# Não altera nenhum dado. Apenas gera JSON/TXT de diagnóstico.
# ============================================================

import html
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


DATA = "2026-05-15"

CASOS = {
    "giselle": {
        "nome": "Giselle / Agrotóxicos",
        "termos": [
            "Giselle Cristina Gonçalves Oliveira",
            "16 kg de agrotóxicos sem registro no Brasil",
            "Art. 70 - Lei: 9605",
        ],
    },
    "aviso_adjudicacao": {
        "nome": "Aviso de Adjudicação e Homologação / Saneantes",
        "termos": [
            "AVISO DE ADJUDICAÇÃO E HOMOLOGAÇÃO",
            "PREGÃO ELETRÔNICO Nº 010/2026",
            "materiais de limpeza, higiene pessoal, saneantes",
            "Nordestina",
        ],
    },
}

ROOT_DIR = Path(__file__).resolve().parents[2]

ARQUIVOS = {
    "match_dou_diario": ROOT_DIR / "backend" / "data" / "dou" / "match" / "dou_diario" / f"match_publicacoes_{DATA}.json",
    "base": ROOT_DIR / "backend" / "data" / "dou" / "base" / f"base_publicacoes_{DATA}.json",
    "bruto": ROOT_DIR / "backend" / "data" / "dou" / "bruto" / f"publicacoes_{DATA}.json",
    "debug_email_links": ROOT_DIR / "backend" / "data" / "dou" / "debug" / "links_modernos_dou" / f"debug_links_modernos_email_{DATA}.json",
    "cache_links": ROOT_DIR / "backend" / "data" / "dou" / "links_resolvidos" / f"links_modernos_{DATA}.json",
}

ZIP_DIR = ROOT_DIR / "backend" / "data" / "dou" / "inlabs" / DATA / "zips"

SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug" / "analise_casos_giselle_vs_aviso"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)

SAIDA_JSON = SAIDA_DIR / f"analise_giselle_vs_aviso_{DATA}.json"
SAIDA_TXT = SAIDA_DIR / f"analise_giselle_vs_aviso_{DATA}.txt"


def normalizar(valor) -> str:
    texto = str(valor or "")
    texto = html.unescape(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_chave(valor) -> str:
    texto = normalizar(valor)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def carregar_json(caminho: Path):
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def extrair_lista(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for chave in ["registros", "publicacoes", "dados", "itens", "base_publicacoes"]:
            valor = payload.get(chave)
            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]
    return []


def primeiro_valor(dados: dict, chaves: list[str], padrao=""):
    for chave in chaves:
        valor = dados.get(chave)
        if valor not in [None, "", [], {}]:
            return valor
    return padrao


def selecionar_titulo(registro: dict) -> str:
    return str(primeiro_valor(registro, ["titulo", "titulo_publicacao", "title", "nome", "ementa"])).strip()


def selecionar_url(registro: dict) -> str:
    for chave in [
        "url_publicacao_web", "url_web_dou", "url_moderno", "url_publicacao_moderno",
        "link_moderno", "url_publicacao", "link", "href", "url_consulta_dou",
        "url_pagina_dou", "url",
    ]:
        valor = str(registro.get(chave) or "").strip()
        if valor:
            return valor
    return ""


def texto_registro(registro: dict) -> str:
    partes = []
    for chave in [
        "titulo", "titulo_publicacao", "title", "nome", "ementa",
        "orgao", "orgao_publicacao", "secao", "pagina", "jornal",
        "texto_integral", "texto", "conteudo", "texto_publicacao",
        "resumo", "descricao", "trecho_relevante", "texto_referencia",
    ]:
        valor = registro.get(chave)
        if valor not in [None, "", [], {}]:
            partes.append(str(valor))

    for chave in ["matchs", "matches", "matchs_detectados", "termos_detectados", "categorias_encontradas"]:
        valor = registro.get(chave)
        if valor not in [None, "", [], {}]:
            partes.append(json.dumps(valor, ensure_ascii=False))
    return "\n".join(partes)


def buscar_registros(payload, termos: list[str], limite=20):
    registros = extrair_lista(payload)
    termos_norm = [normalizar(t) for t in termos if normalizar(t)]
    achados = []

    for idx, registro in enumerate(registros):
        texto = normalizar(texto_registro(registro))
        score = 0
        termos_encontrados = []
        for termo in termos_norm:
            if termo in texto:
                score += len(termo)
                termos_encontrados.append(termo)
        if score > 0:
            achados.append({
                "indice": idx,
                "score_busca": score,
                "termos_encontrados": termos_encontrados,
                "registro": registro,
            })

    achados.sort(key=lambda x: x["score_busca"], reverse=True)
    return achados[:limite]


def titulo_parece_ato_oficial(titulo: str) -> bool:
    t = normalizar(titulo)
    termos_ato = [
        "aviso", "edital", "portaria", "resolucao", "consulta publica",
        "despacho", "extrato", "ato", "instrucao normativa",
        "retificacao", "acordao", "deliberacao",
        "homologacao", "adjudicacao",
    ]
    return any(termo in t for termo in termos_ato)


def titulo_parece_nome_pessoa(titulo: str) -> bool:
    titulo = str(titulo or "").strip()
    if not titulo or titulo_parece_ato_oficial(titulo):
        return False
    palavras = re.findall(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+", titulo)
    return len(palavras) >= 3 and len(titulo.split()) <= 6


def extrair_termos(registro: dict) -> list[str]:
    termos = []
    for campo in ["matchs", "matches", "matchs_detectados", "termos_detectados"]:
        itens = registro.get(campo, [])
        if not isinstance(itens, list):
            continue
        for item in itens:
            if isinstance(item, dict):
                termo = item.get("termo") or item.get("palavra") or item.get("valor")
            else:
                termo = item
            if termo and str(termo).strip() not in termos:
                termos.append(str(termo).strip())

    cats = registro.get("categorias_encontradas", [])
    if isinstance(cats, list):
        for c in cats:
            if c and str(c).strip() not in termos:
                termos.append(str(c).strip())
    return termos


def resumo_registro(registro: dict) -> dict:
    texto = texto_registro(registro)
    titulo = selecionar_titulo(registro)
    return {
        "titulo": titulo,
        "titulo_parece_pessoa": titulo_parece_nome_pessoa(titulo),
        "titulo_parece_ato_oficial": titulo_parece_ato_oficial(titulo),
        "orgao": primeiro_valor(registro, ["orgao", "orgao_publicacao", "órgão"]),
        "secao": primeiro_valor(registro, ["secao", "seção"]),
        "pagina": primeiro_valor(registro, ["pagina", "página"]),
        "jornal": primeiro_valor(registro, ["jornal"]),
        "arquivo_xml": primeiro_valor(registro, ["arquivo_xml", "xml", "nome_xml"]),
        "zip": primeiro_valor(registro, ["zip", "arquivo_zip"]),
        "id_publicacao": primeiro_valor(registro, ["id_publicacao", "id", "id_dou"]),
        "hash_conteudo": primeiro_valor(registro, ["hash_conteudo"]),
        "status_match": primeiro_valor(registro, ["status_match"]),
        "score": primeiro_valor(registro, ["score", "score_contextual"]),
        "termos": extrair_termos(registro),
        "url_escolhida": selecionar_url(registro),
        "url_publicacao_web": primeiro_valor(registro, ["url_publicacao_web", "url_web_dou"]),
        "url_pagina_dou": primeiro_valor(registro, ["url_pagina_dou", "url_consulta_dou"]),
        "texto_preview": re.sub(r"\s+", " ", texto[:2500]).strip(),
    }


def limpar_tag(tag: str) -> str:
    tag = str(tag or "")
    return tag.split("}", 1)[1] if "}" in tag else tag


def texto_elemento(el) -> str:
    partes = []
    for txt in el.itertext():
        txt = str(txt or "").strip()
        if txt:
            partes.append(txt)
    return " ".join(partes).strip()


def extrair_tag(root, nome: str) -> str:
    nome_norm = nome.lower()
    for el in root.iter():
        if limpar_tag(el.tag).lower() == nome_norm:
            return texto_elemento(el)
    return ""


def extrair_urls(texto: str) -> list[str]:
    candidatos = re.findall(r"https?://[^\s\"'<>]+", str(texto or ""))
    saida = []
    for u in candidatos:
        u = html.unescape(u).rstrip(").,;")
        if u not in saida:
            saida.append(u)
    return saida


def analisar_xml_raw(zip_name: str, xml_name: str, xml_bytes: bytes) -> dict:
    raw = xml_bytes.decode("utf-8", errors="ignore")
    raw_unescaped = html.unescape(raw)

    info = {
        "zip": zip_name,
        "xml": xml_name,
        "xml_valido": False,
        "root_tag": "",
        "identifica": "",
        "titulo": "",
        "ementa": "",
        "subtitulo": "",
        "data": "",
        "texto_preview": re.sub(r"\s+", " ", raw_unescaped[:2500]).strip(),
        "urls": extrair_urls(raw_unescaped),
        "erro": "",
    }

    try:
        root = ET.fromstring(raw)
        info["xml_valido"] = True
        info["root_tag"] = limpar_tag(root.tag)
        info["identifica"] = extrair_tag(root, "Identifica")
        info["titulo"] = extrair_tag(root, "Titulo")
        info["ementa"] = extrair_tag(root, "Ementa")
        info["subtitulo"] = extrair_tag(root, "SubTitulo")
        info["data"] = extrair_tag(root, "Data")
        texto = html.unescape(extrair_tag(root, "Texto"))
        info["texto_preview"] = re.sub(r"\s+", " ", texto[:2500]).strip()
    except Exception as e:
        info["erro"] = str(e)

    return info


def localizar_xmls_por_termos(termos: list[str], limite=20) -> list[dict]:
    if not ZIP_DIR.exists():
        return []

    termos_norm = [normalizar(t) for t in termos if normalizar(t)]
    achados = []

    for zip_path in sorted(ZIP_DIR.glob("*.zip")):
        with zipfile.ZipFile(zip_path, "r") as zf:
            for nome in zf.namelist():
                if not nome.lower().endswith(".xml"):
                    continue
                raw = zf.read(nome)
                texto = normalizar(raw.decode("utf-8", errors="ignore"))
                score = 0
                termos_encontrados = []
                for termo in termos_norm:
                    if termo in texto:
                        score += len(termo)
                        termos_encontrados.append(termo)
                if score > 0:
                    info = analisar_xml_raw(zip_path.name, nome, raw)
                    info["score_busca"] = score
                    info["termos_encontrados"] = termos_encontrados
                    achados.append(info)

    achados.sort(key=lambda x: x["score_busca"], reverse=True)
    return achados[:limite]


def buscar_debug_email(payload, termos):
    if not isinstance(payload, dict):
        return []
    publicacoes = payload.get("publicacoes", [])
    if not isinstance(publicacoes, list):
        return []
    termos_norm = [normalizar(t) for t in termos if normalizar(t)]
    achados = []
    for idx, p in enumerate(publicacoes):
        texto = normalizar(json.dumps(p, ensure_ascii=False))
        score = 0
        encontrados = []
        for termo in termos_norm:
            if termo in texto:
                score += len(termo)
                encontrados.append(termo)
        if score > 0:
            achados.append({"indice": idx, "score_busca": score, "termos_encontrados": encontrados, "registro": p})
    achados.sort(key=lambda x: x["score_busca"], reverse=True)
    return achados[:20]


def buscar_cache_links(payload, termos):
    if not isinstance(payload, dict):
        return []
    itens = payload.get("itens", payload)
    if not isinstance(itens, dict):
        return []
    termos_norm = [normalizar(t) for t in termos if normalizar(t)]
    achados = []
    for chave, valor in itens.items():
        texto = normalizar(chave + "\n" + json.dumps(valor, ensure_ascii=False))
        score = 0
        encontrados = []
        for termo in termos_norm:
            if termo in texto:
                score += len(termo)
                encontrados.append(termo)
        if score > 0:
            achados.append({"chave": chave, "score_busca": score, "termos_encontrados": encontrados, "registro": valor})
    achados.sort(key=lambda x: x["score_busca"], reverse=True)
    return achados[:20]


def main():
    print("=" * 80)
    print("ANÁLISE TÉCNICA — GISELLE x AVISO DE ADJUDICAÇÃO")
    print("=" * 80)
    print(f"Data: {DATA}")

    payloads = {}
    for nome, caminho in ARQUIVOS.items():
        payloads[nome] = carregar_json(caminho)
        print(f"{nome}: {caminho} | existe={caminho.exists()}")

    resultado = {
        "data": DATA,
        "arquivos": {k: str(v) for k, v in ARQUIVOS.items()},
        "zip_dir": str(ZIP_DIR),
        "casos": {},
        "hipotese": (
            "O AVISO parece ser uma publicação/ato oficial com título próprio, por isso o portal moderno "
            "retorna um link individual. A Giselle parece ser linha/célula interna de conteúdo, provavelmente "
            "dentro de tabela/listagem em DO3, não uma publicação individual com título próprio. Se confirmado, "
            "o ajuste correto é tratar como item interno de tabela ou preservar o título da publicação pai, "
            "mantendo fallback para a página DOU."
        ),
    }

    for caso_id, cfg in CASOS.items():
        termos = cfg["termos"]
        caso = {"nome": cfg["nome"], "termos": termos, "fontes": {}, "xmls_inlabs": localizar_xmls_por_termos(termos, limite=12)}

        for fonte in ["match_dou_diario", "base", "bruto"]:
            payload = payloads.get(fonte)
            achados = buscar_registros(payload, termos, limite=10) if payload is not None else []
            caso["fontes"][fonte] = [
                {
                    "indice": a["indice"],
                    "score_busca": a["score_busca"],
                    "termos_encontrados": a["termos_encontrados"],
                    "resumo": resumo_registro(a["registro"]),
                }
                for a in achados
            ]

        caso["fontes"]["debug_email_links"] = [
            {"indice": a["indice"], "score_busca": a["score_busca"], "termos_encontrados": a["termos_encontrados"], "registro": a["registro"]}
            for a in buscar_debug_email(payloads.get("debug_email_links"), termos)
        ]

        caso["fontes"]["cache_links"] = [
            {"chave": a["chave"], "score_busca": a["score_busca"], "termos_encontrados": a["termos_encontrados"], "registro": a["registro"]}
            for a in buscar_cache_links(payloads.get("cache_links"), termos)
        ]

        resultado["casos"][caso_id] = caso

    SAIDA_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    linhas = []
    linhas.append("=" * 80)
    linhas.append("ANÁLISE TÉCNICA — GISELLE x AVISO DE ADJUDICAÇÃO")
    linhas.append("=" * 80)
    linhas.append(f"Data: {DATA}")
    linhas.append("")

    for caso_id, caso in resultado["casos"].items():
        linhas.append("=" * 80)
        linhas.append(f"CASO: {caso['nome']} ({caso_id})")
        linhas.append("=" * 80)

        for fonte, achados in caso["fontes"].items():
            linhas.append("-" * 80)
            linhas.append(f"FONTE: {fonte} | achados={len(achados)}")
            for i, achado in enumerate(achados[:5], start=1):
                linhas.append(f"  ACHADO {i} | score_busca={achado.get('score_busca')} | termos={achado.get('termos_encontrados')}")
                if "resumo" in achado:
                    resumo = achado["resumo"]
                    linhas.append(f"    titulo: {resumo.get('titulo')}")
                    linhas.append(f"    titulo_parece_pessoa: {resumo.get('titulo_parece_pessoa')}")
                    linhas.append(f"    titulo_parece_ato_oficial: {resumo.get('titulo_parece_ato_oficial')}")
                    linhas.append(f"    secao/pagina/jornal: {resumo.get('secao')} / {resumo.get('pagina')} / {resumo.get('jornal')}")
                    linhas.append(f"    url_publicacao_web: {resumo.get('url_publicacao_web')}")
                    linhas.append(f"    url_escolhida: {resumo.get('url_escolhida')}")
                    linhas.append(f"    termos: {resumo.get('termos')}")
                    linhas.append(f"    arquivo_xml/zip: {resumo.get('arquivo_xml')} / {resumo.get('zip')}")
                    linhas.append(f"    texto_preview: {resumo.get('texto_preview')[:1000]}")
                else:
                    linhas.append(json.dumps(achado.get("registro", {}), ensure_ascii=False, indent=2)[:2000])
                linhas.append("")

        linhas.append("-" * 80)
        linhas.append(f"XMLs INLABS encontrados: {len(caso['xmls_inlabs'])}")
        for i, xml in enumerate(caso["xmls_inlabs"][:5], start=1):
            linhas.append(f"  XML {i} | zip={xml.get('zip')} | xml={xml.get('xml')} | score={xml.get('score_busca')}")
            linhas.append(f"    Identifica: {xml.get('identifica')}")
            linhas.append(f"    Titulo: {xml.get('titulo')}")
            linhas.append(f"    Ementa: {xml.get('ementa')}")
            linhas.append(f"    SubTitulo: {xml.get('subtitulo')}")
            linhas.append(f"    Data: {xml.get('data')}")
            linhas.append(f"    URLs: {xml.get('urls')[:5]}")
            linhas.append(f"    Texto preview: {xml.get('texto_preview', '')[:1200]}")
            linhas.append("")

    linhas.append("=" * 80)
    linhas.append("HIPÓTESE")
    linhas.append("=" * 80)
    linhas.append(resultado["hipotese"])
    linhas.append("")
    linhas.append("PRÓXIMAS VALIDAÇÕES")
    linhas.append("-" * 80)
    linhas.append("- Confirmar no XML se Giselle aparece dentro de <Texto> e não em <Identifica>.")
    linhas.append("- Confirmar no XML se o AVISO aparece como título/ato oficial.")
    linhas.append("- Se Giselle for item interno de tabela, ajustar parser para não usar nome de pessoa como título da publicação.")
    linhas.append("- Criar campos: titulo_publicacao_pai, item_interno_tabela, descricao_item, url_pagina_dou.")
    linhas.append("- Manter fallback de página DOU quando não houver link moderno individual.")

    SAIDA_TXT.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 80)
    print("ANÁLISE CONCLUÍDA")
    print("=" * 80)
    print(f"JSON: {SAIDA_JSON}")
    print(f"TXT: {SAIDA_TXT}")
    print("=" * 80)
    print(resultado["hipotese"])
    print("=" * 80)


if __name__ == "__main__":
    main()
