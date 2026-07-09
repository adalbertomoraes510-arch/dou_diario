# ============================================================
# SERVICE — Relatório Executivo DOU
# Monta modelo executivo único a partir da auditoria do DOU,
# do resultado de match e gera saídas em JSON e TXT
# Inclui separação entre match executivo, monitoramento setorial
# e revisão contextual
# ============================================================

import datetime
import json
import re
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"

AUDITORIA_BASE_DIR = DATA_DOU_DIR / "auditoria"
MATCH_BASE_DIR = DATA_DOU_DIR / "match"
BRUTO_DIR = DATA_DOU_DIR / "bruto"
BASE_DIR = DATA_DOU_DIR / "base"
LOG_DIR = DATA_DOU_DIR / "logs_execucao"
RELATORIOS_BASE_DIR = DATA_DOU_DIR / "relatorios"

RELATORIOS_BASE_DIR.mkdir(parents=True, exist_ok=True)

INCLUIR_TEXTO_INTEGRA_COMPLETO = True
LIMITE_AMOSTRA_RESUMIDA = 500


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def carregar_json(caminho: Path) -> dict:
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_json_opcional(caminho: Path) -> dict | list | None:
    if not caminho.exists():
        return None

    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_json(caminho: Path, payload: dict) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return caminho


def salvar_txt(caminho: Path, conteudo: str) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    caminho.write_text(
        conteudo,
        encoding="utf-8"
    )

    return caminho


def limpar_espacos(texto: str) -> str:
    texto = str(texto or "")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def preparar_texto_integra(texto: str) -> str:
    return limpar_espacos(texto)


def limitar_texto(texto: str, limite: int = LIMITE_AMOSTRA_RESUMIDA) -> str:
    texto = limpar_espacos(texto)

    if len(texto) <= limite:
        return texto

    return texto[:limite].rstrip() + "..."


def formatar_percentual(valor) -> str:
    if valor is None:
        return "0,00%"

    try:
        numero = float(valor)
    except Exception:
        return f"{valor}%"

    return f"{numero:.2f}%".replace(".", ",")


def formatar_lista_texto(lista: list) -> str:
    if not lista:
        return "-"

    return ", ".join(str(item) for item in lista if item not in [None, ""])


def buscar_valor(dados: dict, chaves: list[str], padrao=None):
    for chave in chaves:
        valor = dados.get(chave)

        if valor not in [None, ""]:
            return valor

    return padrao


def formatar_lista(valor) -> list:
    if valor is None:
        return []

    if isinstance(valor, list):
        return valor

    return [valor]


def extrair_registros_payload(payload: dict | list | None) -> list[dict]:
    if payload is None:
        return []

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for chave in ["registros", "publicacoes", "items", "dados"]:
            valor = payload.get(chave)

            if isinstance(valor, list):
                return valor

    return []


def obter_termos_publicacao(publicacao: dict) -> list:
    termos = buscar_valor(
        publicacao,
        [
            "termos_encontrados",
            "palavras_encontradas",
            "palavras_chave_encontradas",
            "palavras_chave",
        ],
        padrao=[]
    )

    return formatar_lista(termos)


def obter_tipos_match_publicacao(publicacao: dict) -> list:
    tipos = buscar_valor(
        publicacao,
        [
            "tipos_match",
            "tipo_match",
        ],
        padrao=[]
    )

    return formatar_lista(tipos)


def extrair_termos_de_matches(matches: list | None) -> list[str]:
    termos = []

    if not isinstance(matches, list):
        return termos

    for match in matches:
        if isinstance(match, dict):
            termo = match.get("termo")
        else:
            termo = match

        if termo not in [None, ""]:
            termos.append(str(termo))

    return termos


def extrair_tipos_de_matches(matches: list | None) -> list[str]:
    tipos = []

    if not isinstance(matches, list):
        return tipos

    for match in matches:
        if not isinstance(match, dict):
            continue

        tipo = match.get("tipo")

        if tipo not in [None, ""]:
            tipos.append(str(tipo))

    return tipos


def obter_termos_match_publicacao(
    publicacao: dict,
    incluir_detectados: bool = False
) -> list[str]:
    termos = extrair_termos_de_matches(publicacao.get("matchs"))

    if termos:
        return termos

    termos = extrair_termos_de_matches(publicacao.get("matchs_revisao"))

    if termos:
        return termos

    if incluir_detectados:
        return extrair_termos_de_matches(publicacao.get("matchs_detectados"))

    return obter_termos_publicacao(publicacao)


def obter_tipos_match_contextual(
    publicacao: dict,
    incluir_detectados: bool = False
) -> list[str]:
    tipos = extrair_tipos_de_matches(publicacao.get("matchs"))

    if tipos:
        return tipos

    tipos = extrair_tipos_de_matches(publicacao.get("matchs_revisao"))

    if tipos:
        return tipos

    if incluir_detectados:
        return extrair_tipos_de_matches(publicacao.get("matchs_detectados"))

    return obter_tipos_match_publicacao(publicacao)


def obter_motivos_publicacao(publicacao: dict) -> list:
    motivos = buscar_valor(
        publicacao,
        [
            "motivos_score_publicacao",
            "motivos",
            "motivos_confianca",
        ],
        padrao=[]
    )

    return formatar_lista(motivos)


def simplificar_orgao(orgao: str) -> str:
    orgao = str(orgao or "")

    substituicoes = {
        "Ministério da Saúde/Agência Nacional de Vigilância Sanitária": (
            "Ministério da Saúde / ANVISA"
        ),
        "Ministério dos Transportes/Agência Nacional de Transportes Terrestres": (
            "Ministério dos Transportes / ANTT"
        ),
        "Ministério da Educação/Empresa Brasileira de Serviços Hospitalares": (
            "Ministério da Educação / EBSERH"
        ),
        "Ministério da Justiça e Segurança Pública/Secretaria Nacional de Justiça": (
            "Ministério da Justiça e Segurança Pública / Secretaria Nacional de Justiça"
        ),
    }

    for original, simplificado in substituicoes.items():
        if orgao.startswith(original):
            return simplificado

    return orgao


def normalizar_secao(secao) -> str:
    secao_txt = str(secao or "").strip()

    if "| Página:" in secao_txt:
        return secao_txt.split("| Página:")[0].strip()

    return secao_txt


def normalizar_pagina(publicacao: dict) -> str:
    pagina = str(publicacao.get("pagina") or "").strip()

    if pagina:
        return pagina

    secao = str(publicacao.get("secao") or "")

    match = re.search(r"Página:\s*([^\|]+)", secao)

    if match:
        return match.group(1).strip()

    return ""


# ============================================================
# CAMINHOS OFICIAIS
# ============================================================

def montar_caminhos_entrada(
    data_referencia: str,
    finalidade: str
) -> dict:
    return {
        "auditoria": (
            AUDITORIA_BASE_DIR
            / finalidade
            / f"auditoria_match_{data_referencia}.json"
        ),
        "status": (
            LOG_DIR
            / f"status_orquestrador_dou_{data_referencia}.json"
        ),
        "publicacoes": (
            BRUTO_DIR
            / f"publicacoes_{data_referencia}.json"
        ),
        "base": (
            BASE_DIR
            / f"base_publicacoes_{data_referencia}.json"
        ),
        "match": (
            MATCH_BASE_DIR
            / finalidade
            / f"match_publicacoes_{data_referencia}.json"
        ),
    }


def montar_caminhos_auditaveis(
    data_referencia: str,
    finalidade: str
) -> list[dict]:
    return [
        {
            "nome": "Links coletados",
            "tipo": "bruto_links",
            "caminho": str(
                BRUTO_DIR / f"links_dou_{data_referencia}.json"
            ),
        },
        {
            "nome": "Publicações extraídas",
            "tipo": "bruto_publicacoes",
            "caminho": str(
                BRUTO_DIR / f"publicacoes_{data_referencia}.json"
            ),
        },
        {
            "nome": "Base auditável",
            "tipo": "base_publicacoes",
            "caminho": str(
                BASE_DIR / f"base_publicacoes_{data_referencia}.json"
            ),
        },
        {
            "nome": "Resultado do match",
            "tipo": "match",
            "caminho": str(
                MATCH_BASE_DIR
                / finalidade
                / f"match_publicacoes_{data_referencia}.json"
            ),
        },
        {
            "nome": "Auditoria do match",
            "tipo": "auditoria",
            "caminho": str(
                AUDITORIA_BASE_DIR
                / finalidade
                / f"auditoria_match_{data_referencia}.json"
            ),
        },
        {
            "nome": "Status da execução",
            "tipo": "status_execucao",
            "caminho": str(
                LOG_DIR
                / f"status_orquestrador_dou_{data_referencia}.json"
            ),
        },
    ]


def montar_caminhos_saida(
    data_referencia: str,
    finalidade: str
) -> dict:
    relatorio_dir = RELATORIOS_BASE_DIR / finalidade
    relatorio_dir.mkdir(parents=True, exist_ok=True)

    return {
        "modelo_json": (
            relatorio_dir
            / f"relatorio_executivo_modelo_{data_referencia}.json"
        ),
        "relatorio_txt": (
            relatorio_dir
            / f"relatorio_executivo_{data_referencia}.txt"
        ),
    }


# ============================================================
# MAPA DE ÍNTEGRA
# ============================================================

def extrair_texto_integral_registro(registro: dict) -> str:
    texto = buscar_valor(
        registro,
        [
            "texto_integral",
            "texto_completo",
            "integra",
            "texto",
            "conteudo",
        ],
        padrao=""
    )

    return preparar_texto_integra(texto)


def adicionar_registro_mapa_texto(
    mapa: dict,
    registro: dict
) -> None:
    texto = extrair_texto_integral_registro(registro)

    if not texto:
        return

    id_publicacao = registro.get("id_publicacao")
    url = registro.get("url") or registro.get("link")

    if id_publicacao:
        chave_id = f"id::{id_publicacao}"

        if chave_id not in mapa:
            mapa[chave_id] = texto

    if url:
        chave_url = f"url::{url}"

        if chave_url not in mapa:
            mapa[chave_url] = texto


def montar_mapa_texto_integral(
    publicacoes_payload: dict | list | None,
    base_payload: dict | list | None,
    match_payload: dict | list | None
) -> dict:
    mapa = {}

    for payload in [publicacoes_payload, base_payload, match_payload]:
        registros = extrair_registros_payload(payload)

        for registro in registros:
            adicionar_registro_mapa_texto(mapa, registro)

    return mapa


def obter_texto_integral_publicacao(
    publicacao: dict,
    mapa_texto_integral: dict
) -> str:
    id_publicacao = publicacao.get("id_publicacao")
    url = publicacao.get("url") or publicacao.get("link")

    if id_publicacao:
        texto = mapa_texto_integral.get(f"id::{id_publicacao}")

        if texto:
            return texto

    if url:
        texto = mapa_texto_integral.get(f"url::{url}")

        if texto:
            return texto

    texto_direto = extrair_texto_integral_registro(publicacao)

    if texto_direto:
        return texto_direto

    return preparar_texto_integra(publicacao.get("amostra_texto", ""))


# ============================================================
# MONTAGEM DO MODELO EXECUTIVO
# ============================================================


def separar_registros_contextuais(match_payload: dict | list | None) -> dict:
    registros = extrair_registros_payload(match_payload)

    executivos = []
    monitoramento = []
    revisao = []

    for registro in registros:
        if registro.get("status_match") == "COM_MATCH":
            executivos.append(registro)
            continue

        status_revisao = str(
            registro.get("status_revisao_contextual") or ""
        ).upper()

        score_contextual = str(
            registro.get("score_contextual") or ""
        ).upper()

        if (
            status_revisao == "MONITORAMENTO_SETORIAL"
            or score_contextual == "MONITORAMENTO_SETORIAL"
        ):
            monitoramento.append(registro)
            continue

        if status_revisao in {"EM_REVISAO", "REVISAO_CONTEXTUAL"}:
            revisao.append(registro)
            continue

        if score_contextual == "REVISAO":
            revisao.append(registro)

    return {
        "registros": registros,
        "executivos": executivos,
        "monitoramento": monitoramento,
        "revisao": revisao,
    }


def calcular_taxa(qtd: int, total: int) -> float:
    if not total:
        return 0.0

    return round((qtd / total) * 100, 2)


def complementar_resumo_com_match_payload(
    resumo: dict,
    match_payload: dict | list | None
) -> dict:
    contexto = separar_registros_contextuais(match_payload)
    registros = contexto["registros"]
    executivos = contexto["executivos"]
    monitoramento = contexto["monitoramento"]
    revisao = contexto["revisao"]

    total_registros_match = len(registros)
    total_publicacoes = resumo.get("total_publicacoes") or total_registros_match

    if isinstance(match_payload, dict):
        total_termos_detectados = match_payload.get("total_com_termo_detectado")
        total_excluidos_titulo = match_payload.get("total_excluidos_titulo")
        total_resgatados = match_payload.get("total_resgatados")
    else:
        total_termos_detectados = None
        total_excluidos_titulo = None
        total_resgatados = None

    if total_termos_detectados is None:
        total_termos_detectados = sum(
            1 for registro in registros
            if registro.get("quantidade_matchs_detectados", 0) > 0
        )

    if total_excluidos_titulo is None:
        total_excluidos_titulo = sum(
            1 for registro in registros
            if registro.get("status_exclusao") == "EXCLUIDO_POR_TITULO"
        )

    if total_resgatados is None:
        total_resgatados = sum(
            1 for registro in registros
            if registro.get("status_resgate") == "RESGATADO"
        )

    total_sem_match_contextual = max(
        total_publicacoes - len(executivos) - len(monitoramento) - len(revisao),
        0,
    )

    resumo_atualizado = dict(resumo)
    resumo_atualizado.update({
        "match_executivo": len(executivos),
        "match_executivo_leroy": len(executivos),
        "monitoramento_setorial": len(monitoramento),
        "revisao_contextual": len(revisao),
        "sem_match_contextual": total_sem_match_contextual,
        "total_registros_match": total_registros_match,
        "total_publicacoes_com_termo_detectado": total_termos_detectados,
        "total_excluidos_titulo": total_excluidos_titulo,
        "total_resgatados": total_resgatados,
        "taxa_match_executivo": calcular_taxa(len(executivos), total_publicacoes),
        "taxa_monitoramento_setorial": calcular_taxa(len(monitoramento), total_publicacoes),
        "taxa_revisao_contextual": calcular_taxa(len(revisao), total_publicacoes),
    })

    return resumo_atualizado


def montar_resumo_executivo(
    auditoria: dict,
    status_execucao: dict | None = None
) -> dict:
    resumo = auditoria.get("resumo_executivo", {})
    consolidado = auditoria.get("resumo_executivo_consolidado", {})
    visao_geral = consolidado.get("visao_geral", {})

    publicacoes_confirmadas = auditoria.get(
        "publicacoes_relevantes_confirmadas",
        []
    )

    publicacoes_suspeitas = auditoria.get(
        "publicacoes_com_suspeita_falso_positivo",
        []
    )

    possiveis_falsos_positivos = auditoria.get(
        "possiveis_falsos_positivos",
        []
    )

    return {
        "status_execucao": (
            status_execucao.get("status")
            if isinstance(status_execucao, dict)
            else None
        ),
        "inicio_execucao": (
            status_execucao.get("inicio")
            if isinstance(status_execucao, dict)
            else None
        ),
        "fim_execucao": (
            status_execucao.get("fim")
            if isinstance(status_execucao, dict)
            else None
        ),
        "total_publicacoes": resumo.get("total_publicacoes", 0),
        "com_match": resumo.get("com_match", 0),
        "sem_match": resumo.get("sem_match", 0),
        "total_matchs": resumo.get("total_matchs", 0),
        "taxa_match": resumo.get("taxa_match", 0),
        "publicacoes_relevantes_confirmadas": len(publicacoes_confirmadas),
        "publicacoes_com_suspeita_falso_positivo": len(publicacoes_suspeitas),
        "possiveis_falsos_positivos": len(possiveis_falsos_positivos),
        "taxa_match_confirmado": visao_geral.get(
            "taxa_match_confirmado",
            resumo.get("taxa_match_confirmado", 0)
        ),
    }


def montar_publicacao_relevante(
    publicacao: dict,
    indice: int,
    mapa_texto_integral: dict,
    incluir_texto_integra_completo: bool = True
) -> dict:
    termos = obter_termos_publicacao(publicacao)
    tipos_match = obter_tipos_match_publicacao(publicacao)
    texto_integral = obter_texto_integral_publicacao(
        publicacao,
        mapa_texto_integral
    )

    payload = {
        "ordem": indice,
        "id_publicacao": publicacao.get("id_publicacao"),
        "titulo": publicacao.get("titulo"),
        "orgao": publicacao.get("orgao"),
        "orgao_resumido": simplificar_orgao(publicacao.get("orgao", "")),
        "secao": normalizar_secao(publicacao.get("secao")),
        "pagina": normalizar_pagina(publicacao),
        "score": buscar_valor(
            publicacao,
            ["score_publicacao", "score", "nivel_score"],
            padrao=""
        ),
        "termos_encontrados": termos,
        "tipos_match": tipos_match,
        "quantidade_matchs": publicacao.get("quantidade_matchs"),
        "url": publicacao.get("url"),
        "amostra_texto": limitar_texto(
            texto_integral or publicacao.get("amostra_texto", ""),
            limite=LIMITE_AMOSTRA_RESUMIDA
        ),
    }

    if incluir_texto_integra_completo:
        payload["texto_integra"] = texto_integral

    return payload


def montar_publicacao_suspeita(
    publicacao: dict,
    indice: int,
    mapa_falsos_positivos: dict,
    mapa_texto_integral: dict,
    incluir_texto_integra_completo: bool = True
) -> dict:
    id_publicacao = publicacao.get("id_publicacao")
    detalhe_fp = mapa_falsos_positivos.get(id_publicacao, {})

    termos = obter_termos_publicacao(publicacao)
    tipos_match = obter_tipos_match_publicacao(publicacao)

    motivos = (
        detalhe_fp.get("motivos")
        or obter_motivos_publicacao(publicacao)
        or []
    )

    texto_integral = obter_texto_integral_publicacao(
        publicacao,
        mapa_texto_integral
    )

    if not texto_integral:
        texto_integral = preparar_texto_integra(
            detalhe_fp.get("amostra_texto", "")
        )

    payload = {
        "ordem": indice,
        "id_publicacao": id_publicacao,
        "titulo": publicacao.get("titulo"),
        "orgao": publicacao.get("orgao"),
        "orgao_resumido": simplificar_orgao(publicacao.get("orgao", "")),
        "secao": normalizar_secao(publicacao.get("secao")),
        "pagina": normalizar_pagina(publicacao),
        "score": buscar_valor(
            publicacao,
            ["score_publicacao", "score", "nivel_score"],
            padrao=detalhe_fp.get("score_confianca", "")
        ),
        "termos_encontrados": termos,
        "tipos_match": tipos_match,
        "quantidade_matchs": publicacao.get("quantidade_matchs"),
        "motivos_suspeita": motivos,
        "url": publicacao.get("url"),
        "amostra_texto": limitar_texto(
            texto_integral,
            limite=LIMITE_AMOSTRA_RESUMIDA
        ),
    }

    if incluir_texto_integra_completo:
        payload["texto_integra"] = texto_integral

    return payload


def montar_publicacao_contextual(
    publicacao: dict,
    indice: int,
    mapa_texto_integral: dict,
    incluir_texto_integra_completo: bool = True
) -> dict:
    texto_integral = obter_texto_integral_publicacao(
        publicacao,
        mapa_texto_integral
    )

    termos_validos = obter_termos_match_publicacao(
        publicacao,
        incluir_detectados=True
    )

    tipos_match = obter_tipos_match_contextual(
        publicacao,
        incluir_detectados=True
    )

    payload = {
        "ordem": indice,
        "id_publicacao": publicacao.get("id_publicacao"),
        "titulo": publicacao.get("titulo") or publicacao.get("titulo_publicacao"),
        "orgao": publicacao.get("orgao") or publicacao.get("orgao_publicacao"),
        "orgao_resumido": simplificar_orgao(
            publicacao.get("orgao") or publicacao.get("orgao_publicacao") or ""
        ),
        "secao": normalizar_secao(publicacao.get("secao")),
        "pagina": normalizar_pagina(publicacao),
        "score_contextual": publicacao.get("score_contextual"),
        "nivel_contextual": publicacao.get("nivel_contextual"),
        "motivo_contextual": publicacao.get("motivo_contextual"),
        "status_match": publicacao.get("status_match"),
        "status_revisao_contextual": publicacao.get("status_revisao_contextual"),
        "categorias_encontradas": publicacao.get("categorias_encontradas", []),
        "termos_empresa": publicacao.get("termos_empresa", []),
        "termos_orgao_regulador": publicacao.get("termos_orgao_regulador", []),
        "termos_ato_normativo": publicacao.get("termos_ato_normativo", []),
        "termos_evento_material": publicacao.get("termos_evento_material", []),
        "termos_atividade_regulatoria": publicacao.get(
            "termos_atividade_regulatoria",
            []
        ),
        "termos_produto_especifico": publicacao.get(
            "termos_produto_especifico",
            []
        ),
        "termos_produto_generico": publicacao.get(
            "termos_produto_generico",
            []
        ),
        "termos_fracos_encontrados": publicacao.get(
            "termos_fracos_encontrados",
            []
        ),
        "termos_detectados": extrair_termos_de_matches(
            publicacao.get("matchs_detectados")
        ),
        "termos_encontrados": termos_validos,
        "tipos_match": tipos_match,
        "quantidade_matchs_detectados": publicacao.get(
            "quantidade_matchs_detectados"
        ),
        "quantidade_matchs_revisao": publicacao.get(
            "quantidade_matchs_revisao"
        ),
        "url": publicacao.get("url") or publicacao.get("link"),
        "amostra_texto": limitar_texto(
            texto_integral or publicacao.get("amostra_texto", ""),
            limite=LIMITE_AMOSTRA_RESUMIDA
        ),
    }

    if incluir_texto_integra_completo:
        payload["texto_integra"] = texto_integral

    return payload


def montar_mapa_falsos_positivos(auditoria: dict) -> dict:
    mapa = {}

    for item in auditoria.get("possiveis_falsos_positivos", []):
        id_publicacao = item.get("id_publicacao")

        if id_publicacao:
            mapa[id_publicacao] = item

    return mapa


def montar_termos_encontrados(
    auditoria: dict,
    monitoramento_setorial: list[dict] | None = None,
    revisao_contextual: list[dict] | None = None,
) -> list[dict]:
    contador_confirmados = Counter()
    contador_suspeitos = Counter()
    contador_monitoramento = Counter()
    contador_revisao = Counter()

    monitoramento_setorial = monitoramento_setorial or []
    revisao_contextual = revisao_contextual or []

    for publicacao in auditoria.get("publicacoes_relevantes_confirmadas", []):
        for termo in obter_termos_publicacao(publicacao):
            contador_confirmados[str(termo)] += 1

    for publicacao in auditoria.get(
        "publicacoes_com_suspeita_falso_positivo",
        []
    ):
        for termo in obter_termos_publicacao(publicacao):
            contador_suspeitos[str(termo)] += 1

    for publicacao in monitoramento_setorial:
        for termo in publicacao.get("termos_encontrados", []):
            contador_monitoramento[str(termo)] += 1

    for publicacao in revisao_contextual:
        for termo in publicacao.get("termos_encontrados", []):
            contador_revisao[str(termo)] += 1

    todos_termos = sorted(
        set(contador_confirmados.keys())
        | set(contador_suspeitos.keys())
        | set(contador_monitoramento.keys())
        | set(contador_revisao.keys())
    )

    termos = []

    for termo in todos_termos:
        confirmados = contador_confirmados.get(termo, 0)
        suspeitos = contador_suspeitos.get(termo, 0)
        monitoramento = contador_monitoramento.get(termo, 0)
        revisao = contador_revisao.get(termo, 0)

        termos.append({
            "termo": termo,
            "publicacoes_confirmadas": confirmados,
            "publicacoes_suspeitas": suspeitos,
            "publicacoes_monitoramento_setorial": monitoramento,
            "publicacoes_revisao_contextual": revisao,
            "total": confirmados + suspeitos + monitoramento + revisao,
        })

    termos.sort(
        key=lambda item: (
            -item["total"],
            item["termo"]
        )
    )

    return termos


def montar_status_etapas(status_execucao: dict | None) -> list[dict]:
    if not isinstance(status_execucao, dict):
        return []

    etapas = status_execucao.get("etapas", [])

    if not isinstance(etapas, list):
        return []

    return [
        {
            "timestamp": etapa.get("timestamp"),
            "etapa": etapa.get("etapa"),
            "status": etapa.get("status"),
            "detalhes": etapa.get("detalhes", {}),
        }
        for etapa in etapas
    ]


def montar_conclusao_executiva(modelo_parcial: dict) -> str:
    resumo = modelo_parcial.get("resumo_executivo", {})

    total = resumo.get("total_publicacoes", 0)
    confirmadas = resumo.get("publicacoes_relevantes_confirmadas", 0)
    suspeitas = resumo.get("publicacoes_com_suspeita_falso_positivo", 0)
    monitoramento = resumo.get("monitoramento_setorial", 0)
    revisao = resumo.get("revisao_contextual", 0)

    if confirmadas == 0 and suspeitas == 0 and monitoramento == 0 and revisao == 0:
        return (
            f"A execução analisou {total} publicações do DOU e não identificou "
            "publicações relevantes, monitoramento setorial ou revisão "
            "contextual para a finalidade configurada."
        )

    partes = [
        f"A execução analisou {total} publicações do DOU."
    ]

    if confirmadas:
        partes.append(
            f"Foram identificada(s) {confirmadas} publicação(ões) "
            "com match executivo confirmado para a finalidade configurada."
        )
    else:
        partes.append(
            "Não houve publicação com match executivo direto para a "
            "finalidade configurada."
        )

    if monitoramento:
        partes.append(
            f"Foram separada(s) {monitoramento} publicação(ões) em "
            "monitoramento setorial, por conterem sinais regulatórios "
            "relevantes sem vínculo direto com a empresa/finalidade."
        )

    if revisao:
        partes.append(
            f"Também há {revisao} publicação(ões) em revisão contextual, "
            "mantidas fora da lista executiva até validação."
        )

    if suspeitas:
        partes.append(
            f"Foi identificada {suspeitas} publicação com suspeita de falso "
            "positivo, separada da lista principal para evitar interpretação "
            "operacional incorreta."
        )

    return " ".join(partes)


def montar_modelo_relatorio_executivo(
    data_referencia: str,
    finalidade: str,
    auditoria: dict,
    status_execucao: dict | None = None,
    mapa_texto_integral: dict | None = None,
    incluir_texto_integra_completo: bool = True,
    match_payload: dict | list | None = None,
) -> dict:
    if mapa_texto_integral is None:
        mapa_texto_integral = {}

    resumo = montar_resumo_executivo(
        auditoria=auditoria,
        status_execucao=status_execucao
    )

    resumo = complementar_resumo_com_match_payload(
        resumo=resumo,
        match_payload=match_payload,
    )

    registros_contextuais = separar_registros_contextuais(match_payload)

    mapa_falsos_positivos = montar_mapa_falsos_positivos(auditoria)

    publicacoes_confirmadas = [
        montar_publicacao_relevante(
            publicacao=publicacao,
            indice=indice,
            mapa_texto_integral=mapa_texto_integral,
            incluir_texto_integra_completo=incluir_texto_integra_completo
        )
        for indice, publicacao in enumerate(
            auditoria.get("publicacoes_relevantes_confirmadas", []),
            start=1
        )
    ]

    publicacoes_suspeitas = [
        montar_publicacao_suspeita(
            publicacao=publicacao,
            indice=indice,
            mapa_falsos_positivos=mapa_falsos_positivos,
            mapa_texto_integral=mapa_texto_integral,
            incluir_texto_integra_completo=incluir_texto_integra_completo
        )
        for indice, publicacao in enumerate(
            auditoria.get("publicacoes_com_suspeita_falso_positivo", []),
            start=1
        )
    ]

    publicacoes_monitoramento_setorial = [
        montar_publicacao_contextual(
            publicacao=publicacao,
            indice=indice,
            mapa_texto_integral=mapa_texto_integral,
            incluir_texto_integra_completo=incluir_texto_integra_completo,
        )
        for indice, publicacao in enumerate(
            registros_contextuais.get("monitoramento", []),
            start=1
        )
    ]

    publicacoes_revisao_contextual = [
        montar_publicacao_contextual(
            publicacao=publicacao,
            indice=indice,
            mapa_texto_integral=mapa_texto_integral,
            incluir_texto_integra_completo=incluir_texto_integra_completo,
        )
        for indice, publicacao in enumerate(
            registros_contextuais.get("revisao", []),
            start=1
        )
    ]

    modelo = {
        "metadata": {
            "tipo": "relatorio_executivo_dou",
            "versao": "v3_monitoramento_setorial",
            "gerado_em": agora_iso(),
            "data_referencia": data_referencia,
            "finalidade": finalidade,
            "inclui_texto_integra_completo": incluir_texto_integra_completo,
        },
        "cabecalho": {
            "titulo": "Relatório Executivo — Monitoramento DOU",
            "data_referencia": data_referencia,
            "finalidade": finalidade,
            "status_execucao": resumo.get("status_execucao"),
        },
        "resumo_executivo": resumo,
        "publicacoes_relevantes_confirmadas": publicacoes_confirmadas,
        "publicacoes_suspeitas_falso_positivo": publicacoes_suspeitas,
        "publicacoes_monitoramento_setorial": publicacoes_monitoramento_setorial,
        "publicacoes_revisao_contextual": publicacoes_revisao_contextual,
        "termos_encontrados": montar_termos_encontrados(
            auditoria,
            monitoramento_setorial=publicacoes_monitoramento_setorial,
            revisao_contextual=publicacoes_revisao_contextual,
        ),
        "status_etapas": montar_status_etapas(status_execucao),
        "arquivos_auditaveis": montar_caminhos_auditaveis(
            data_referencia=data_referencia,
            finalidade=finalidade
        ),
    }

    modelo["conclusao_executiva"] = montar_conclusao_executiva(modelo)

    return modelo


# ============================================================
# RENDER TXT
# ============================================================

def adicionar_texto_integra_linhas(
    linhas: list[str],
    texto_integra: str
) -> None:
    linhas.append("   Íntegra:")
    linhas.append("   " + (texto_integra or "Texto integral não localizado."))
    linhas.append("")


def adicionar_publicacoes_contextuais_linhas(
    linhas: list[str],
    publicacoes: list[dict],
    mensagem_vazia: str,
    incluir_integra: bool = False,
) -> None:
    if not publicacoes:
        linhas.append(mensagem_vazia)
        return

    for pub in publicacoes:
        linhas.append(f"{pub.get('ordem')}. {pub.get('titulo')}")
        linhas.append(f"   Órgão: {pub.get('orgao_resumido')}")
        linhas.append(f"   Seção: {pub.get('secao')} | Página: {pub.get('pagina')}")
        linhas.append(f"   Score contextual: {pub.get('score_contextual')}")
        linhas.append(f"   Nível contextual: {pub.get('nivel_contextual')}")
        linhas.append(f"   Motivo: {pub.get('motivo_contextual')}")
        linhas.append(
            "   Empresa: "
            f"{formatar_lista_texto(pub.get('termos_empresa', []))}"
        )
        linhas.append(
            "   Órgão regulador: "
            f"{formatar_lista_texto(pub.get('termos_orgao_regulador', []))}"
        )
        linhas.append(
            "   Evento material: "
            f"{formatar_lista_texto(pub.get('termos_evento_material', []))}"
        )
        linhas.append(
            "   Atividade regulatória: "
            f"{formatar_lista_texto(pub.get('termos_atividade_regulatoria', []))}"
        )
        linhas.append(
            "   Produto específico: "
            f"{formatar_lista_texto(pub.get('termos_produto_especifico', []))}"
        )
        linhas.append(
            "   Produto genérico: "
            f"{formatar_lista_texto(pub.get('termos_produto_generico', []))}"
        )
        linhas.append(
            "   Termo(s) detectado(s): "
            f"{formatar_lista_texto(pub.get('termos_detectados', []))}"
        )
        linhas.append(f"   Link: {pub.get('url')}")

        if incluir_integra:
            adicionar_texto_integra_linhas(
                linhas,
                pub.get("texto_integra", "")
            )
        else:
            linhas.append(f"   Amostra: {pub.get('amostra_texto')}")
            linhas.append("")


def renderizar_relatorio_txt(modelo: dict) -> str:
    linhas = []

    cabecalho = modelo.get("cabecalho", {})
    resumo = modelo.get("resumo_executivo", {})

    linhas.append("=" * 80)
    linhas.append(str(cabecalho.get("titulo", "Relatório Executivo DOU")).upper())
    linhas.append("=" * 80)
    linhas.append(f"Data de referência: {cabecalho.get('data_referencia')}")
    linhas.append(f"Finalidade: {cabecalho.get('finalidade')}")
    linhas.append(f"Status execução: {cabecalho.get('status_execucao')}")
    linhas.append("")

    linhas.append("-" * 80)
    linhas.append("RESUMO EXECUTIVO")
    linhas.append("-" * 80)
    linhas.append(f"Total de publicações analisadas: {resumo.get('total_publicacoes', 0)}")
    linhas.append(f"Match executivo: {resumo.get('match_executivo', resumo.get('com_match', 0))}")
    linhas.append(f"Monitoramento setorial: {resumo.get('monitoramento_setorial', 0)}")
    linhas.append(f"Revisão contextual: {resumo.get('revisao_contextual', 0)}")
    linhas.append(f"Publicações sem match contextual: {resumo.get('sem_match_contextual', resumo.get('sem_match', 0))}")
    linhas.append(
        "Publicações relevantes confirmadas: "
        f"{resumo.get('publicacoes_relevantes_confirmadas', 0)}"
    )
    linhas.append(
        "Publicações com suspeita de falso positivo: "
        f"{resumo.get('publicacoes_com_suspeita_falso_positivo', 0)}"
    )
    linhas.append(f"Total de matchs executivos: {resumo.get('total_matchs', 0)}")
    linhas.append(
        "Publicações com termo detectado: "
        f"{resumo.get('total_publicacoes_com_termo_detectado', 0)}"
    )
    linhas.append(f"Excluídas por título: {resumo.get('total_excluidos_titulo', 0)}")
    linhas.append(f"Resgatadas: {resumo.get('total_resgatados', 0)}")
    linhas.append(
        "Taxa de match executivo: "
        f"{formatar_percentual(resumo.get('taxa_match_executivo', resumo.get('taxa_match', 0)))}"
    )
    linhas.append(
        "Taxa de monitoramento setorial: "
        f"{formatar_percentual(resumo.get('taxa_monitoramento_setorial', 0))}"
    )
    linhas.append(
        "Taxa de revisão contextual: "
        f"{formatar_percentual(resumo.get('taxa_revisao_contextual', 0))}"
    )
    linhas.append("")

    linhas.append("-" * 80)
    linhas.append("PUBLICAÇÕES RELEVANTES CONFIRMADAS")
    linhas.append("-" * 80)

    confirmadas = modelo.get("publicacoes_relevantes_confirmadas", [])

    if not confirmadas:
        linhas.append("Nenhuma publicação relevante confirmada.")
    else:
        for pub in confirmadas:
            linhas.append(f"{pub.get('ordem')}. {pub.get('titulo')}")
            linhas.append(f"   Órgão: {pub.get('orgao_resumido')}")
            linhas.append(f"   Seção: {pub.get('secao')} | Página: {pub.get('pagina')}")
            linhas.append(f"   Score: {pub.get('score')}")
            linhas.append(
                f"   Palavra-chave(s): {formatar_lista_texto(pub.get('termos_encontrados', []))}"
            )
            linhas.append(
                f"   Tipo(s) de match: {formatar_lista_texto(pub.get('tipos_match', []))}"
            )
            linhas.append(f"   Link: {pub.get('url')}")
            adicionar_texto_integra_linhas(
                linhas,
                pub.get("texto_integra", "")
            )

    linhas.append("-" * 80)
    linhas.append("PUBLICAÇÕES SUSPEITAS / POSSÍVEIS FALSOS POSITIVOS")
    linhas.append("-" * 80)

    suspeitas = modelo.get("publicacoes_suspeitas_falso_positivo", [])

    if not suspeitas:
        linhas.append("Nenhuma publicação suspeita encontrada.")
    else:
        for pub in suspeitas:
            linhas.append(f"{pub.get('ordem')}. {pub.get('titulo')}")
            linhas.append(f"   Órgão: {pub.get('orgao_resumido')}")
            linhas.append(f"   Seção: {pub.get('secao')} | Página: {pub.get('pagina')}")
            linhas.append(f"   Score: {pub.get('score')}")
            linhas.append(
                f"   Palavra-chave(s): {formatar_lista_texto(pub.get('termos_encontrados', []))}"
            )
            linhas.append(
                f"   Tipo(s) de match: {formatar_lista_texto(pub.get('tipos_match', []))}"
            )

            motivos = pub.get("motivos_suspeita", [])

            if motivos:
                linhas.append("   Motivo(s) da suspeita:")

                for motivo in motivos:
                    linhas.append(f"   - {motivo}")

            linhas.append(f"   Link: {pub.get('url')}")
            adicionar_texto_integra_linhas(
                linhas,
                pub.get("texto_integra", "")
            )

    linhas.append("-" * 80)
    linhas.append("MONITORAMENTO SETORIAL")
    linhas.append("-" * 80)
    adicionar_publicacoes_contextuais_linhas(
        linhas=linhas,
        publicacoes=modelo.get("publicacoes_monitoramento_setorial", []),
        mensagem_vazia="Nenhuma publicação em monitoramento setorial.",
        incluir_integra=False,
    )

    linhas.append("-" * 80)
    linhas.append("REVISÃO CONTEXTUAL")
    linhas.append("-" * 80)
    adicionar_publicacoes_contextuais_linhas(
        linhas=linhas,
        publicacoes=modelo.get("publicacoes_revisao_contextual", []),
        mensagem_vazia="Nenhuma publicação em revisão contextual.",
        incluir_integra=False,
    )

    linhas.append("-" * 80)
    linhas.append("TERMOS ENCONTRADOS")
    linhas.append("-" * 80)

    termos = modelo.get("termos_encontrados", [])

    if not termos:
        linhas.append("Nenhum termo encontrado.")
    else:
        for termo in termos:
            linhas.append(
                f"{termo.get('termo')}: "
                f"{termo.get('publicacoes_confirmadas', 0)} confirmada(s), "
                f"{termo.get('publicacoes_suspeitas', 0)} suspeita(s), "
                f"{termo.get('publicacoes_monitoramento_setorial', 0)} monitoramento, "
                f"{termo.get('publicacoes_revisao_contextual', 0)} revisão, "
                f"{termo.get('total', 0)} total"
            )

    linhas.append("")
    linhas.append("-" * 80)
    linhas.append("CONCLUSÃO EXECUTIVA")
    linhas.append("-" * 80)
    linhas.append(modelo.get("conclusao_executiva", ""))
    linhas.append("")

    linhas.append("-" * 80)
    linhas.append("ARQUIVOS AUDITÁVEIS")
    linhas.append("-" * 80)

    for arquivo in modelo.get("arquivos_auditaveis", []):
        linhas.append(f"{arquivo.get('nome')}: {arquivo.get('caminho')}")

    linhas.append("")
    linhas.append("=" * 80)
    linhas.append("FIM DO RELATÓRIO")
    linhas.append("=" * 80)

    return "\n".join(linhas)


# ============================================================
# FUNÇÃO PRINCIPAL DO SERVICE
# ============================================================

def gerar_relatorio_executivo_dou(
    data_referencia: str,
    finalidade: str = "dou_diario",
    caminho_auditoria: Path | None = None,
    caminho_status: Path | None = None,
    salvar: bool = True,
    incluir_texto_integra_completo: bool = INCLUIR_TEXTO_INTEGRA_COMPLETO
) -> dict:
    caminhos_entrada = montar_caminhos_entrada(
        data_referencia=data_referencia,
        finalidade=finalidade
    )

    if caminho_auditoria is None:
        caminho_auditoria = caminhos_entrada["auditoria"]

    if caminho_status is None:
        caminho_status = caminhos_entrada["status"]

    auditoria = carregar_json(caminho_auditoria)

    status_execucao = None

    if caminho_status.exists():
        status_execucao = carregar_json(caminho_status)

    publicacoes_payload = carregar_json_opcional(
        caminhos_entrada["publicacoes"]
    )

    base_payload = carregar_json_opcional(
        caminhos_entrada["base"]
    )

    match_payload = carregar_json_opcional(
        caminhos_entrada["match"]
    )

    mapa_texto_integral = montar_mapa_texto_integral(
        publicacoes_payload=publicacoes_payload,
        base_payload=base_payload,
        match_payload=match_payload
    )

    modelo = montar_modelo_relatorio_executivo(
        data_referencia=data_referencia,
        finalidade=finalidade,
        auditoria=auditoria,
        status_execucao=status_execucao,
        mapa_texto_integral=mapa_texto_integral,
        incluir_texto_integra_completo=incluir_texto_integra_completo,
        match_payload=match_payload,
    )

    conteudo_txt = renderizar_relatorio_txt(modelo)

    caminhos_saida = montar_caminhos_saida(
        data_referencia=data_referencia,
        finalidade=finalidade
    )

    resultado = {
        "modelo": modelo,
        "conteudo_txt": conteudo_txt,
        "arquivos": {
            "modelo_json": str(caminhos_saida["modelo_json"]),
            "relatorio_txt": str(caminhos_saida["relatorio_txt"]),
        }
    }

    if salvar:
        salvar_json(caminhos_saida["modelo_json"], modelo)
        salvar_txt(caminhos_saida["relatorio_txt"], conteudo_txt)

    return resultado
