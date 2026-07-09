# ============================================================
# RUNNER — Gerar Relatório Executivo DOU
# Gera modelo JSON e relatório TXT a partir da auditoria nova
# ============================================================

import datetime
import sys

from backend.services.relatorio_executivo_dou_service import (
    gerar_relatorio_executivo_dou,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 12)
FINALIDADE = "dou_diario"


# ============================================================
# AJUSTE UTF-8 TERMINAL
# ============================================================

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ============================================================
# MAIN
# ============================================================

def main():
    data_txt = DATA_EXECUCAO.isoformat()

    print("=" * 80)
    print("RUNNER — GERAR RELATÓRIO EXECUTIVO DOU")
    print("=" * 80)
    print(f"Data execução: {data_txt}")
    print(f"Finalidade: {FINALIDADE}")
    print("=" * 80)

    resultado = gerar_relatorio_executivo_dou(
        data_referencia=data_txt,
        finalidade=FINALIDADE,
        salvar=True
    )

    modelo = resultado["modelo"]
    resumo = modelo.get("resumo_executivo", {})
    arquivos = resultado.get("arquivos", {})

    print("=" * 80)
    print("RELATÓRIO EXECUTIVO GERADO COM SUCESSO")
    print("=" * 80)
    print(f"Total publicações: {resumo.get('total_publicacoes')}")
    print(f"Com match: {resumo.get('com_match')}")
    print(
        "Relevantes confirmadas: "
        f"{resumo.get('publicacoes_relevantes_confirmadas')}"
    )
    print(
        "Com suspeita falso positivo: "
        f"{resumo.get('publicacoes_com_suspeita_falso_positivo')}"
    )
    print(f"Taxa match: {resumo.get('taxa_match')}%")
    print(f"Taxa match confirmado: {resumo.get('taxa_match_confirmado')}%")
    print("-" * 80)
    print(f"Modelo JSON: {arquivos.get('modelo_json')}")
    print(f"Relatório TXT: {arquivos.get('relatorio_txt')}")
    print("=" * 80)

    print("Prévia da conclusão executiva:")
    print("-" * 80)
    print(modelo.get("conclusao_executiva", ""))
    print("=" * 80)


if __name__ == "__main__":
    main()