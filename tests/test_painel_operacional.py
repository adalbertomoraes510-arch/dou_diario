import datetime as dt
import unittest
from unittest.mock import patch

import backend.operacao.services.execution_service as exe


class TestPainelOperacional(unittest.TestCase):

    def test_comando_incremental_usa_data(self):
        comando = exe._montar_comando(
            "INCREMENTAL_DOU",
            "2026-09-10",
        )

        self.assertIn(
            "backend.runners.run_pesquisa_processos_incremental_dou_2026",
            comando,
        )
        self.assertEqual(
            comando[-2:],
            ["--data", "2026-09-10"],
        )

    def test_comando_rejeita_acao_inexistente(self):
        with self.assertRaises(ValueError):
            exe._montar_comando("APAGAR_TUDO", None)

    def test_data_invalida_e_bloqueada(self):
        with self.assertRaises(ValueError):
            exe._montar_comando(
                "INCREMENTAL_DOU",
                "10/09/2026",
            )

    def test_orquestrador_nao_recebe_argumento_de_data(self):
        comando = exe._montar_comando(
            "ORQUESTRADOR_HOJE",
            None,
        )

        self.assertEqual(
            comando[-1],
            "backend.runners.run_orquestrador_dou_periodo",
        )


if __name__ == "__main__":
    unittest.main()
