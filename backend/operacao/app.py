from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.operacao.config import (
    AMBIENTE,
    STATIC_DIR,
    TEMPLATE_DIR,
)
from backend.operacao.services.execution_service import (
    ACOES,
    execucao_atual,
    iniciar_execucao,
)
from backend.operacao.services.status_service import (
    ler_log,
    listar_execucoes,
    listar_logs,
    listar_processos,
    status_geral,
)


app = FastAPI(
    title="Painel Operacional DOU",
    version="1.0.0",
    description=(
        "Visibilidade e operação controlada do processamento DOU."
    ),
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC_DIR)),
    name="static",
)


class ExecutarRequest(BaseModel):
    acao: str
    confirmacao: str
    data_referencia: str | None = None
    forcar: bool = False


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(TEMPLATE_DIR / "index.html")


@app.get("/api/health")
def health():
    return {
        "status": "OK",
        "ambiente": AMBIENTE,
        "execucao_atual": execucao_atual(),
    }


@app.get("/api/status")
def api_status():
    return status_geral()


@app.get("/api/processos")
def api_processos():
    return {
        "total": len(listar_processos()),
        "itens": listar_processos(),
    }


@app.get("/api/execucoes")
def api_execucoes(
    limite: int = Query(default=50, ge=1, le=200),
):
    itens = listar_execucoes(limite=limite)
    return {
        "total": len(itens),
        "itens": itens,
    }


@app.get("/api/logs")
def api_logs(
    limite: int = Query(default=80, ge=1, le=250),
):
    itens = listar_logs(limite=limite)
    return {
        "total": len(itens),
        "itens": itens,
    }


@app.get("/api/logs/conteudo")
def api_log_conteudo(
    path: str = Query(min_length=1),
):
    try:
        return ler_log(path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Arquivo não encontrado.",
        )
    except ValueError as erro:
        raise HTTPException(
            status_code=400,
            detail=str(erro),
        )


@app.get("/api/acoes")
def api_acoes():
    return {
        "ambiente": AMBIENTE,
        "acoes": [
            {
                "codigo": codigo,
                "titulo": dados["titulo"],
                "aceita_data": dados["aceita_data"],
            }
            for codigo, dados in ACOES.items()
        ],
    }


@app.post("/api/executar", status_code=202)
def api_executar(payload: ExecutarRequest):
    try:
        item = iniciar_execucao(
            acao=payload.acao,
            confirmacao=payload.confirmacao,
            data_referencia=payload.data_referencia,
            forcar=payload.forcar,
        )
        return {
            "status": "ACEITO",
            "execucao": item,
        }
    except ValueError as erro:
        raise HTTPException(
            status_code=400,
            detail=str(erro),
        )
    except RuntimeError as erro:
        raise HTTPException(
            status_code=409,
            detail=str(erro),
        )
