# ============================================================
# RUNNER â€” Orquestrador DOU por PerÃ­odo
# Etapa 3.6: data atual por padrÃ£o, perÃ­odo manual opcional,
# ignora fins de semana, identifica dias/finalidades jÃ¡ gerados,
# agrupa execuÃ§Ãµes por data, executa busca/base DOU uma Ãºnica vez,
# processa mÃºltiplas finalidades sobre a mesma base, salva resumo
# operacional consolidado do perÃ­odo e dispara e-mail diÃ¡rio apenas
# para a finalidade dou_diario
# ============================================================

import asyncio
import datetime
import json
import traceback
from pathlib import Path

from backend.orquestradores.orquestrador_dou import (
    executar_pipeline_dou_multifinalidade,
)
from backend.services.email_dou_diario_service import (
    enviar_email_dou_diario,
)
from backend.runners.run_sincronizacao_processos_incremental_2026 import (
    executar as executar_sincronizacao_processos_incremental,
)
from backend.runners.run_pesquisa_processos_incremental_dou_2026 import (
    caminho_resultado_json as caminho_resultado_processos_dou_json,
    executar as executar_pesquisa_processos_incremental_dou,
)
from backend.runners.run_descoberta_documentos_anvisa_incremental_2026 import (
    executar as executar_descoberta_documentos_anvisa_incremental,
)
from backend.runners.run_processamento_documentos_anvisa_incremental_2026 import (
    caminho_resultado_json as caminho_resultado_processos_anvisa_json,
    executar as executar_processamento_documentos_anvisa_incremental,
)
from backend.runners.run_revisao_historica_processos_pendentes_2026 import (
    CAMINHO_JSON as CAMINHO_RESULTADO_HISTORICO_PROCESSOS,
)
from backend.services.controle_email_processos_service import (
    marcar_ocorrencias_comunicadas,
    obter_ocorrencias_pendentes,
    registrar_falha_envio,
    registrar_ocorrencias_pendentes,
)


# ============================================================
# CONFIGURAÃ‡ÃƒO
# ============================================================

# None = usa a data atual.
# Para rodar perÃ­odo especÃ­fico, altere manualmente, por exemplo:
#DATA_INICIO = datetime.date(2026, 4, 23)
#DATA_FIM = datetime.date(2026, 4, 30)
DATA_INICIO = None
DATA_FIM = None

FINALIDADES_CONFIG = [
    "dou_diario",
    "informativos",
]

LIMITE_DIAS_PERIODO = 31

# True = apenas lista o que seria processado
# False = executa o pipeline nos itens pendentes
MODO_SIMULACAO = False

# False = nÃ£o reprocessa data/finalidade jÃ¡ gerada
# True = reprocessa match/auditoria/relatÃ³rio das finalidades jÃ¡ geradas
# ObservaÃ§Ã£o: nÃ£o forÃ§a nova busca/extraÃ§Ã£o/base do DOU.
FORCAR_REPROCESSAMENTO = False

# False = reaproveita links/publicaÃ§Ãµes/base do DOU quando jÃ¡ existirem
# True = refaz busca, extraÃ§Ã£o e base da data uma Ãºnica vez
# Usar True somente quando houver necessidade real de reconstruir a base fonte.
FORCAR_REPROCESSAMENTO_BASE = False

# None = todas as pÃ¡ginas
MAX_PAGINAS = None

# None = todas as publicaÃ§Ãµes
LIMITE_PUBLICACOES = None

# False = visual
# True = headless
HEADLESS = False

# Executa retenÃ§Ã£o automÃ¡tica apenas no Ãºltimo item efetivamente executado
EXECUTAR_LIMPEZA = True

# True = apenas simula limpeza
# False = remove arquivos antigos
LIMPEZA_MODO_SIMULACAO = True

# True = apÃ³s execuÃ§Ã£o bem-sucedida da finalidade dou_diario,
# simula/envia o e-mail diÃ¡rio usando email_dou_diario_service.py.
# A finalidade informativos nunca envia e-mail diÃ¡rio.
ENVIAR_EMAIL_DOU_DIARIO = True

# None = respeita EMAIL_MODO_SIMULACAO do email_service.py.
# True = forÃ§a simulaÃ§Ã£o do e-mail.
# False = permite envio real, desde que EMAIL_USER/EMAIL_PASS estejam configurados.
EMAIL_DOU_DIARIO_MODO_SIMULACAO = False

# False = se o pipeline rodar com sucesso, mas o e-mail falhar,
# registra o erro do e-mail no status tÃ©cnico e continua o perÃ­odo.
FALHAR_EXECUCAO_SE_EMAIL_FALHAR = False

# True = ativa o novo fluxo incremental de processos:
# - sincroniza a planilha e revisa o histórico apenas de processos novos;
# - pesquisa processos ativos somente na base DOU da data gerada;
# - descobre e processa somente documentos novos da Anvisa.
EXECUTAR_MONITORAMENTO_INCREMENTAL_PROCESSOS = True

# False = falha no monitoramento incremental não invalida o DOU diário.
# O erro fica registrado no resumo/status técnico para nova tentativa.
FALHAR_EXECUCAO_SE_MONITORAMENTO_PROCESSOS_FALHAR = False


# ============================================================
# CAMINHOS
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DOU_DIR = ROOT_DIR / "backend" / "data" / "dou"
RELATORIOS_BASE_DIR = DATA_DOU_DIR / "relatorios"
LOGS_EXECUCAO_DIR = DATA_DOU_DIR / "logs_execucao"
PERIODOS_DIR = DATA_DOU_DIR / "periodos"

LOGS_EXECUCAO_DIR.mkdir(parents=True, exist_ok=True)
PERIODOS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# FUNÃ‡Ã•ES AUXILIARES â€” PERÃODO
# ============================================================

def resolver_periodo_execucao() -> tuple[datetime.date, datetime.date]:
    """
    Resolve o perÃ­odo efetivo da execuÃ§Ã£o.

    Regra operacional:
    - DATA_INICIO = None e DATA_FIM = None: usa a data atual.
    - Apenas DATA_INICIO preenchida: roda somente DATA_INICIO.
    - Apenas DATA_FIM preenchida: roda somente DATA_FIM.
    - Ambas preenchidas: roda o intervalo informado.
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
            "DATA_INICIO nÃ£o pode ser maior que DATA_FIM."
        )

    total_dias_corridos = (data_fim - data_inicio).days + 1

    if total_dias_corridos > limite_dias:
        raise ValueError(
            f"PerÃ­odo informado possui {total_dias_corridos} dias corridos. "
            f"O limite mÃ¡ximo permitido Ã© {limite_dias} dias."
        )


def eh_dia_util(data: datetime.date) -> bool:
    # Monday = 0
    # Tuesday = 1
    # Wednesday = 2
    # Thursday = 3
    # Friday = 4
    # Saturday = 5
    # Sunday = 6
    return data.weekday() < 5


def gerar_datas_periodo(
    data_inicio: datetime.date,
    data_fim: datetime.date,
) -> tuple[list[datetime.date], list[datetime.date]]:
    datas_uteis = []
    datas_ignoradas = []

    data_atual = data_inicio

    while data_atual <= data_fim:
        if eh_dia_util(data_atual):
            datas_uteis.append(data_atual)
        else:
            datas_ignoradas.append(data_atual)

        data_atual += datetime.timedelta(days=1)

    return datas_uteis, datas_ignoradas


# ============================================================
# FUNÃ‡Ã•ES AUXILIARES â€” CONTROLE DE GERAÃ‡ÃƒO
# ============================================================

def montar_caminho_modelo_relatorio(
    data_execucao: datetime.date,
    finalidade: str,
) -> Path:
    data_txt = data_execucao.isoformat()

    return (
        RELATORIOS_BASE_DIR
        / finalidade
        / f"relatorio_executivo_modelo_{data_txt}.json"
    )


def montar_caminho_txt_relatorio(
    data_execucao: datetime.date,
    finalidade: str,
) -> Path:
    data_txt = data_execucao.isoformat()

    return (
        RELATORIOS_BASE_DIR
        / finalidade
        / f"relatorio_executivo_{data_txt}.txt"
    )


def arquivo_json_valido(caminho: Path) -> bool:
    if not caminho.exists():
        return False

    try:
        json.loads(caminho.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def verificar_status_geracao(
    data_execucao: datetime.date,
    finalidade: str,
) -> dict:
    caminho_modelo_json = montar_caminho_modelo_relatorio(
        data_execucao=data_execucao,
        finalidade=finalidade,
    )

    caminho_relatorio_txt = montar_caminho_txt_relatorio(
        data_execucao=data_execucao,
        finalidade=finalidade,
    )

    existe_modelo_json = caminho_modelo_json.exists()
    existe_relatorio_txt = caminho_relatorio_txt.exists()
    modelo_json_valido = arquivo_json_valido(caminho_modelo_json)

    if modelo_json_valido and existe_relatorio_txt:
        status = "JA_GERADO"

    elif existe_modelo_json and not modelo_json_valido:
        status = "ARQUIVO_JSON_INVALIDO"

    elif existe_modelo_json or existe_relatorio_txt:
        status = "GERACAO_INCOMPLETA"

    else:
        status = "AGUARDANDO_PROCESSAMENTO"

    if status == "JA_GERADO" and FORCAR_REPROCESSAMENTO:
        status = "REPROCESSAMENTO_SOLICITADO"

    resumo_relatorio = {}

    if modelo_json_valido:
        resumo_relatorio = carregar_resumo_relatorio_existente(
            caminho_modelo_json
        )

    return {
        "data": data_execucao.isoformat(),
        "data_obj": data_execucao,
        "finalidade": finalidade,
        "status": status,
        "existe_modelo_json": existe_modelo_json,
        "existe_relatorio_txt": existe_relatorio_txt,
        "modelo_json_valido": modelo_json_valido,
        "caminho_modelo_json": str(caminho_modelo_json),
        "caminho_relatorio_txt": str(caminho_relatorio_txt),
        "resumo_relatorio": resumo_relatorio,
    }


def montar_planejamento_execucao(
    data_inicio: datetime.date,
    data_fim: datetime.date,
    datas_uteis: list[datetime.date],
    datas_ignoradas: list[datetime.date],
) -> dict:
    itens_processamento = []

    for data in datas_uteis:
        for finalidade in FINALIDADES_CONFIG:
            status = verificar_status_geracao(
                data_execucao=data,
                finalidade=finalidade,
            )
            itens_processamento.append(status)

    itens_ignorados = [
        {
            "data": data.isoformat(),
            "status": "IGNORADO_FIM_DE_SEMANA",
        }
        for data in datas_ignoradas
    ]

    return {
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "finalidades": FINALIDADES_CONFIG,
        "modo_simulacao": MODO_SIMULACAO,
        "forcar_reprocessamento": FORCAR_REPROCESSAMENTO,
        "forcar_reprocessamento_base": FORCAR_REPROCESSAMENTO_BASE,
        "total_dias_uteis": len(datas_uteis),
        "total_fins_de_semana_ignorados": len(datas_ignoradas),
        "itens_processamento": itens_processamento,
        "itens_ignorados": itens_ignorados,
    }


def deve_executar_item(item: dict) -> bool:
    status = item.get("status")

    return status in {
        "AGUARDANDO_PROCESSAMENTO",
        "GERACAO_INCOMPLETA",
        "ARQUIVO_JSON_INVALIDO",
        "REPROCESSAMENTO_SOLICITADO",
    }


def remover_objetos_nao_serializaveis(payload: dict) -> dict:
    """
    Remove objetos datetime.date usados internamente antes de salvar JSON.
    """

    payload_limpo = json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        )
    )

    return payload_limpo


# ============================================================
# FUNÃ‡Ã•ES AUXILIARES â€” RESUMO CONTEXTUAL
# ============================================================

def carregar_json_seguro(caminho: str | Path | None) -> dict:
    if not caminho:
        return {}

    caminho_path = Path(caminho)

    if not caminho_path.exists():
        return {}

    try:
        return json.loads(caminho_path.read_text(encoding="utf-8"))
    except Exception as erro:
        print(f"[AVISO] NÃ£o foi possÃ­vel ler JSON: {caminho_path} | {erro}")
        return {}


def extrair_resumo_de_modelo_json(modelo_json: dict) -> dict:
    """
    Extrai resumo executivo/contextual do modelo JSON do relatÃ³rio.

    MantÃ©m compatibilidade com dois formatos jÃ¡ usados no projeto:
    - modelo_json["resumo_executivo"]
    - modelo_json["resumo_executivo_consolidado"]["visao_geral"]
    """

    if not isinstance(modelo_json, dict):
        return {}

    resumo_modelo = modelo_json.get("resumo_executivo", {}) or {}

    if isinstance(resumo_modelo, dict) and resumo_modelo:
        return resumo_modelo

    consolidado = modelo_json.get("resumo_executivo_consolidado", {}) or {}

    if isinstance(consolidado, dict):
        visao_geral = consolidado.get("visao_geral", {}) or {}

        if isinstance(visao_geral, dict) and visao_geral:
            return visao_geral

    return {}


def carregar_resumo_relatorio_existente(caminho_modelo_json: str | Path | None) -> dict:
    modelo_json = carregar_json_seguro(caminho_modelo_json)

    return extrair_resumo_de_modelo_json(modelo_json)


def formatar_resumo_contextual(resumo: dict) -> str:
    if not isinstance(resumo, dict) or not resumo:
        return ""

    executivo = resumo.get("match_executivo")
    monitoramento = resumo.get("monitoramento_setorial")
    revisao = resumo.get("revisao_contextual")
    sem_match_contextual = resumo.get("sem_match_contextual")
    suspeitos = resumo.get("possiveis_falsos_positivos")

    if executivo is not None or monitoramento is not None or revisao is not None:
        partes = [
            f"executivo={valor_resumo(resumo, 'match_executivo')}",
            f"monitoramento={valor_resumo(resumo, 'monitoramento_setorial')}",
            f"revisao={valor_resumo(resumo, 'revisao_contextual')}",
        ]

        if sem_match_contextual is not None:
            partes.append(
                f"sem_match_contextual={valor_resumo(resumo, 'sem_match_contextual')}"
            )

        partes.append(
            f"suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos')}"
        )

        return " | ".join(partes)

    com_match = resumo.get("com_match")

    if com_match is not None or suspeitos is not None:
        return (
            f"matches={valor_resumo(resumo, 'com_match', com_match)} | "
            f"suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos', suspeitos)}"
        )

    return ""


def obter_resumo_modelo_relatorio(resultado: dict) -> dict:
    resumo_orquestrador = resultado.get("resultado", {}) or {}

    if not isinstance(resumo_orquestrador, dict):
        return {}

    relatorio = resumo_orquestrador.get("relatorio_executivo", {}) or {}
    caminho_modelo_json = relatorio.get("modelo_json")

    modelo_json = carregar_json_seguro(caminho_modelo_json)

    return extrair_resumo_de_modelo_json(modelo_json)


def obter_resumo_expandido_resultado(resultado: dict) -> dict:
    """
    O orquestrador pode retornar resumo antigo em resultado["resultado"].
    O relatÃ³rio modelo JSON contÃ©m o resumo contextual completo.
    Esta funÃ§Ã£o combina os dois sem quebrar compatibilidade.
    """

    resumo_orquestrador = resultado.get("resultado", {}) or {}

    if not isinstance(resumo_orquestrador, dict):
        resumo_orquestrador = {}

    resumo_modelo = obter_resumo_modelo_relatorio(resultado)

    resumo_expandido = dict(resumo_orquestrador)
    resumo_expandido.update(resumo_modelo)

    return resumo_expandido


def valor_resumo(resumo: dict, chave: str, padrao=0):
    valor = resumo.get(chave)

    if valor is None:
        return padrao

    return valor


def converter_numero(valor, padrao=0):
    if valor is None:
        return padrao

    try:
        return int(valor)
    except Exception:
        pass

    try:
        return int(float(valor))
    except Exception:
        return padrao


# ============================================================
# IMPRESSÃƒO
# ============================================================

def imprimir_resumo_status(itens: list[dict]) -> None:
    total_ja_gerado = sum(
        1 for item in itens
        if item.get("status") == "JA_GERADO"
    )

    total_aguardando = sum(
        1 for item in itens
        if item.get("status") == "AGUARDANDO_PROCESSAMENTO"
    )

    total_reprocessamento = sum(
        1 for item in itens
        if item.get("status") == "REPROCESSAMENTO_SOLICITADO"
    )

    total_incompleto = sum(
        1 for item in itens
        if item.get("status") == "GERACAO_INCOMPLETA"
    )

    total_json_invalido = sum(
        1 for item in itens
        if item.get("status") == "ARQUIVO_JSON_INVALIDO"
    )

    total_a_executar = sum(
        1 for item in itens
        if deve_executar_item(item)
    )

    print("RESUMO DO CONTROLE DE GERAÃ‡ÃƒO")
    print("-" * 80)
    print(f"JÃ¡ gerados: {total_ja_gerado}")
    print(f"Aguardando processamento: {total_aguardando}")
    print(f"Reprocessamento solicitado: {total_reprocessamento}")
    print(f"GeraÃ§Ã£o incompleta: {total_incompleto}")
    print(f"JSON invÃ¡lido: {total_json_invalido}")
    print(f"Itens que serÃ£o executados: {total_a_executar}")
    print("=" * 80)


def imprimir_planejamento(planejamento: dict) -> None:
    itens_processamento = planejamento["itens_processamento"]
    itens_ignorados = planejamento["itens_ignorados"]

    print("=" * 80)
    print("PLANEJAMENTO DE EXECUÃ‡ÃƒO POR PERÃODO")
    print("=" * 80)
    print(f"Data inÃ­cio: {planejamento['data_inicio']}")
    print(f"Data fim: {planejamento['data_fim']}")
    print(f"Finalidades: {planejamento['finalidades']}")
    print(f"Modo simulaÃ§Ã£o: {planejamento['modo_simulacao']}")
    print(f"ForÃ§ar reprocessamento finalidades: {planejamento['forcar_reprocessamento']}")
    print(f"ForÃ§ar reprocessamento base DOU: {planejamento.get('forcar_reprocessamento_base')}")
    print("-" * 80)
    print(f"Total de dias Ãºteis para processar: {planejamento['total_dias_uteis']}")
    print(
        "Total de fins de semana ignorados: "
        f"{planejamento['total_fins_de_semana_ignorados']}"
    )
    print("=" * 80)

    imprimir_resumo_status(itens_processamento)

    print("DIAS ÃšTEIS / FINALIDADES")
    print("-" * 80)

    for item in itens_processamento:
        acao = "EXECUTAR" if deve_executar_item(item) else "PULAR"
        resumo_txt = formatar_resumo_contextual(
            item.get("resumo_relatorio", {})
        )

        linha = (
            f"{item['data']} | "
            f"{item['finalidade']} | "
            f"{item['status']} | "
            f"{acao}"
        )

        if resumo_txt:
            linha = f"{linha} | {resumo_txt}"

        print(linha)

    print("=" * 80)
    print("DIAS IGNORADOS POR FIM DE SEMANA")
    print("-" * 80)

    if not itens_ignorados:
        print("Nenhum sÃ¡bado/domingo no perÃ­odo.")
    else:
        for item in itens_ignorados:
            print(
                f"{item['data']} | {item['status']} | PULAR"
            )

    print("=" * 80)


def imprimir_resumo_execucao(resultados_execucao: list[dict]) -> None:
    print("=" * 80)
    print("RESUMO DA EXECUÃ‡ÃƒO REAL POR PERÃODO")
    print("=" * 80)

    if not resultados_execucao:
        print("Nenhum item foi executado.")
        print("=" * 80)
        return

    for item in resultados_execucao:
        data = item.get("data")
        finalidade = item.get("finalidade")
        status = item.get("status_execucao")
        status_original = item.get("status_original")

        resultado = item.get("resultado") or {}
        resumo = obter_resumo_expandido_resultado(resultado) if isinstance(resultado, dict) else {}

        com_match = resumo.get("com_match")
        executivo = resumo.get("match_executivo")
        monitoramento = resumo.get("monitoramento_setorial")
        revisao = resumo.get("revisao_contextual")
        sem_match_contextual = resumo.get("sem_match_contextual")
        suspeitos = resumo.get("possiveis_falsos_positivos")

        partes = [
            f"{data}",
            finalidade,
            f"origem={status_original}",
            f"execucao={status}",
        ]

        if executivo is not None or monitoramento is not None or revisao is not None:
            partes.extend([
                f"executivo={valor_resumo(resumo, 'match_executivo')}",
                f"monitoramento={valor_resumo(resumo, 'monitoramento_setorial')}",
                f"revisao={valor_resumo(resumo, 'revisao_contextual')}",
            ])

            if sem_match_contextual is not None:
                partes.append(
                    f"sem_match_contextual={valor_resumo(resumo, 'sem_match_contextual')}"
                )

            partes.append(
                f"suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos')}"
            )
        else:
            partes.extend([
                f"matches={valor_resumo(resumo, 'com_match', com_match)}",
                f"suspeitos={valor_resumo(resumo, 'possiveis_falsos_positivos', suspeitos)}",
            ])

        monitoramento_processos = item.get(
            "monitoramento_processos_dou_incremental"
        )

        if (
            isinstance(monitoramento_processos, dict)
            and monitoramento_processos.get("status")
        ):
            partes.append(
                "processos_dou_incremental="
                f"{monitoramento_processos.get('status')}"
            )

        email_dou = item.get("email_dou_diario")

        if isinstance(email_dou, dict) and email_dou.get("status"):
            partes.append(f"email_dou_diario={email_dou.get('status')}")

        print(" | ".join(str(p) for p in partes))

    print("=" * 80)


def imprimir_resumo_periodo(resumo_periodo: dict) -> None:
    print("=" * 80)
    print("RESUMO OPERACIONAL CONSOLIDADO DO PERÃODO")
    print("=" * 80)
    print(f"Data inÃ­cio: {resumo_periodo.get('data_inicio')}")
    print(f"Data fim: {resumo_periodo.get('data_fim')}")
    print(f"Total de dias Ãºteis: {resumo_periodo.get('total_dias_uteis')}")
    print(f"Fins de semana ignorados: {resumo_periodo.get('total_fins_de_semana_ignorados')}")
    print("-" * 80)
    print(f"Total de itens: {resumo_periodo.get('total_itens')}")
    print(f"JÃ¡ gerados: {resumo_periodo.get('ja_gerados')}")
    print(f"Executados: {resumo_periodo.get('executados')}")
    print(f"Pendentes: {resumo_periodo.get('pendentes')}")
    print(f"Erros: {resumo_periodo.get('erros')}")
    print("-" * 80)
    print(f"Executivo total: {resumo_periodo.get('executivo_total')}")
    print(f"Monitoramento total: {resumo_periodo.get('monitoramento_total')}")
    print(f"RevisÃ£o total: {resumo_periodo.get('revisao_total')}")
    print(f"Suspeitos total: {resumo_periodo.get('suspeitos_total')}")
    print("=" * 80)


# ============================================================
# CONTROLE DE OCORRÊNCIAS — PROCESSOS / E-MAIL
# ============================================================

def extrair_resultados_monitoramento(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []

    payload = carregar_json_seguro(caminho)
    resultados = payload.get("resultados", [])

    if not isinstance(resultados, list):
        return []

    return [
        item
        for item in resultados
        if isinstance(item, dict)
    ]


def registrar_resultados_monitoramento_seguro(
    *,
    caminho: Path,
    etapa: str,
) -> dict:
    """
    Registra resultados no controle de e-mail sem invalidar o DOU diário.

    A ocorrência permanece pendente até confirmação de envio real.
    """

    try:
        resultados = extrair_resultados_monitoramento(caminho)

        if not resultados:
            return {
                "status": "SEM_RESULTADOS_PARA_REGISTRAR",
                "etapa": etapa,
                "arquivo_resultado": str(caminho),
                "resultados_lidos": 0,
            }

        resultados_enriquecidos = []

        for item in resultados:
            ocorrencia = dict(item)
            ocorrencia["origem_fluxo"] = etapa
            resultados_enriquecidos.append(ocorrencia)

        controle = registrar_ocorrencias_pendentes(
            resultados_enriquecidos
        )

        return {
            "status": controle.get("status"),
            "etapa": etapa,
            "arquivo_resultado": str(caminho),
            "resultados_lidos": len(resultados_enriquecidos),
            "novas": len(controle.get("novas", []) or []),
            "ja_pendentes": len(
                controle.get("ja_pendentes", []) or []
            ),
            "ja_comunicadas": len(
                controle.get("ja_comunicadas", []) or []
            ),
            "total_pendentes": controle.get("total_pendentes"),
            "caminho_controle": controle.get("caminho_controle"),
        }

    except Exception as erro:
        traceback_texto = traceback.format_exc()
        nome_etapa = "".join(
            caractere
            if caractere.isalnum()
            else "_"
            for caractere in str(etapa).lower()
        )
        erro_path = (
            LOGS_EXECUCAO_DIR
            / f"erro_registro_email_processos_{nome_etapa}.txt"
        )
        erro_path.write_text(traceback_texto, encoding="utf-8")

        resultado_erro = {
            "status": "ERRO_REGISTRO_CONTROLE_EMAIL",
            "etapa": etapa,
            "arquivo_resultado": str(caminho),
            "erro": str(erro),
            "traceback_path": str(erro_path),
        }

        if FALHAR_EXECUCAO_SE_MONITORAMENTO_PROCESSOS_FALHAR:
            raise

        return resultado_erro


def registrar_historico_novos_processos_seguro(
    resultado_sincronizacao: dict,
) -> dict:
    status = str(
        resultado_sincronizacao.get("status") or ""
    ).upper()
    processos_revisados = (
        resultado_sincronizacao.get(
            "processos_historicos_pendentes",
            [],
        )
        or []
    )

    if status != "SUCESSO" or not processos_revisados:
        return {
            "status": "IGNORADO_SEM_NOVO_HISTORICO_CONCLUIDO",
            "processos_revisados": len(processos_revisados),
        }

    return registrar_resultados_monitoramento_seguro(
        caminho=CAMINHO_RESULTADO_HISTORICO_PROCESSOS,
        etapa="HISTORICO_PROCESSO_NOVO",
    )


def obter_chaves_pendentes_email() -> list[str]:
    chaves = []

    for ocorrencia in obter_ocorrencias_pendentes():
        chave = str(
            ocorrencia.get("chave_email") or ""
        ).strip()

        if chave and chave not in chaves:
            chaves.append(chave)

    return chaves


def status_email_confirma_envio_real(resultado_email: dict) -> bool:
    status = str(
        resultado_email.get("status") or ""
    ).strip().upper()

    return status == "ENVIADO"


# ============================================================
# ENVIO DE E-MAIL â€” DOU DIÃRIO
# ============================================================

def execucao_pipeline_sucesso(resultado: dict) -> bool:
    status = str(resultado.get("status", "")).strip().upper()

    return status == "SUCESSO"


def deve_enviar_email_para_item(
    finalidade: str,
    resultado: dict,
) -> bool:
    if not ENVIAR_EMAIL_DOU_DIARIO:
        return False

    if finalidade != "dou_diario":
        return False

    return execucao_pipeline_sucesso(resultado)


def tentar_enviar_email_dou_diario_item(
    data_execucao: datetime.date,
    finalidade: str,
    resultado: dict,
) -> dict | None:
    """
    Envia o e-mail diário e confirma as ocorrências somente após status ENVIADO.

    Falha de SMTP, Cloudflare ou montagem:
    - não remove ocorrências pendentes;
    - registra a tentativa para nova execução.
    """

    if finalidade != "dou_diario":
        return None

    if not ENVIAR_EMAIL_DOU_DIARIO:
        return {
            "status": "DESABILITADO",
            "mensagem": "Envio de e-mail dou_diario desabilitado no runner.",
        }

    if not execucao_pipeline_sucesso(resultado):
        return {
            "status": "IGNORADO_STATUS_NAO_SUCESSO",
            "status_execucao": resultado.get("status"),
            "mensagem": (
                "E-mail não enviado porque a execução "
                "não retornou SUCESSO."
            ),
        }

    chaves_tentativa = obter_chaves_pendentes_email()

    print("=" * 80)
    print("ENVIO DE E-MAIL — DOU DIÁRIO + PROCESSOS")
    print("=" * 80)
    print(f"Data: {data_execucao.isoformat()}")
    print("Finalidade: dou_diario")
    print(
        "Ocorrências de processos pendentes antes do envio: "
        f"{len(chaves_tentativa)}"
    )
    print("Modo de e-mail: ENVIO REAL")
    print("=" * 80)

    try:
        resultado_email = enviar_email_dou_diario(
            data_execucao=data_execucao,
            modo_simulacao=EMAIL_DOU_DIARIO_MODO_SIMULACAO,
        )

        chaves_incluidas = [
            str(chave)
            for chave in (
                resultado_email.get(
                    "chaves_ocorrencias_processos_incluidas",
                    [],
                )
                or []
            )
            if str(chave).strip()
        ]

        controle_email = {
            "status": "SEM_OCORRENCIAS_DE_PROCESSOS_NO_EMAIL",
            "ocorrencias": 0,
        }

        if status_email_confirma_envio_real(resultado_email):
            if chaves_incluidas:
                controle_email = marcar_ocorrencias_comunicadas(
                    chaves_incluidas,
                    data_email=data_execucao.isoformat(),
                    status_email="ENVIADO",
                )
        elif chaves_incluidas:
            controle_email = registrar_falha_envio(
                chaves_incluidas,
                erro=(
                    "O serviço de e-mail não confirmou envio real. "
                    f"Status retornado: {resultado_email.get('status')}"
                ),
            )

        resultado_email["controle_email_processos"] = controle_email

        print("=" * 80)
        print("RESULTADO DO E-MAIL — DOU DIÁRIO + PROCESSOS")
        print("=" * 80)
        print(f"Status e-mail: {resultado_email.get('status')}")
        print(
            "Quantidade total de publicações: "
            f"{resultado_email.get('quantidade_publicacoes')}"
        )
        print(
            "Ocorrências de processos incluídas: "
            f"{len(chaves_incluidas)}"
        )
        print(
            "Ocorrências confirmadas como comunicadas: "
            f"{controle_email.get('ocorrencias_movidas', 0)}"
        )
        print("=" * 80)

        return resultado_email

    except Exception as erro:
        traceback_texto = traceback.format_exc()

        erro_path = (
            LOGS_EXECUCAO_DIR
            / f"erro_email_dou_diario_{data_execucao.isoformat()}.txt"
        )
        erro_path.write_text(traceback_texto, encoding="utf-8")

        controle_email = {
            "status": "SEM_OCORRENCIAS_PENDENTES",
            "ocorrencias_atualizadas": 0,
        }

        if chaves_tentativa:
            try:
                controle_email = registrar_falha_envio(
                    chaves_tentativa,
                    erro=str(erro),
                )
            except Exception as erro_controle:
                controle_email = {
                    "status": "ERRO_AO_REGISTRAR_FALHA_EMAIL",
                    "erro": str(erro_controle),
                }

        resultado_erro = {
            "status": "ERRO_EMAIL",
            "data": data_execucao.isoformat(),
            "finalidade": finalidade,
            "erro": str(erro),
            "traceback_path": str(erro_path),
            "controle_email_processos": controle_email,
        }

        print("=" * 80)
        print("ERRO NO ENVIO DO E-MAIL — DOU DIÁRIO")
        print("=" * 80)
        print(f"Data: {data_execucao.isoformat()}")
        print(f"Erro: {erro}")
        print(
            "As ocorrências de processos permanecem pendentes "
            "para nova tentativa."
        )
        print(f"Traceback: {erro_path}")
        print("=" * 80)

        if FALHAR_EXECUCAO_SE_EMAIL_FALHAR:
            raise

        return resultado_erro


# ============================================================
# MONITORAMENTO INCREMENTAL DE PROCESSOS — EXECUÇÃO SEGURA
# ============================================================

async def executar_sincronizacao_processos_incremental_segura() -> dict:
    """
    Sincroniza a planilha com o controle e revisa o histórico somente dos
    processos novos. Processos já ativos não têm o acervo anual reprocessado.
    """

    if not EXECUTAR_MONITORAMENTO_INCREMENTAL_PROCESSOS:
        return {
            "status": "DESABILITADO",
            "mensagem": "Monitoramento incremental desabilitado no runner.",
        }

    print("=" * 80)
    print("SINCRONIZAÇÃO INCREMENTAL DE PROCESSOS")
    print("=" * 80)

    try:
        resultado = await asyncio.to_thread(
            executar_sincronizacao_processos_incremental
        )
        resultado["controle_email_historico"] = (
            registrar_historico_novos_processos_seguro(
                resultado
            )
        )
        return resultado

    except Exception as erro:
        traceback_texto = traceback.format_exc()
        data_txt = datetime.date.today().isoformat()
        erro_path = (
            LOGS_EXECUCAO_DIR
            / f"erro_sincronizacao_processos_incremental_{data_txt}.txt"
        )
        erro_path.write_text(traceback_texto, encoding="utf-8")

        resultado_erro = {
            "status": "ERRO",
            "etapa": "SINCRONIZACAO_E_HISTORICO_NOVOS",
            "erro": str(erro),
            "traceback_path": str(erro_path),
        }

        if FALHAR_EXECUCAO_SE_MONITORAMENTO_PROCESSOS_FALHAR:
            raise

        return resultado_erro


async def executar_pesquisa_processos_dou_incremental_segura(
    data_execucao: datetime.date,
    resultado_dou_diario: dict,
) -> dict:
    """
    Pesquisa os processos ativos somente na base DOU da data recém-gerada.
    Não abre sessão INLABS e não pesquisa outras datas.
    """

    if not EXECUTAR_MONITORAMENTO_INCREMENTAL_PROCESSOS:
        return {
            "status": "DESABILITADO",
            "data": data_execucao.isoformat(),
        }

    if not execucao_pipeline_sucesso(resultado_dou_diario):
        return {
            "status": "IGNORADO_DOU_DIARIO_SEM_SUCESSO",
            "data": data_execucao.isoformat(),
            "status_dou_diario": resultado_dou_diario.get("status"),
        }

    print("=" * 80)
    print("PESQUISA INCREMENTAL DE PROCESSOS — DOU DA DATA")
    print("=" * 80)
    print(f"Data: {data_execucao.isoformat()}")
    print("Regra: somente a base DOU desta data.")
    print("=" * 80)

    try:
        resultado = await asyncio.to_thread(
            executar_pesquisa_processos_incremental_dou,
            data_execucao,
        )
        resultado["controle_email_processos"] = (
            registrar_resultados_monitoramento_seguro(
                caminho=caminho_resultado_processos_dou_json(
                    data_execucao
                ),
                etapa="DOU_INCREMENTAL_DIARIO",
            )
        )
        return resultado

    except Exception as erro:
        traceback_texto = traceback.format_exc()
        erro_path = (
            LOGS_EXECUCAO_DIR
            / f"erro_processos_incremental_dou_{data_execucao.isoformat()}.txt"
        )
        erro_path.write_text(traceback_texto, encoding="utf-8")

        resultado_erro = {
            "status": "ERRO",
            "etapa": "PESQUISA_INCREMENTAL_DOU",
            "data": data_execucao.isoformat(),
            "erro": str(erro),
            "traceback_path": str(erro_path),
        }

        if FALHAR_EXECUCAO_SE_MONITORAMENTO_PROCESSOS_FALHAR:
            raise

        return resultado_erro


async def executar_anvisa_incremental_segura() -> dict:
    """
    Executa uma vez por chamada do runner oficial:
    - descoberta dos documentos atuais de Atas/Pautas;
    - processamento apenas dos documentos NOVO_PENDENTE.
    """

    if not EXECUTAR_MONITORAMENTO_INCREMENTAL_PROCESSOS:
        return {
            "status": "DESABILITADO",
            "mensagem": "Monitoramento incremental desabilitado no runner.",
        }

    print("=" * 80)
    print("MONITORAMENTO INCREMENTAL ANVISA/DICOL")
    print("=" * 80)

    resultado: dict = {
        "status": "NAO_EXECUTADO",
        "descoberta": None,
        "processamento": None,
    }

    try:
        descoberta = await asyncio.to_thread(
            executar_descoberta_documentos_anvisa_incremental
        )
        resultado["descoberta"] = descoberta

        processamento = await asyncio.to_thread(
            executar_processamento_documentos_anvisa_incremental
        )
        resultado["processamento"] = processamento
        resultado["controle_email_processos"] = (
            registrar_resultados_monitoramento_seguro(
                caminho=caminho_resultado_processos_anvisa_json(
                    datetime.date.today().isoformat()
                ),
                etapa="ANVISA_INCREMENTAL",
            )
        )

        status_descoberta = str(descoberta.get("status") or "").upper()
        status_processamento = str(processamento.get("status") or "").upper()

        status_aceitos = {
            "SUCESSO",
            "SEM_DOCUMENTOS_NOVOS_PENDENTES",
        }

        if (
            status_descoberta == "SUCESSO"
            and status_processamento in status_aceitos
        ):
            resultado["status"] = "SUCESSO"
        else:
            resultado["status"] = "CONCLUIDO_COM_PENDENCIAS"

        return resultado

    except Exception as erro:
        traceback_texto = traceback.format_exc()
        data_txt = datetime.date.today().isoformat()
        erro_path = (
            LOGS_EXECUCAO_DIR
            / f"erro_anvisa_incremental_{data_txt}.txt"
        )
        erro_path.write_text(traceback_texto, encoding="utf-8")

        resultado.update({
            "status": "ERRO",
            "etapa": "ANVISA_INCREMENTAL",
            "erro": str(erro),
            "traceback_path": str(erro_path),
        })

        if FALHAR_EXECUCAO_SE_MONITORAMENTO_PROCESSOS_FALHAR:
            raise

        return resultado


# ============================================================
# EXECUÃ‡ÃƒO DO PIPELINE â€” MULTIFINALIDADE POR DATA
# ============================================================

def agrupar_itens_a_executar_por_data(itens: list[dict]) -> list[dict]:
    """
    Agrupa itens pendentes por data.

    Antes: 1 item = 1 chamada completa do DOU.
    Agora: 1 data = 1 chamada multifinalidade, com busca/base Ãºnica.
    """

    grupos: list[dict] = []
    indice_por_data: dict[str, int] = {}

    for item in itens:
        if not deve_executar_item(item):
            continue

        data_txt = item.get("data")

        if data_txt not in indice_por_data:
            indice_por_data[data_txt] = len(grupos)
            grupos.append({
                "data": data_txt,
                "data_obj": item.get("data_obj"),
                "itens": [],
            })

        grupos[indice_por_data[data_txt]]["itens"].append(item)

    return grupos


def deve_forcar_reprocessamento_finalidades_grupo(itens_grupo: list[dict]) -> bool:
    """
    ForÃ§a match/auditoria/relatÃ³rio quando:
    - usuÃ¡rio pediu reprocessamento;
    - havia geraÃ§Ã£o incompleta;
    - havia JSON invÃ¡lido.

    NÃ£o forÃ§a busca/base DOU. A base tem flag prÃ³pria:
    FORCAR_REPROCESSAMENTO_BASE.
    """

    status_que_exigem_forcar = {
        "REPROCESSAMENTO_SOLICITADO",
        "GERACAO_INCOMPLETA",
        "ARQUIVO_JSON_INVALIDO",
    }

    return any(
        item.get("status") in status_que_exigem_forcar
        for item in itens_grupo
    )


def extrair_resultado_finalidade_multifinalidade(
    resultado_multifinalidade: dict,
    finalidade: str,
) -> dict:
    """
    Converte o retorno do orquestrador multifinalidade para o formato
    que o runner jÃ¡ usava por item/finalidade.
    """

    if not isinstance(resultado_multifinalidade, dict):
        return {
            "pipeline": "DOU_FINALIDADE",
            "finalidade_config": finalidade,
            "status": "ERRO",
            "erro": {
                "mensagem": "Resultado multifinalidade invÃ¡lido.",
            },
            "resultado": {},
        }

    resultado_geral = resultado_multifinalidade.get("resultado", {}) or {}
    finalidades = resultado_geral.get("finalidades", {}) or {}
    dados_finalidade = finalidades.get(finalidade)

    if not isinstance(dados_finalidade, dict):
        return {
            "pipeline": "DOU_FINALIDADE",
            "data_execucao": resultado_multifinalidade.get("data_execucao"),
            "finalidade_config": finalidade,
            "status": "ERRO",
            "erro": {
                "mensagem": "Finalidade nÃ£o encontrada no resultado multifinalidade.",
            },
            "resultado": {},
        }

    return {
        "pipeline": "DOU_FINALIDADE",
        "data_execucao": resultado_multifinalidade.get("data_execucao"),
        "finalidade_config": finalidade,
        "status": dados_finalidade.get("status"),
        "resultado": dados_finalidade.get("resultado", {}) or {},
    }


async def executar_itens_planejados(planejamento: dict) -> list[dict]:
    itens = planejamento["itens_processamento"]
    grupos_a_executar = agrupar_itens_a_executar_por_data(itens)

    resultados_execucao = []

    if not grupos_a_executar:
        print("Nenhum item pendente para execuÃ§Ã£o real.")
        return resultados_execucao

    total_itens_a_executar = sum(
        len(grupo.get("itens", []))
        for grupo in grupos_a_executar
    )

    print("=" * 80)
    print("INICIANDO EXECUÃ‡ÃƒO REAL POR PERÃODO â€” MULTIFINALIDADE")
    print("=" * 80)
    print(f"Total de datas a executar: {len(grupos_a_executar)}")
    print(f"Total de itens/finalidades a executar: {total_itens_a_executar}")
    print("Regra: busca/extraÃ§Ã£o/base DOU executadas uma Ãºnica vez por data.")
    print("=" * 80)

    for indice_grupo, grupo in enumerate(grupos_a_executar, start=1):
        data_execucao = grupo["data_obj"]
        itens_grupo = grupo["itens"]
        finalidades_grupo = [
            item.get("finalidade")
            for item in itens_grupo
            if item.get("finalidade")
        ]

        executar_limpeza_agora = (
            EXECUTAR_LIMPEZA
            if indice_grupo == len(grupos_a_executar)
            else False
        )

        forcar_finalidades = deve_forcar_reprocessamento_finalidades_grupo(
            itens_grupo
        )

        print("=" * 80)
        print(f"EXECUTANDO DATA {indice_grupo}/{len(grupos_a_executar)}")
        print(f"Data: {data_execucao.isoformat()}")
        print(f"Finalidades: {finalidades_grupo}")
        print(f"ForÃ§ar reprocessamento base DOU: {FORCAR_REPROCESSAMENTO_BASE}")
        print(f"ForÃ§ar reprocessamento finalidades: {forcar_finalidades}")
        print(f"Executar limpeza nesta data: {executar_limpeza_agora}")
        print("=" * 80)

        try:
            resultado_multifinalidade = await executar_pipeline_dou_multifinalidade(
                data_execucao=data_execucao,
                finalidades_config=finalidades_grupo,
                max_paginas=MAX_PAGINAS,
                limite_publicacoes=LIMITE_PUBLICACOES,
                headless=HEADLESS,
                executar_limpeza=executar_limpeza_agora,
                limpeza_modo_simulacao=LIMPEZA_MODO_SIMULACAO,
                forcar_reprocessamento_base=FORCAR_REPROCESSAMENTO_BASE,
                forcar_reprocessamento_finalidades=forcar_finalidades,
                continuar_se_finalidade_erro=True,
            )

            resultado_processos_dou_incremental = None

            if "dou_diario" in finalidades_grupo:
                resultado_dou_grupo = (
                    extrair_resultado_finalidade_multifinalidade(
                        resultado_multifinalidade=resultado_multifinalidade,
                        finalidade="dou_diario",
                    )
                )

                resultado_processos_dou_incremental = (
                    await executar_pesquisa_processos_dou_incremental_segura(
                        data_execucao=data_execucao,
                        resultado_dou_diario=resultado_dou_grupo,
                    )
                )

            for item in itens_grupo:
                finalidade = item.get("finalidade")
                status_original = item.get("status")

                resultado_finalidade = extrair_resultado_finalidade_multifinalidade(
                    resultado_multifinalidade=resultado_multifinalidade,
                    finalidade=finalidade,
                )

                resultado_email_dou_diario = tentar_enviar_email_dou_diario_item(
                    data_execucao=data_execucao,
                    finalidade=finalidade,
                    resultado=resultado_finalidade,
                )

                resultados_execucao.append({
                    "data": data_execucao.isoformat(),
                    "finalidade": finalidade,
                    "status_original": status_original,
                    "status_execucao": resultado_finalidade.get("status"),
                    "resultado": resultado_finalidade,
                    "email_dou_diario": resultado_email_dou_diario,
                    "monitoramento_processos_dou_incremental": (
                        resultado_processos_dou_incremental
                        if finalidade == "dou_diario"
                        else None
                    ),
                    "execucao_multifinalidade": {
                        "status": resultado_multifinalidade.get("status"),
                        "status_path": resultado_multifinalidade.get("status_path"),
                    },
                })

        except Exception as erro:
            traceback_texto = traceback.format_exc()

            erro_path = (
                LOGS_EXECUCAO_DIR
                / f"erro_orquestrador_periodo_{data_execucao.isoformat()}_multifinalidade.txt"
            )

            erro_path.write_text(traceback_texto, encoding="utf-8")

            for item in itens_grupo:
                resultados_execucao.append({
                    "data": data_execucao.isoformat(),
                    "finalidade": item.get("finalidade"),
                    "status_original": item.get("status"),
                    "status_execucao": "ERRO",
                    "erro": str(erro),
                    "traceback_path": str(erro_path),
                    "email_dou_diario": None,
                    "monitoramento_processos_dou_incremental": None,
                })

            print("=" * 80)
            print("ERRO AO EXECUTAR DATA DO PERÃODO â€” MULTIFINALIDADE")
            print(f"Data: {data_execucao.isoformat()}")
            print(f"Finalidades: {finalidades_grupo}")
            print(f"Erro: {erro}")
            print(f"Traceback: {erro_path}")
            print("=" * 80)

            # Continua para as prÃ³ximas datas do perÃ­odo.
            continue

    return resultados_execucao


# ============================================================
# RESUMO CONSOLIDADO DO PERÃODO
# ============================================================

def inicializar_resumo_finalidade() -> dict:
    return {
        "total_itens": 0,
        "ja_gerados": 0,
        "aguardando_processamento": 0,
        "reprocessamento_solicitado": 0,
        "geracao_incompleta": 0,
        "json_invalido": 0,
        "executados": 0,
        "erros": 0,
        "pendentes": 0,
        "executivo": 0,
        "monitoramento": 0,
        "revisao": 0,
        "suspeitos": 0,
        "sem_match_contextual": 0,
    }


def obter_resumo_item_planejamento(item: dict) -> dict:
    return item.get("resumo_relatorio", {}) or {}


def montar_mapa_resultados_execucao(resultados_execucao: list[dict]) -> dict:
    mapa = {}

    for resultado_item in resultados_execucao:
        chave = (
            resultado_item.get("data"),
            resultado_item.get("finalidade"),
        )
        mapa[chave] = resultado_item

    return mapa


def obter_resumo_resultado_execucao(resultado_item: dict | None) -> dict:
    if not resultado_item:
        return {}

    if resultado_item.get("status_execucao") == "ERRO":
        return {}

    resultado = resultado_item.get("resultado") or {}

    if not isinstance(resultado, dict):
        return {}

    return obter_resumo_expandido_resultado(resultado)


def somar_metricas_resumo(
    destino: dict,
    resumo: dict,
) -> None:
    if not isinstance(resumo, dict) or not resumo:
        return

    destino["executivo"] += converter_numero(
        resumo.get("match_executivo", resumo.get("com_match", 0))
    )
    destino["monitoramento"] += converter_numero(
        resumo.get("monitoramento_setorial", 0)
    )
    destino["revisao"] += converter_numero(
        resumo.get("revisao_contextual", 0)
    )
    destino["suspeitos"] += converter_numero(
        resumo.get("possiveis_falsos_positivos", 0)
    )
    destino["sem_match_contextual"] += converter_numero(
        resumo.get("sem_match_contextual", resumo.get("sem_match", 0))
    )


def montar_resumo_periodo(
    planejamento: dict,
    resultados_execucao: list[dict],
) -> dict:
    itens = planejamento.get("itens_processamento", [])
    mapa_resultados = montar_mapa_resultados_execucao(resultados_execucao)

    por_finalidade = {
        finalidade: inicializar_resumo_finalidade()
        for finalidade in FINALIDADES_CONFIG
    }

    itens_detalhados = []

    totais = inicializar_resumo_finalidade()

    for item in itens:
        data = item.get("data")
        finalidade = item.get("finalidade")
        status_planejamento = item.get("status")
        chave = (data, finalidade)
        resultado_execucao = mapa_resultados.get(chave)
        status_execucao = (
            resultado_execucao.get("status_execucao")
            if resultado_execucao
            else None
        )

        resumo_para_metricas = obter_resumo_resultado_execucao(
            resultado_execucao
        ) or obter_resumo_item_planejamento(item)

        if finalidade not in por_finalidade:
            por_finalidade[finalidade] = inicializar_resumo_finalidade()

        resumo_finalidade = por_finalidade[finalidade]

        for alvo in [totais, resumo_finalidade]:
            alvo["total_itens"] += 1

            if status_planejamento == "JA_GERADO":
                alvo["ja_gerados"] += 1
            elif status_planejamento == "AGUARDANDO_PROCESSAMENTO":
                alvo["aguardando_processamento"] += 1
            elif status_planejamento == "REPROCESSAMENTO_SOLICITADO":
                alvo["reprocessamento_solicitado"] += 1
            elif status_planejamento == "GERACAO_INCOMPLETA":
                alvo["geracao_incompleta"] += 1
            elif status_planejamento == "ARQUIVO_JSON_INVALIDO":
                alvo["json_invalido"] += 1

            if status_execucao:
                alvo["executados"] += 1

            if status_execucao == "ERRO":
                alvo["erros"] += 1

            if deve_executar_item(item) and not status_execucao:
                alvo["pendentes"] += 1

            somar_metricas_resumo(alvo, resumo_para_metricas)

        itens_detalhados.append({
            "data": data,
            "finalidade": finalidade,
            "status_planejamento": status_planejamento,
            "status_execucao": status_execucao,
            "deve_executar": deve_executar_item(item),
            "caminho_modelo_json": item.get("caminho_modelo_json"),
            "caminho_relatorio_txt": item.get("caminho_relatorio_txt"),
            "resumo": resumo_para_metricas,
            "email_dou_diario": (
                resultado_execucao.get("email_dou_diario")
                if resultado_execucao
                else None
            ),
            "monitoramento_processos_dou_incremental": (
                resultado_execucao.get(
                    "monitoramento_processos_dou_incremental"
                )
                if resultado_execucao
                else None
            ),
        })

    resumo_periodo = {
        "data_inicio": planejamento.get("data_inicio"),
        "data_fim": planejamento.get("data_fim"),
        "finalidades": planejamento.get("finalidades", []),
        "modo_simulacao": planejamento.get("modo_simulacao"),
        "forcar_reprocessamento": planejamento.get("forcar_reprocessamento"),
        "forcar_reprocessamento_base": planejamento.get("forcar_reprocessamento_base"),
        "total_dias_uteis": planejamento.get("total_dias_uteis", 0),
        "total_fins_de_semana_ignorados": planejamento.get(
            "total_fins_de_semana_ignorados",
            0,
        ),
        "total_itens": totais["total_itens"],
        "ja_gerados": totais["ja_gerados"],
        "aguardando_processamento": totais["aguardando_processamento"],
        "reprocessamento_solicitado": totais["reprocessamento_solicitado"],
        "geracao_incompleta": totais["geracao_incompleta"],
        "json_invalido": totais["json_invalido"],
        "executados": totais["executados"],
        "pendentes": totais["pendentes"],
        "erros": totais["erros"],
        "executivo_total": totais["executivo"],
        "monitoramento_total": totais["monitoramento"],
        "revisao_total": totais["revisao"],
        "suspeitos_total": totais["suspeitos"],
        "sem_match_contextual_total": totais["sem_match_contextual"],
        "por_finalidade": por_finalidade,
        "itens": itens_detalhados,
        "itens_ignorados": planejamento.get("itens_ignorados", []),
    }

    return resumo_periodo


def salvar_resumo_periodo(
    data_inicio: datetime.date,
    data_fim: datetime.date,
    resumo_periodo: dict,
) -> Path:
    nome = (
        f"resumo_periodo_"
        f"{data_inicio.isoformat()}_a_{data_fim.isoformat()}.json"
    )

    caminho = PERIODOS_DIR / nome

    caminho.write_text(
        json.dumps(
            remover_objetos_nao_serializaveis(resumo_periodo),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return caminho


# ============================================================
# SALVAR STATUS TÃ‰CNICO DO PERÃODO
# ============================================================

def salvar_status_periodo(
    data_inicio: datetime.date,
    data_fim: datetime.date,
    planejamento: dict,
    resultados_execucao: list[dict],
    resumo_periodo: dict,
) -> Path:
    nome = (
        f"status_orquestrador_dou_periodo_"
        f"{data_inicio.isoformat()}_a_{data_fim.isoformat()}.json"
    )

    caminho = LOGS_EXECUCAO_DIR / nome

    payload = {
        "data_inicio": data_inicio.isoformat(),
        "data_fim": data_fim.isoformat(),
        "finalidades": FINALIDADES_CONFIG,
        "modo_simulacao": MODO_SIMULACAO,
        "forcar_reprocessamento": FORCAR_REPROCESSAMENTO,
        "forcar_reprocessamento_base": FORCAR_REPROCESSAMENTO_BASE,
        "planejamento": planejamento,
        "resultados_execucao": resultados_execucao,
        "resumo_periodo": resumo_periodo,
    }

    caminho.write_text(
        json.dumps(
            remover_objetos_nao_serializaveis(payload),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return caminho


# ============================================================
# EXECUÃ‡ÃƒO PRINCIPAL
# ============================================================

async def main() -> None:
    data_inicio, data_fim = resolver_periodo_execucao()

    validar_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        limite_dias=LIMITE_DIAS_PERIODO,
    )

    datas_uteis, datas_ignoradas = gerar_datas_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    planejamento = montar_planejamento_execucao(
        data_inicio=data_inicio,
        data_fim=data_fim,
        datas_uteis=datas_uteis,
        datas_ignoradas=datas_ignoradas,
    )

    imprimir_planejamento(planejamento)

    resultados_execucao = []

    resultado_sincronizacao_processos = {
        "status": (
            "IGNORADO_MODO_SIMULACAO"
            if MODO_SIMULACAO
            else "NAO_EXECUTADO"
        )
    }
    resultado_anvisa_incremental = {
        "status": (
            "IGNORADO_MODO_SIMULACAO"
            if MODO_SIMULACAO
            else "NAO_EXECUTADO"
        )
    }

    if MODO_SIMULACAO:
        print("SIMULAÇÃO FINALIZADA. Nenhum pipeline foi executado.")
    else:
        # Executado uma única vez por chamada do runner.
        # Se houver processo novo, somente ele passa pela revisão histórica.
        resultado_sincronizacao_processos = (
            await executar_sincronizacao_processos_incremental_segura()
        )

        # A Anvisa é executada antes dos itens diários para que qualquer
        # ocorrência nova já esteja no mesmo e-mail do DOU.
        resultado_anvisa_incremental = (
            await executar_anvisa_incremental_segura()
        )

        resultados_execucao = await executar_itens_planejados(
            planejamento=planejamento,
        )
        imprimir_resumo_execucao(resultados_execucao)

    resumo_periodo = montar_resumo_periodo(
        planejamento=planejamento,
        resultados_execucao=resultados_execucao,
    )

    resumo_periodo["monitoramento_incremental_processos"] = {
        "sincronizacao_e_historico_novos": (
            resultado_sincronizacao_processos
        ),
        "anvisa_incremental": resultado_anvisa_incremental,
    }

    imprimir_resumo_periodo(resumo_periodo)

    caminho_resumo_periodo = salvar_resumo_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        resumo_periodo=resumo_periodo,
    )

    caminho_status = salvar_status_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        planejamento=planejamento,
        resultados_execucao=resultados_execucao,
        resumo_periodo=resumo_periodo,
    )

    print(f"Resumo operacional do período salvo em: {caminho_resumo_periodo}")
    print(f"Status técnico do período salvo em: {caminho_status}")
    print(
        "Status sincronização/histórico de processos: "
        f"{resultado_sincronizacao_processos.get('status')}"
    )
    print(
        "Status Anvisa incremental: "
        f"{resultado_anvisa_incremental.get('status')}"
    )


if __name__ == "__main__":
    asyncio.run(main())

