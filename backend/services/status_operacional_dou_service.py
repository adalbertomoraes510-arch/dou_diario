# ============================================================
# SERVICE — Status Operacional DOU
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Consultar o estado real dos arquivos gerados pelo pipeline DOU,
# por data, finalidade e período.
#
# Este serviço NÃO executa coleta.
# Este serviço NÃO altera match.
# Este serviço NÃO altera curadoria.
# Este serviço NÃO altera relatório.
# Este serviço NÃO substitui o status_service.py existente.
#
# Ele apenas verifica se os artefatos esperados existem nas pastas
# oficiais do projeto, preparando o backend para API e front.
# ============================================================

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union


# ============================================================
# CONFIGURAÇÃO DE CAMINHOS
# ============================================================

ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT_DIR / "backend" / "data"

DOU_DIR = DATA_DIR / "dou"

BRUTO_DIR = DOU_DIR / "bruto"
BASE_DOU_DIR = DOU_DIR / "base"
MATCH_DIR = DOU_DIR / "match"
AUDITORIA_DIR = DOU_DIR / "auditoria"
RELATORIOS_DIR = DOU_DIR / "relatorios"
LOGS_EXECUCAO_DIR = DOU_DIR / "logs_execucao"
CONSOLIDADOS_PERIODO_DIR = DOU_DIR / "consolidados_periodo"
BOLETINS_DIR = DOU_DIR / "boletins"
MAPEAMENTOS_DIR = DOU_DIR / "mapeamentos"

PUBLICACOES_PADRAO_DIR = DATA_DIR / "publicacoes_padrao" / "dou"

STATUS_OPERACIONAL_DIR = DOU_DIR / "status_operacional"

FINALIDADES_PADRAO = [
    "dou_diario",
    "informativos",
]


# ============================================================
# TIPOS
# ============================================================

DataEntrada = Union[str, dt.date, dt.datetime]


# ============================================================
# UTILITÁRIOS GERAIS
# ============================================================

def _agora_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _normalizar_data(valor: DataEntrada) -> str:
    """
    Normaliza datas para YYYY-MM-DD.

    Aceita:
    - datetime.date
    - datetime.datetime
    - string YYYY-MM-DD
    - string DD/MM/YYYY
    """
    if isinstance(valor, dt.datetime):
        return valor.date().isoformat()

    if isinstance(valor, dt.date):
        return valor.isoformat()

    texto = str(valor or "").strip()

    if not texto:
        raise ValueError("Data vazia ou inválida.")

    formatos = [
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    for formato in formatos:
        try:
            return dt.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass

    raise ValueError(
        f"Data inválida: {valor}. Use YYYY-MM-DD ou DD/MM/YYYY."
    )


def _converter_para_date(valor: DataEntrada) -> dt.date:
    data_str = _normalizar_data(valor)
    return dt.datetime.strptime(data_str, "%Y-%m-%d").date()


def _caminho_relativo(caminho: Path) -> str:
    try:
        return str(caminho.resolve().relative_to(ROOT_DIR)).replace("\\", "/")
    except Exception:
        return str(caminho).replace("\\", "/")


def _garantir_pasta_status_operacional() -> None:
    STATUS_OPERACIONAL_DIR.mkdir(parents=True, exist_ok=True)


def _carregar_json(caminho: Path) -> Any:
    with caminho.open("r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _salvar_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with caminho.open("w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


# ============================================================
# DIAGNÓSTICO DE ARQUIVOS
# ============================================================

def _contar_registros_json(dados: Any) -> Optional[int]:
    """
    Tenta estimar a quantidade de registros relevantes em um JSON.

    A função é propositalmente tolerante, pois os arquivos do projeto
    possuem estruturas diferentes conforme a etapa.
    """
    if isinstance(dados, list):
        return len(dados)

    if not isinstance(dados, dict):
        return None

    chaves_lista_prioritarias = [
        "publicacoes",
        "registros",
        "dados",
        "base_publicacoes",
        "itens",
        "matches",
        "publicacoes_convertidas",
        "publicacoes_padrao",
        "resultados",
        "etapas",
    ]

    for chave in chaves_lista_prioritarias:
        valor = dados.get(chave)

        if isinstance(valor, list):
            return len(valor)

    chaves_totais_prioritarias = [
        "total_publicacoes",
        "total_origem",
        "total_validadas",
        "total_convertidas",
        "total_itens",
        "total_matches",
        "total_relevantes",
        "total_publicacoes_lidas",
    ]

    for chave in chaves_totais_prioritarias:
        valor = dados.get(chave)

        if isinstance(valor, int):
            return valor

    for valor in dados.values():
        if isinstance(valor, list):
            return len(valor)

    return None


def _diagnosticar_json(caminho: Path) -> Dict[str, Any]:
    if not caminho.exists():
        return {
            "json_valido": None,
            "tipo_json": None,
            "total_registros_estimado": None,
            "chaves_raiz": [],
            "erro_json": None,
        }

    try:
        dados = _carregar_json(caminho)
    except Exception as erro:
        return {
            "json_valido": False,
            "tipo_json": None,
            "total_registros_estimado": None,
            "chaves_raiz": [],
            "erro_json": str(erro),
        }

    chaves_raiz: List[str] = []

    if isinstance(dados, dict):
        chaves_raiz = list(dados.keys())[:50]

    return {
        "json_valido": True,
        "tipo_json": type(dados).__name__,
        "total_registros_estimado": _contar_registros_json(dados),
        "chaves_raiz": chaves_raiz,
        "erro_json": None,
    }


def _obter_info_arquivo(
    caminho: Path,
    nome: str,
    descricao: str,
    obrigatorio: bool = True,
) -> Dict[str, Any]:
    """
    Retorna diagnóstico padronizado de um arquivo esperado.
    """
    info: Dict[str, Any] = {
        "nome": nome,
        "descricao": descricao,
        "obrigatorio": obrigatorio,
        "existe": caminho.exists(),
        "caminho": _caminho_relativo(caminho),
        "tamanho_bytes": None,
        "modificado_em": None,
        "json_valido": None,
        "tipo_json": None,
        "total_registros_estimado": None,
        "chaves_raiz": [],
        "erro_json": None,
    }

    if not caminho.exists():
        return info

    try:
        stat = caminho.stat()
        info["tamanho_bytes"] = stat.st_size
        info["modificado_em"] = dt.datetime.fromtimestamp(
            stat.st_mtime
        ).isoformat(timespec="seconds")
    except Exception:
        pass

    if caminho.suffix.lower() == ".json":
        info.update(_diagnosticar_json(caminho))

    return info


# ============================================================
# RESUMO DE CHECKS
# ============================================================

def _coletar_checks(objeto: Any) -> List[Dict[str, Any]]:
    """
    Percorre um dicionário/lista e coleta itens que representem
    verificação de arquivo.
    """
    checks: List[Dict[str, Any]] = []

    if isinstance(objeto, dict):
        if "existe" in objeto and "obrigatorio" in objeto:
            checks.append(objeto)

        for valor in objeto.values():
            checks.extend(_coletar_checks(valor))

    elif isinstance(objeto, list):
        for item in objeto:
            checks.extend(_coletar_checks(item))

    return checks


def _montar_resumo_checks(payload: Dict[str, Any]) -> Dict[str, Any]:
    checks = _coletar_checks(payload)

    obrigatorios = [
        check for check in checks
        if check.get("obrigatorio") is True
    ]

    opcionais = [
        check for check in checks
        if check.get("obrigatorio") is False
    ]

    total_obrigatorios = len(obrigatorios)
    total_obrigatorios_ok = sum(
        1 for check in obrigatorios
        if check.get("existe") is True
    )

    total_obrigatorios_pendentes = (
        total_obrigatorios - total_obrigatorios_ok
    )

    total_opcionais = len(opcionais)
    total_opcionais_ok = sum(
        1 for check in opcionais
        if check.get("existe") is True
    )

    if total_obrigatorios == 0:
        percentual = 0.0
        status_geral = "SEM_CHECKS_OBRIGATORIOS"
    else:
        percentual = round(
            (total_obrigatorios_ok / total_obrigatorios) * 100,
            2,
        )

        if total_obrigatorios_ok == total_obrigatorios:
            status_geral = "COMPLETO"
        elif total_obrigatorios_ok == 0:
            status_geral = "PENDENTE"
        else:
            status_geral = "PARCIAL"

    pendencias = [
        {
            "nome": check.get("nome"),
            "descricao": check.get("descricao"),
            "caminho": check.get("caminho"),
        }
        for check in obrigatorios
        if check.get("existe") is not True
    ]

    return {
        "status_geral": status_geral,
        "percentual_conclusao_obrigatorios": percentual,
        "total_checks_obrigatorios": total_obrigatorios,
        "total_checks_obrigatorios_ok": total_obrigatorios_ok,
        "total_checks_obrigatorios_pendentes": total_obrigatorios_pendentes,
        "total_checks_opcionais": total_opcionais,
        "total_checks_opcionais_ok": total_opcionais_ok,
        "pendencias_obrigatorias": pendencias,
    }


# ============================================================
# STATUS POR DATA — CAMADA DOU
# ============================================================

def _montar_status_camada_fonte_dou(data_str: str) -> Dict[str, Any]:
    """
    Verifica os artefatos gerais do DOU para uma data.
    """
    return {
        "links_busca": _obter_info_arquivo(
            caminho=BRUTO_DIR / f"links_dou_{data_str}.json",
            nome="links_busca",
            descricao="Arquivo com links coletados na busca do DOU.",
            obrigatorio=True,
        ),
        "publicacoes_brutas": _obter_info_arquivo(
            caminho=BRUTO_DIR / f"publicacoes_{data_str}.json",
            nome="publicacoes_brutas",
            descricao="Arquivo bruto com publicações extraídas do DOU.",
            obrigatorio=True,
        ),
        "base_auditavel": _obter_info_arquivo(
            caminho=BASE_DOU_DIR / f"base_publicacoes_{data_str}.json",
            nome="base_auditavel",
            descricao="Base auditável oficial do DOU.",
            obrigatorio=True,
        ),
        "base_padronizada": _obter_info_arquivo(
            caminho=PUBLICACOES_PADRAO_DIR / f"publicacoes_padrao_{data_str}.json",
            nome="base_padronizada",
            descricao="Base DOU convertida para PublicacaoPadrao.",
            obrigatorio=False,
        ),
        "resumo_base_padronizada": _obter_info_arquivo(
            caminho=PUBLICACOES_PADRAO_DIR / f"resumo_publicacoes_padrao_{data_str}.txt",
            nome="resumo_base_padronizada",
            descricao="Resumo textual da base padronizada DOU.",
            obrigatorio=False,
        ),
        "validacao_contrato": _obter_info_arquivo(
            caminho=(
                MAPEAMENTOS_DIR
                / "contrato_publicacao"
                / f"validacao_contrato_publicacao_dou_{data_str}.json"
            ),
            nome="validacao_contrato",
            descricao="Validação do contrato PublicacaoPadrao com a base DOU.",
            obrigatorio=False,
        ),
    }


# ============================================================
# STATUS POR FINALIDADE
# ============================================================

def _montar_status_finalidade_dou(
    data_str: str,
    finalidade: str,
) -> Dict[str, Any]:
    """
    Verifica os artefatos de uma finalidade específica.
    """
    return {
        "finalidade": finalidade,
        "match": _obter_info_arquivo(
            caminho=(
                MATCH_DIR
                / finalidade
                / f"match_publicacoes_{data_str}.json"
            ),
            nome=f"match_{finalidade}",
            descricao=f"Resultado de match da finalidade {finalidade}.",
            obrigatorio=True,
        ),
        "auditoria_match": _obter_info_arquivo(
            caminho=(
                AUDITORIA_DIR
                / finalidade
                / f"auditoria_match_{data_str}.json"
            ),
            nome=f"auditoria_match_{finalidade}",
            descricao=f"Auditoria do match da finalidade {finalidade}.",
            obrigatorio=True,
        ),
        "relatorio_executivo_txt": _obter_info_arquivo(
            caminho=(
                RELATORIOS_DIR
                / finalidade
                / f"relatorio_executivo_{data_str}.txt"
            ),
            nome=f"relatorio_executivo_txt_{finalidade}",
            descricao=f"Relatório executivo TXT da finalidade {finalidade}.",
            obrigatorio=True,
        ),
        "relatorio_executivo_modelo_json": _obter_info_arquivo(
            caminho=(
                RELATORIOS_DIR
                / finalidade
                / f"relatorio_executivo_modelo_{data_str}.json"
            ),
            nome=f"relatorio_executivo_modelo_json_{finalidade}",
            descricao=f"Modelo JSON do relatório executivo da finalidade {finalidade}.",
            obrigatorio=False,
        ),
        "status_orquestrador": _obter_info_arquivo(
            caminho=(
                LOGS_EXECUCAO_DIR
                / f"status_orquestrador_dou_{data_str}_{finalidade}.json"
            ),
            nome=f"status_orquestrador_{finalidade}",
            descricao=f"Status do orquestrador DOU para a finalidade {finalidade}.",
            obrigatorio=False,
        ),
    }


# ============================================================
# STATUS OPERACIONAL DOU — DATA ÚNICA
# ============================================================

def obter_status_operacional_dou(
    data_referencia: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Retorna o status operacional do DOU para uma data.

    Exemplo:
        obter_status_operacional_dou("2026-05-14")
    """
    data_str = _normalizar_data(data_referencia)
    finalidades_uso = list(finalidades or FINALIDADES_PADRAO)

    payload: Dict[str, Any] = {
        "tipo": "status_operacional_dou",
        "fonte": "dou",
        "data_referencia": data_str,
        "gerado_em": _agora_iso(),
        "camada_fonte": _montar_status_camada_fonte_dou(data_str),
        "finalidades": {},
    }

    for finalidade in finalidades_uso:
        payload["finalidades"][finalidade] = _montar_status_finalidade_dou(
            data_str=data_str,
            finalidade=finalidade,
        )

    payload["resumo"] = _montar_resumo_checks(payload)

    return payload


def salvar_status_operacional_dou(
    data_referencia: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Gera o status operacional e salva snapshot em JSON.
    """
    _garantir_pasta_status_operacional()

    status = obter_status_operacional_dou(
        data_referencia=data_referencia,
        finalidades=finalidades,
    )

    data_str = status["data_referencia"]

    caminho = STATUS_OPERACIONAL_DIR / f"status_operacional_dou_{data_str}.json"

    status["arquivo_saida"] = _caminho_relativo(caminho)

    _salvar_json(caminho, status)

    return status


# ============================================================
# STATUS OPERACIONAL DOU — PERÍODO
# ============================================================

def _listar_dias_periodo(
    data_inicio: DataEntrada,
    data_fim: DataEntrada,
    apenas_dias_uteis: bool = True,
) -> List[str]:
    inicio = _converter_para_date(data_inicio)
    fim = _converter_para_date(data_fim)

    if fim < inicio:
        raise ValueError(
            f"Data fim menor que data início: {fim} < {inicio}"
        )

    dias: List[str] = []
    atual = inicio

    while atual <= fim:
        if apenas_dias_uteis:
            if atual.weekday() < 5:
                dias.append(atual.isoformat())
        else:
            dias.append(atual.isoformat())

        atual += dt.timedelta(days=1)

    return dias


def _montar_status_periodo_finalidade(
    data_inicio_str: str,
    data_fim_str: str,
    finalidade: str,
) -> Dict[str, Any]:
    """
    Verifica artefatos consolidados por período para uma finalidade.
    """
    status: Dict[str, Any] = {
        "finalidade": finalidade,
        "consolidado_periodo": _obter_info_arquivo(
            caminho=(
                CONSOLIDADOS_PERIODO_DIR
                / f"consolidado_{finalidade}_{data_inicio_str}_a_{data_fim_str}.json"
            ),
            nome=f"consolidado_periodo_{finalidade}",
            descricao=f"Consolidado por período da finalidade {finalidade}.",
            obrigatorio=False,
        ),
    }

    if finalidade == "informativos":
        status["pre_boletim_json"] = _obter_info_arquivo(
            caminho=(
                BOLETINS_DIR
                / "informativos"
                / f"pre_boletim_informativos_{data_inicio_str}_a_{data_fim_str}.json"
            ),
            nome="pre_boletim_informativos_json",
            descricao="Pré-boletim informativos em JSON para o período.",
            obrigatorio=False,
        )

        status["pre_boletim_txt"] = _obter_info_arquivo(
            caminho=(
                BOLETINS_DIR
                / "informativos"
                / f"pre_boletim_informativos_{data_inicio_str}_a_{data_fim_str}.txt"
            ),
            nome="pre_boletim_informativos_txt",
            descricao="Pré-boletim informativos em TXT para o período.",
            obrigatorio=False,
        )

        status["prompt_ia_pre_boletim"] = _obter_info_arquivo(
            caminho=(
                BOLETINS_DIR
                / "informativos"
                / "prompts_ia"
                / f"prompt_ia_pre_boletim_informativos_{data_inicio_str}_a_{data_fim_str}.txt"
            ),
            nome="prompt_ia_pre_boletim_informativos",
            descricao="Prompt IA de apoio ao pré-boletim informativos.",
            obrigatorio=False,
        )

    return status


def obter_status_operacional_dou_periodo(
    data_inicio: DataEntrada,
    data_fim: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
    apenas_dias_uteis: bool = True,
) -> Dict[str, Any]:
    """
    Retorna o status operacional do DOU para um período.

    Exemplo:
        obter_status_operacional_dou_periodo(
            data_inicio="2026-05-13",
            data_fim="2026-05-14",
        )
    """
    data_inicio_str = _normalizar_data(data_inicio)
    data_fim_str = _normalizar_data(data_fim)

    finalidades_uso = list(finalidades or FINALIDADES_PADRAO)

    dias = _listar_dias_periodo(
        data_inicio=data_inicio_str,
        data_fim=data_fim_str,
        apenas_dias_uteis=apenas_dias_uteis,
    )

    status_dias = [
        obter_status_operacional_dou(
            data_referencia=dia,
            finalidades=finalidades_uso,
        )
        for dia in dias
    ]

    payload: Dict[str, Any] = {
        "tipo": "status_operacional_dou_periodo",
        "fonte": "dou",
        "data_inicio": data_inicio_str,
        "data_fim": data_fim_str,
        "apenas_dias_uteis": apenas_dias_uteis,
        "gerado_em": _agora_iso(),
        "dias_considerados": dias,
        "total_dias_considerados": len(dias),
        "status_periodo_finalidades": {},
        "status_dias": status_dias,
    }

    for finalidade in finalidades_uso:
        payload["status_periodo_finalidades"][finalidade] = (
            _montar_status_periodo_finalidade(
                data_inicio_str=data_inicio_str,
                data_fim_str=data_fim_str,
                finalidade=finalidade,
            )
        )

    payload["resumo"] = _montar_resumo_checks(payload)

    return payload


def salvar_status_operacional_dou_periodo(
    data_inicio: DataEntrada,
    data_fim: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
    apenas_dias_uteis: bool = True,
) -> Dict[str, Any]:
    """
    Gera o status operacional por período e salva snapshot em JSON.
    """
    _garantir_pasta_status_operacional()

    status = obter_status_operacional_dou_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        finalidades=finalidades,
        apenas_dias_uteis=apenas_dias_uteis,
    )

    data_inicio_str = status["data_inicio"]
    data_fim_str = status["data_fim"]

    caminho = (
        STATUS_OPERACIONAL_DIR
        / f"status_operacional_dou_{data_inicio_str}_a_{data_fim_str}.json"
    )

    status["arquivo_saida"] = _caminho_relativo(caminho)

    _salvar_json(caminho, status)

    return status


# ============================================================
# API INTERNA SIMPLES
# ============================================================

def obter_resumo_status_data(
    data_referencia: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Retorna apenas o resumo do status de uma data.
    Útil para API/front quando não quiser carregar todo o detalhe.
    """
    status = obter_status_operacional_dou(
        data_referencia=data_referencia,
        finalidades=finalidades,
    )

    return {
        "fonte": status["fonte"],
        "data_referencia": status["data_referencia"],
        "gerado_em": status["gerado_em"],
        "resumo": status["resumo"],
    }


def obter_resumo_status_periodo(
    data_inicio: DataEntrada,
    data_fim: DataEntrada,
    finalidades: Optional[Sequence[str]] = None,
    apenas_dias_uteis: bool = True,
) -> Dict[str, Any]:
    """
    Retorna apenas o resumo do status de um período.
    Útil para API/front quando não quiser carregar todo o detalhe.
    """
    status = obter_status_operacional_dou_periodo(
        data_inicio=data_inicio,
        data_fim=data_fim,
        finalidades=finalidades,
        apenas_dias_uteis=apenas_dias_uteis,
    )

    return {
        "fonte": status["fonte"],
        "data_inicio": status["data_inicio"],
        "data_fim": status["data_fim"],
        "apenas_dias_uteis": status["apenas_dias_uteis"],
        "gerado_em": status["gerado_em"],
        "total_dias_considerados": status["total_dias_considerados"],
        "resumo": status["resumo"],
    }