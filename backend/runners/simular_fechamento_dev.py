# -*- coding: utf-8 -*-
"""Simulacao isolada do fechamento diario. Sem SMTP e sem pesquisas."""

import argparse
import datetime as dt
from pathlib import Path
from unittest.mock import patch
import tempfile
import json

from backend.runners import run_dia_integral_dev_v6 as runner
from backend.services import registro_pesquisa_diaria_fontes_service as reg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    dia = dt.date.fromisoformat(args.data).isoformat()
    raiz = Path(__file__).resolve().parents[2]

    if raiz.name.lower() != "dou_diario_dev":
        raise RuntimeError("Simulador permitido apenas no DEV.")

    origem = (
        raiz / "backend/data/dou/pesquisas/processos_2026"
        / "teste_dia_isolado_fresco_v3" / dia
    )

    arquivo_grade = origem / "grade" / (dia + ".json")
    evidencia = origem / "evidencias/dou_inlabs_palavras_chave.json"

    if not arquivo_grade.is_file() or not evidencia.is_file():
        raise RuntimeError("Grade ou evidencia INLABS ausente.")

    with tempfile.TemporaryDirectory(prefix="dou_fechamento_dev_") as tmp:
        pasta = Path(tmp)
        grade = pasta / "grade"
        grade.mkdir()
        (grade / arquivo_grade.name).write_bytes(arquivo_grade.read_bytes())

        evidencias = pasta / "evidencias"
        evidencias.mkdir()
        (evidencias / evidencia.name).write_bytes(evidencia.read_bytes())

        resumo, completo, linhas, _ = runner.preparar_relatorio_email(
            dia, grade, reg
        )
        assert len(linhas) == 108

        assunto, texto, html = runner.montar_mensagem_email(
            dia, resumo, completo, linhas, grade
        )

        chamadas = []

        def envio_simulado(**kwargs):
            chamadas.append(kwargs)
            return {"status": "ENVIADO"}

        with patch.object(
            runner, "configuracao_email_dev",
            return_value="teste@example.invalid"
        ), patch(
            "backend.services.email_service.enviar_email",
            side_effect=envio_simulado
        ):
            resultado = runner.enviar_relatorio_operacional_dev(
                dia, grade, reg
            )

        assert resultado["status"] == "ENVIADO"
        assert len(chamadas) == 1

        print("SIMULACAO_FECHAMENTO: APROVADA")
        print("DATA:", dia)
        print("PROCESSOS:", len(set(x[0] for x in linhas)))
        print("REGISTROS:", len(linhas))
        print("COBERTURA:", "INTEGRAL" if completo else "PARCIAL")
        print("EMAIL_SIMULADO: OK")
        print("SMTP_REAL: NAO")
        print("PESQUISAS_EXECUTADAS: NAO")
        print("DADOS_ORIGINAIS_ALTERADOS: NAO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
