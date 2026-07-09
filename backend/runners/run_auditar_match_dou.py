# ============================================================
# RUNNER — Auditar Match DOU
# Gera auditoria estrutural do resultado de match
# ============================================================

import asyncio
import datetime
import json
from pathlib import Path

from backend.services.auditoria_match_service import (
    gerar_auditoria_match,
    salvar_auditoria,
)


DATA_TESTE = datetime.date(2026, 5, 8)
FINALIDADE_CONFIG = "dou_diario"

ROOT_DIR = Path(__file__).resolve().parents[2]

MATCH_DIR = (
    ROOT_DIR
    / "backend"
    / "data"
    / "dou"
    / "match"
    / FINALIDADE_CONFIG
)

ARQUIVO_MATCH = (
    MATCH_DIR
    / f"match_publicacoes_{DATA_TESTE.isoformat()}.json"
)


def imprimir_publicacoes_com_match(auditoria: dict) -> None:
    publicacoes = auditoria.get("publicacoes_com_match", [])

    if not publicacoes:
        print("Nenhuma publicação com match encontrada.")
        return

    print("=" * 80)
    print("PUBLICAÇÕES COM MATCH")
    print("=" * 80)

    for idx, pub in enumerate(publicacoes, start=1):
        print(f"\n#{idx}")
        print(f"Título: {pub.get('titulo')}")
        print(f"Órgão: {pub.get('orgao')}")
        print(f"URL: {pub.get('url')}")
        print(f"Quantidade de matchs: {pub.get('quantidade_matchs')}")

        for termo in pub.get("termos", []):
            encontrados = termo.get("encontrados", [])

            print(
                f"  - Termo: {termo.get('termo')} | "
                f"Tipo: {termo.get('tipo')} | "
                f"Encontrado: {', '.join(encontrados)}"
            )


def imprimir_possiveis_falsos_positivos(auditoria: dict) -> None:
    suspeitos = auditoria.get("possiveis_falsos_positivos", [])

    if not suspeitos:
        print("\nPossíveis falsos positivos: 0")
        return

    print("=" * 80)
    print("POSSÍVEIS FALSOS POSITIVOS")
    print("=" * 80)

    for idx, item in enumerate(suspeitos, start=1):
        print(f"\n#{idx}")
        print(f"Título: {item.get('titulo')}")
        print(f"Órgão: {item.get('orgao')}")
        print(f"URL: {item.get('url')}")
        print(f"Termo: {item.get('termo')}")
        print(f"Tipo: {item.get('tipo')}")
        print(f"Encontrado: {', '.join(item.get('encontrados', []))}")
        print(f"Motivos: {'; '.join(item.get('motivos', []))}")


async def main():
    print("=" * 80)
    print("AUDITORIA MATCH — DOU")
    print(f"Data: {DATA_TESTE.isoformat()}")
    print(f"Finalidade: {FINALIDADE_CONFIG}")
    print("=" * 80)

    if not ARQUIVO_MATCH.exists():
        raise FileNotFoundError(
            f"Arquivo de match não encontrado: {ARQUIVO_MATCH}"
        )

    payload_match = json.loads(
        ARQUIVO_MATCH.read_text(encoding="utf-8")
    )

    auditoria = gerar_auditoria_match(payload_match)

    caminho_saida = salvar_auditoria(
        data_referencia=DATA_TESTE.isoformat(),
        auditoria=auditoria
    )

    resumo = auditoria.get("resumo_executivo", {})
    estatisticas = auditoria.get("estatisticas_match", {})
    suspeitos = auditoria.get("possiveis_falsos_positivos", [])

    print("=" * 80)
    print("AUDITORIA GERADA")
    print(f"Total publicações: {resumo.get('total_publicacoes')}")
    print(f"Com match: {resumo.get('com_match')}")
    print(f"Sem match: {resumo.get('sem_match')}")
    print(f"Total matchs: {resumo.get('total_matchs')}")
    print(f"Taxa match: {resumo.get('taxa_match')}%")
    print(f"Tipos de match: {estatisticas.get('tipos_match')}")
    print(f"Possíveis falsos positivos: {len(suspeitos)}")
    print(f"Arquivo: {caminho_saida}")
    print("=" * 80)

    imprimir_publicacoes_com_match(auditoria)
    imprimir_possiveis_falsos_positivos(auditoria)


if __name__ == "__main__":
    asyncio.run(main())