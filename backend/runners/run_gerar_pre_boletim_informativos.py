# ============================================================
# RUNNER — Gerar Pré-Boletim Informativos
# Projeto: Informativos / DOU
# ============================================================
#
# Objetivo:
# Gerar um pré-boletim informativo por dia ou período, usando
# os arquivos já gerados da finalidade "informativos".
#
# Este runner NÃO executa busca no DOU.
# Este runner NÃO altera match_service.py.
# Este runner NÃO altera orquestrador.
# Este runner NÃO envia e-mail.
#
# Ele apenas chama:
# backend/services/curadoria_boletim_informativos_service.py
#
# Saídas:
# - JSON estruturado do pré-boletim;
# - TXT executivo do pré-boletim;
# - TXT com prompt pronto para IA.
# ============================================================

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from backend.services.curadoria_boletim_informativos_service import (
    gerar_pre_boletim_informativos,
    diagnosticar_pre_boletim,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================
#
# Para o primeiro teste real, vamos usar o período já validado:
#
# 13/05/2026 a 14/05/2026
#
# Esse período é importante porque o consolidado informativos já havia
# apresentado 4 monitoramentos no dia 13/05 e 0 no dia 14/05.
#
# Depois da validação, você pode alterar para:
#
# DATA_INICIO = None
# DATA_FIM = None
#
# Nesse caso o runner usa a data atual.
# ============================================================

DATA_INICIO: Optional[datetime.date] = datetime.date(2026, 5, 13)
DATA_FIM: Optional[datetime.date] = datetime.date(2026, 5, 14)

# True = tenta usar o consolidado já gerado do período.
# Se não existir, o service usa relatórios/matches diários como fallback.
PREFERIR_CONSOLIDADO = True

# True = inclui também itens descartados no JSON/TXT.
# Isso é útil para auditoria da curadoria.
INCLUIR_DESCARTADOS = True


# ============================================================
# UTILITÁRIOS
# ============================================================

def imprimir_titulo(texto: str) -> None:
    print("=" * 80)
    print(texto)
    print("=" * 80)


def resolver_periodo() -> tuple[datetime.date, datetime.date]:
    """
    Resolve o período de geração do pré-boletim.

    Regra:
    - se DATA_INICIO e DATA_FIM forem None, usa a data atual;
    - se só DATA_INICIO for preenchida, usa a mesma data como fim;
    - se as duas datas forem preenchidas, usa o período informado.
    """
    hoje = datetime.date.today()

    if DATA_INICIO is None and DATA_FIM is None:
        return hoje, hoje

    if DATA_INICIO is not None and DATA_FIM is None:
        return DATA_INICIO, DATA_INICIO

    if DATA_INICIO is None and DATA_FIM is not None:
        return DATA_FIM, DATA_FIM

    assert DATA_INICIO is not None
    assert DATA_FIM is not None

    if DATA_FIM < DATA_INICIO:
        raise ValueError("DATA_FIM não pode ser menor que DATA_INICIO.")

    return DATA_INICIO, DATA_FIM


def obter_visao_executiva_resultado(resultado: Dict[str, Any]) -> Dict[str, Any]:
    """
    Obtém a visão executiva do resultado.

    Prioridade:
    1. resultado["visao_executiva"]
    2. resultado["boletim"]["metadados"]["visao_executiva"]
    3. dicionário vazio
    """
    visao = resultado.get("visao_executiva")

    if isinstance(visao, dict) and visao:
        return visao

    boletim = resultado.get("boletim") or {}
    metadados = boletim.get("metadados") or {}
    visao = metadados.get("visao_executiva")

    if isinstance(visao, dict):
        return visao

    return {}


def obter_visao_item(item: Dict[str, Any]) -> str:
    """
    Obtém a visão executiva do item, quando disponível.
    """
    metadados = item.get("metadados") or {}
    return metadados.get("visao_executiva") or ""


# ============================================================
# IMPRESSÕES NO TERMINAL
# ============================================================

def imprimir_resumo_resultado(resultado: Dict[str, Any]) -> None:
    """
    Imprime no terminal apenas o resumo operacional.
    O JSON completo fica salvo em arquivo.
    """
    print(f"Status: {resultado.get('status')}")
    print(f"Período: {resultado.get('data_inicio')} a {resultado.get('data_fim')}")
    print(f"Total publicações lidas: {resultado.get('total_publicacoes_lidas')}")
    print(f"Total itens curados: {resultado.get('total_itens_curados')}")
    print(f"Total relevantes: {resultado.get('total_relevantes')}")
    print(f"Total descartados: {resultado.get('total_descartados')}")
    print("")

    visao = obter_visao_executiva_resultado(resultado)

    print("Visão executiva:")
    print(f"- Destaques executivos: {resultado.get('total_destaques_executivos', visao.get('total_destaques_executivos', 0))}")
    print(f"- Possíveis destaques para revisão: {resultado.get('total_possiveis_destaques_revisao', visao.get('total_possiveis_destaques_revisao', 0))}")
    print(f"- Monitoramento: {resultado.get('total_monitoramento', visao.get('total_monitoramento', 0))}")
    print(f"- Revisão humana: {resultado.get('total_revisao_humana', visao.get('total_revisao_humana', 0))}")
    print(f"- Descartados: {resultado.get('total_descartados', visao.get('total_descartados', 0))}")
    print("")

    validacao = resultado.get("validacao") or {}

    print("Validação:")
    print(f"- válido: {validacao.get('valido')}")
    print(f"- erros: {len(validacao.get('erros') or [])}")
    print(f"- avisos: {len(validacao.get('avisos') or [])}")

    if validacao.get("erros"):
        print("")
        print("Erros de validação:")
        for erro in validacao.get("erros", []):
            print(f"- {erro}")

    if validacao.get("avisos"):
        print("")
        print("Avisos de validação:")
        for aviso in validacao.get("avisos", []):
            print(f"- {aviso}")

    print("")

    arquivos = resultado.get("arquivos") or {}

    print("Arquivos gerados:")
    print(f"- JSON:      {arquivos.get('json')}")
    print(f"- TXT:       {arquivos.get('txt')}")
    print(f"- Prompt IA: {arquivos.get('prompt_ia')}")
    print("")

    fontes = resultado.get("fontes") or {}

    print("Fontes usadas:")
    print(f"- usou consolidado: {fontes.get('usar_consolidado')}")
    print(f"- consolidado: {fontes.get('consolidado')}")
    print(f"- relatórios modelo: {len(fontes.get('relatorios_modelo') or [])}")
    print(f"- matches: {len(fontes.get('matches') or [])}")
    print(f"- dias úteis: {len(fontes.get('dias_uteis') or [])}")
    print(f"- fins de semana ignorados: {len(fontes.get('dias_ignorados_fim_de_semana') or [])}")
    print(f"- dias sem arquivo: {len(fontes.get('dias_sem_arquivo') or [])}")

    if fontes.get("dias_sem_arquivo"):
        print("")
        print("Dias sem arquivo:")
        for dia in fontes.get("dias_sem_arquivo", []):
            print(f"- {dia}")


def imprimir_diagnostico_boletim(resultado: Dict[str, Any]) -> None:
    """
    Imprime diagnóstico resumido por relevância, classificação, seção
    e visão executiva.
    """
    boletim = resultado.get("boletim") or {}
    diagnostico = diagnosticar_pre_boletim(boletim)

    print("")
    imprimir_titulo("DIAGNÓSTICO DO PRÉ-BOLETIM")

    print(f"Total itens: {diagnostico.get('total_itens')}")
    print("")

    print("Por relevância:")
    for chave, valor in sorted((diagnostico.get("por_relevancia") or {}).items()):
        print(f"- {chave}: {valor}")

    print("")
    print("Por classificação:")
    for chave, valor in sorted((diagnostico.get("por_classificacao") or {}).items()):
        print(f"- {chave}: {valor}")

    print("")
    print("Por seção:")
    for chave, valor in sorted((diagnostico.get("por_secao") or {}).items()):
        print(f"- {chave}: {valor}")

    print("")
    print("Por visão executiva:")
    por_visao = diagnostico.get("por_visao_executiva") or {}

    if por_visao:
        for chave, valor in sorted(por_visao.items()):
            chave_exibir = chave or "SEM_VISAO_EXECUTIVA"
            print(f"- {chave_exibir}: {valor}")
    else:
        visao = obter_visao_executiva_resultado(resultado)
        print(f"- DESTAQUE_EXECUTIVO: {visao.get('total_destaques_executivos', 0)}")
        print(f"- POSSIVEL_DESTAQUE_REVISAO: {visao.get('total_possiveis_destaques_revisao', 0)}")
        print(f"- MONITORAMENTO: {visao.get('total_monitoramento', 0)}")
        print(f"- REVISAO_HUMANA: {visao.get('total_revisao_humana', 0)}")
        print(f"- DESCARTADO: {visao.get('total_descartados', 0)}")


def imprimir_amostra_itens(resultado: Dict[str, Any], limite: int = 10) -> None:
    """
    Mostra uma amostra dos itens não descartados para conferência rápida.
    """
    boletim = resultado.get("boletim") or {}
    itens = boletim.get("itens_curados") or []

    nao_descartados = [
        item for item in itens
        if not item.get("descartado")
    ]

    print("")
    imprimir_titulo("AMOSTRA DE ITENS NÃO DESCARTADOS")

    if not nao_descartados:
        print("Nenhum item não descartado encontrado.")
        return

    for indice, item in enumerate(nao_descartados[:limite], start=1):
        print("")
        print(f"{indice}. {item.get('titulo')}")
        print(f"   Data: {item.get('data_publicacao')}")
        print(f"   Órgão: {item.get('orgao')}")
        print(f"   Relevância: {item.get('nivel_relevancia')}")
        print(f"   Classificação: {item.get('classificacao_relacao')}")
        print(f"   Seção: {item.get('secao_boletim')}")

        visao_item = obter_visao_item(item)
        if visao_item:
            print(f"   Visão executiva: {visao_item}")

        if item.get("tema"):
            print(f"   Tema: {item.get('tema')}")

        if item.get("produto_assunto"):
            print(f"   Produto/assunto: {item.get('produto_assunto')}")

        if item.get("motivo_relevancia"):
            print(f"   Motivo: {item.get('motivo_relevancia')}")

        if item.get("recomendacao_acompanhamento"):
            print(f"   Recomendação: {item.get('recomendacao_acompanhamento')}")


def imprimir_amostra_por_visao_executiva(
    resultado: Dict[str, Any],
    limite_por_grupo: int = 5,
) -> None:
    """
    Mostra os itens agrupados pela visão executiva.
    """
    boletim = resultado.get("boletim") or {}
    itens = boletim.get("itens_curados") or []

    grupos: Dict[str, list[Dict[str, Any]]] = {
        "DESTAQUE_EXECUTIVO": [],
        "POSSIVEL_DESTAQUE_REVISAO": [],
        "MONITORAMENTO": [],
        "REVISAO_HUMANA": [],
        "DESCARTADO": [],
        "SEM_VISAO_EXECUTIVA": [],
    }

    for item in itens:
        visao = obter_visao_item(item)

        if not visao:
            if item.get("descartado"):
                visao = "DESCARTADO"
            else:
                visao = "SEM_VISAO_EXECUTIVA"

        grupos.setdefault(visao, []).append(item)

    print("")
    imprimir_titulo("AMOSTRA POR VISÃO EXECUTIVA")

    ordem = [
        "DESTAQUE_EXECUTIVO",
        "POSSIVEL_DESTAQUE_REVISAO",
        "MONITORAMENTO",
        "REVISAO_HUMANA",
        "DESCARTADO",
        "SEM_VISAO_EXECUTIVA",
    ]

    for visao in ordem:
        itens_grupo = grupos.get(visao) or []

        print("")
        print(f"{visao}: {len(itens_grupo)}")

        if not itens_grupo:
            print("- Nenhum item.")
            continue

        for indice, item in enumerate(itens_grupo[:limite_por_grupo], start=1):
            print(f"- {indice}. {item.get('titulo')}")
            print(f"     Relevância: {item.get('nivel_relevancia')}")
            print(f"     Classificação: {item.get('classificacao_relacao')}")
            print(f"     Órgão: {item.get('orgao')}")

        if len(itens_grupo) > limite_por_grupo:
            print(f"  ... mais {len(itens_grupo) - limite_por_grupo} item(ns).")


# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def main() -> None:
    imprimir_titulo("GERAR PRÉ-BOLETIM INFORMATIVOS")

    data_inicio, data_fim = resolver_periodo()

    print(f"Data início: {data_inicio}")
    print(f"Data fim: {data_fim}")
    print(f"Preferir consolidado: {PREFERIR_CONSOLIDADO}")
    print(f"Incluir descartados: {INCLUIR_DESCARTADOS}")
    print("")

    resultado = gerar_pre_boletim_informativos(
        data_inicio=data_inicio,
        data_fim=data_fim,
        preferir_consolidado=PREFERIR_CONSOLIDADO,
        incluir_descartados=INCLUIR_DESCARTADOS,
    )

    imprimir_titulo("RESULTADO DO PRÉ-BOLETIM")
    imprimir_resumo_resultado(resultado)
    imprimir_diagnostico_boletim(resultado)
    imprimir_amostra_itens(resultado)
    imprimir_amostra_por_visao_executiva(resultado)

    imprimir_titulo("PRÉ-BOLETIM FINALIZADO")


if __name__ == "__main__":
    main()