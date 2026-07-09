# ============================================================
# SERVICE — Operação Real DOU
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Centralizar a operação real do DOU para preparar API/front.
#
# Esta camada pode:
# - consultar status operacional;
# - executar rotina diária real;
# - reprocessar finalidades;
# - chamar o orquestrador multifinalidade;
# - acionar/simular e-mail do DOU diário quando aplicável.
#
# Esta camada NÃO substitui o runner oficial imediatamente.
# Ela prepara o backend para que a futura API/front não chame runners.
# ============================================================

from __future__ import annotations

import asyncio
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# IMPORTS DO PIPELINE REAL
# ============================================================

from backend.orquestradores.orquestrador_dou import (
    executar_pipeline_dou_multifinalidade,
)

try:
    from backend.services.email_dou_diario_service import (
        enviar_email_dou_diario as enviar_email_dou_diario_service,
    )
except Exception:
    enviar_email_dou_diario_service = None


# ============================================================
# CONFIGURAÇÕES PADRÃO
# ============================================================

PASTA_DATA_DOU = Path("backend/data/dou")

PASTA_BRUTO = PASTA_DATA_DOU / "bruto"
PASTA_BASE = PASTA_DATA_DOU / "base"
PASTA_MATCH = PASTA_DATA_DOU / "match"
PASTA_AUDITORIA = PASTA_DATA_DOU / "auditoria"
PASTA_RELATORIOS = PASTA_DATA_DOU / "relatorios"
PASTA_LOGS_EXECUCAO = PASTA_DATA_DOU / "logs_execucao"
PASTA_PERIODOS = PASTA_DATA_DOU / "periodos"

FINALIDADES_PADRAO = ["dou_diario", "informativos"]

STATUS_JA_GERADO = "JA_GERADO"
STATUS_PENDENTE = "PENDENTE"
STATUS_GERACAO_INCOMPLETA = "GERACAO_INCOMPLETA"
STATUS_ARQUIVO_INVALIDO = "ARQUIVO_JSON_INVALIDO"
STATUS_IGNORADO_FIM_DE_SEMANA = "IGNORADO_FIM_DE_SEMANA"
STATUS_EXECUTADO = "EXECUTADO"
STATUS_ERRO = "ERRO"


# ============================================================
# DATACLASSES
# ============================================================

@dataclass
class ArquivosFinalidadeDou:
    finalidade: str
    data_publicacao: str

    match_json: str = ""
    auditoria_json: str = ""
    relatorio_txt: str = ""
    relatorio_modelo_json: str = ""
    status_orquestrador_json: str = ""

    existe_match_json: bool = False
    existe_auditoria_json: bool = False
    existe_relatorio_txt: bool = False
    existe_relatorio_modelo_json: bool = False
    existe_status_orquestrador_json: bool = False


@dataclass
class StatusFinalidadeDou:
    data_publicacao: str
    finalidade: str
    status: str
    arquivos: ArquivosFinalidadeDou
    resumo: Dict[str, Any] = field(default_factory=dict)
    avisos: List[str] = field(default_factory=list)
    erros: List[str] = field(default_factory=list)


@dataclass
class StatusDataDou:
    data_publicacao: str
    dia_semana: str
    eh_fim_de_semana: bool
    arquivos_base: Dict[str, Any]
    finalidades: List[StatusFinalidadeDou]
    status_geral: str
    resumo: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# UTILITÁRIOS
# ============================================================

def formatar_data(data_publicacao: date | str) -> str:
    if isinstance(data_publicacao, date):
        return data_publicacao.strftime("%Y-%m-%d")

    texto = str(data_publicacao).strip()

    try:
        return datetime.strptime(texto, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        pass

    try:
        return datetime.strptime(texto, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        pass

    raise ValueError(
        f"Data inválida: {data_publicacao}. Use YYYY-MM-DD ou DD/MM/YYYY."
    )


def converter_para_date(data_publicacao: date | str) -> date:
    if isinstance(data_publicacao, date):
        return data_publicacao

    data_str = formatar_data(data_publicacao)
    return datetime.strptime(data_str, "%Y-%m-%d").date()


def nome_dia_semana(data_publicacao: date) -> str:
    nomes = {
        0: "segunda-feira",
        1: "terça-feira",
        2: "quarta-feira",
        3: "quinta-feira",
        4: "sexta-feira",
        5: "sábado",
        6: "domingo",
    }

    return nomes[data_publicacao.weekday()]


def eh_fim_de_semana(data_publicacao: date) -> bool:
    return data_publicacao.weekday() >= 5


def carregar_json_seguro(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        return {}

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)

        if isinstance(dados, dict):
            return dados

        return {"_conteudo": dados}

    except Exception as erro:
        return {
            "_erro_leitura_json": str(erro),
            "_tipo_erro": type(erro).__name__,
        }


def arquivo_json_valido(caminho: Path) -> bool:
    if not caminho.exists():
        return False

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            json.load(arquivo)
        return True
    except Exception:
        return False


def contar_lista_em_json(dados: Any, chaves_possiveis: List[str]) -> int:
    if isinstance(dados, list):
        return len(dados)

    if not isinstance(dados, dict):
        return 0

    for chave in chaves_possiveis:
        valor = dados.get(chave)

        if isinstance(valor, list):
            return len(valor)

    return 0


def gerar_datas_periodo(data_inicio: date, data_fim: date) -> List[date]:
    if data_fim < data_inicio:
        raise ValueError("data_fim não pode ser menor que data_inicio.")

    datas = []
    atual = data_inicio

    while atual <= data_fim:
        datas.append(atual)
        atual += timedelta(days=1)

    return datas


def executar_callable_async_em_contexto_sync(factory: Any) -> Any:
    """
    Executa uma coroutine a partir de uma função síncrona.

    Usa asyncio.run quando não existe loop ativo.
    Se já houver loop ativo, executa em uma thread separada para evitar erro
    de nested event loop em contexto de API/notebook.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    if loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(lambda: asyncio.run(factory()))
            return futuro.result()

    return loop.run_until_complete(factory())


def executar_awaitable_em_contexto_sync(awaitable: Any) -> Any:
    """
    Resolve um awaitable já criado.

    Normalmente o orquestrador será tratado antes por coroutinefunction.
    Esta função fica como proteção extra para funções que retornem coroutine.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    if loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            futuro = executor.submit(lambda: asyncio.run(awaitable))
            return futuro.result()

    return loop.run_until_complete(awaitable)


def chamar_funcao_com_parametros_compativeis(funcao: Any, parametros: Dict[str, Any]) -> Any:
    """
    Chama uma função usando apenas os parâmetros aceitos por ela.

    Também resolve automaticamente funções assíncronas, como:
    - executar_pipeline_dou_multifinalidade
    - possíveis services assíncronos futuros
    """
    if funcao is None:
        raise ValueError("Função não informada para chamada dinâmica.")

    assinatura = inspect.signature(funcao)
    parametros_aceitos = {}

    for nome_parametro in assinatura.parameters.keys():
        if nome_parametro in parametros:
            parametros_aceitos[nome_parametro] = parametros[nome_parametro]

    if inspect.iscoroutinefunction(funcao):
        return executar_callable_async_em_contexto_sync(
            lambda: funcao(**parametros_aceitos)
        )

    resultado = funcao(**parametros_aceitos)

    if inspect.isawaitable(resultado):
        return executar_awaitable_em_contexto_sync(resultado)

    return resultado


# ============================================================
# CAMINHOS
# ============================================================

def obter_caminhos_base(data_publicacao: str) -> Dict[str, Path]:
    return {
        "links_json": PASTA_BRUTO / f"links_dou_{data_publicacao}.json",
        "publicacoes_json": PASTA_BRUTO / f"publicacoes_{data_publicacao}.json",
        "base_json": PASTA_BASE / f"base_publicacoes_{data_publicacao}.json",
        "status_multifinalidade_json": (
            PASTA_LOGS_EXECUCAO
            / f"status_orquestrador_dou_{data_publicacao}_multifinalidade.json"
        ),
    }


def obter_caminhos_finalidade(data_publicacao: str, finalidade: str) -> Dict[str, Path]:
    return {
        "match_json": (
            PASTA_MATCH
            / finalidade
            / f"match_publicacoes_{data_publicacao}.json"
        ),
        "auditoria_json": (
            PASTA_AUDITORIA
            / finalidade
            / f"auditoria_match_{data_publicacao}.json"
        ),
        "relatorio_txt": (
            PASTA_RELATORIOS
            / finalidade
            / f"relatorio_executivo_{data_publicacao}.txt"
        ),
        "relatorio_modelo_json": (
            PASTA_RELATORIOS
            / finalidade
            / f"relatorio_executivo_modelo_{data_publicacao}.json"
        ),
        "status_orquestrador_json": (
            PASTA_LOGS_EXECUCAO
            / f"status_orquestrador_dou_{data_publicacao}_{finalidade}.json"
        ),
    }


# ============================================================
# CONSULTA STATUS — BASE
# ============================================================

def consultar_arquivos_base(data_publicacao: date | str) -> Dict[str, Any]:
    data_str = formatar_data(data_publicacao)
    caminhos = obter_caminhos_base(data_str)

    links_json = caminhos["links_json"]
    publicacoes_json = caminhos["publicacoes_json"]
    base_json = caminhos["base_json"]
    status_multifinalidade_json = caminhos["status_multifinalidade_json"]

    dados_links = carregar_json_seguro(links_json)
    dados_publicacoes = carregar_json_seguro(publicacoes_json)
    dados_base = carregar_json_seguro(base_json)

    return {
        "data_publicacao": data_str,
        "links_json": str(links_json),
        "publicacoes_json": str(publicacoes_json),
        "base_json": str(base_json),
        "status_multifinalidade_json": str(status_multifinalidade_json),

        "existe_links_json": links_json.exists(),
        "existe_publicacoes_json": publicacoes_json.exists(),
        "existe_base_json": base_json.exists(),
        "existe_status_multifinalidade_json": status_multifinalidade_json.exists(),

        "links_json_valido": arquivo_json_valido(links_json),
        "publicacoes_json_valido": arquivo_json_valido(publicacoes_json),
        "base_json_valido": arquivo_json_valido(base_json),
        "status_multifinalidade_json_valido": arquivo_json_valido(
            status_multifinalidade_json
        ),

        "total_links": contar_lista_em_json(
            dados_links,
            ["links", "dados", "itens", "publicacoes"],
        ),
        "total_publicacoes_extraidas": contar_lista_em_json(
            dados_publicacoes,
            ["publicacoes", "dados", "itens", "registros"],
        ),
        "total_publicacoes_base": contar_lista_em_json(
            dados_base,
            ["publicacoes", "base_publicacoes", "dados", "itens", "registros"],
        ),
    }


# ============================================================
# CONSULTA STATUS — FINALIDADE
# ============================================================

def consultar_arquivos_finalidade(
    data_publicacao: date | str,
    finalidade: str,
) -> ArquivosFinalidadeDou:
    data_str = formatar_data(data_publicacao)
    caminhos = obter_caminhos_finalidade(data_str, finalidade)

    match_json = caminhos["match_json"]
    auditoria_json = caminhos["auditoria_json"]
    relatorio_txt = caminhos["relatorio_txt"]
    relatorio_modelo_json = caminhos["relatorio_modelo_json"]
    status_orquestrador_json = caminhos["status_orquestrador_json"]

    return ArquivosFinalidadeDou(
        finalidade=finalidade,
        data_publicacao=data_str,
        match_json=str(match_json),
        auditoria_json=str(auditoria_json),
        relatorio_txt=str(relatorio_txt),
        relatorio_modelo_json=str(relatorio_modelo_json),
        status_orquestrador_json=str(status_orquestrador_json),
        existe_match_json=match_json.exists(),
        existe_auditoria_json=auditoria_json.exists(),
        existe_relatorio_txt=relatorio_txt.exists(),
        existe_relatorio_modelo_json=relatorio_modelo_json.exists(),
        existe_status_orquestrador_json=status_orquestrador_json.exists(),
    )


def extrair_resumo_relatorio_modelo(caminho_modelo: Path) -> Dict[str, Any]:
    dados = carregar_json_seguro(caminho_modelo)

    if not dados:
        return {}

    if "_erro_leitura_json" in dados:
        return {
            "erro_leitura_json": dados.get("_erro_leitura_json"),
            "tipo_erro": dados.get("_tipo_erro"),
        }

    for chave in ["resumo", "resumo_executivo", "totais", "indicadores"]:
        valor = dados.get(chave)

        if isinstance(valor, dict):
            return valor

    resumo = {}

    for chave in [
        "total_publicacoes",
        "total_relevantes",
        "total_executivo",
        "total_monitoramento",
        "total_revisao",
        "total_suspeitos",
        "executivo",
        "monitoramento",
        "revisao",
        "suspeitos",
        "sem_match_contextual",
    ]:
        if chave in dados:
            resumo[chave] = dados.get(chave)

    return resumo


def definir_status_finalidade(arquivos: ArquivosFinalidadeDou) -> str:
    arquivos_essenciais = [
        arquivos.existe_match_json,
        arquivos.existe_auditoria_json,
        arquivos.existe_relatorio_txt,
        arquivos.existe_relatorio_modelo_json,
    ]

    if all(arquivos_essenciais):
        return STATUS_JA_GERADO

    if any(arquivos_essenciais):
        return STATUS_GERACAO_INCOMPLETA

    return STATUS_PENDENTE


def consultar_status_finalidade(
    data_publicacao: date | str,
    finalidade: str,
) -> StatusFinalidadeDou:
    data_str = formatar_data(data_publicacao)
    arquivos = consultar_arquivos_finalidade(data_str, finalidade)
    status = definir_status_finalidade(arquivos)

    caminhos = obter_caminhos_finalidade(data_str, finalidade)
    resumo = extrair_resumo_relatorio_modelo(caminhos["relatorio_modelo_json"])

    avisos: List[str] = []
    erros: List[str] = []

    if status == STATUS_GERACAO_INCOMPLETA:
        avisos.append(
            "Há arquivos parciais da finalidade, mas nem todos os arquivos essenciais existem."
        )

    if arquivos.existe_match_json and not arquivo_json_valido(caminhos["match_json"]):
        erros.append("Arquivo de match existe, mas o JSON está inválido.")

    if arquivos.existe_auditoria_json and not arquivo_json_valido(caminhos["auditoria_json"]):
        erros.append("Arquivo de auditoria existe, mas o JSON está inválido.")

    if arquivos.existe_relatorio_modelo_json and not arquivo_json_valido(
        caminhos["relatorio_modelo_json"]
    ):
        erros.append("Arquivo modelo do relatório existe, mas o JSON está inválido.")

    if erros:
        status = STATUS_ARQUIVO_INVALIDO

    return StatusFinalidadeDou(
        data_publicacao=data_str,
        finalidade=finalidade,
        status=status,
        arquivos=arquivos,
        resumo=resumo,
        avisos=avisos,
        erros=erros,
    )


def consultar_status_data(
    data_publicacao: date | str,
    finalidades: Optional[List[str]] = None,
) -> StatusDataDou:
    data_str = formatar_data(data_publicacao)
    data_obj = converter_para_date(data_str)
    finalidades_consulta = finalidades or FINALIDADES_PADRAO

    if eh_fim_de_semana(data_obj):
        finalidades_status = []

        for finalidade in finalidades_consulta:
            arquivos = consultar_arquivos_finalidade(data_str, finalidade)

            finalidades_status.append(
                StatusFinalidadeDou(
                    data_publicacao=data_str,
                    finalidade=finalidade,
                    status=STATUS_IGNORADO_FIM_DE_SEMANA,
                    arquivos=arquivos,
                    resumo={},
                    avisos=["Fim de semana ignorado pela regra operacional."],
                    erros=[],
                )
            )

        return StatusDataDou(
            data_publicacao=data_str,
            dia_semana=nome_dia_semana(data_obj),
            eh_fim_de_semana=True,
            arquivos_base=consultar_arquivos_base(data_str),
            finalidades=finalidades_status,
            status_geral=STATUS_IGNORADO_FIM_DE_SEMANA,
            resumo={
                "total_finalidades": len(finalidades_status),
                "ja_gerado": 0,
                "pendente": 0,
                "incompleto": 0,
                "invalido": 0,
            },
        )

    arquivos_base = consultar_arquivos_base(data_str)

    finalidades_status = [
        consultar_status_finalidade(data_str, finalidade)
        for finalidade in finalidades_consulta
    ]

    total_ja_gerado = sum(
        1 for item in finalidades_status if item.status == STATUS_JA_GERADO
    )
    total_pendente = sum(
        1 for item in finalidades_status if item.status == STATUS_PENDENTE
    )
    total_incompleto = sum(
        1 for item in finalidades_status if item.status == STATUS_GERACAO_INCOMPLETA
    )
    total_invalido = sum(
        1 for item in finalidades_status if item.status == STATUS_ARQUIVO_INVALIDO
    )

    if total_invalido > 0:
        status_geral = STATUS_ARQUIVO_INVALIDO
    elif total_incompleto > 0:
        status_geral = STATUS_GERACAO_INCOMPLETA
    elif total_pendente > 0:
        status_geral = STATUS_PENDENTE
    else:
        status_geral = STATUS_JA_GERADO

    return StatusDataDou(
        data_publicacao=data_str,
        dia_semana=nome_dia_semana(data_obj),
        eh_fim_de_semana=False,
        arquivos_base=arquivos_base,
        finalidades=finalidades_status,
        status_geral=status_geral,
        resumo={
            "total_finalidades": len(finalidades_status),
            "ja_gerado": total_ja_gerado,
            "pendente": total_pendente,
            "incompleto": total_incompleto,
            "invalido": total_invalido,
        },
    )


# ============================================================
# SERIALIZAÇÃO
# ============================================================

def converter_status_finalidade_para_dict(
    status: StatusFinalidadeDou,
) -> Dict[str, Any]:
    return {
        "data_publicacao": status.data_publicacao,
        "finalidade": status.finalidade,
        "status": status.status,
        "arquivos": status.arquivos.__dict__,
        "resumo": status.resumo,
        "avisos": status.avisos,
        "erros": status.erros,
    }


def converter_status_data_para_dict(status: StatusDataDou) -> Dict[str, Any]:
    return {
        "data_publicacao": status.data_publicacao,
        "dia_semana": status.dia_semana,
        "eh_fim_de_semana": status.eh_fim_de_semana,
        "status_geral": status.status_geral,
        "arquivos_base": status.arquivos_base,
        "resumo": status.resumo,
        "finalidades": [
            converter_status_finalidade_para_dict(item)
            for item in status.finalidades
        ],
    }


# ============================================================
# CONSULTAS OPERACIONAIS PARA FUTURA API
# ============================================================

def obter_status_operacional_dia(
    data_publicacao: date | str,
    finalidades: Optional[List[str]] = None,
) -> Dict[str, Any]:
    status = consultar_status_data(
        data_publicacao=data_publicacao,
        finalidades=finalidades,
    )

    return converter_status_data_para_dict(status)


def obter_status_operacional_periodo(
    data_inicio: date | str,
    data_fim: date | str,
    finalidades: Optional[List[str]] = None,
) -> Dict[str, Any]:
    inicio = converter_para_date(data_inicio)
    fim = converter_para_date(data_fim)
    datas = gerar_datas_periodo(inicio, fim)

    status_datas = [
        consultar_status_data(data_item, finalidades=finalidades)
        for data_item in datas
    ]

    total_dias = len(status_datas)
    total_fins_semana = sum(1 for item in status_datas if item.eh_fim_de_semana)
    total_dias_uteis = total_dias - total_fins_semana

    total_ja_gerado = 0
    total_pendente = 0
    total_incompleto = 0
    total_invalido = 0

    for status_data in status_datas:
        if status_data.eh_fim_de_semana:
            continue

        for finalidade in status_data.finalidades:
            if finalidade.status == STATUS_JA_GERADO:
                total_ja_gerado += 1
            elif finalidade.status == STATUS_PENDENTE:
                total_pendente += 1
            elif finalidade.status == STATUS_GERACAO_INCOMPLETA:
                total_incompleto += 1
            elif finalidade.status == STATUS_ARQUIVO_INVALIDO:
                total_invalido += 1

    return {
        "data_inicio": formatar_data(inicio),
        "data_fim": formatar_data(fim),
        "finalidades": finalidades or FINALIDADES_PADRAO,
        "total_dias": total_dias,
        "total_dias_uteis": total_dias_uteis,
        "total_fins_semana_ignorados": total_fins_semana,
        "total_ja_gerado": total_ja_gerado,
        "total_pendente": total_pendente,
        "total_incompleto": total_incompleto,
        "total_invalido": total_invalido,
        "status_datas": [
            converter_status_data_para_dict(item)
            for item in status_datas
        ],
    }


def obter_status_operacional_hoje(
    finalidades: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return obter_status_operacional_dia(
        data_publicacao=date.today(),
        finalidades=finalidades,
    )


# ============================================================
# EXECUÇÃO REAL — ORQUESTRADOR MULTIFINALIDADE
# ============================================================

def executar_dou_data_real(
    data_publicacao: date | str,
    finalidades: Optional[List[str]] = None,
    forcar_reprocessamento: bool = False,
    forcar_reprocessamento_base: bool = False,
    max_paginas: Optional[int] = None,
    limite_publicacoes: Optional[int] = None,
    headless: bool = True,
    executar_limpeza: bool = True,
    limpeza_modo_simulacao: bool = True,
    enviar_email_dou_diario: bool = True,
    email_dou_diario_modo_simulacao: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Executa uma data real do DOU via orquestrador multifinalidade.

    Regra:
    - se for fim de semana, não executa;
    - se tudo já estiver gerado e forcar_reprocessamento=False, não executa;
    - se houver pendência ou reprocessamento solicitado, executa o orquestrador;
    - e-mail é chamado somente para dou_diario quando solicitado.
    """
    data_obj = converter_para_date(data_publicacao)
    data_str = formatar_data(data_obj)
    finalidades_execucao = finalidades or FINALIDADES_PADRAO

    status_antes = consultar_status_data(data_str, finalidades_execucao)

    if status_antes.eh_fim_de_semana:
        return {
            "status": STATUS_IGNORADO_FIM_DE_SEMANA,
            "data_publicacao": data_str,
            "mensagem": "Data ignorada por ser fim de semana.",
            "status_antes": converter_status_data_para_dict(status_antes),
            "resultado_orquestrador": None,
            "email_dou_diario": None,
            "status_depois": converter_status_data_para_dict(status_antes),
        }

    if (
        status_antes.status_geral == STATUS_JA_GERADO
        and not forcar_reprocessamento
        and not forcar_reprocessamento_base
    ):
        return {
            "status": STATUS_JA_GERADO,
            "data_publicacao": data_str,
            "mensagem": (
                "Todas as finalidades já estão geradas. "
                "Nada foi executado porque não houve reprocessamento solicitado."
            ),
            "status_antes": converter_status_data_para_dict(status_antes),
            "resultado_orquestrador": None,
            "email_dou_diario": None,
            "status_depois": converter_status_data_para_dict(status_antes),
        }

    parametros_orquestrador = {
        "data_execucao": data_obj,
        "data_publicacao": data_obj,
        "data": data_obj,
        "finalidades_config": finalidades_execucao,
        "finalidades": finalidades_execucao,
        "max_paginas": max_paginas,
        "limite_publicacoes": limite_publicacoes,
        "headless": headless,
        "executar_limpeza": executar_limpeza,
        "limpeza_modo_simulacao": limpeza_modo_simulacao,

        # Compatibilidade com nomes possíveis usados pelo orquestrador.
        # O orquestrador atual usa o nome que existir na assinatura dele,
        # porque chamar_funcao_com_parametros_compativeis filtra automaticamente.
        "forcar_reprocessamento": forcar_reprocessamento,
        "forcar_reprocessamento_finalidade": forcar_reprocessamento,
        "forcar_reprocessamento_finalidades": forcar_reprocessamento,

        "forcar_reprocessamento_base": forcar_reprocessamento_base,
    }

    resultado_orquestrador = chamar_funcao_com_parametros_compativeis(
        executar_pipeline_dou_multifinalidade,
        parametros_orquestrador,
    )

    resultado_email = None

    if enviar_email_dou_diario and "dou_diario" in finalidades_execucao:
        if enviar_email_dou_diario_service is None:
            resultado_email = {
                "status": "NAO_EXECUTADO",
                "motivo": "Serviço email_dou_diario_service não pôde ser importado.",
            }
        else:
            try:
                parametros_email = {
                    "data_execucao": data_obj,
                    "data_publicacao": data_obj,
                    "data": data_obj,
                    "modo_simulacao": email_dou_diario_modo_simulacao,
                    "email_modo_simulacao": email_dou_diario_modo_simulacao,
                }

                resultado_email = chamar_funcao_com_parametros_compativeis(
                    enviar_email_dou_diario_service,
                    parametros_email,
                )

            except Exception as erro:
                resultado_email = {
                    "status": "ERRO",
                    "tipo_erro": type(erro).__name__,
                    "erro": str(erro),
                }

    status_depois = consultar_status_data(data_str, finalidades_execucao)

    return {
        "status": STATUS_EXECUTADO,
        "data_publicacao": data_str,
        "finalidades": finalidades_execucao,
        "forcar_reprocessamento": forcar_reprocessamento,
        "forcar_reprocessamento_base": forcar_reprocessamento_base,
        "status_antes": converter_status_data_para_dict(status_antes),
        "resultado_orquestrador": resultado_orquestrador,
        "email_dou_diario": resultado_email,
        "status_depois": converter_status_data_para_dict(status_depois),
    }


def executar_rotina_diaria_dou_real(
    finalidades: Optional[List[str]] = None,
    headless: bool = True,
    enviar_email_dou_diario: bool = True,
    email_dou_diario_modo_simulacao: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Executa a rotina real da data atual.

    Equivalente operacional futuro ao botão:
    'Executar rotina diária'
    """
    return executar_dou_data_real(
        data_publicacao=date.today(),
        finalidades=finalidades or FINALIDADES_PADRAO,
        forcar_reprocessamento=False,
        forcar_reprocessamento_base=False,
        max_paginas=None,
        limite_publicacoes=None,
        headless=headless,
        executar_limpeza=True,
        limpeza_modo_simulacao=True,
        enviar_email_dou_diario=enviar_email_dou_diario,
        email_dou_diario_modo_simulacao=email_dou_diario_modo_simulacao,
    )


def reprocessar_dou_data_real(
    data_publicacao: date | str,
    finalidades: Optional[List[str]] = None,
    reprocessar_base: bool = False,
    headless: bool = True,
    enviar_email_dou_diario: bool = True,
    email_dou_diario_modo_simulacao: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Reprocessa uma data real.

    Padrão seguro:
    - reprocessar_base=False
    - ou seja, refaz finalidade sem refazer busca/base DOU.
    """
    return executar_dou_data_real(
        data_publicacao=data_publicacao,
        finalidades=finalidades or FINALIDADES_PADRAO,
        forcar_reprocessamento=True,
        forcar_reprocessamento_base=reprocessar_base,
        max_paginas=None,
        limite_publicacoes=None,
        headless=headless,
        executar_limpeza=True,
        limpeza_modo_simulacao=True,
        enviar_email_dou_diario=enviar_email_dou_diario,
        email_dou_diario_modo_simulacao=email_dou_diario_modo_simulacao,
    )