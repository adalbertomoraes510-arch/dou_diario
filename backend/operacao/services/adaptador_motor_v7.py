from __future__ import annotations

import threading
from copy import deepcopy
from datetime import date

from backend.operacao.services import motor_dou_v7_original as motor


_LOCK_ADAPTADOR = threading.Lock()


def pesquisar_processos(
    processos: list[dict],
    data_inicial: date,
    data_final: date,
    progresso_callback=None,
    modo_navegador: str = "oculto",
) -> dict:
    """Executa o motor V7 sem iniciar seu servidor HTTP."""

    if not processos:
        raise ValueError("Nenhum processo informado.")

    if data_inicial > data_final:
        raise ValueError("Periodo de pesquisa invalido.")

    if modo_navegador not in ("oculto", "visivel"):
        raise ValueError("Modo de navegador invalido.")

    numeros = [
        str(item["processo"]).strip()
        for item in processos
    ]

    if any(not numero for numero in numeros):
        raise ValueError("Processo sem numero.")

    if len(numeros) != len(set(numeros)):
        raise ValueError("Processos duplicados.")

    if len(numeros) > 500:
        raise ValueError("Limite de 500 processos excedido.")

    if not _LOCK_ADAPTADOR.acquire(blocking=False):
        raise RuntimeError("Contingencia V7 ja esta em execucao.")

    bloqueio_motor = False
    publicar_original = motor.publish

    try:
        bloqueio_motor = motor.BUSY.acquire(blocking=False)

        if not bloqueio_motor:
            raise RuntimeError("Motor V7 ocupado.")

        def publicar_adaptado(**valores):
            publicar_original(**valores)

            if progresso_callback is not None:
                progresso_callback(deepcopy(valores))

        motor.publish = publicar_adaptado

        publicar_original(
            estado="pesquisando",
            mensagem="Preparando contingencia V7.",
            resultados=[],
            diagnostico=[],
            falhas=[],
            paginacao=[],
            auditoria=[],
            progresso=0,
            total_processos=len(processos),
        )

        parametros = {
            "processos": processos,
            "inicio": data_inicial.isoformat(),
            "fim": data_final.isoformat(),
            "ampliada": False,
            "modo_navegador": modo_navegador,
        }

        # O motor V7 e sincrono. A integracao assincrona
        # com o orquestrador sera tratada separadamente.
        motor.pesquisar_lote(parametros)

        with motor.LOCK:
            resultado = deepcopy(motor.STATE)

        if resultado.get("estado") == "erro":
            raise RuntimeError(
                resultado.get("mensagem", "Falha geral na contingencia V7.")
            )

        return resultado

    finally:
        motor.publish = publicar_original

        # O motor normalmente libera BUSY. Em falha inesperada
        # anterior ao seu finally, o adaptador faz a limpeza.
        if bloqueio_motor and motor.BUSY.locked():
            motor.BUSY.release()

        _LOCK_ADAPTADOR.release()
