# ============================================================
# RUNNER — Consolidado Avulso de Informativos por Período
# Item 8.1: consolida relatórios diários já gerados de informativos
# sem executar o DOU e sem depender do fechamento mensal oficial
# ============================================================

import datetime
import json
from pathlib import Path


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# None = usa a data atual.
# Para consolidar uma data específica:
# DATA_INICIO = datetime.date(2026, 5, 14)
# DATA_FIM = datetime.date(2026, 5, 14)
#
# Para consolidar um período:
#DATA_INICIO = datetime.date(2026, 5, 12)
#DATA_FIM = datetime.date(2026, 5, 14)
DATA_INICIO = None
DATA_FIM = None

FINALIDADE = "informativos"

LIMITE_DIAS_PERIODO = 31

# True = gera JSON e TXT normalmente.
# Mantido como configuração para facilitar testes futuros.
GERAR_ARQUIVOS = True


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

CONSOLIDADOS_PERIODO_DIR = (
    DATA_DOU_DIR
    / "consolidados_periodo"
)

CONSOLIDADOS_PERIODO_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FUNÇÕES AUXILIARES — PERÍODO
# ============================================================

def resolver_periodo_execucao() -> tuple[datetime.date, datetime.date]:
    """
    Resolve o período efetivo da consolidação.

    Regra operacional:
    - DATA_INICIO = None e DATA_FIM = None: usa a data atual.
    - Apenas DATA_INICIO preenchida: consolida somente DATA_INICIO.
    - Apenas DATA_FIM preenchida: consolida somente DATA_FIM.
    - Ambas preenchidas: consolida o intervalo informado.
    """

    hoje = datetime.date.today()

    if DATA_INICIO is None and DATA_FIM is None:
        return hoje, hoje

    if DATA_INICIO is not None and DATA_FIM is None:
        return DATA_INICIO, DATA_INICIO

    if DATA_INICIO is None and DATA_FIM is not None:
        return DATA_FIM, DATA_FIM

    return DATA_INICIO, DATA_FIM


def validar_periodo(
    data_inicio: datetime.date,
    data_fim: datetime.date,
    limite_dias: int,
) -> None:
    if data_inicio > data_fim:
        raise ValueError(
            "DATA_INICIO não pode ser maior que DATA_FIM."
        )

    total_dias_corridos = (data_fim - data_inicio).days + 1

    if total_dias_corridos > limite_dias:
        raise ValueError(
            f"Período informado possui {total_dias_corridos} dias corridos. "
            f"O limite máximo permitido é {limite_dias} dias."
        )


def eh_dia_util(data: datetime.date) -> bool:
    # Monday = 0
    # Friday = 4
    # Saturday = 5
    # Sunday = 6
    return data.weekday() < 5


def gerar_datas_periodo(
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


def extrair_publicacoes_relevantes_de_modelo_json(modelo_json: dict) -> list[dict]:
    """
    Busca publicações relevantes em chaves conhecidas do modelo do relatório.
    A função é tolerante a formatos diferentes para não quebrar compatibilidade.
    """

    if not isinstance(modelo_json, dict):
        return []

    chaves_possiveis = [
        "publicacoes_relevantes",
        "publicacoes_executivas",
        "publicacoes_monitoramento_setorial",
        "publicacoes_revisao_contextual",
        "itens_relevantes",
        "registros_relevantes",
    ]

    publicacoes = []

    for chave in chaves_possiveis:
        valor = modelo_json.get(chave)

        if isinstance(valor, list):
            for item in valor:
                if isinstance(item, dict):
                    publicacoes.append(item)

    secoes = modelo_json.get("secoes", {}) or {}

    if isinstance(secoes, dict):
        for chave in chaves_possiveis:
            valor = secoes.get(chave)

            if isinstance(valor, list):
                for item in valor:
                    if isinstance(item, dict):
                        publicacoes.append(item)

    # Remoção simples de duplicados por URL/id/título.
    vistos = set()
    unicas = []

    for item in publicacoes:
        chave = (
            item.get("id_publicacao")
            or item.get("url")
            or item.get("link")
            or item.get("titulo")
            or json.dumps(item, ensure_ascii=False, sort_keys=True)
        )

        if chave in vistos:
            continue

        vistos.add(chave)
        unicas.append(item)

    return unicas


def valor_resumo(resumo: dict, chave: str, padrao=0):
    valor = resumo.get(chave)

    if valor is None:
        return padrao

    return valor


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

    publicacoes_relevantes = extrair_publicacoes_relevantes_de_modelo_json(payload)

    return {
        "data": data.isoformat(),
        "status": "GERADO",
        "motivo": "relatório diário de informativos encontrado",
        "caminho_modelo_json": str(caminho),
        "resumo": resumo,
        "publicacoes_relevantes": publicacoes_relevantes,
    }


# ============================================================
# CONSOLIDAÇÃO
# ============================================================

def consolidar_periodo(
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
    publicacoes_relevantes_mes = []

    for item in diagnosticos_dias:
        if item.get("status") != "GERADO":
            continue

        resumo = item.get("resumo", {}) or {}

        executivo_total += int(valor_resumo(resumo, "match_executivo", 0))
        monitoramento_total += int(valor_resumo(resumo, "monitoramento_setorial", 0))
        revisao_total += int(valor_resumo(resumo, "revisao_contextual", 0))
        suspeitos_total += int(valor_resumo(resumo, "possiveis_falsos_positivos", 0))
        sem_match_contextual_total += int(valor_resumo(resumo, "sem_match_contextual", 0))

        for publicacao in item.get("publicacoes_relevantes", []):
            publicacao_com_data = dict(publicacao)
            publicacao_com_data["data_referencia"] = item.get("data")
            publicacoes_relevantes_mes.append(publicacao_com_data)

    if total_gerados == 0:
        status_consolidado = "SEM_DADOS"
    elif total_pendentes > 0 or total_json_invalido > 0 or total_sem_resumo > 0:
        status_consolidado = "CONSOLIDADO_PARCIAL"
    else:
        status_consolidado = "CONSOLIDADO_COMPLETO"

    return {
        "tipo": "consolidado_avulso_informativos_periodo",
        "versao": "8.1",
        "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "finalidade": FINALIDADE,
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "status_consolidado": status_consolidado,
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
        "publicacoes_relevantes_total": len(publicacoes_relevantes_mes),
        "dias": diagnosticos_dias,
        "fins_de_semana_ignorados": [
            data.isoformat()
            for data in fins_de_semana
        ],
        "publicacoes_relevantes_periodo": publicacoes_relevantes_mes,
    }


# ============================================================
# TXT EXECUTIVO
# ============================================================

def montar_txt_consolidado(consolidado: dict) -> str:
    linhas = []

    linhas.append("=" * 100)
    linhas.append("CONSOLIDADO AVULSO — INFORMATIVOS POR PERÍODO")
    linhas.append("=" * 100)
    linhas.append(f"Data início: {consolidado['data_inicio']}")
    linhas.append(f"Data fim: {consolidado['data_fim']}")
    linhas.append(f"Finalidade: {consolidado['finalidade']}")
    linhas.append(f"Status: {consolidado['status_consolidado']}")
    linhas.append("-" * 100)
    linhas.append(f"Dias úteis: {consolidado['total_dias_uteis']}")
    linhas.append(f"Fins de semana ignorados: {consolidado['total_fins_de_semana_ignorados']}")
    linhas.append(f"Gerados: {consolidado['total_gerados']}")
    linhas.append(f"Pendentes: {consolidado['total_pendentes']}")
    linhas.append(f"JSON inválido: {consolidado['total_json_invalido']}")
    linhas.append(f"Sem resumo: {consolidado['total_sem_resumo']}")
    linhas.append("-" * 100)
    linhas.append(f"Executivo total: {consolidado['executivo_total']}")
    linhas.append(f"Monitoramento total: {consolidado['monitoramento_total']}")
    linhas.append(f"Revisão total: {consolidado['revisao_total']}")
    linhas.append(f"Suspeitos total: {consolidado['suspeitos_total']}")
    linhas.append(f"Sem match contextual total: {consolidado['sem_match_contextual_total']}")
    linhas.append(f"Publicações relevantes total: {consolidado['publicacoes_relevantes_total']}")
    linhas.append("=" * 100)
    linhas.append("")

    linhas.append("DIAS ÚTEIS DO PERÍODO")
    linhas.append("-" * 100)

    for item in consolidado["dias"]:
        resumo = item.get("resumo", {}) or {}
        publicacoes_relevantes = item.get("publicacoes_relevantes", []) or []

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
                f" | publicacoes_relevantes={len(publicacoes_relevantes)}"
            )
        else:
            linha += f" | {item.get('motivo')}"

        linhas.append(linha)

    linhas.append("=" * 100)
    linhas.append("")

    linhas.append("PUBLICAÇÕES RELEVANTES CONSOLIDADAS")
    linhas.append("-" * 100)

    publicacoes = consolidado.get("publicacoes_relevantes_periodo", []) or []

    if not publicacoes:
        linhas.append("Nenhuma publicação relevante no período.")
    else:
        for indice, pub in enumerate(publicacoes, start=1):
            titulo = pub.get("titulo") or pub.get("titulo_publicacao") or ""
            orgao = pub.get("orgao") or pub.get("orgao_publicacao") or ""
            url = pub.get("url") or pub.get("link") or ""
            status = pub.get("status_revisao_contextual") or pub.get("status_match") or ""
            motivo = pub.get("motivo_contextual") or pub.get("motivo") or ""

            linhas.append("-" * 100)
            linhas.append(f"#{indice}")
            linhas.append(f"Data referência: {pub.get('data_referencia')}")
            linhas.append(f"Título: {titulo}")
            linhas.append(f"Órgão: {orgao}")
            linhas.append(f"Status: {status}")
            linhas.append(f"Motivo: {motivo}")
            linhas.append(f"URL: {url}")

    linhas.append("=" * 100)
    linhas.append("")

    linhas.append("FINS DE SEMANA IGNORADOS")
    linhas.append("-" * 100)

    if not consolidado["fins_de_semana_ignorados"]:
        linhas.append("Nenhum.")
    else:
        for data in consolidado["fins_de_semana_ignorados"]:
            linhas.append(f"{data} | IGNORADO_FIM_DE_SEMANA")

    linhas.append("=" * 100)

    return "\n".join(linhas)


# ============================================================
# SALVAMENTO
# ============================================================

def montar_nome_base_arquivo(consolidado: dict) -> str:
    return (
        f"consolidado_{FINALIDADE}_"
        f"{consolidado['data_inicio']}_a_{consolidado['data_fim']}"
    )


def salvar_consolidado_json(consolidado: dict) -> Path:
    caminho = CONSOLIDADOS_PERIODO_DIR / f"{montar_nome_base_arquivo(consolidado)}.json"

    caminho.write_text(
        json.dumps(
            consolidado,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return caminho


def salvar_consolidado_txt(consolidado: dict) -> Path:
    caminho = CONSOLIDADOS_PERIODO_DIR / f"{montar_nome_base_arquivo(consolidado)}.txt"

    caminho.write_text(
        montar_txt_consolidado(consolidado),
        encoding="utf-8",
    )

    return caminho


# ============================================================
# IMPRESSÃO
# ============================================================

def imprimir_consolidado(consolidado: dict) -> None:
    print("=" * 80)
    print("CONSOLIDADO AVULSO — INFORMATIVOS POR PERÍODO")
    print("=" * 80)
    print(f"Data início: {consolidado['data_inicio']}")
    print(f"Data fim: {consolidado['data_fim']}")
    print(f"Status: {consolidado['status_consolidado']}")
    print("-" * 80)
    print(f"Dias úteis: {consolidado['total_dias_uteis']}")
    print(f"Fins de semana ignorados: {consolidado['total_fins_de_semana_ignorados']}")
    print(f"Gerados: {consolidado['total_gerados']}")
    print(f"Pendentes: {consolidado['total_pendentes']}")
    print(f"JSON inválido: {consolidado['total_json_invalido']}")
    print(f"Sem resumo: {consolidado['total_sem_resumo']}")
    print("-" * 80)
    print(f"Executivo total: {consolidado['executivo_total']}")
    print(f"Monitoramento total: {consolidado['monitoramento_total']}")
    print(f"Revisão total: {consolidado['revisao_total']}")
    print(f"Suspeitos total: {consolidado['suspeitos_total']}")
    print(f"Publicações relevantes total: {consolidado['publicacoes_relevantes_total']}")
    print("=" * 80)

    print("DIAS ÚTEIS DO PERÍODO")
    print("-" * 80)

    for item in consolidado["dias"]:
        resumo = item.get("resumo", {}) or {}
        publicacoes_relevantes = item.get("publicacoes_relevantes", []) or []

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
                f" | publicacoes_relevantes={len(publicacoes_relevantes)}"
            )
        else:
            linha += f" | {item.get('motivo')}"

        print(linha)

    print("=" * 80)


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    data_inicio, data_fim = resolver_periodo_execucao()

    validar_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        limite_dias=LIMITE_DIAS_PERIODO,
    )

    dias_uteis, fins_de_semana = gerar_datas_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    consolidado = consolidar_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        dias_uteis=dias_uteis,
        fins_de_semana=fins_de_semana,
    )

    imprimir_consolidado(consolidado)

    if not GERAR_ARQUIVOS:
        print("GERAR_ARQUIVOS=False. Nenhum arquivo foi salvo.")
        return

    caminho_json = salvar_consolidado_json(consolidado)
    caminho_txt = salvar_consolidado_txt(consolidado)

    print(f"Consolidado JSON salvo em: {caminho_json}")
    print(f"Consolidado TXT salvo em: {caminho_txt}")


if __name__ == "__main__":
    main()
