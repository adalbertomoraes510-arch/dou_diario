# ============================================================
# SERVICE — Base de Publicações DOU
# Projeto Informativos
#
# Compatível com fluxo antigo e com fluxo oficial INLABS.
# Preserva campos críticos para e-mail/auditoria:
# url, url_publicacao, link, href, url_consulta_dou, pagina, jornal,
# arquivo_xml, zip, fonte, origem, texto_integral.
# ============================================================

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "base"
BASE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILITÁRIOS
# ============================================================

def agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def limpar_texto(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def limpar_texto_multilinha(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    linhas = []
    for linha in texto.split("\n"):
        linha = re.sub(r"\s+", " ", linha).strip()
        if linha:
            linhas.append(linha)
    return "\n".join(linhas).strip()


def primeiro_valor(dados: dict, chaves: list[str], padrao: Any = "") -> Any:
    for chave in chaves:
        if chave in dados and dados.get(chave) not in [None, "", [], {}]:
            return dados.get(chave)
    return padrao


def extrair_lista_publicacoes(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for chave in ["publicacoes", "registros", "links", "dados", "itens"]:
        valor = payload.get(chave)
        if isinstance(valor, list):
            return [item for item in valor if isinstance(item, dict)]

    return []


def gerar_hash(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8", errors="ignore")).hexdigest()


def gerar_id_publicacao(publicacao: dict, texto_integral: str) -> str:
    existente = primeiro_valor(
        publicacao,
        ["id_publicacao", "id", "id_dou", "identificador", "hash_conteudo"],
    )
    if existente:
        return str(existente)

    fonte = limpar_texto(primeiro_valor(publicacao, ["fonte", "origem"], "DOU")) or "DOU"
    data = limpar_texto(primeiro_valor(publicacao, ["data_publicacao", "data", "data_referencia"], ""))
    secao = limpar_texto(primeiro_valor(publicacao, ["secao", "seção"], ""))
    arquivo_xml = limpar_texto(primeiro_valor(publicacao, ["arquivo_xml", "arquivo_origem"], ""))
    url = limpar_texto(primeiro_valor(publicacao, ["url", "url_publicacao", "link", "href", "url_consulta_dou"], ""))

    base = "|".join([fonte, data, secao, arquivo_xml, url, texto_integral[:300]])
    return f"{fonte}|{gerar_hash(base)[:20]}"


# ============================================================
# NORMALIZAÇÃO
# ============================================================

def montar_registro_base(publicacao: dict, indice: int) -> dict:
    titulo = limpar_texto(primeiro_valor(
        publicacao,
        ["titulo", "titulo_publicacao", "titulo_listagem", "title", "nome", "ementa", "identifica"],
    ))

    texto_integral = limpar_texto_multilinha(primeiro_valor(
        publicacao,
        ["texto_integral", "texto", "conteudo", "texto_publicacao", "descricao"],
    ))

    if not titulo and texto_integral:
        titulo = limpar_texto(texto_integral.splitlines()[0])[:300]

    resumo = limpar_texto(primeiro_valor(
        publicacao,
        ["resumo_listagem", "resumo", "ementa", "descricao"],
    ))

    url = limpar_texto(primeiro_valor(
        publicacao,
        ["url", "url_publicacao", "link", "href", "url_consulta_dou"],
    ))

    data_publicacao = limpar_texto(primeiro_valor(
        publicacao,
        ["data_publicacao", "data", "data_referencia"],
    ))

    id_publicacao = gerar_id_publicacao(publicacao, texto_integral)
    hash_conteudo = gerar_hash(texto_integral)

    registro = {
        "id_publicacao": id_publicacao,
        "hash_conteudo": hash_conteudo,
        "indice_base": indice,
        "fonte": limpar_texto(primeiro_valor(publicacao, ["fonte"], "DOU")),
        "origem": limpar_texto(primeiro_valor(publicacao, ["origem"], primeiro_valor(publicacao, ["fonte"], "DOU"))),
        "data_publicacao": data_publicacao,
        "data_referencia": data_publicacao,
        "data_xml": limpar_texto(primeiro_valor(publicacao, ["data_xml"], "")),
        "data_url": limpar_texto(primeiro_valor(publicacao, ["data_url"], "")),
        "secao": limpar_texto(primeiro_valor(publicacao, ["secao", "seção"], "")),
        "pagina": limpar_texto(primeiro_valor(publicacao, ["pagina", "página"], "")),
        "jornal": limpar_texto(primeiro_valor(publicacao, ["jornal"], "")),
        "orgao": limpar_texto(primeiro_valor(publicacao, ["orgao", "órgão", "orgao_publicacao"], "")),
        "titulo": titulo,
        "titulo_publicacao": titulo,
        "titulo_listagem": limpar_texto(primeiro_valor(publicacao, ["titulo_listagem"], titulo)),
        "resumo": resumo,
        "resumo_listagem": resumo,
        "ementa": limpar_texto(primeiro_valor(publicacao, ["ementa"], "")),
        "identifica": limpar_texto(primeiro_valor(publicacao, ["identifica"], "")),
        "sub_titulo": limpar_texto(primeiro_valor(publicacao, ["sub_titulo", "subtitulo"], "")),
        "texto_integral": texto_integral,
        "texto": texto_integral,
        "texto_html": primeiro_valor(publicacao, ["texto_html"], ""),
        "texto_tamanho": len(texto_integral),
        "url": url,
        "url_publicacao": url,
        "link": url,
        "href": url,
        "url_consulta_dou": url,
        "url_host": limpar_texto(primeiro_valor(publicacao, ["url_host"], "")),
        "url_path": limpar_texto(primeiro_valor(publicacao, ["url_path"], "")),
        "arquivo_xml": limpar_texto(primeiro_valor(publicacao, ["arquivo_xml"], "")),
        "zip": limpar_texto(primeiro_valor(publicacao, ["zip"], "")),
        "arquivo_origem": limpar_texto(primeiro_valor(publicacao, ["arquivo_origem", "zip"], "")),
        "tem_url_oficial": bool(url),
        "atos_internos_estimados": primeiro_valor(publicacao, ["atos_internos_estimados"], 0),
        "tem_multiplos_atos": bool(primeiro_valor(publicacao, ["tem_multiplos_atos"], False)),
        "status_base": "OK" if texto_integral else "SEM_TEXTO",
        "gerado_em": agora_iso(),
    }

    # Preserva campos adicionais do parser sem sobrescrever o contrato principal.
    metadados_preservados = {}
    for chave, valor in publicacao.items():
        if chave not in registro:
            metadados_preservados[chave] = valor
    registro["metadados_origem"] = metadados_preservados

    return registro


# ============================================================
# FUNÇÕES PÚBLICAS
# ============================================================

def montar_base_publicacoes(payload_publicacoes: dict | list) -> list[dict]:
    publicacoes = extrair_lista_publicacoes(payload_publicacoes)

    registros: list[dict] = []
    ids_vistos: set[str] = set()

    for indice, publicacao in enumerate(publicacoes, start=1):
        registro = montar_registro_base(publicacao, indice)

        chave = registro.get("id_publicacao") or registro.get("hash_conteudo")
        if chave in ids_vistos:
            continue

        ids_vistos.add(chave)
        registros.append(registro)

    return registros


def salvar_base_publicacoes(data_referencia: str, registros: list[dict]) -> Path:
    caminho = BASE_DIR / f"base_publicacoes_{data_referencia}.json"

    payload = {
        "data_referencia": data_referencia,
        "fonte": "INLABS" if any(r.get("fonte") == "INLABS" for r in registros) else "DOU",
        "gerado_em": agora_iso(),
        "total_registros": len(registros),
        "total_com_url": sum(1 for r in registros if r.get("url")),
        "total_sem_url": sum(1 for r in registros if not r.get("url")),
        "total_com_texto": sum(1 for r in registros if r.get("texto_integral")),
        "registros": registros,
        "publicacoes": registros,
    }

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return caminho
