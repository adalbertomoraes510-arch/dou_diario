import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.runners.run_pesquisa_processos_incremental_dou_2026 as inc
import backend.runners.run_revisao_historica_processos_pendentes_2026 as hist
import backend.services.controle_monitoramento_processos_service as svc


class TestCatchupProcessos2026(unittest.TestCase):

    def test_bloqueia_salto_sem_catchup(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "controle.json"

            caminho.write_text(
                json.dumps(
                    {
                        "processos": {
                            "TESTE-001": {
                                "status": svc.STATUS_ATIVO_INCREMENTAL,
                                "ativo": True,
                                "historico_revisado": True,
                                "ultima_data_dou_processada": "2026-09-08",
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with patch.object(
                svc,
                "CAMINHO_CONTROLE",
                caminho,
            ):
                with self.assertRaises(RuntimeError):
                    svc.registrar_execucao_incremental(
                        ["TESTE-001"],
                        data_dou_processada="2026-09-10",
                    )

                estado = json.loads(
                    caminho.read_text(encoding="utf-8")
                )

                self.assertEqual(
                    estado["processos"]["TESTE-001"][
                        "ultima_data_dou_processada"
                    ],
                    "2026-09-08",
                )

    def test_permite_salto_com_catchup_validado(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "controle.json"

            caminho.write_text(
                json.dumps(
                    {
                        "processos": {
                            "TESTE-001": {
                                "status": svc.STATUS_ATIVO_INCREMENTAL,
                                "ativo": True,
                                "historico_revisado": True,
                                "ultima_data_dou_processada": "2026-09-08",
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with patch.object(
                svc,
                "CAMINHO_CONTROLE",
                caminho,
            ):
                resultado = svc.registrar_execucao_incremental(
                    ["TESTE-001"],
                    data_dou_processada="2026-09-10",
                    processos_catchup_validados=["TESTE-001"],
                )

                self.assertEqual(
                    resultado["saltos_validados"],
                    1,
                )

                estado = json.loads(
                    caminho.read_text(encoding="utf-8")
                )

                self.assertEqual(
                    estado["processos"]["TESTE-001"][
                        "ultima_data_dou_processada"
                    ],
                    "2026-09-10",
                )

    def test_data_referencia_define_vespera(self):
        resultado = hist.resolver_data_fim_historico(
            data_referencia=dt.date(2026, 8, 15)
        )

        self.assertEqual(
            resultado,
            dt.date(2026, 8, 14),
        )

    def test_catchup_seleciona_somente_atrasado(self):
        inicios = {
            "ATUAL": dt.date(2026, 9, 10),
            "ATRASADO": dt.date(2026, 9, 9),
        }

        chamadas = {
            "cobertura": [],
            "pesquisa": [],
        }

        def cobertura_fake(*, data_inicio, data_fim):
            chamadas["cobertura"].append(
                (
                    data_inicio.isoformat(),
                    data_fim.isoformat(),
                )
            )
            return {
                "status": "SUCESSO",
                "total_erros": 0,
            }

        def pesquisa_fake(*, processos, data_fim):
            chamadas["pesquisa"].append(
                (
                    tuple(processos),
                    data_fim.isoformat(),
                )
            )
            return (
                [],
                {
                    "total_erros": 0,
                    "total_datas": 1,
                },
            )

        with (
            patch.object(
                inc,
                "resolver_data_inicio_processo_pendente",
                side_effect=lambda processo: inicios[processo],
            ),
            patch.object(
                inc,
                "garantir_cobertura_dou_para_revisao",
                side_effect=cobertura_fake,
            ),
            patch.object(
                inc,
                "pesquisar_historico_dou_pendentes_por_faixa",
                side_effect=pesquisa_fake,
            ),
        ):
            _, resumo = (
                inc.executar_catchup_ativos_se_necessario(
                    processos=("ATUAL", "ATRASADO"),
                    data_execucao=dt.date(2026, 9, 10),
                )
            )

        self.assertEqual(
            resumo["processos"],
            ["ATRASADO"],
        )

        self.assertEqual(
            resumo["processos_catchup_validados"],
            ["ATRASADO"],
        )

        self.assertEqual(
            chamadas["cobertura"],
            [("2026-09-09", "2026-09-09")],
        )

        self.assertEqual(
            chamadas["pesquisa"],
            [(("ATRASADO",), "2026-09-09")],
        )


if __name__ == "__main__":
    unittest.main()
