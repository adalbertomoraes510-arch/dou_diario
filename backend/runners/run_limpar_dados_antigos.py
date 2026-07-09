# ============================================================
# RUNNER — Limpeza de Dados Antigos
# Executa política de retenção de dados do projeto
# ============================================================

import datetime
import json
from pathlib import Path

from backend.services.retencao_dados_service import (
    limpar_arquivos_antigos,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# True = apenas mostra o que seria removido
# False = remove de verdade
MODO_SIMULACAO = True

ROOT_DIR = Path(__file__).resolve().parents[2]

LOG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "logs_execucao"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def main():
    hoje = datetime.date.today()

    print("=" * 80)
    print("LIMPEZA DE DADOS ANTIGOS")
    print(f"Data referência: {hoje.isoformat()}")
    print(f"Modo simulação: {MODO_SIMULACAO}")
    print("=" * 80)

    resultado = limpar_arquivos_antigos(
        data_referencia=hoje,
        modo_simulacao=MODO_SIMULACAO
    )

    caminho_log = (
        LOG_DIR
        / f"limpeza_dados_antigos_{hoje.isoformat()}.json"
    )

    caminho_log.write_text(
        json.dumps(
            resultado,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("LIMPEZA FINALIZADA")
    print(f"Status: {resultado.get('status')}")
    print(f"Retenção dias: {resultado.get('retencao_dias')}")
    print(f"Data limite: {resultado.get('data_limite')}")
    print(f"Total encontrados: {resultado.get('total_encontrados')}")
    print(f"Total processados: {resultado.get('total_processados')}")
    print(f"Total erros: {resultado.get('total_erros')}")
    print(f"Log: {caminho_log}")
    print("=" * 80)

    if resultado.get("total_encontrados", 0) > 0:
        print("Arquivos encontrados para remoção:")

        for item in resultado.get("arquivos", [])[:50]:
            print(f"- {item.get('arquivo')}")

        if resultado.get("total_encontrados", 0) > 50:
            print("... lista limitada aos primeiros 50 arquivos.")


if __name__ == "__main__":
    main()