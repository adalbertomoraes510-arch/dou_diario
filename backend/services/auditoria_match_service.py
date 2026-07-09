# ============================================================
# SERVICE — Auditoria Match DOU
# Gera diagnóstico estrutural e auditável do motor de match
# Compatível com match executivo, monitoramento setorial e revisão contextual
# ============================================================

from collections import Counter
from pathlib import Path
import json
import re
import unicodedata


ROOT_DIR = Path(__file__).resolve().parents[2]

FINALIDADE_CONFIG = "dou_diario"

AUDITORIA_BASE_DIR = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "auditoria"
)

AUDITORIA_DIR = AUDITORIA_BASE_DIR / FINALIDADE_CONFIG
AUDITORIA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# NORMALIZAÇÃO AUXILIAR
# ============================================================

def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = unicodedata.normalize("NFKD", str(texto))
    texto = texto.encode("ASCII", "ignore").decode("ASCII")
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def gerar_amostra_texto(texto: str, limite: int = 1000) -> str:
    texto = texto or ""
    texto = re.sub(r"\s+", " ", texto).strip()

    return texto[:limite]


def extrair_digitos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def obter_lista_registro(registro: dict, chaves: list[str]) -> list:
    for chave in chaves:
        valor = registro.get(chave)

        if isinstance(valor, list):
            return valor

    return []


def obter_matchs_registro(registro: dict) -> list[dict]:
    """
    Retorna somente os matches executivos válidos.

    Mantém compatibilidade com estruturas antigas e novas.
    O projeto vem usando principalmente a chave 'matchs'.
    Esta função também aceita 'matches', caso algum módulo futuro
    passe a usar nomenclatura em inglês.
    """

    return obter_lista_registro(registro, ["matchs", "matches"])


def obter_matchs_revisao_registro(registro: dict) -> list[dict]:
    """
    Retorna termos usados para monitoramento setorial ou revisão contextual.
    """

    return obter_lista_registro(
        registro,
        [
            "matchs_revisao",
            "matches_revisao",
            "matches_contextuais",
        ]
    )


def obter_matchs_detectados_registro(registro: dict) -> list[dict]:
    """
    Retorna todos os termos detectados antes do filtro contextual.
    """

    return obter_lista_registro(
        registro,
        [
            "matchs_detectados",
            "matches_detectados",
            "matchs_brutos",
            "matches_brutos",
        ]
    )


def obter_matchs_contextuais_registro(registro: dict) -> list[dict]:
    matchs_revisao = obter_matchs_revisao_registro(registro)

    if matchs_revisao:
        return matchs_revisao

    return obter_matchs_detectados_registro(registro)


def obter_valor_registro(
    registro: dict,
    chaves: list[str],
    padrao=None
):
    for chave in chaves:
        valor = registro.get(chave)

        if valor not in [None, ""]:
            return valor

    return padrao


def obter_status_revisao_contextual(registro: dict) -> str:
    return str(registro.get("status_revisao_contextual") or "").upper()


def eh_monitoramento_setorial(registro: dict) -> bool:
    status = obter_status_revisao_contextual(registro)
    score = str(registro.get("score_contextual") or "").upper()

    return status == "MONITORAMENTO_SETORIAL" or score == "MONITORAMENTO_SETORIAL"


def eh_revisao_contextual(registro: dict) -> bool:
    status = obter_status_revisao_contextual(registro)
    score = str(registro.get("score_contextual") or "").upper()

    return (
        status in {"EM_REVISAO", "REVISAO_CONTEXTUAL"}
        or score == "REVISAO"
    ) and not eh_monitoramento_setorial(registro)


def eh_match_executivo(registro: dict) -> bool:
    return registro.get("status_match") == "COM_MATCH"


# ============================================================
# SCORE DE CONFIANÇA DO MATCH
# ============================================================

def detectar_token_curto_em_termo(termo: str) -> list[str]:
    termo_norm = normalizar_texto(termo)
    tokens = termo_norm.split()

    return [
        token
        for token in tokens
        if len(token) <= 2
    ]


def classificar_confianca_match(match: dict) -> dict:
    termo = str(match.get("termo", ""))
    tipo = match.get("tipo", "")
    encontrados = match.get("encontrados", [])

    motivos = []
    score = "MEDIO"
    suspeita_falso_positivo = False

    if tipo == "match_processo":
        score = "ALTO"
        motivos.append(
            "Processo administrativo encontrado por comparação numérica normalizada"
        )

    elif tipo == "match_direto":
        score = "ALTO"
        motivos.append(
            "Termo textual encontrado por palavra/expressão normalizada"
        )

    elif tipo == "match_numero":
        numero = extrair_digitos(
            encontrados[0] if encontrados else termo
        )

        if len(numero) >= 6:
            score = "MEDIO"
            motivos.append(
                "Número com tamanho razoável encontrado no texto"
            )
        else:
            score = "BAIXO"
            suspeita_falso_positivo = True
            motivos.append(
                "Número curto pode gerar falso positivo"
            )

    elif tipo in {"match_hibrido", "match_texto_hibrido"}:
        tokens_curtos = detectar_token_curto_em_termo(termo)
        qtd_tokens = len(normalizar_texto(termo).split())

        if tokens_curtos and qtd_tokens >= 3:
            score = "CRITICO"
            suspeita_falso_positivo = True
            motivos.append("Termo híbrido contém tokens curtos")
            motivos.append(
                "Termo híbrido longo pode ter sido encontrado por tokens espalhados"
            )

        elif tokens_curtos:
            score = "BAIXO"
            suspeita_falso_positivo = True
            motivos.append("Termo híbrido contém tokens curtos")

        else:
            score = "MEDIO"
            motivos.append(
                "Termo híbrido encontrado sem tokens curtos relevantes"
            )

    else:
        score = "MEDIO"
        motivos.append(
            "Tipo de match sem regra específica de confiança"
        )

    return {
        "score_confianca": score,
        "suspeita_falso_positivo": suspeita_falso_positivo,
        "motivos_confianca": motivos
    }


def enriquecer_match_com_confianca(match: dict) -> dict:
    enriquecido = dict(match)
    classificacao = classificar_confianca_match(match)
    enriquecido.update(classificacao)

    return enriquecido


# ============================================================
# SCORE CONSOLIDADO DA PUBLICAÇÃO
# ============================================================

def classificar_score_publicacao(matchs_enriquecidos: list[dict]) -> dict:
    scores = [
        m.get("score_confianca", "DESCONHECIDO")
        for m in matchs_enriquecidos
    ]

    motivos = []

    if not scores:
        return {
            "score_publicacao": "SEM_MATCH",
            "motivos_score_publicacao": [
                "Publicação sem matches identificados"
            ]
        }

    if "CRITICO" in scores:
        motivos.append(
            "Publicação possui pelo menos um match crítico"
        )
        return {
            "score_publicacao": "CRITICO",
            "motivos_score_publicacao": motivos
        }

    if "BAIXO" in scores:
        if "ALTO" in scores:
            motivos.append(
                "Publicação possui match alto, mas também possui match baixo"
            )
            return {
                "score_publicacao": "MEDIO",
                "motivos_score_publicacao": motivos
            }

        motivos.append(
            "Publicação possui match baixo e nenhum match alto"
        )
        return {
            "score_publicacao": "BAIXO",
            "motivos_score_publicacao": motivos
        }

    if "MEDIO" in scores:
        motivos.append(
            "Publicação possui pelo menos um match médio"
        )
        return {
            "score_publicacao": "MEDIO",
            "motivos_score_publicacao": motivos
        }

    if all(score == "ALTO" for score in scores):
        motivos.append(
            "Todos os matches da publicação possuem alta confiança"
        )
        return {
            "score_publicacao": "ALTO",
            "motivos_score_publicacao": motivos
        }

    return {
        "score_publicacao": "DESCONHECIDO",
        "motivos_score_publicacao": [
            "Não foi possível consolidar o score da publicação"
        ]
    }


def ordem_score(score: str) -> int:
    ordem = {
        "CRITICO": 1,
        "ALTO": 2,
        "MEDIO": 3,
        "BAIXO": 4,
        "MONITORAMENTO_SETORIAL": 5,
        "REVISAO": 6,
        "DESCONHECIDO": 7,
        "SEM_MATCH": 8,
    }

    return ordem.get(score or "DESCONHECIDO", 7)


# ============================================================
# DESCRIÇÃO OPERACIONAL DOS SCORES
# ============================================================

def obter_descricao_scores() -> dict:
    return {
        "ALTO": {
            "ordem_relevancia": 1,
            "significado_operacional": "Match muito confiável",
            "interpretacao": (
                "Forte evidência de relevância. "
                "Pode seguir fluxo operacional com alta segurança."
            )
        },
        "MEDIO": {
            "ordem_relevancia": 2,
            "significado_operacional": "Match razoavelmente confiável",
            "interpretacao": (
                "Publicação provavelmente relevante, "
                "mas merece validação dependendo do cenário."
            )
        },
        "BAIXO": {
            "ordem_relevancia": 3,
            "significado_operacional": "Match pouco confiável",
            "interpretacao": (
                "Possui baixa evidência textual. "
                "Recomendado validar antes de ações automáticas."
            )
        },
        "CRITICO": {
            "ordem_relevancia": 4,
            "significado_operacional": "Possível falso positivo",
            "interpretacao": (
                "Fortes indícios de ruído ou match incorreto. "
                "Necessita revisão prioritária."
            )
        },
        "MONITORAMENTO_SETORIAL": {
            "ordem_relevancia": 5,
            "significado_operacional": "Monitoramento setorial",
            "interpretacao": (
                "Publicação sem vínculo direto com a finalidade/empresa, "
                "mas com sinal regulatório setorial relevante."
            )
        },
        "REVISAO": {
            "ordem_relevancia": 6,
            "significado_operacional": "Revisão contextual",
            "interpretacao": (
                "Publicação com sinais contextuais, mantida fora da lista "
                "executiva até validação."
            )
        },
        "DESCONHECIDO": {
            "ordem_relevancia": 7,
            "significado_operacional": "Classificação indefinida",
            "interpretacao": (
                "O sistema não conseguiu classificar a confiança."
            )
        },
        "SEM_MATCH": {
            "ordem_relevancia": 8,
            "significado_operacional": "Sem match",
            "interpretacao": (
                "Nenhum termo ou processo configurado foi encontrado na publicação."
            )
        }
    }


# ============================================================
# RESUMO EXECUTIVO
# ============================================================

def gerar_resumo_executivo(registros: list[dict]) -> dict:
    total = len(registros)

    com_match = sum(1 for r in registros if eh_match_executivo(r))
    monitoramento_setorial = sum(1 for r in registros if eh_monitoramento_setorial(r))
    revisao_contextual = sum(1 for r in registros if eh_revisao_contextual(r))

    sem_match = sum(
        1 for r in registros
        if r.get("status_match") == "SEM_MATCH"
    )

    sem_match_contextual = max(
        total - com_match - monitoramento_setorial - revisao_contextual,
        0,
    )

    total_matchs = sum(
        len(obter_matchs_registro(r))
        for r in registros
    )

    total_matchs_revisao = sum(
        len(obter_matchs_revisao_registro(r))
        for r in registros
    )

    total_com_termo_detectado = sum(
        1 for r in registros
        if (
            r.get("quantidade_matchs_detectados", 0) > 0
            or len(obter_matchs_detectados_registro(r)) > 0
        )
    )

    total_excluidos_titulo = sum(
        1 for r in registros
        if r.get("status_exclusao") == "EXCLUIDO_POR_TITULO"
    )

    total_resgatados = sum(
        1 for r in registros
        if r.get("status_resgate") == "RESGATADO"
    )

    total_publicacoes_com_suspeita = 0
    total_matchs_suspeitos = 0

    for registro in registros:
        if not eh_match_executivo(registro):
            continue

        matchs_enriquecidos = [
            enriquecer_match_com_confianca(m)
            for m in obter_matchs_registro(registro)
        ]

        possui_suspeita = any(
            m.get("suspeita_falso_positivo")
            for m in matchs_enriquecidos
        )

        if possui_suspeita:
            total_publicacoes_com_suspeita += 1

        total_matchs_suspeitos += sum(
            1 for m in matchs_enriquecidos
            if m.get("suspeita_falso_positivo")
        )

    publicacoes_relevantes_confirmadas = (
        com_match - total_publicacoes_com_suspeita
    )

    return {
        "total_publicacoes": total,

        # Nomenclatura legada preservada.
        "com_match": com_match,
        "sem_match": sem_match,
        "total_matchs": total_matchs,
        "taxa_match": round((com_match / total) * 100, 2) if total else 0,

        # Nomenclatura contextual nova.
        "match_executivo": com_match,
        "match_executivo_leroy": com_match,
        "monitoramento_setorial": monitoramento_setorial,
        "revisao_contextual": revisao_contextual,
        "sem_match_contextual": sem_match_contextual,
        "total_matchs_revisao": total_matchs_revisao,
        "total_publicacoes_com_termo_detectado": total_com_termo_detectado,
        "total_excluidos_titulo": total_excluidos_titulo,
        "total_resgatados": total_resgatados,
        "taxa_match_executivo": round((com_match / total) * 100, 2) if total else 0,
        "taxa_monitoramento_setorial": round((monitoramento_setorial / total) * 100, 2) if total else 0,
        "taxa_revisao_contextual": round((revisao_contextual / total) * 100, 2) if total else 0,

        "publicacoes_relevantes_confirmadas": publicacoes_relevantes_confirmadas,
        "publicacoes_com_suspeita_falso_positivo": total_publicacoes_com_suspeita,
        "matchs_suspeitos": total_matchs_suspeitos,
        "taxa_match_confirmado": round(
            (publicacoes_relevantes_confirmadas / total) * 100,
            2
        ) if total else 0,
    }


# ============================================================
# ESTATÍSTICAS DE MATCH
# ============================================================

def gerar_estatisticas_match(registros: list[dict]) -> dict:
    contador_tipos = Counter()
    contador_termos = Counter()
    contador_termo_tipo = Counter()
    contador_confianca = Counter()
    contador_score_publicacao = Counter()

    contador_score_contextual = Counter()
    contador_status_revisao = Counter()
    contador_motivo_contextual = Counter()
    contador_termos_detectados = Counter()
    contador_termos_revisao = Counter()

    for registro in registros:
        score_contextual = registro.get("score_contextual") or "NAO_INFORMADO"
        status_revisao = registro.get("status_revisao_contextual") or "NAO_INFORMADO"
        motivo_contextual = registro.get("motivo_contextual") or "NAO_INFORMADO"

        contador_score_contextual[score_contextual] += 1
        contador_status_revisao[status_revisao] += 1
        contador_motivo_contextual[motivo_contextual] += 1

        for match_detectado in obter_matchs_detectados_registro(registro):
            termo = match_detectado.get("termo", "desconhecido")
            contador_termos_detectados[termo] += 1

        for match_revisao in obter_matchs_revisao_registro(registro):
            termo = match_revisao.get("termo", "desconhecido")
            contador_termos_revisao[termo] += 1

        matchs_enriquecidos = [
            enriquecer_match_com_confianca(m)
            for m in obter_matchs_registro(registro)
        ]

        if matchs_enriquecidos:
            score_pub = classificar_score_publicacao(
                matchs_enriquecidos
            ).get("score_publicacao", "DESCONHECIDO")

            contador_score_publicacao[score_pub] += 1

        for match_enriquecido in matchs_enriquecidos:
            tipo = match_enriquecido.get("tipo", "desconhecido")
            termo = match_enriquecido.get("termo", "desconhecido")
            score = match_enriquecido.get(
                "score_confianca",
                "DESCONHECIDO"
            )

            contador_tipos[tipo] += 1
            contador_termos[termo] += 1
            contador_termo_tipo[f"{termo} | {tipo}"] += 1
            contador_confianca[score] += 1

    return {
        "tipos_match": dict(contador_tipos),
        "score_confianca": dict(contador_confianca),
        "score_publicacao": dict(contador_score_publicacao),
        "top_termos": contador_termos.most_common(50),
        "top_termo_tipo": contador_termo_tipo.most_common(50),

        "score_contextual": dict(contador_score_contextual),
        "status_revisao_contextual": dict(contador_status_revisao),
        "motivos_contextuais": contador_motivo_contextual.most_common(50),
        "top_termos_detectados": contador_termos_detectados.most_common(50),
        "top_termos_revisao": contador_termos_revisao.most_common(50),
    }


# ============================================================
# ESTATÍSTICAS PUBLICAÇÕES
# ============================================================

def gerar_estatisticas_publicacoes(registros: list[dict]) -> dict:
    contador_orgaos = Counter()
    contador_secoes = Counter()
    contador_orgaos_monitoramento = Counter()
    contador_orgaos_executivo = Counter()

    for registro in registros:
        orgao = registro.get("orgao") or "NAO_IDENTIFICADO"
        secao = registro.get("secao") or "NAO_IDENTIFICADA"

        contador_orgaos[orgao] += 1
        contador_secoes[secao] += 1

        if eh_match_executivo(registro):
            contador_orgaos_executivo[orgao] += 1

        if eh_monitoramento_setorial(registro):
            contador_orgaos_monitoramento[orgao] += 1

    return {
        "top_orgaos": contador_orgaos.most_common(20),
        "top_secoes": contador_secoes.most_common(20),
        "top_orgaos_match_executivo": contador_orgaos_executivo.most_common(20),
        "top_orgaos_monitoramento_setorial": contador_orgaos_monitoramento.most_common(20),
    }


# ============================================================
# DETALHAMENTO DOS MATCHES
# ============================================================

def montar_termos_publicacao(matchs: list[dict]) -> list[dict]:
    return [
        {
            "termo": m.get("termo"),
            "tipo": m.get("tipo"),
            "categoria": m.get("categoria"),
            "encontrados": m.get("encontrados", []),
            "score_confianca": m.get("score_confianca"),
            "suspeita_falso_positivo": m.get("suspeita_falso_positivo"),
            "motivos_confianca": m.get("motivos_confianca", [])
        }
        for m in matchs
    ]


def extrair_termos_matchs(matchs: list[dict]) -> list[str]:
    return [
        str(m.get("termo"))
        for m in matchs
        if isinstance(m, dict) and m.get("termo") not in [None, ""]
    ]


def extrair_tipos_matchs(matchs: list[dict]) -> list[str]:
    return [
        str(m.get("tipo"))
        for m in matchs
        if isinstance(m, dict) and m.get("tipo") not in [None, ""]
    ]


def ordenar_publicacoes_por_relevancia(publicacoes: list[dict]) -> list[dict]:
    return sorted(
        publicacoes,
        key=lambda p: (
            ordem_score(p.get("score_publicacao") or p.get("score_contextual")),
            str(p.get("orgao") or ""),
            str(p.get("titulo") or "")
        )
    )


def montar_base_publicacao(registro: dict) -> dict:
    return {
        "id_publicacao": registro.get("id_publicacao"),
        "titulo": registro.get("titulo") or registro.get("titulo_publicacao"),
        "orgao": registro.get("orgao") or registro.get("orgao_publicacao"),
        "secao": registro.get("secao"),
        "pagina": registro.get("pagina"),
        "url": registro.get("url") or registro.get("link"),
        "amostra_texto": gerar_amostra_texto(
            registro.get("texto_integral", "") or registro.get("texto_normalizado", ""),
            limite=1500
        ),
    }


def gerar_publicacoes_com_match(registros: list[dict]) -> list[dict]:
    publicacoes = []

    for registro in registros:
        if not eh_match_executivo(registro):
            continue

        matchs = [
            enriquecer_match_com_confianca(m)
            for m in obter_matchs_registro(registro)
        ]

        scores = [
            m.get("score_confianca", "DESCONHECIDO")
            for m in matchs
        ]

        score_publicacao = classificar_score_publicacao(matchs)

        termos = montar_termos_publicacao(matchs)

        termos_encontrados = [
            termo.get("termo")
            for termo in termos
            if termo.get("termo")
        ]

        tipos_match = [
            termo.get("tipo")
            for termo in termos
            if termo.get("tipo")
        ]

        tem_suspeita = any(
            m.get("suspeita_falso_positivo")
            for m in matchs
        )

        score_pub = score_publicacao.get("score_publicacao")

        publicacao = montar_base_publicacao(registro)
        publicacao.update({
            "status_match": registro.get("status_match"),
            "status_revisao_contextual": registro.get("status_revisao_contextual"),
            "score_contextual": registro.get("score_contextual"),
            "nivel_contextual": registro.get("nivel_contextual"),
            "motivo_contextual": registro.get("motivo_contextual"),
            "quantidade_matchs": len(matchs),
            "score_publicacao": score_pub,
            "score": score_pub,
            "nivel_score": score_pub,
            "classificacao_score": score_pub,
            "motivos_score_publicacao": score_publicacao.get(
                "motivos_score_publicacao",
                []
            ),
            "scores_confianca": scores,
            "tem_suspeita_falso_positivo": tem_suspeita,
            "termos_encontrados": termos_encontrados,
            "palavras_encontradas": termos_encontrados,
            "palavras_chave_encontradas": termos_encontrados,
            "palavras_chave": termos_encontrados,
            "tipos_match": tipos_match,
            "termos": termos,
            "matchs": termos,
            "matches": termos,
        })

        publicacoes.append(publicacao)

    return ordenar_publicacoes_por_relevancia(publicacoes)


def gerar_publicacoes_contextuais(
    registros: list[dict],
    tipo_contextual: str
) -> list[dict]:
    publicacoes = []

    for registro in registros:
        if tipo_contextual == "MONITORAMENTO_SETORIAL":
            if not eh_monitoramento_setorial(registro):
                continue
        elif tipo_contextual == "REVISAO_CONTEXTUAL":
            if not eh_revisao_contextual(registro):
                continue
        else:
            continue

        matchs_contextuais = obter_matchs_contextuais_registro(registro)
        termos_contextuais = montar_termos_publicacao(matchs_contextuais)
        termos_encontrados = extrair_termos_matchs(matchs_contextuais)
        tipos_match = extrair_tipos_matchs(matchs_contextuais)

        publicacao = montar_base_publicacao(registro)
        publicacao.update({
            "status_match": registro.get("status_match"),
            "status_revisao_contextual": registro.get("status_revisao_contextual"),
            "score_contextual": registro.get("score_contextual"),
            "score_publicacao": registro.get("score_contextual"),
            "nivel_contextual": registro.get("nivel_contextual"),
            "motivo_contextual": registro.get("motivo_contextual"),
            "categorias_encontradas": registro.get("categorias_encontradas", []),
            "termos_empresa": registro.get("termos_empresa", []),
            "termos_orgao_regulador": registro.get("termos_orgao_regulador", []),
            "termos_tecnicos_fortes": registro.get("termos_tecnicos_fortes", []),
            "termos_ato_normativo": registro.get("termos_ato_normativo", []),
            "termos_evento_material": registro.get("termos_evento_material", []),
            "termos_atividade_regulatoria": registro.get("termos_atividade_regulatoria", []),
            "termos_produto_especifico": registro.get("termos_produto_especifico", []),
            "termos_produto_generico": registro.get("termos_produto_generico", []),
            "termos_fracos_encontrados": registro.get("termos_fracos_encontrados", []),
            "quantidade_matchs_detectados": registro.get("quantidade_matchs_detectados"),
            "quantidade_matchs_revisao": registro.get("quantidade_matchs_revisao"),
            "termos_detectados": extrair_termos_matchs(obter_matchs_detectados_registro(registro)),
            "termos_encontrados": termos_encontrados,
            "palavras_encontradas": termos_encontrados,
            "palavras_chave_encontradas": termos_encontrados,
            "palavras_chave": termos_encontrados,
            "tipos_match": tipos_match,
            "termos": termos_contextuais,
            "matchs": termos_contextuais,
            "matches": termos_contextuais,
        })

        publicacoes.append(publicacao)

    return ordenar_publicacoes_por_relevancia(publicacoes)


def gerar_publicacoes_monitoramento_setorial(registros: list[dict]) -> list[dict]:
    return gerar_publicacoes_contextuais(
        registros=registros,
        tipo_contextual="MONITORAMENTO_SETORIAL",
    )


def gerar_publicacoes_revisao_contextual(registros: list[dict]) -> list[dict]:
    return gerar_publicacoes_contextuais(
        registros=registros,
        tipo_contextual="REVISAO_CONTEXTUAL",
    )


def gerar_publicacoes_relevantes_confirmadas(publicacoes_com_match: list[dict]) -> list[dict]:
    confirmadas = [
        publicacao
        for publicacao in publicacoes_com_match
        if not publicacao.get("tem_suspeita_falso_positivo")
    ]

    return ordenar_publicacoes_por_relevancia(confirmadas)


def gerar_publicacoes_com_suspeita(publicacoes_com_match: list[dict]) -> list[dict]:
    suspeitas = [
        publicacao
        for publicacao in publicacoes_com_match
        if publicacao.get("tem_suspeita_falso_positivo")
    ]

    return ordenar_publicacoes_por_relevancia(suspeitas)


def gerar_publicacoes_sem_match(registros: list[dict], limite: int = 20) -> list[dict]:
    publicacoes = []

    for registro in registros:
        if registro.get("status_match") != "SEM_MATCH":
            continue

        if eh_monitoramento_setorial(registro) or eh_revisao_contextual(registro):
            continue

        publicacoes.append({
            "id_publicacao": registro.get("id_publicacao"),
            "titulo": registro.get("titulo"),
            "orgao": registro.get("orgao"),
            "secao": registro.get("secao"),
            "pagina": registro.get("pagina"),
            "url": registro.get("url"),
            "status_exclusao": registro.get("status_exclusao"),
            "score_contextual": registro.get("score_contextual"),
            "motivo_contextual": registro.get("motivo_contextual"),
            "amostra_texto_normalizado": gerar_amostra_texto(
                registro.get("texto_normalizado", ""),
                limite=1000
            )
        })

        if len(publicacoes) >= limite:
            break

    return publicacoes


# ============================================================
# AGRUPAMENTO EXECUTIVO
# ============================================================

def agrupar_publicacoes_por_score(publicacoes_com_match: list[dict]) -> dict:
    descricao_scores = obter_descricao_scores()

    grupos = {
        "ALTO": [],
        "MEDIO": [],
        "BAIXO": [],
        "CRITICO": [],
        "DESCONHECIDO": []
    }

    for publicacao in publicacoes_com_match:
        score = publicacao.get("score_publicacao", "DESCONHECIDO")

        if score not in grupos:
            score = "DESCONHECIDO"

        grupos[score].append(publicacao)

    retorno = {}

    for score, publicacoes in grupos.items():
        info = descricao_scores.get(score, descricao_scores["DESCONHECIDO"])

        retorno[score] = {
            "score": score,
            "ordem_relevancia": info.get("ordem_relevancia"),
            "significado_operacional": info.get("significado_operacional"),
            "interpretacao": info.get("interpretacao"),
            "total_publicacoes": len(publicacoes),
            "publicacoes": ordenar_publicacoes_por_relevancia(publicacoes)
        }

    return retorno


def simplificar_publicacao_para_relatorio(publicacao: dict) -> dict:
    return {
        "id_publicacao": publicacao.get("id_publicacao"),
        "titulo": publicacao.get("titulo"),
        "orgao": publicacao.get("orgao"),
        "secao": publicacao.get("secao"),
        "pagina": publicacao.get("pagina"),
        "url": publicacao.get("url"),
        "score_publicacao": publicacao.get("score_publicacao"),
        "score_contextual": publicacao.get("score_contextual"),
        "nivel_contextual": publicacao.get("nivel_contextual"),
        "motivo_contextual": publicacao.get("motivo_contextual"),
        "status_match": publicacao.get("status_match"),
        "status_revisao_contextual": publicacao.get("status_revisao_contextual"),
        "quantidade_matchs": publicacao.get("quantidade_matchs"),
        "quantidade_matchs_revisao": publicacao.get("quantidade_matchs_revisao"),
        "termos_encontrados": publicacao.get("termos_encontrados", []),
        "termos_detectados": publicacao.get("termos_detectados", []),
        "tipos_match": publicacao.get("tipos_match", []),
        "tem_suspeita_falso_positivo": publicacao.get("tem_suspeita_falso_positivo"),
        "motivos_score_publicacao": publicacao.get("motivos_score_publicacao", []),
    }


def gerar_resumo_executivo_consolidado(auditoria_base: dict) -> dict:
    resumo = auditoria_base.get("resumo_executivo", {})
    estatisticas_match = auditoria_base.get("estatisticas_match", {})
    estatisticas_publicacoes = auditoria_base.get("estatisticas_publicacoes", {})
    publicacoes_com_match = auditoria_base.get("publicacoes_com_match", [])
    publicacoes_confirmadas = auditoria_base.get("publicacoes_relevantes_confirmadas", [])
    publicacoes_suspeitas = auditoria_base.get("publicacoes_com_suspeita_falso_positivo", [])
    publicacoes_monitoramento = auditoria_base.get("publicacoes_monitoramento_setorial", [])
    publicacoes_revisao = auditoria_base.get("publicacoes_revisao_contextual", [])
    falsos_positivos = auditoria_base.get("possiveis_falsos_positivos", [])

    grupos_por_score = agrupar_publicacoes_por_score(publicacoes_com_match)

    return {
        "visao_geral": {
            "data_referencia": auditoria_base.get("data_referencia"),
            "finalidade_config": auditoria_base.get("finalidade_config"),
            "total_publicacoes": resumo.get("total_publicacoes", 0),

            "com_match": resumo.get("com_match", 0),
            "sem_match": resumo.get("sem_match", 0),
            "total_matchs": resumo.get("total_matchs", 0),
            "taxa_match": resumo.get("taxa_match", 0),

            "match_executivo": resumo.get("match_executivo", resumo.get("com_match", 0)),
            "monitoramento_setorial": resumo.get("monitoramento_setorial", 0),
            "revisao_contextual": resumo.get("revisao_contextual", 0),
            "sem_match_contextual": resumo.get("sem_match_contextual", 0),
            "taxa_match_executivo": resumo.get("taxa_match_executivo", resumo.get("taxa_match", 0)),
            "taxa_monitoramento_setorial": resumo.get("taxa_monitoramento_setorial", 0),
            "taxa_revisao_contextual": resumo.get("taxa_revisao_contextual", 0),
            "total_publicacoes_com_termo_detectado": resumo.get("total_publicacoes_com_termo_detectado", 0),
            "total_excluidos_titulo": resumo.get("total_excluidos_titulo", 0),
            "total_resgatados": resumo.get("total_resgatados", 0),

            "publicacoes_relevantes_confirmadas": len(publicacoes_confirmadas),
            "publicacoes_com_suspeita_falso_positivo": len(publicacoes_suspeitas),
            "publicacoes_monitoramento_setorial": len(publicacoes_monitoramento),
            "publicacoes_revisao_contextual": len(publicacoes_revisao),
            "possiveis_falsos_positivos": len(falsos_positivos),
            "taxa_match_confirmado": resumo.get("taxa_match_confirmado", 0)
        },

        "scores": {
            "descricao": obter_descricao_scores(),
            "matches": estatisticas_match.get("score_confianca", {}),
            "publicacoes": estatisticas_match.get("score_publicacao", {}),
            "contextual": estatisticas_match.get("score_contextual", {}),
        },

        "match": {
            "tipos_match": estatisticas_match.get("tipos_match", {}),
            "top_termos": estatisticas_match.get("top_termos", []),
            "top_termo_tipo": estatisticas_match.get("top_termo_tipo", []),
            "top_termos_detectados": estatisticas_match.get("top_termos_detectados", []),
            "top_termos_revisao": estatisticas_match.get("top_termos_revisao", []),
            "status_revisao_contextual": estatisticas_match.get("status_revisao_contextual", {}),
            "motivos_contextuais": estatisticas_match.get("motivos_contextuais", []),
        },

        "publicacoes_por_score": grupos_por_score,

        "listas_executivas": {
            "publicacoes_relevantes_confirmadas": [
                simplificar_publicacao_para_relatorio(p)
                for p in publicacoes_confirmadas
            ],
            "publicacoes_com_suspeita_falso_positivo": [
                simplificar_publicacao_para_relatorio(p)
                for p in publicacoes_suspeitas
            ],
            "publicacoes_monitoramento_setorial": [
                simplificar_publicacao_para_relatorio(p)
                for p in publicacoes_monitoramento
            ],
            "publicacoes_revisao_contextual": [
                simplificar_publicacao_para_relatorio(p)
                for p in publicacoes_revisao
            ],
        },

        "possiveis_falsos_positivos": falsos_positivos,

        "estatisticas_publicacoes": {
            "top_orgaos": estatisticas_publicacoes.get("top_orgaos", []),
            "top_secoes": estatisticas_publicacoes.get("top_secoes", []),
            "top_orgaos_match_executivo": estatisticas_publicacoes.get("top_orgaos_match_executivo", []),
            "top_orgaos_monitoramento_setorial": estatisticas_publicacoes.get("top_orgaos_monitoramento_setorial", []),
        }
    }


# ============================================================
# DETECÇÃO SUSPEITA FALSO POSITIVO
# ============================================================

def detectar_falsos_positivos(registros: list[dict]) -> list[dict]:
    suspeitos = []

    for registro in registros:
        texto_integral = registro.get("texto_integral", "") or ""

        for match in obter_matchs_registro(registro):
            match_enriquecido = enriquecer_match_com_confianca(match)

            if not match_enriquecido.get("suspeita_falso_positivo"):
                continue

            suspeitos.append({
                "id_publicacao": registro.get("id_publicacao"),
                "titulo": registro.get("titulo"),
                "orgao": registro.get("orgao"),
                "secao": registro.get("secao"),
                "pagina": registro.get("pagina"),
                "url": registro.get("url"),
                "termo": match_enriquecido.get("termo"),
                "tipo": match_enriquecido.get("tipo"),
                "encontrados": match_enriquecido.get("encontrados", []),
                "score_confianca": match_enriquecido.get("score_confianca"),
                "motivos": match_enriquecido.get("motivos_confianca", []),
                "amostra_texto": gerar_amostra_texto(texto_integral, limite=1500)
            })

    return suspeitos


# ============================================================
# GERAÇÃO AUDITORIA
# ============================================================

def extrair_registros_payload_match(payload_match: dict | list) -> list[dict]:
    if isinstance(payload_match, list):
        return payload_match

    if isinstance(payload_match, dict):
        registros = payload_match.get("registros")

        if isinstance(registros, list):
            return registros

        publicacoes = payload_match.get("publicacoes")

        if isinstance(publicacoes, list):
            return publicacoes

    return []


def gerar_auditoria_match(payload_match: dict) -> dict:
    registros = extrair_registros_payload_match(payload_match)

    publicacoes_com_match = gerar_publicacoes_com_match(registros)

    publicacoes_relevantes_confirmadas = gerar_publicacoes_relevantes_confirmadas(
        publicacoes_com_match
    )

    publicacoes_com_suspeita_falso_positivo = gerar_publicacoes_com_suspeita(
        publicacoes_com_match
    )

    publicacoes_monitoramento_setorial = gerar_publicacoes_monitoramento_setorial(
        registros
    )

    publicacoes_revisao_contextual = gerar_publicacoes_revisao_contextual(
        registros
    )

    publicacoes_sem_match = gerar_publicacoes_sem_match(registros)

    possiveis_falsos_positivos = detectar_falsos_positivos(registros)

    auditoria = {
        "data_referencia": payload_match.get("data_referencia"),
        "finalidade_config": payload_match.get("finalidade_config", FINALIDADE_CONFIG),
        "pasta_config": payload_match.get("pasta_config"),

        "resumo_executivo": gerar_resumo_executivo(registros),

        "estatisticas_match": gerar_estatisticas_match(registros),

        "estatisticas_publicacoes": gerar_estatisticas_publicacoes(registros),

        "publicacoes_com_match": publicacoes_com_match,

        "publicacoes_relevantes_confirmadas": publicacoes_relevantes_confirmadas,

        "publicacoes_com_suspeita_falso_positivo": publicacoes_com_suspeita_falso_positivo,

        "publicacoes_monitoramento_setorial": publicacoes_monitoramento_setorial,

        "publicacoes_revisao_contextual": publicacoes_revisao_contextual,

        "publicacoes_sem_match_amostra": publicacoes_sem_match,

        "amostras_com_match": publicacoes_com_match[:10],

        "amostras_relevantes_confirmadas": publicacoes_relevantes_confirmadas[:10],

        "amostras_com_suspeita_falso_positivo": publicacoes_com_suspeita_falso_positivo[:10],

        "amostras_monitoramento_setorial": publicacoes_monitoramento_setorial[:10],

        "amostras_revisao_contextual": publicacoes_revisao_contextual[:10],

        "amostras_sem_match": publicacoes_sem_match[:10],

        "possiveis_falsos_positivos": possiveis_falsos_positivos
    }

    auditoria["resumo_executivo_consolidado"] = gerar_resumo_executivo_consolidado(
        auditoria
    )

    return auditoria


# ============================================================
# SALVAR AUDITORIA
# ============================================================

def salvar_auditoria(data_referencia: str, auditoria: dict) -> Path:
    finalidade_config = auditoria.get("finalidade_config", FINALIDADE_CONFIG)

    auditoria_dir = AUDITORIA_BASE_DIR / finalidade_config
    auditoria_dir.mkdir(parents=True, exist_ok=True)

    caminho = auditoria_dir / f"auditoria_match_{data_referencia}.json"

    caminho.write_text(
        json.dumps(auditoria, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return caminho
