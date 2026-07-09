# ============================================================
# RUNNER — Comparar Matches Programa Antigo x Novo
# Projeto Informativos / DOU
#
# Data analisada: 2026-05-15
#
# Objetivo:
# - Comparar a lista antiga informada manualmente/prints com os matches
#   gerados pelo programa novo.
# - Identificar:
#   1. itens iguais;
#   2. itens que existiam no antigo e não apareceram no novo;
#   3. itens que apareceram no novo e não estavam na lista antiga;
#   4. status detalhado no match/base/debug;
#   5. explicação técnica provável para divergências.
#
# Não altera nenhum dado.
# ============================================================

import json
import re
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher


DATA = "2026-05-15"

# Lista extraída dos prints do programa antigo enviados no chat.
# Observação: havia dois prints do ATO Nº 30, mas aqui fica só uma vez.
LISTA_ANTIGA = [
    "DESPACHO DO DIRETOR PRESIDENTE Nº 71-E, DE 14 DE MAIO DE 2026",
    "CONSULTA PÚBLICA Nº 1.397, DE 12 DE MAIO DE 2026",
    "ATO Nº 30, DE 12 DE MAIO DE 2026",
    "RESOLUÇÃO-RE Nº 1.953, DE 13 DE MAIO DE 2026",
    "AVISO DE REABERTURA DE PRAZO",
    "AVISO DE alteração",
    "AVISO DE ADJUDICAÇÃO E HOMOLOGAÇÃO",
    "Edital de Notificação nº 9/2026 - Dipro",
]

ROOT_DIR = Path(__file__).resolve().parents[2]

ARQUIVOS = {
    "debug_email_links": ROOT_DIR / "backend" / "data" / "dou" / "debug" / "links_modernos_dou" / f"debug_links_modernos_email_{DATA}.json",
    "match_dou_diario": ROOT_DIR / "backend" / "data" / "dou" / "match" / "dou_diario" / f"match_publicacoes_{DATA}.json",
    "base": ROOT_DIR / "backend" / "data" / "dou" / "base" / f"base_publicacoes_{DATA}.json",
    "bruto": ROOT_DIR / "backend" / "data" / "dou" / "bruto" / f"publicacoes_{DATA}.json",
}

SAIDA_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug" / "comparacao_antigo_vs_novo"
SAIDA_DIR.mkdir(parents=True, exist_ok=True)

SAIDA_JSON = SAIDA_DIR / f"comparacao_matches_antigo_vs_novo_{DATA}.json"
SAIDA_TXT = SAIDA_DIR / f"comparacao_matches_antigo_vs_novo_{DATA}.txt"


def normalizar(valor) -> str:
    texto = str(valor or "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = texto.replace("º", "")
    texto = texto.replace("°", "")
    texto = texto.replace("ª", "")
    texto = re.sub(r"\bn\s*[º°]?\b", "n", texto)
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def similaridade(a, b) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def carregar_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def extrair_lista(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if isinstance(payload, dict):
        for chave in ["publicacoes", "registros", "dados", "itens", "links"]:
            valor = payload.get(chave)
            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]

    return []


def titulo_de(registro: dict) -> str:
    return str(
        registro.get("titulo")
        or registro.get("titulo_publicacao")
        or registro.get("texto_link_resolvido")
        or registro.get("titulo_listagem")
        or ""
    ).strip()


def texto_registro(registro: dict) -> str:
    campos = [
        "titulo", "titulo_publicacao", "titulo_listagem", "titulo_publicacao_pai",
        "item_interno_tabela", "texto_link_resolvido", "resumo_listagem",
        "texto", "texto_integral", "trecho", "trecho_relevante",
        "secao", "pagina", "jornal", "arquivo_xml", "zip",
        "status_match", "categoria", "classificacao", "tipo_match",
        "status_resolucao_link", "mensagem_resolucao_link",
    ]

    partes = []
    for c in campos:
        v = registro.get(c)
        if v not in [None, "", [], {}]:
            partes.append(str(v))

    for c in ["matchs", "matches", "matchs_detectados", "termos_detectados", "categorias_encontradas"]:
        v = registro.get(c)
        if v not in [None, "", [], {}]:
            partes.append(json.dumps(v, ensure_ascii=False))

    return "\n".join(partes)


def resumo(registro: dict) -> dict:
    return {
        "titulo": titulo_de(registro),
        "titulo_publicacao_pai": registro.get("titulo_publicacao_pai", ""),
        "item_interno_tabela": registro.get("item_interno_tabela", ""),
        "secao": registro.get("secao", ""),
        "pagina": registro.get("pagina", ""),
        "jornal": registro.get("jornal", ""),
        "status_match": registro.get("status_match", ""),
        "categoria": registro.get("categoria", ""),
        "classificacao": registro.get("classificacao", ""),
        "score": registro.get("score") or registro.get("score_contextual", ""),
        "eh_executivo": registro.get("eh_executivo", ""),
        "status_resolucao_link": registro.get("status_resolucao_link", ""),
        "url_publicacao_web": registro.get("url_publicacao_web", ""),
        "url_final_email": registro.get("url_final_email", ""),
        "url": registro.get("url") or registro.get("link") or registro.get("href") or "",
        "arquivo_xml": registro.get("arquivo_xml", ""),
        "zip": registro.get("zip", ""),
        "tipo_publicacao_inlabs": registro.get("tipo_publicacao_inlabs", ""),
        "eh_continuacao_inlabs": registro.get("eh_continuacao_inlabs", ""),
        "preview": re.sub(r"\s+", " ", texto_registro(registro)[:900]).strip(),
    }


def eh_relevante_match(registro: dict) -> bool:
    status = str(registro.get("status_match") or "").upper()
    categoria = str(registro.get("categoria") or registro.get("classificacao") or registro.get("tipo_match") or "").upper()
    score = str(registro.get("score") or registro.get("score_contextual") or "").upper()

    if status in ["COM_MATCH", "MATCH", "EXECUTIVO"]:
        return True

    if categoria in ["EXECUTIVO", "RELEVANTE", "ALTO"]:
        return True

    if score in ["ALTO", "FORTE"]:
        return True

    if registro.get("eh_executivo") is True:
        return True

    # Alguns serviços já gravam "termos" ou "matchs" mesmo sem status padronizado.
    for c in ["matchs", "matches", "matchs_detectados", "termos_detectados"]:
        v = registro.get(c)
        if isinstance(v, list) and v:
            return True

    return False


def melhor_match_por_titulo(titulo: str, registros: list[dict], minimo=0.82):
    melhor = None
    melhor_score = 0.0

    titulo_norm = normalizar(titulo)

    for r in registros:
        candidatos = [
            titulo_de(r),
            str(r.get("titulo_publicacao_pai") or ""),
            str(r.get("item_interno_tabela") or ""),
            str(r.get("texto_link_resolvido") or ""),
        ]

        for c in candidatos:
            if not c:
                continue

            score = similaridade(titulo, c)

            # Match exato/contido aumenta a confiança.
            if titulo_norm and titulo_norm in normalizar(c):
                score = max(score, 0.99)
            if normalizar(c) and normalizar(c) in titulo_norm:
                score = max(score, 0.95)

            if score > melhor_score:
                melhor_score = score
                melhor = r

    if melhor and melhor_score >= minimo:
        return melhor, melhor_score

    return None, melhor_score


def buscar_por_texto(termo: str, registros: list[dict], limite=10):
    termo_norm = normalizar(termo)
    achados = []

    for r in registros:
        texto_norm = normalizar(texto_registro(r))
        if termo_norm and termo_norm in texto_norm:
            achados.append(r)

    return achados[:limite]


def main():
    payloads = {nome: carregar_json(path) for nome, path in ARQUIVOS.items()}

    debug_publicacoes = extrair_lista(payloads.get("debug_email_links"))
    match_registros = extrair_lista(payloads.get("match_dou_diario"))
    base_registros = extrair_lista(payloads.get("base"))
    bruto_registros = extrair_lista(payloads.get("bruto"))

    # Lista nova principal: o que foi efetivamente para o e-mail.
    lista_nova_email = [titulo_de(r) for r in debug_publicacoes if titulo_de(r)]

    # Lista nova alternativa: filtro direto no match, caso debug não exista.
    match_relevantes = [r for r in match_registros if eh_relevante_match(r)]
    lista_nova_match = [titulo_de(r) for r in match_relevantes if titulo_de(r)]

    lista_nova = lista_nova_email or lista_nova_match

    comparacoes = []

    for titulo_antigo in LISTA_ANTIGA:
        achado_email, score_email = melhor_match_por_titulo(titulo_antigo, debug_publicacoes, minimo=0.82)
        achado_match, score_match = melhor_match_por_titulo(titulo_antigo, match_relevantes, minimo=0.82)
        achado_base, score_base = melhor_match_por_titulo(titulo_antigo, base_registros, minimo=0.82)
        achado_bruto, score_bruto = melhor_match_por_titulo(titulo_antigo, bruto_registros, minimo=0.82)

        status = "NAO_ENCONTRADO_NO_NOVO"
        melhor_fonte = ""
        melhor_resumo = None
        melhor_score = 0.0

        candidatos = [
            ("debug_email_links", achado_email, score_email),
            ("match_relevantes", achado_match, score_match),
            ("base", achado_base, score_base),
            ("bruto", achado_bruto, score_bruto),
        ]

        for fonte, achado, score in candidatos:
            if achado and score > melhor_score:
                melhor_fonte = fonte
                melhor_resumo = resumo(achado)
                melhor_score = score

        if melhor_resumo:
            if melhor_fonte == "debug_email_links":
                status = "IGUAL_NO_EMAIL_NOVO"
            elif melhor_fonte == "match_relevantes":
                status = "EXISTE_COMO_MATCH_RELEVANTE_MAS_NAO_CONFIRMADO_NO_EMAIL"
            elif melhor_fonte in ["base", "bruto"]:
                status = "EXISTE_NA_BASE_BRUTA_MAS_NAO_ENTROU_COMO_MATCH_RELEVANTE"

        comparacoes.append({
            "titulo_antigo": titulo_antigo,
            "status_comparacao": status,
            "melhor_fonte_novo": melhor_fonte,
            "similaridade": round(melhor_score, 4),
            "registro_novo": melhor_resumo,
        })

    # Novos que não estão na lista antiga.
    novos_diferentes = []
    for titulo_novo in lista_nova:
        achado, score = melhor_match_por_titulo(titulo_novo, [{"titulo": t} for t in LISTA_ANTIGA], minimo=0.82)
        if not achado:
            reg, _ = melhor_match_por_titulo(titulo_novo, debug_publicacoes, minimo=0.82)
            novos_diferentes.append({
                "titulo_novo": titulo_novo,
                "registro_novo": resumo(reg) if reg else {},
            })

    # Busca pontual dos casos críticos.
    investigacoes = {
        "ATO Nº 30": {
            "em_match_relevantes": [resumo(r) for r in buscar_por_texto("ATO Nº 30, DE 12 DE MAIO DE 2026", match_relevantes)],
            "em_base": [resumo(r) for r in buscar_por_texto("ATO Nº 30, DE 12 DE MAIO DE 2026", base_registros)],
            "em_bruto": [resumo(r) for r in buscar_por_texto("ATO Nº 30, DE 12 DE MAIO DE 2026", bruto_registros)],
        },
        "Edital de Notificação nº 9/2026 - Dipro": {
            "em_match_relevantes": [resumo(r) for r in buscar_por_texto("Edital de Notificação nº 9/2026 - Dipro", match_relevantes)],
            "em_base": [resumo(r) for r in buscar_por_texto("Edital de Notificação nº 9/2026 - Dipro", base_registros)],
            "em_bruto": [resumo(r) for r in buscar_por_texto("Edital de Notificação nº 9/2026 - Dipro", bruto_registros)],
        },
        "Giselle": {
            "em_match_relevantes": [resumo(r) for r in buscar_por_texto("Giselle Cristina Gonçalves Oliveira", match_relevantes)],
            "em_base": [resumo(r) for r in buscar_por_texto("Giselle Cristina Gonçalves Oliveira", base_registros)],
            "em_bruto": [resumo(r) for r in buscar_por_texto("Giselle Cristina Gonçalves Oliveira", bruto_registros)],
        },
        "Aviso de Dispensa": {
            "em_match_relevantes": [resumo(r) for r in buscar_por_texto("DISPENSA DE LICITAÇÃO", match_relevantes)],
            "em_base": [resumo(r) for r in buscar_por_texto("DISPENSA DE LICITAÇÃO", base_registros)],
            "em_bruto": [resumo(r) for r in buscar_por_texto("DISPENSA DE LICITAÇÃO", bruto_registros)],
        },
    }

    resultado = {
        "data": DATA,
        "arquivos": {k: str(v) for k, v in ARQUIVOS.items()},
        "lista_antiga_unica": LISTA_ANTIGA,
        "lista_nova_email": lista_nova_email,
        "lista_nova_match_relevante": lista_nova_match,
        "total_antigo": len(LISTA_ANTIGA),
        "total_novo_email": len(lista_nova_email),
        "total_novo_match_relevante": len(lista_nova_match),
        "comparacoes_antigo_para_novo": comparacoes,
        "novos_no_email_que_nao_estavam_na_lista_antiga": novos_diferentes,
        "investigacoes_pontuais": investigacoes,
    }

    SAIDA_JSON.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    linhas = []
    linhas.append("=" * 100)
    linhas.append("COMPARAÇÃO MATCHES — PROGRAMA ANTIGO x PROGRAMA NOVO")
    linhas.append("=" * 100)
    linhas.append(f"Data: {DATA}")
    linhas.append(f"Total antigo informado por prints: {len(LISTA_ANTIGA)}")
    linhas.append(f"Total novo no debug do e-mail: {len(lista_nova_email)}")
    linhas.append(f"Total novo por filtro match relevante: {len(lista_nova_match)}")
    linhas.append("")

    linhas.append("LISTA ANTIGA")
    linhas.append("-" * 100)
    for i, t in enumerate(LISTA_ANTIGA, start=1):
        linhas.append(f"{i}. {t}")

    linhas.append("")
    linhas.append("LISTA NOVA — E-MAIL/DEBUG")
    linhas.append("-" * 100)
    for i, t in enumerate(lista_nova_email, start=1):
        linhas.append(f"{i}. {t}")

    linhas.append("")
    linhas.append("COMPARAÇÃO ITEM A ITEM")
    linhas.append("-" * 100)
    for c in comparacoes:
        linhas.append(f"ANTIGO: {c['titulo_antigo']}")
        linhas.append(f"STATUS: {c['status_comparacao']} | fonte={c['melhor_fonte_novo']} | similaridade={c['similaridade']}")
        if c["registro_novo"]:
            r = c["registro_novo"]
            linhas.append(f"NOVO: {r.get('titulo')}")
            linhas.append(f"pai: {r.get('titulo_publicacao_pai')}")
            linhas.append(f"item_interno_tabela: {r.get('item_interno_tabela')}")
            linhas.append(f"secao/pagina: {r.get('secao')} / {r.get('pagina')}")
            linhas.append(f"status_match: {r.get('status_match')} | categoria: {r.get('categoria')} | score: {r.get('score')}")
            linhas.append(f"status_resolucao_link: {r.get('status_resolucao_link')}")
            linhas.append(f"url_publicacao_web: {r.get('url_publicacao_web')}")
            linhas.append(f"url: {r.get('url') or r.get('url_final_email')}")
            linhas.append(f"arquivo_xml: {r.get('arquivo_xml')}")
        linhas.append("")

    linhas.append("NOVOS NO E-MAIL QUE NÃO ESTAVAM NA LISTA ANTIGA")
    linhas.append("-" * 100)
    if novos_diferentes:
        for n in novos_diferentes:
            linhas.append(f"- {n['titulo_novo']}")
            r = n.get("registro_novo") or {}
            if r:
                linhas.append(f"  secao/pagina: {r.get('secao')} / {r.get('pagina')}")
                linhas.append(f"  url: {r.get('url_publicacao_web') or r.get('url_final_email') or r.get('url')}")
    else:
        linhas.append("Nenhum.")

    linhas.append("")
    linhas.append("INVESTIGAÇÕES PONTUAIS")
    linhas.append("-" * 100)
    for nome, fontes in investigacoes.items():
        linhas.append(f"## {nome}")
        for fonte, regs in fontes.items():
            linhas.append(f"{fonte}: {len(regs)}")
            for r in regs[:3]:
                linhas.append(f"  - titulo={r.get('titulo')} | pai={r.get('titulo_publicacao_pai')} | item={r.get('item_interno_tabela')} | secao/pag={r.get('secao')}/{r.get('pagina')} | status={r.get('status_match')} | xml={r.get('arquivo_xml')}")
        linhas.append("")

    SAIDA_TXT.write_text("\n".join(linhas), encoding="utf-8")

    print("=" * 100)
    print("COMPARAÇÃO CONCLUÍDA")
    print("=" * 100)
    print(f"JSON: {SAIDA_JSON}")
    print(f"TXT:  {SAIDA_TXT}")
    print("=" * 100)
    print("Resumo rápido:")
    print(f"- Antigo/prints: {len(LISTA_ANTIGA)}")
    print(f"- Novo/e-mail debug: {len(lista_nova_email)}")
    print(f"- Novo/match relevante: {len(lista_nova_match)}")
    print("- Verifique o TXT para explicação item a item.")
    print("=" * 100)


if __name__ == "__main__":
    main()
