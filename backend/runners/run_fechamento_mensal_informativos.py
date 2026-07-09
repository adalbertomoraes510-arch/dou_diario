# ============================================================
# RUNNER — Fechamento Mensal Informativos
# Etapa 7.5: diagnóstico mensal, trava de segurança, preparação
# do fechamento final em JSON e geração de TXT executivo
# ============================================================

import calendar
import datetime
import json
from pathlib import Path


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# None = usa mês/ano atual.
# Para fechar mês específico, altere manualmente:
# ANO_FECHAMENTO = 2026
# MES_FECHAMENTO = 5
ANO_FECHAMENTO = None
MES_FECHAMENTO = None

FINALIDADE = "informativos"

# True = apenas diagnostica e valida a trava, não gera consolidado final
# False = permite gerar o fechamento final se estiver APTO_PARA_CONSOLIDAR
MODO_SIMULACAO = True


# ============================================================
# CAMINHOS
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"

RELATORIOS_FINALIDADE_DIR = (
    DATA_DOU_DIR
    / "relatorios"
    / FINALIDADE
)

FECHAMENTO_MENSAL_DIR = (
    DATA_DOU_DIR
    / "fechamento_mensal"
)

FECHAMENTO_MENSAL_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FUNÇÕES AUXILIARES — PERÍODO MENSAL
# ============================================================

def resolver_mes_fechamento() -> tuple[int, int]:
    hoje = datetime.date.today()

    ano = ANO_FECHAMENTO if ANO_FECHAMENTO is not None else hoje.year
    mes = MES_FECHAMENTO if MES_FECHAMENTO is not None else hoje.month

    if mes < 1 or mes > 12:
        raise ValueError("MES_FECHAMENTO deve estar entre 1 e 12.")

    return ano, mes


def obter_primeiro_ultimo_dia_mes(
    ano: int,
    mes: int,
) -> tuple[datetime.date, datetime.date]:
    ultimo_dia = calendar.monthrange(ano, mes)[1]

    data_inicio = datetime.date(ano, mes, 1)
    data_fim = datetime.date(ano, mes, ultimo_dia)

    return data_inicio, data_fim


def eh_dia_util(data: datetime.date) -> bool:
    # Monday = 0
    # Friday = 4
    # Saturday = 5
    # Sunday = 6
    return data.weekday() < 5


def gerar_dias_mes(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> tuple[list[datetime.date], list[datetime.date]]:
    dias_uteis = []
    fins_de_semana = []

    data_atual = data_inicio

    while data_atual <= data_fim:
        if eh_dia_util(data_atual):
            dias_uteis.append(data_atual)
        else:
            fins_de_semana.append(data_atual)

        data_atual += datetime.timedelta(days=1)

    return dias_uteis, fins_de_semana


# ============================================================
# FUNÇÕES AUXILIARES — RELATÓRIOS
# ============================================================

def montar_caminho_modelo_relatorio(data: datetime.date) -> Path:
    return (
        RELATORIOS_FINALIDADE_DIR
        / f"relatorio_executivo_modelo_{data.isoformat()}.json"
    )


def carregar_json_seguro(caminho: Path) -> tuple[dict, str | None]:
    if not caminho.exists():
        return {}, "ARQUIVO_AUSENTE"

    try:
        payload = json.loads(caminho.read_text(encoding="utf-8"))
        return payload, None
    except Exception as erro:
        return {}, f"JSON_INVALIDO: {erro}"


def extrair_resumo_de_modelo_json(modelo_json: dict) -> dict:
    """
    Mantém compatibilidade com os formatos já usados:
    - modelo_json["resumo_executivo"]
    - modelo_json["resumo_executivo_consolidado"]["visao_geral"]
    """

    if not isinstance(modelo_json, dict):
        return {}

    resumo = modelo_json.get("resumo_executivo", {}) or {}

    if isinstance(resumo, dict) and resumo:
        return resumo

    consolidado = modelo_json.get("resumo_executivo_consolidado", {}) or {}

    if isinstance(consolidado, dict):
        visao_geral = consolidado.get("visao_geral", {}) or {}

        if isinstance(visao_geral, dict) and visao_geral:
            return visao_geral

    return {}


def valor_resumo(resumo: dict, chave: str, padrao=0):
    valor = resumo.get(chave)

    if valor is None:
        return padrao

    return valor


def extrair_lista_segura(payload: dict, caminhos: list[list[str]]) -> list:
    """
    Tenta extrair uma lista de caminhos conhecidos dentro de um JSON.

    Exemplo de caminhos:
    [
        ["publicacoes_executivas"],
        ["resumo_executivo_consolidado", "publicacoes"],
    ]
    """

    if not isinstance(payload, dict):
        return []

    for caminho in caminhos:
        cursor = payload

        for chave in caminho:
            if not isinstance(cursor, dict):
                cursor = None
                break

            cursor = cursor.get(chave)

        if isinstance(cursor, list):
            return cursor

    return []


def extrair_publicacoes_relevantes_de_modelo_json(
    modelo_json: dict,
    data_referencia: str,
) -> list[dict]:
    """
    Extrai publicações relevantes do modelo diário, mantendo compatibilidade
    com chaves prováveis já usadas ou que venham a ser adicionadas.

    Se o modelo diário não possuir listas de publicações, retorna lista vazia
    sem quebrar o fechamento.
    """

    caminhos_possiveis = [
        ["publicacoes_relevantes"],
        ["publicacoes_executivas"],
        ["publicacoes_monitoramento_setorial"],
        ["publicacoes_revisao_contextual"],
        ["resumo_executivo_consolidado", "publicacoes"],
        ["detalhamento", "publicacoes"],
        ["dados", "publicacoes"],
    ]

    publicacoes = []

    for caminho in caminhos_possiveis:
        lista = extrair_lista_segura(modelo_json, [caminho])

        if not lista:
            continue

        for item in lista:
            if not isinstance(item, dict):
                continue

            item_saida = dict(item)
            item_saida.setdefault("data_referencia", data_referencia)
            item_saida.setdefault("origem_modelo_json", ".".join(caminho))

            publicacoes.append(item_saida)

    # Deduplicação conservadora por título + órgão + url + data.
    publicacoes_deduplicadas = []
    vistos = set()

    for item in publicacoes:
        chave = (
            str(item.get("data_referencia") or ""),
            str(item.get("titulo") or item.get("titulo_publicacao") or ""),
            str(item.get("orgao") or item.get("orgao_publicacao") or ""),
            str(item.get("url") or item.get("link") or ""),
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        publicacoes_deduplicadas.append(item)

    return publicacoes_deduplicadas


def diagnosticar_dia(data: datetime.date) -> dict:
    caminho = montar_caminho_modelo_relatorio(data)
    payload, erro = carregar_json_seguro(caminho)

    if erro == "ARQUIVO_AUSENTE":
        return {
            "data": data.isoformat(),
            "status": "PENDENTE",
            "motivo": "relatório diário de informativos não encontrado",
            "caminho_modelo_json": str(caminho),
            "resumo": {},
            "publicacoes_relevantes": [],
        }

    if erro:
        return {
            "data": data.isoformat(),
            "status": "JSON_INVALIDO",
            "motivo": erro,
            "caminho_modelo_json": str(caminho),
            "resumo": {},
            "publicacoes_relevantes": [],
        }

    resumo = extrair_resumo_de_modelo_json(payload)

    if not resumo:
        return {
            "data": data.isoformat(),
            "status": "SEM_RESUMO",
            "motivo": "modelo JSON existe, mas não contém resumo executivo reconhecido",
            "caminho_modelo_json": str(caminho),
            "resumo": {},
            "publicacoes_relevantes": [],
        }

    publicacoes_relevantes = extrair_publicacoes_relevantes_de_modelo_json(
        modelo_json=payload,
        data_referencia=data.isoformat(),
    )

    return {
        "data": data.isoformat(),
        "status": "GERADO",
        "motivo": "relatório diário de informativos encontrado",
        "caminho_modelo_json": str(caminho),
        "resumo": resumo,
        "publicacoes_relevantes": publicacoes_relevantes,
    }


# ============================================================
# CONSOLIDAÇÃO DO DIAGNÓSTICO
# ============================================================

def consolidar_diagnostico(
    ano: int,
    mes: int,
    data_inicio: datetime.date,
    data_fim: datetime.date,
    dias_uteis: list[datetime.date],
    fins_de_semana: list[datetime.date],
) -> dict:
    diagnosticos_dias = [
        diagnosticar_dia(data)
        for data in dias_uteis
    ]

    total_gerados = sum(
        1 for item in diagnosticos_dias
        if item.get("status") == "GERADO"
    )

    total_pendentes = sum(
        1 for item in diagnosticos_dias
        if item.get("status") == "PENDENTE"
    )

    total_json_invalido = sum(
        1 for item in diagnosticos_dias
        if item.get("status") == "JSON_INVALIDO"
    )

    total_sem_resumo = sum(
        1 for item in diagnosticos_dias
        if item.get("status") == "SEM_RESUMO"
    )

    executivo_total = 0
    monitoramento_total = 0
    revisao_total = 0
    suspeitos_total = 0
    sem_match_contextual_total = 0
    publicacoes_relevantes_total = 0

    for item in diagnosticos_dias:
        if item.get("status") != "GERADO":
            continue

        resumo = item.get("resumo", {}) or {}

        executivo_total += int(valor_resumo(resumo, "match_executivo", 0))
        monitoramento_total += int(valor_resumo(resumo, "monitoramento_setorial", 0))
        revisao_total += int(valor_resumo(resumo, "revisao_contextual", 0))
        suspeitos_total += int(valor_resumo(resumo, "possiveis_falsos_positivos", 0))
        sem_match_contextual_total += int(valor_resumo(resumo, "sem_match_contextual", 0))
        publicacoes_relevantes_total += len(item.get("publicacoes_relevantes", []) or [])

    status_fechamento = (
        "APTO_PARA_CONSOLIDAR"
        if total_pendentes == 0
        and total_json_invalido == 0
        and total_sem_resumo == 0
        else "PENDENTE_DE_REGULARIZACAO"
    )

    return {
        "tipo": "diagnostico_fechamento_mensal_informativos",
        "versao": "7.5",
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "ano": ano,
        "mes": mes,
        "referencia": f"{ano}-{mes:02d}",
        "finalidade": FINALIDADE,
        "modo_simulacao": MODO_SIMULACAO,
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "status_fechamento": status_fechamento,
        "total_dias_uteis": len(dias_uteis),
        "total_fins_de_semana_ignorados": len(fins_de_semana),
        "total_gerados": total_gerados,
        "total_pendentes": total_pendentes,
        "total_json_invalido": total_json_invalido,
        "total_sem_resumo": total_sem_resumo,
        "executivo_total": executivo_total,
        "monitoramento_total": monitoramento_total,
        "revisao_total": revisao_total,
        "suspeitos_total": suspeitos_total,
        "sem_match_contextual_total": sem_match_contextual_total,
        "publicacoes_relevantes_total": publicacoes_relevantes_total,
        "dias": diagnosticos_dias,
        "fins_de_semana_ignorados": [
            data.isoformat()
            for data in fins_de_semana
        ],
    }


# ============================================================
# TRAVA E FECHAMENTO FINAL
# ============================================================

def avaliar_trava_fechamento_final(diagnostico: dict) -> dict:
    """
    Regra:
    - Diagnóstico sempre pode ser salvo.
    - Fechamento final só pode ser gerado fora do modo simulação
      e quando todos os dias úteis estiverem regulares.
    """

    if MODO_SIMULACAO:
        return {
            "pode_gerar": False,
            "motivo": (
                "modo simulação ativo: diagnóstico salvo, mas fechamento mensal final "
                "não será gerado"
            ),
        }

    if diagnostico.get("status_fechamento") != "APTO_PARA_CONSOLIDAR":
        return {
            "pode_gerar": False,
            "motivo": (
                "fechamento mensal não está apto: existem dias pendentes, "
                "JSON inválido ou relatório sem resumo"
            ),
        }

    return {
        "pode_gerar": True,
        "motivo": "fechamento mensal apto para consolidar",
    }


def montar_fechamento_final_json(diagnostico: dict) -> dict:
    """
    Monta a estrutura final do fechamento mensal.

    Esta função já fica preparada para o futuro. Ela só será salva se a trava
    permitir. Enquanto o mês estiver pendente, nada final será gerado.
    """

    dias_gerados = [
        item for item in diagnostico.get("dias", [])
        if item.get("status") == "GERADO"
    ]

    arquivos_diarios_usados = [
        {
            "data": item.get("data"),
            "caminho_modelo_json": item.get("caminho_modelo_json"),
            "status": item.get("status"),
        }
        for item in dias_gerados
    ]

    publicacoes_relevantes_mes = []

    for item in dias_gerados:
        publicacoes = item.get("publicacoes_relevantes", []) or []

        for publicacao in publicacoes:
            if not isinstance(publicacao, dict):
                continue

            publicacao_saida = dict(publicacao)
            publicacao_saida.setdefault("data_referencia", item.get("data"))

            publicacoes_relevantes_mes.append(publicacao_saida)

    # Deduplicação conservadora por data + título + órgão + url.
    publicacoes_deduplicadas = []
    vistos = set()

    for item in publicacoes_relevantes_mes:
        chave = (
            str(item.get("data_referencia") or ""),
            str(item.get("titulo") or item.get("titulo_publicacao") or ""),
            str(item.get("orgao") or item.get("orgao_publicacao") or ""),
            str(item.get("url") or item.get("link") or ""),
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        publicacoes_deduplicadas.append(item)

    fechamento = {
        "tipo": "fechamento_mensal_informativos",
        "versao": "7.5",
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "referencia": diagnostico.get("referencia"),
        "finalidade": diagnostico.get("finalidade"),
        "data_inicio": diagnostico.get("data_inicio"),
        "data_fim": diagnostico.get("data_fim"),
        "status_fechamento": diagnostico.get("status_fechamento"),
        "resumo_mensal": {
            "total_dias_uteis": diagnostico.get("total_dias_uteis"),
            "total_fins_de_semana_ignorados": diagnostico.get("total_fins_de_semana_ignorados"),
            "total_gerados": diagnostico.get("total_gerados"),
            "total_pendentes": diagnostico.get("total_pendentes"),
            "total_json_invalido": diagnostico.get("total_json_invalido"),
            "total_sem_resumo": diagnostico.get("total_sem_resumo"),
            "executivo_total": diagnostico.get("executivo_total"),
            "monitoramento_total": diagnostico.get("monitoramento_total"),
            "revisao_total": diagnostico.get("revisao_total"),
            "suspeitos_total": diagnostico.get("suspeitos_total"),
            "sem_match_contextual_total": diagnostico.get("sem_match_contextual_total"),
            "publicacoes_relevantes_total": len(publicacoes_deduplicadas),
        },
        "dias_considerados": [
            {
                "data": item.get("data"),
                "status": item.get("status"),
                "resumo": item.get("resumo", {}),
                "caminho_modelo_json": item.get("caminho_modelo_json"),
            }
            for item in diagnostico.get("dias", [])
        ],
        "fins_de_semana_ignorados": diagnostico.get("fins_de_semana_ignorados", []),
        "arquivos_diarios_usados": arquivos_diarios_usados,
        "publicacoes_relevantes_mes": publicacoes_deduplicadas,
        "diagnostico_origem": {
            "tipo": diagnostico.get("tipo"),
            "versao": diagnostico.get("versao"),
            "gerado_em": diagnostico.get("gerado_em"),
            "status_fechamento": diagnostico.get("status_fechamento"),
        },
    }

    return fechamento


# ============================================================
# SALVAMENTO
# ============================================================

def salvar_diagnostico_mensal(diagnostico: dict) -> Path:
    referencia = diagnostico.get("referencia")

    if not referencia:
        raise ValueError("Diagnóstico sem referência mensal.")

    caminho = (
        FECHAMENTO_MENSAL_DIR
        / f"diagnostico_fechamento_{FINALIDADE}_{referencia}.json"
    )

    caminho.write_text(
        json.dumps(
            diagnostico,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return caminho


def salvar_fechamento_final(fechamento: dict) -> Path:
    referencia = fechamento.get("referencia")

    if not referencia:
        raise ValueError("Fechamento final sem referência mensal.")

    caminho = (
        FECHAMENTO_MENSAL_DIR
        / f"fechamento_{FINALIDADE}_{referencia}.json"
    )

    caminho.write_text(
        json.dumps(
            fechamento,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return caminho


def normalizar_valor_texto(valor) -> str:
    if valor is None:
        return ""

    texto = str(valor).strip()

    if texto.lower() in {"none", "nan"}:
        return ""

    return texto


def obter_titulo_publicacao(publicacao: dict) -> str:
    return normalizar_valor_texto(
        publicacao.get("titulo")
        or publicacao.get("titulo_publicacao")
        or publicacao.get("ementa")
        or "Sem título identificado"
    )


def obter_orgao_publicacao(publicacao: dict) -> str:
    return normalizar_valor_texto(
        publicacao.get("orgao")
        or publicacao.get("orgao_publicacao")
        or publicacao.get("origem")
        or "Órgão não identificado"
    )


def obter_url_publicacao(publicacao: dict) -> str:
    return normalizar_valor_texto(
        publicacao.get("url")
        or publicacao.get("link")
        or publicacao.get("href")
    )


def obter_classificacao_publicacao(publicacao: dict) -> str:
    return normalizar_valor_texto(
        publicacao.get("status_revisao_contextual")
        or publicacao.get("status_match")
        or publicacao.get("classificacao")
        or publicacao.get("score_contextual")
        or "CLASSIFICACAO_NAO_INFORMADA"
    )


def coletar_publicacoes_relevantes_diagnostico(diagnostico: dict) -> list[dict]:
    publicacoes = []

    for dia in diagnostico.get("dias", []):
        data_referencia = dia.get("data")

        for publicacao in dia.get("publicacoes_relevantes", []) or []:
            if not isinstance(publicacao, dict):
                continue

            item = dict(publicacao)
            item.setdefault("data_referencia", data_referencia)
            publicacoes.append(item)

    # Deduplicação conservadora por data + título + órgão + URL.
    publicacoes_deduplicadas = []
    vistos = set()

    for item in publicacoes:
        chave = (
            normalizar_valor_texto(item.get("data_referencia")),
            obter_titulo_publicacao(item),
            obter_orgao_publicacao(item),
            obter_url_publicacao(item),
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        publicacoes_deduplicadas.append(item)

    return publicacoes_deduplicadas


def montar_texto_diagnostico_mensal(
    diagnostico: dict,
    trava: dict,
) -> str:
    referencia = diagnostico.get("referencia")
    publicacoes_relevantes = coletar_publicacoes_relevantes_diagnostico(
        diagnostico
    )

    linhas = []

    linhas.append("=" * 100)
    linhas.append("DIAGNÓSTICO EXECUTIVO — FECHAMENTO MENSAL INFORMATIVOS")
    linhas.append("=" * 100)
    linhas.append(f"Referência: {referencia}")
    linhas.append(f"Finalidade: {diagnostico.get('finalidade')}")
    linhas.append(f"Gerado em: {datetime.datetime.now().isoformat(timespec='seconds')}")
    linhas.append(f"Modo simulação: {diagnostico.get('modo_simulacao')}")
    linhas.append(f"Data início: {diagnostico.get('data_inicio')}")
    linhas.append(f"Data fim: {diagnostico.get('data_fim')}")
    linhas.append(f"Status fechamento: {diagnostico.get('status_fechamento')}")
    linhas.append("-" * 100)
    linhas.append("RESUMO OPERACIONAL")
    linhas.append("-" * 100)
    linhas.append(f"Dias úteis: {diagnostico.get('total_dias_uteis')}")
    linhas.append(f"Fins de semana ignorados: {diagnostico.get('total_fins_de_semana_ignorados')}")
    linhas.append(f"Dias gerados: {diagnostico.get('total_gerados')}")
    linhas.append(f"Dias pendentes: {diagnostico.get('total_pendentes')}")
    linhas.append(f"JSON inválido: {diagnostico.get('total_json_invalido')}")
    linhas.append(f"Sem resumo: {diagnostico.get('total_sem_resumo')}")
    linhas.append("-" * 100)
    linhas.append("RESULTADO CONSOLIDADO")
    linhas.append("-" * 100)
    linhas.append(f"Executivo total: {diagnostico.get('executivo_total')}")
    linhas.append(f"Monitoramento total: {diagnostico.get('monitoramento_total')}")
    linhas.append(f"Revisão total: {diagnostico.get('revisao_total')}")
    linhas.append(f"Suspeitos total: {diagnostico.get('suspeitos_total')}")
    linhas.append(f"Sem match contextual total: {diagnostico.get('sem_match_contextual_total')}")
    linhas.append(f"Publicações relevantes total: {len(publicacoes_relevantes)}")
    linhas.append("-" * 100)
    linhas.append("TRAVA DO FECHAMENTO FINAL")
    linhas.append("-" * 100)
    linhas.append(f"Pode gerar fechamento final: {trava.get('pode_gerar')}")
    linhas.append(f"Motivo: {trava.get('motivo')}")
    linhas.append("=" * 100)

    linhas.append("")
    linhas.append("DIAS GERADOS")
    linhas.append("-" * 100)

    dias_gerados = [
        item for item in diagnostico.get("dias", [])
        if item.get("status") == "GERADO"
    ]

    if not dias_gerados:
        linhas.append("Nenhum dia gerado.")
    else:
        for item in dias_gerados:
            resumo = item.get("resumo", {}) or {}
            linhas.append(
                f"{item.get('data')} | GERADO | "
                f"executivo={valor_resumo(resumo, 'match_executivo')} | "
                f"monitoramento={valor_resumo(resumo, 'monitoramento_setorial')} | "
                f"revisao={valor_resumo(resumo, 'revisao_contextual')} | "
                f"suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos')} | "
                f"publicacoes_relevantes={len(item.get('publicacoes_relevantes', []) or [])}"
            )

    linhas.append("")
    linhas.append("DIAS PENDENTES / IRREGULARES")
    linhas.append("-" * 100)

    dias_irregulares = [
        item for item in diagnostico.get("dias", [])
        if item.get("status") != "GERADO"
    ]

    if not dias_irregulares:
        linhas.append("Nenhum dia pendente ou irregular.")
    else:
        for item in dias_irregulares:
            linhas.append(
                f"{item.get('data')} | {item.get('status')} | "
                f"{item.get('motivo')}"
            )

    linhas.append("")
    linhas.append("FINS DE SEMANA IGNORADOS")
    linhas.append("-" * 100)

    fins_de_semana = diagnostico.get("fins_de_semana_ignorados", []) or []

    if not fins_de_semana:
        linhas.append("Nenhum.")
    else:
        for data in fins_de_semana:
            linhas.append(f"{data} | IGNORADO_FIM_DE_SEMANA")

    linhas.append("")
    linhas.append("PUBLICAÇÕES RELEVANTES CONSOLIDADAS")
    linhas.append("-" * 100)

    if not publicacoes_relevantes:
        linhas.append("Nenhuma publicação relevante consolidada no mês.")
    else:
        for indice, publicacao in enumerate(publicacoes_relevantes, start=1):
            titulo = obter_titulo_publicacao(publicacao)
            orgao = obter_orgao_publicacao(publicacao)
            url = obter_url_publicacao(publicacao)
            classificacao = obter_classificacao_publicacao(publicacao)
            data_referencia = normalizar_valor_texto(
                publicacao.get("data_referencia")
            )
            motivo = normalizar_valor_texto(
                publicacao.get("motivo_contextual")
                or publicacao.get("motivo")
                or publicacao.get("motivo_score_publicacao")
            )

            linhas.append(f"#{indice}")
            linhas.append(f"Data: {data_referencia}")
            linhas.append(f"Classificação: {classificacao}")
            linhas.append(f"Título: {titulo}")
            linhas.append(f"Órgão: {orgao}")

            if motivo:
                linhas.append(f"Motivo: {motivo}")

            if url:
                linhas.append(f"URL: {url}")

            linhas.append("-" * 100)

    linhas.append("")
    linhas.append("OBSERVAÇÃO")
    linhas.append("-" * 100)
    linhas.append(
        "Este arquivo é um diagnóstico executivo mensal. O fechamento final "
        "só deve ser gerado quando o status estiver APTO_PARA_CONSOLIDAR "
        "e o modo simulação estiver desativado."
    )
    linhas.append("=" * 100)

    return "\n".join(linhas)


def salvar_diagnostico_mensal_txt(
    diagnostico: dict,
    trava: dict,
) -> Path:
    referencia = diagnostico.get("referencia")

    if not referencia:
        raise ValueError("Diagnóstico sem referência mensal.")

    caminho = (
        FECHAMENTO_MENSAL_DIR
        / f"diagnostico_fechamento_{FINALIDADE}_{referencia}.txt"
    )

    texto = montar_texto_diagnostico_mensal(
        diagnostico=diagnostico,
        trava=trava,
    )

    caminho.write_text(texto, encoding="utf-8")

    return caminho


def montar_texto_fechamento_final(fechamento: dict) -> str:
    resumo = fechamento.get("resumo_mensal", {}) or {}
    publicacoes = fechamento.get("publicacoes_relevantes_mes", []) or []

    linhas = []

    linhas.append("=" * 100)
    linhas.append("FECHAMENTO MENSAL FINAL — INFORMATIVOS")
    linhas.append("=" * 100)
    linhas.append(f"Referência: {fechamento.get('referencia')}")
    linhas.append(f"Finalidade: {fechamento.get('finalidade')}")
    linhas.append(f"Gerado em: {fechamento.get('gerado_em')}")
    linhas.append(f"Status fechamento: {fechamento.get('status_fechamento')}")
    linhas.append("-" * 100)
    linhas.append(f"Dias úteis: {resumo.get('total_dias_uteis')}")
    linhas.append(f"Dias gerados: {resumo.get('total_gerados')}")
    linhas.append(f"Dias pendentes: {resumo.get('total_pendentes')}")
    linhas.append(f"Executivo total: {resumo.get('executivo_total')}")
    linhas.append(f"Monitoramento total: {resumo.get('monitoramento_total')}")
    linhas.append(f"Revisão total: {resumo.get('revisao_total')}")
    linhas.append(f"Suspeitos total: {resumo.get('suspeitos_total')}")
    linhas.append(f"Publicações relevantes total: {resumo.get('publicacoes_relevantes_total')}")
    linhas.append("=" * 100)
    linhas.append("")
    linhas.append("PUBLICAÇÕES RELEVANTES DO MÊS")
    linhas.append("-" * 100)

    if not publicacoes:
        linhas.append("Nenhuma publicação relevante consolidada no mês.")
    else:
        for indice, publicacao in enumerate(publicacoes, start=1):
            titulo = obter_titulo_publicacao(publicacao)
            orgao = obter_orgao_publicacao(publicacao)
            url = obter_url_publicacao(publicacao)
            classificacao = obter_classificacao_publicacao(publicacao)
            data_referencia = normalizar_valor_texto(
                publicacao.get("data_referencia")
            )

            linhas.append(f"#{indice}")
            linhas.append(f"Data: {data_referencia}")
            linhas.append(f"Classificação: {classificacao}")
            linhas.append(f"Título: {titulo}")
            linhas.append(f"Órgão: {orgao}")

            if url:
                linhas.append(f"URL: {url}")

            linhas.append("-" * 100)

    linhas.append("=" * 100)

    return "\n".join(linhas)


def salvar_fechamento_final_txt(fechamento: dict) -> Path:
    referencia = fechamento.get("referencia")

    if not referencia:
        raise ValueError("Fechamento final sem referência mensal.")

    caminho = (
        FECHAMENTO_MENSAL_DIR
        / f"fechamento_{FINALIDADE}_{referencia}.txt"
    )

    caminho.write_text(
        montar_texto_fechamento_final(fechamento),
        encoding="utf-8",
    )

    return caminho


# ============================================================
# IMPRESSÃO
# ============================================================

def imprimir_diagnostico(diagnostico: dict) -> None:
    print("=" * 80)
    print("DIAGNÓSTICO — FECHAMENTO MENSAL INFORMATIVOS")
    print("=" * 80)
    print(f"Referência: {diagnostico['referencia']}")
    print(f"Finalidade: {diagnostico['finalidade']}")
    print(f"Modo simulação: {diagnostico['modo_simulacao']}")
    print(f"Data início: {diagnostico['data_inicio']}")
    print(f"Data fim: {diagnostico['data_fim']}")
    print(f"Status fechamento: {diagnostico['status_fechamento']}")
    print("-" * 80)
    print(f"Dias úteis: {diagnostico['total_dias_uteis']}")
    print(f"Fins de semana ignorados: {diagnostico['total_fins_de_semana_ignorados']}")
    print(f"Gerados: {diagnostico['total_gerados']}")
    print(f"Pendentes: {diagnostico['total_pendentes']}")
    print(f"JSON inválido: {diagnostico['total_json_invalido']}")
    print(f"Sem resumo: {diagnostico['total_sem_resumo']}")
    print("-" * 80)
    print(f"Executivo total: {diagnostico['executivo_total']}")
    print(f"Monitoramento total: {diagnostico['monitoramento_total']}")
    print(f"Revisão total: {diagnostico['revisao_total']}")
    print(f"Suspeitos total: {diagnostico['suspeitos_total']}")
    print(f"Sem match contextual total: {diagnostico['sem_match_contextual_total']}")
    print(f"Publicações relevantes total: {diagnostico['publicacoes_relevantes_total']}")
    print("=" * 80)

    print("DIAS ÚTEIS DO MÊS")
    print("-" * 80)

    for item in diagnostico["dias"]:
        resumo = item.get("resumo", {}) or {}

        linha = (
            f"{item['data']} | "
            f"{item['status']}"
        )

        if item["status"] == "GERADO":
            linha += (
                f" | executivo={valor_resumo(resumo, 'match_executivo')}"
                f" | monitoramento={valor_resumo(resumo, 'monitoramento_setorial')}"
                f" | revisao={valor_resumo(resumo, 'revisao_contextual')}"
                f" | suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos')}"
                f" | publicacoes_relevantes={len(item.get('publicacoes_relevantes', []) or [])}"
            )
        else:
            linha += f" | {item.get('motivo')}"

        print(linha)

    print("=" * 80)

    print("FINS DE SEMANA IGNORADOS")
    print("-" * 80)

    if not diagnostico["fins_de_semana_ignorados"]:
        print("Nenhum.")
    else:
        for data in diagnostico["fins_de_semana_ignorados"]:
            print(f"{data} | IGNORADO_FIM_DE_SEMANA")

    print("=" * 80)


def imprimir_trava(trava: dict) -> None:
    print("=" * 80)
    print("TRAVA DE FECHAMENTO MENSAL FINAL")
    print("=" * 80)
    print(f"Pode gerar fechamento final: {trava.get('pode_gerar')}")
    print(f"Motivo: {trava.get('motivo')}")
    print("=" * 80)


def imprimir_resumo_fechamento_final(fechamento: dict) -> None:
    resumo = fechamento.get("resumo_mensal", {}) or {}

    print("=" * 80)
    print("FECHAMENTO MENSAL FINAL — RESUMO")
    print("=" * 80)
    print(f"Referência: {fechamento.get('referencia')}")
    print(f"Finalidade: {fechamento.get('finalidade')}")
    print(f"Status fechamento: {fechamento.get('status_fechamento')}")
    print("-" * 80)
    print(f"Dias úteis: {resumo.get('total_dias_uteis')}")
    print(f"Gerados: {resumo.get('total_gerados')}")
    print(f"Pendentes: {resumo.get('total_pendentes')}")
    print(f"Executivo total: {resumo.get('executivo_total')}")
    print(f"Monitoramento total: {resumo.get('monitoramento_total')}")
    print(f"Revisão total: {resumo.get('revisao_total')}")
    print(f"Suspeitos total: {resumo.get('suspeitos_total')}")
    print(f"Publicações relevantes total: {resumo.get('publicacoes_relevantes_total')}")
    print("=" * 80)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    ano, mes = resolver_mes_fechamento()

    data_inicio, data_fim = obter_primeiro_ultimo_dia_mes(
        ano=ano,
        mes=mes,
    )

    dias_uteis, fins_de_semana = gerar_dias_mes(
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    diagnostico = consolidar_diagnostico(
        ano=ano,
        mes=mes,
        data_inicio=data_inicio,
        data_fim=data_fim,
        dias_uteis=dias_uteis,
        fins_de_semana=fins_de_semana,
    )

    imprimir_diagnostico(diagnostico)

    caminho_diagnostico = salvar_diagnostico_mensal(diagnostico)

    print(
        "Diagnóstico mensal salvo em: "
        f"{caminho_diagnostico}"
    )

    trava = avaliar_trava_fechamento_final(diagnostico)
    imprimir_trava(trava)

    caminho_diagnostico_txt = salvar_diagnostico_mensal_txt(
        diagnostico=diagnostico,
        trava=trava,
    )

    print(
        "Diagnóstico mensal TXT salvo em: "
        f"{caminho_diagnostico_txt}"
    )

    if not trava.get("pode_gerar"):
        print("Fechamento final não gerado.")
        print("=" * 80)
        return

    fechamento_final = montar_fechamento_final_json(diagnostico)
    caminho_fechamento = salvar_fechamento_final(fechamento_final)
    caminho_fechamento_txt = salvar_fechamento_final_txt(fechamento_final)

    imprimir_resumo_fechamento_final(fechamento_final)

    print(
        "Fechamento mensal final JSON salvo em: "
        f"{caminho_fechamento}"
    )
    print(
        "Fechamento mensal final TXT salvo em: "
        f"{caminho_fechamento_txt}"
    )


if __name__ == "__main__":
    main()
