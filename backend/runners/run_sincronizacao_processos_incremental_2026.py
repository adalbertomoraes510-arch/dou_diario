# -*- coding: utf-8 -*-
"""
Runner automático — sincronização e revisão histórica de processos — 2026.

Responsabilidades desta etapa:
- sincronizar a planilha com o controle incremental;
- identificar processos novos;
- executar revisão histórica somente dos processos pendentes;
- promover automaticamente para ATIVO_INCREMENTAL quando a revisão
  terminar sem erros;
- não pesquisar novamente o histórico dos processos já ativos;
- não enviar e-mail;
- não alterar o runner oficial do DOU nesta etapa.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from backend.runners.run_revisao_historica_processos_pendentes_2026 import (
    executar as executar_revisao_historica_pendentes,
)
from backend.services.controle_monitoramento_processos_service import (
    CAMINHO_CONTROLE,
    obter_processos_historicos_pendentes,
    sincronizar_com_planilha,
)


ROOT_DIR = Path(__file__).resolve().parents[2]

PASTA_LOGS = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "pesquisas"
    / "processos_2026"
    / "logs"
)

CAMINHO_ULTIMO_STATUS = (
    PASTA_LOGS
    / "ultimo_status_sincronizacao_historica_2026.json"
)


def salvar_json(caminho: Path, payload: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    temporario.replace(caminho)


def executar() -> dict[str, Any]:
    print("=" * 80)
    print("SINCRONIZAÇÃO AUTOMÁTICA DE PROCESSOS — 2026")
    print("=" * 80)

    sincronizacao = sincronizar_com_planilha()
    pendentes = obter_processos_historicos_pendentes()

    print(f"Processos na planilha: {sincronizacao.get('processos_planilha', 0)}")
    print(f"Ativos incrementais: {sincronizacao.get('ativos_incrementais', 0)}")
    print(f"Históricos pendentes: {len(pendentes)}")
    print(f"Inativos: {sincronizacao.get('inativos', 0)}")

    if sincronizacao.get("novos"):
        print(f"Novos: {', '.join(sincronizacao['novos'])}")

    if sincronizacao.get("removidos"):
        print(f"Removidos: {', '.join(sincronizacao['removidos'])}")

    if sincronizacao.get("reativados"):
        print(f"Reativados: {', '.join(sincronizacao['reativados'])}")

    print("=" * 80)

    if not pendentes:
        resultado = {
            "status": "SINCRONIZADO_SEM_HISTORICOS_PENDENTES",
            "sincronizacao": sincronizacao,
            "processos_historicos_pendentes": [],
            "revisao_historica": None,
            "controle": str(CAMINHO_CONTROLE),
        }

        salvar_json(CAMINHO_ULTIMO_STATUS, resultado)

        print("Nenhum processo novo exige revisão histórica.")
        print("Nenhum acervo anual foi reprocessado.")
        print(f"Status salvo em: {CAMINHO_ULTIMO_STATUS}")
        print("=" * 80)

        return resultado

    print("=" * 80)
    print("INICIANDO REVISÃO HISTÓRICA AUTOMÁTICA")
    print("=" * 80)
    print(
        "Somente os processos com status "
        "NOVO_HISTORICO_PENDENTE serão pesquisados."
    )

    for processo in pendentes:
        print(f"- {processo}")

    print("=" * 80)

    try:
        revisao = executar_revisao_historica_pendentes(
            confirmar=True,
        )

        resultado = {
            "status": "SUCESSO",
            "sincronizacao": sincronizacao,
            "processos_historicos_pendentes": pendentes,
            "revisao_historica": revisao,
            "controle": str(CAMINHO_CONTROLE),
        }

        salvar_json(CAMINHO_ULTIMO_STATUS, resultado)

        print("=" * 80)
        print("SINCRONIZAÇÃO E REVISÃO HISTÓRICA CONCLUÍDAS")
        print("=" * 80)
        print(f"Processos revisados: {len(pendentes)}")
        print(
            "Resultados históricos: "
            f"{revisao.get('total_resultados', 0)}"
        )
        print(
            "Histórico confirmado no controle: "
            f"{revisao.get('historico_confirmado_no_controle')}"
        )
        print(f"Status salvo em: {CAMINHO_ULTIMO_STATUS}")
        print("=" * 80)

        return resultado

    except Exception as erro:
        resultado = {
            "status": "ERRO",
            "erro": str(erro),
            "traceback": traceback.format_exc(),
            "sincronizacao": sincronizacao,
            "processos_historicos_pendentes": pendentes,
            "controle": str(CAMINHO_CONTROLE),
        }

        salvar_json(CAMINHO_ULTIMO_STATUS, resultado)

        print("=" * 80)
        print("ERRO NA SINCRONIZAÇÃO/REVISÃO HISTÓRICA")
        print("=" * 80)
        print(f"Erro: {erro}")
        print(
            "Os processos permanecem como "
            "NOVO_HISTORICO_PENDENTE."
        )
        print(f"Status salvo em: {CAMINHO_ULTIMO_STATUS}")
        print("=" * 80)

        raise


def main() -> None:
    executar()


if __name__ == "__main__":
    main()
