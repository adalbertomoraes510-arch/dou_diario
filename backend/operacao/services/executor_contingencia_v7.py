from __future__ import annotations

import argparse
import json
from datetime import date

from backend.operacao.services.contingencia_dou_service import carregar_processos_ativos


def preparar_execucao(data_execucao: date) -> dict:
    """Prepara a pesquisa de contingencia sem acessar o DOU."""
    processos = carregar_processos_ativos()

    if not processos:
        raise ValueError("Nenhum processo ativo para monitoramento.")

    return {
        "data_execucao": data_execucao.isoformat(),
        "fonte": "PORTAL_DOU_CONTINGENCIA_V7",
        "tipo_cobertura": "SOMENTE_PROCESSOS",
        "quantidade_processos": len(processos),
        "status": "PREPARADA",
    }


def executar_pesquisa(
    data_execucao: date,
    progresso_callback=None,
) -> dict:
    """Executa a pesquisa dos processos ativos usando o motor V7."""
    from backend.operacao.services.adaptador_motor_v7 import pesquisar_processos

    processos = carregar_processos_ativos()

    if not processos:
        raise ValueError("Nenhum processo ativo para pesquisa.")

    from backend.operacao.services.progress_service import registrar_evento

    total = len(processos)

    def acompanhar_progresso(evento):
        realizados = evento.get("progresso", 0)

        if not isinstance(realizados, int):
            realizados = 0

        realizados = max(0, min(realizados, total))

        registrar_evento(
            "CONTINGENCIA_V7_PROGRESSO",
            "PARCIAL",
            {
                "processos_concluidos": realizados,
                "total_processos": total,
                "percentual": round(realizados * 100 / total, 2),
                "estado": evento.get("estado", "pesquisando"),
            },
        )

        if progresso_callback is not None:
            progresso_callback(evento)

    resultado = pesquisar_processos(
        processos=processos,
        data_inicial=data_execucao,
        data_final=data_execucao,
        progresso_callback=acompanhar_progresso,
        modo_navegador="oculto",
    )

    estado = str(resultado.get("estado") or "").lower()
    falhas = resultado.get("falhas") or []
    auditoria = resultado.get("auditoria") or []
    paginacao = resultado.get("paginacao") or []

    cobertura_confirmada = (
        estado == "concluido"
        and not falhas
        and len(auditoria) == len(processos)
        and len(paginacao) == len(processos)
        and all(item.get("completa") is True for item in paginacao)
    )

    if estado == "erro":
        status_evento = "ERRO"
    elif cobertura_confirmada:
        status_evento = "CONCLUIDA"
    else:
        status_evento = "PARCIAL"

    registrar_evento(
        "CONTINGENCIA_V7",
        status_evento,
        {
            "total_processos": len(processos),
            "processos_auditados": len(auditoria),
            "publicacoes_candidatas": len(resultado.get("resultados") or []),
            "falhas": len(falhas),
            "cobertura_confirmada": cobertura_confirmada,
            "tipo_cobertura": "SOMENTE_PROCESSOS",
        },
    )

    return {
        "data_execucao": data_execucao.isoformat(),
        "fonte": "PORTAL_DOU_CONTINGENCIA_V7",
        "tipo_cobertura": "SOMENTE_PROCESSOS",
        "quantidade_processos": len(processos),
        "status": estado,
        "cobertura_confirmada": cobertura_confirmada,
        "resultados": resultado.get("resultados", []),
        "falhas": falhas,
        "auditoria": auditoria,
        "paginacao": paginacao,
    }

def salvar_resultado_execucao(resultado: dict) -> str:
    """Preserva o resultado individual da contingencia no DEV."""
    import os
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[3]

    if raiz.name.upper() != "DOU_DIARIO_DEV":
        raise RuntimeError("Gravacao da contingencia permitida somente no DEV.")

    identificador = os.getenv("DOU_EXECUCAO_ID", "").strip()

    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identificador):
        raise RuntimeError("Identificador DOU_EXECUCAO_ID ausente ou invalido.")

    pasta = raiz / "backend" / "data" / "painel_operacional" / "contingencia_v7"
    pasta.mkdir(parents=True, exist_ok=True)

    caminho = pasta / f"{identificador}.json"

    if caminho.exists():
        raise FileExistsError(
            "Resultado da contingencia ja existe para esta execucao."
        )

    with caminho.open("x", encoding="utf-8") as arquivo:
        json.dump(resultado, arquivo, ensure_ascii=False, indent=2, default=str)

    return str(caminho)

def main() -> None:
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)

    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--preparar", action="store_true")
    modo.add_argument("--executar", action="store_true")

    args = parser.parse_args()
    data_execucao = date.fromisoformat(args.data)

    if args.preparar:
        resultado = preparar_execucao(data_execucao)
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return

    raiz_projeto = Path(__file__).resolve().parents[3]

    if raiz_projeto.name.upper() != "DOU_DIARIO_DEV":
        raise SystemExit(
            "Execucao real da contingencia V7 permitida somente no DEV."
        )

    resultado = executar_pesquisa(data_execucao)
    caminho_resultado = salvar_resultado_execucao(resultado)
    print("RESULTADO_V7_SALVO:", caminho_resultado, flush=True)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))

    if not resultado.get("cobertura_confirmada", False):
        raise SystemExit(2)


if __name__ == "__main__":
    main()