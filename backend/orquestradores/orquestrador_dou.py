# ============================================================
# ORQUESTRADOR — DOU
# Execução oficial do pipeline DOU ponta a ponta
# Fonte oficial de coleta: INLABS via backend.drivers.dou.comum.busca_diaria
#
# Ajuste definitivo:
# - não abre Playwright na etapa oficial de busca;
# - usa o mesmo busca_diaria.py, agora convertido para INLABS;
# - reconhece publicacoes_YYYY-MM-DD.json no formato INLABS;
# - pula extração antiga por URL quando a fonte é INLABS;
# - evita reutilizar artefatos antigos zerados/legados quando há base INLABS nova.
# ============================================================

import datetime
import json
import traceback
from pathlib import Path
from typing import Any

from backend.drivers.dou.comum.busca_diaria import coletar_links_dou_diario
from backend.drivers.dou.comum.extrator_texto_integral import (
    extrair_multiplas_publicacoes,
)
from backend.services.base_publicacoes_service import (
    montar_base_publicacoes,
    salvar_base_publicacoes,
)
from backend.services.match_service import (
    aplicar_match_base,
    salvar_resultado_match,
)
from backend.services.auditoria_match_service import (
    gerar_auditoria_match,
    salvar_auditoria,
)
from backend.services.relatorio_executivo_dou_service import (
    gerar_relatorio_executivo_dou,
)
from backend.services.retencao_dados_service import (
    limpar_arquivos_antigos,
)


ROOT_DIR = Path(__file__).resolve().parents[2]

BRUTO_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"
BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "base"
MATCH_BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "match"
AUDITORIA_BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "auditoria"
RELATORIOS_BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "relatorios"
DEBUG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug"
LOG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "logs_execucao"

DEFAULT_MAX_CONCORRENCIA_EXTRACAO = 1

for pasta in [
    BRUTO_DIR,
    BASE_DIR,
    MATCH_BASE_DIR,
    AUDITORIA_BASE_DIR,
    RELATORIOS_BASE_DIR,
    DEBUG_DIR,
    LOG_DIR,
]:
    pasta.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILITÁRIOS GERAIS
# ============================================================

def agora_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def salvar_json(caminho: Path, payload: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)

    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def carregar_json(caminho: Path) -> Any:
    return json.loads(caminho.read_text(encoding="utf-8"))


def registrar_etapa(
    status_execucao: dict,
    etapa: str,
    status: str,
    detalhes: dict | None = None,
) -> None:
    status_execucao["etapas"].append({
        "timestamp": agora_iso(),
        "etapa": etapa,
        "status": status,
        "detalhes": detalhes or {},
    })

    print(f"[ORQUESTRADOR] {etapa} | {status}")


def caminhos_execucao(
    data_execucao: datetime.date,
    finalidade_config: str = "dou_diario",
) -> dict:
    data_txt = data_execucao.isoformat()

    match_dir = MATCH_BASE_DIR / finalidade_config
    auditoria_dir = AUDITORIA_BASE_DIR / finalidade_config
    relatorio_dir = RELATORIOS_BASE_DIR / finalidade_config

    match_dir.mkdir(parents=True, exist_ok=True)
    auditoria_dir.mkdir(parents=True, exist_ok=True)
    relatorio_dir.mkdir(parents=True, exist_ok=True)

    return {
        "links": BRUTO_DIR / f"links_dou_{data_txt}.json",
        "publicacoes": BRUTO_DIR / f"publicacoes_{data_txt}.json",
        "base": BASE_DIR / f"base_publicacoes_{data_txt}.json",
        "match": match_dir / f"match_publicacoes_{data_txt}.json",
        "auditoria": auditoria_dir / f"auditoria_match_{data_txt}.json",
        "relatorio_modelo": (
            relatorio_dir / f"relatorio_executivo_modelo_{data_txt}.json"
        ),
        "relatorio_txt": (
            relatorio_dir / f"relatorio_executivo_{data_txt}.txt"
        ),
        "status": (
            LOG_DIR
            / f"status_orquestrador_dou_{data_txt}_{finalidade_config}.json"
        ),
        "erro": (
            DEBUG_DIR
            / f"erro_orquestrador_dou_{data_txt}_{finalidade_config}.txt"
        ),
    }


def caminhos_status_multifinalidade(
    data_execucao: datetime.date,
) -> Path:
    data_txt = data_execucao.isoformat()

    return (
        LOG_DIR
        / f"status_orquestrador_dou_{data_txt}_multifinalidade.json"
    )


def normalizar_max_concorrencia(valor: int | None) -> int:
    if valor is None:
        return DEFAULT_MAX_CONCORRENCIA_EXTRACAO

    if valor < 1:
        return 1

    return valor


def extrair_registros_base(payload_base: dict | list) -> list[dict]:
    if isinstance(payload_base, list):
        return payload_base

    if isinstance(payload_base, dict):
        if isinstance(payload_base.get("registros"), list):
            return payload_base["registros"]

        if isinstance(payload_base.get("publicacoes"), list):
            return payload_base["publicacoes"]

    return []


def extrair_registros_match(payload_match: dict | list) -> list[dict]:
    if isinstance(payload_match, list):
        return payload_match

    if isinstance(payload_match, dict):
        if isinstance(payload_match.get("registros"), list):
            return payload_match["registros"]

    return []


def _extrair_publicacoes_payload(payload: dict | list | None) -> list[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]

    if not isinstance(payload, dict):
        return []

    for chave in ["publicacoes", "registros", "links"]:
        valor = payload.get(chave)
        if isinstance(valor, list):
            return [p for p in valor if isinstance(p, dict)]

    return []


def _payload_eh_inlabs(payload: dict | list | None) -> bool:
    if isinstance(payload, dict):
        fonte = str(payload.get("fonte") or payload.get("origem") or "").upper()
        if fonte == "INLABS":
            return True

    publicacoes = _extrair_publicacoes_payload(payload)

    if not publicacoes:
        return False

    for item in publicacoes[:10]:
        fonte_item = str(item.get("fonte") or item.get("origem") or "").upper()
        if fonte_item == "INLABS":
            return True

    return False


def _normalizar_publicacao_inlabs(item: dict) -> dict:
    """
    Garante campos mínimos esperados pelo pipeline antigo.
    O XML do INLABS já contém a íntegra; portanto status_extracao deve ser SUCESSO.
    """
    novo = dict(item)

    texto = (
        novo.get("texto_integral")
        or novo.get("texto")
        or novo.get("conteudo")
        or novo.get("texto_publicacao")
        or ""
    )

    titulo = (
        novo.get("titulo")
        or novo.get("titulo_listagem")
        or novo.get("identifica")
        or novo.get("ementa")
        or "Publicação INLABS"
    )

    novo.setdefault("fonte", "INLABS")
    novo.setdefault("origem", "INLABS")
    novo.setdefault("status_extracao", "SUCESSO")
    novo.setdefault("titulo", titulo)
    novo.setdefault("titulo_listagem", titulo)
    novo.setdefault("texto_integral", texto)
    novo.setdefault("texto_publicacao", texto)
    novo.setdefault("conteudo", texto)
    novo.setdefault("url", novo.get("url_publicacao") or novo.get("link") or "")
    novo.setdefault("url_publicacao", novo.get("url") or "")
    novo.setdefault("resumo_listagem", str(texto)[:500] if texto else "")

    return novo


def _normalizar_payload_publicacoes(
    data_execucao: datetime.date,
    payload: dict | list,
    fonte_padrao: str = "INLABS",
) -> dict:
    publicacoes = _extrair_publicacoes_payload(payload)

    if fonte_padrao.upper() == "INLABS" or _payload_eh_inlabs(payload):
        publicacoes = [_normalizar_publicacao_inlabs(p) for p in publicacoes]

    sucesso = sum(
        1 for p in publicacoes
        if str(p.get("status_extracao") or "SUCESSO").upper() == "SUCESSO"
    )

    erro = sum(
        1 for p in publicacoes
        if str(p.get("status_extracao") or "").upper() == "ERRO"
    )

    return {
        "data": data_execucao.isoformat(),
        "status": "FINALIZADO" if publicacoes else "SEM_PUBLICACOES",
        "fonte": fonte_padrao,
        "origem": fonte_padrao,
        "total_links_disponiveis": len(publicacoes),
        "total_extraidas": len(publicacoes),
        "total_publicacoes": len(publicacoes),
        "sucesso": sucesso,
        "erro": erro,
        "publicacoes": publicacoes,
    }


def _total_publicacoes_auditoria(auditoria: dict) -> int | None:
    if not isinstance(auditoria, dict):
        return None

    resumo = auditoria.get("resumo_executivo") or {}

    for chave in ["total_publicacoes", "total_registros"]:
        valor = resumo.get(chave)
        if isinstance(valor, int):
            return valor

    return None


def inicializar_status_execucao(
    data_execucao: datetime.date,
    pipeline: str,
    finalidade_config: str | None,
    parametros: dict,
    forcar_reprocessamento: bool | dict = False,
) -> dict:
    return {
        "pipeline": pipeline,
        "data_execucao": data_execucao.isoformat(),
        "finalidade_config": finalidade_config,
        "inicio": agora_iso(),
        "fim": None,
        "status": "EM_EXECUCAO",
        "erro": None,
        "forcar_reprocessamento": forcar_reprocessamento,
        "parametros": parametros,
        "etapas": [],
        "resultado": {},
    }


def montar_resultado_orquestrador(
    auditoria: dict,
    arquivos_relatorio: dict,
    resultado_retencao: dict | None,
    max_concorrencia_extracao: int,
) -> dict:
    resumo = auditoria.get("resumo_executivo", {})
    estatisticas = auditoria.get("estatisticas_match", {})
    suspeitos = auditoria.get("possiveis_falsos_positivos", [])

    return {
        "total_publicacoes": resumo.get("total_publicacoes"),
        "com_match": resumo.get("com_match"),
        "sem_match": resumo.get("sem_match"),
        "total_matchs": resumo.get("total_matchs"),
        "taxa_match": resumo.get("taxa_match"),
        "score_publicacao": estatisticas.get("score_publicacao"),
        "possiveis_falsos_positivos": len(suspeitos),
        "max_concorrencia_extracao": max_concorrencia_extracao,
        "relatorio_executivo": arquivos_relatorio,
        "retencao": resultado_retencao,
    }


def normalizar_finalidades_config(
    finalidades_config: list[str] | tuple[str, ...] | str,
) -> list[str]:
    if isinstance(finalidades_config, str):
        finalidades = [finalidades_config]
    else:
        finalidades = list(finalidades_config or [])

    finalidades_normalizadas = []

    for finalidade in finalidades:
        finalidade_txt = str(finalidade).strip()

        if finalidade_txt and finalidade_txt not in finalidades_normalizadas:
            finalidades_normalizadas.append(finalidade_txt)

    if not finalidades_normalizadas:
        raise ValueError("Nenhuma finalidade informada para execução multifinalidade.")

    return finalidades_normalizadas


# ============================================================
# ETAPAS COMUNS DO DOU — FONTE/DATA
# ============================================================

async def executar_busca_links(
    data_execucao: datetime.date,
    max_paginas: int | None,
    headless: bool,
    status_execucao: dict,
    forcar_reprocessamento: bool = False,
) -> dict:
    """
    Busca oficial do DOU.

    Antes usava Playwright e gravava links do site.
    Agora usa o mesmo contrato de função, mas chama busca_diaria.py via INLABS.
    """
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=status_execucao.get("finalidade_config", "dou_diario"),
    )

    caminho = caminhos["links"]

    if caminho.exists() and not forcar_reprocessamento:
        payload = carregar_json(caminho)

        if _payload_eh_inlabs(payload):
            publicacoes = _extrair_publicacoes_payload(payload)

            registrar_etapa(
                status_execucao,
                etapa="BUSCA_LINKS",
                status="REUTILIZADA_INLABS",
                detalhes={
                    "arquivo": str(caminho),
                    "fonte": "INLABS",
                    "total_links": len(publicacoes),
                    "total_publicacoes": len(publicacoes),
                    "status_busca": payload.get("status_busca") if isinstance(payload, dict) else None,
                },
            )

            return payload

        registrar_etapa(
            status_execucao,
            etapa="BUSCA_LINKS",
            status="ARTEFATO_ANTIGO_IGNORADO",
            detalhes={
                "arquivo": str(caminho),
                "motivo": "Arquivo links_dou existente não é INLABS. A fonte oficial atual é INLABS.",
            },
        )

    registrar_etapa(
        status_execucao,
        etapa="BUSCA_LINKS",
        status="INICIADA",
        detalhes={
            "data": data_execucao.isoformat(),
            "fonte": "INLABS",
            "max_paginas_ignorado": max_paginas,
            "headless_ignorado": headless,
        },
    )

    resultado = await coletar_links_dou_diario(
        page=None,
        data_alvo=data_execucao,
        max_paginas=max_paginas,
    )

    salvar_json(caminho, resultado)

    registrar_etapa(
        status_execucao,
        etapa="BUSCA_LINKS",
        status="CONCLUIDA",
        detalhes={
            "status_busca": resultado.get("status_busca"),
            "fonte": resultado.get("fonte"),
            "total_links": resultado.get("total_links"),
            "total_publicacoes": resultado.get("total_publicacoes"),
            "arquivo": str(caminho),
        },
    )

    return resultado


async def executar_extracao_publicacoes(
    data_execucao: datetime.date,
    payload_links: dict,
    limite_publicacoes: int | None,
    status_execucao: dict,
    max_concorrencia_extracao: int | None = DEFAULT_MAX_CONCORRENCIA_EXTRACAO,
    forcar_reprocessamento: bool = False,
) -> dict:
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=status_execucao.get("finalidade_config", "dou_diario"),
    )

    caminho = caminhos["publicacoes"]

    max_concorrencia_extracao = normalizar_max_concorrencia(
        max_concorrencia_extracao,
    )

    payload_links_eh_inlabs = _payload_eh_inlabs(payload_links)

    if caminho.exists() and not forcar_reprocessamento:
        payload_existente = carregar_json(caminho)
        publicacoes_existentes = _extrair_publicacoes_payload(payload_existente)

        if payload_links_eh_inlabs:
            if _payload_eh_inlabs(payload_existente) and publicacoes_existentes:
                payload_normalizado = _normalizar_payload_publicacoes(
                    data_execucao=data_execucao,
                    payload=payload_existente,
                    fonte_padrao="INLABS",
                )
                salvar_json(caminho, payload_normalizado)

                registrar_etapa(
                    status_execucao,
                    etapa="EXTRACAO_PUBLICACOES",
                    status="REUTILIZADA_INLABS",
                    detalhes={
                        "arquivo": str(caminho),
                        "fonte": "INLABS",
                        "total_extraidas": payload_normalizado.get("total_extraidas"),
                        "sucesso": payload_normalizado.get("sucesso"),
                        "erro": payload_normalizado.get("erro"),
                        "observacao": "Texto integral já veio dos XMLs INLABS; extração por URL foi pulada.",
                    },
                )

                return payload_normalizado

            registrar_etapa(
                status_execucao,
                etapa="EXTRACAO_PUBLICACOES",
                status="ARTEFATO_ANTIGO_IGNORADO",
                detalhes={
                    "arquivo": str(caminho),
                    "motivo": "Arquivo publicacoes existente não contém publicações INLABS válidas.",
                },
            )
        else:
            if isinstance(payload_existente, list):
                payload_existente = _normalizar_payload_publicacoes(
                    data_execucao=data_execucao,
                    payload=payload_existente,
                    fonte_padrao="LEGADO",
                )
                salvar_json(caminho, payload_existente)

            registrar_etapa(
                status_execucao,
                etapa="EXTRACAO_PUBLICACOES",
                status="REUTILIZADA",
                detalhes={
                    "arquivo": str(caminho),
                    "total_extraidas": payload_existente.get("total_extraidas"),
                    "sucesso": payload_existente.get("sucesso"),
                    "erro": payload_existente.get("erro"),
                    "max_concorrencia_extracao": payload_existente.get(
                        "max_concorrencia_extracao"
                    ),
                },
            )

            return payload_existente

    registrar_etapa(
        status_execucao,
        etapa="EXTRACAO_PUBLICACOES",
        status="INICIADA",
        detalhes={
            "limite_publicacoes": limite_publicacoes,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "fonte": "INLABS" if payload_links_eh_inlabs else "LEGADO_URL",
        },
    )

    if payload_links_eh_inlabs:
        publicacoes = _extrair_publicacoes_payload(payload_links)

        if limite_publicacoes:
            publicacoes = publicacoes[:limite_publicacoes]

        payload = _normalizar_payload_publicacoes(
            data_execucao=data_execucao,
            payload={
                "fonte": "INLABS",
                "publicacoes": publicacoes,
            },
            fonte_padrao="INLABS",
        )

        payload["limite_publicacoes"] = limite_publicacoes
        payload["max_concorrencia_extracao"] = max_concorrencia_extracao
        payload["observacao"] = (
            "Publicações extraídas diretamente dos XMLs INLABS. "
            "Etapa antiga de extração por URL não foi executada."
        )

        salvar_json(caminho, payload)

        registrar_etapa(
            status_execucao,
            etapa="EXTRACAO_PUBLICACOES",
            status="CONCLUIDA_INLABS",
            detalhes={
                "arquivo": str(caminho),
                "fonte": "INLABS",
                "total_extraidas": payload.get("total_extraidas"),
                "sucesso": payload.get("sucesso"),
                "erro": payload.get("erro"),
                "max_concorrencia_extracao": max_concorrencia_extracao,
            },
        )

        return payload

    links = payload_links.get("links", []) if isinstance(payload_links, dict) else []

    urls = [
        item.get("url")
        for item in links
        if item.get("url")
    ]

    if not urls:
        payload = {
            "data": data_execucao.isoformat(),
            "status": "SEM_LINKS",
            "limite_publicacoes": limite_publicacoes,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "total_links_disponiveis": 0,
            "total_extraidas": 0,
            "sucesso": 0,
            "erro": 0,
            "publicacoes": [],
        }

        salvar_json(caminho, payload)

        registrar_etapa(
            status_execucao,
            etapa="EXTRACAO_PUBLICACOES",
            status="SEM_LINKS",
            detalhes={
                "arquivo": str(caminho),
                "max_concorrencia_extracao": max_concorrencia_extracao,
            },
        )

        return payload

    publicacoes = await extrair_multiplas_publicacoes(
        urls=urls,
        limite=limite_publicacoes,
        max_concorrencia=max_concorrencia_extracao,
    )

    sucesso = sum(
        1 for p in publicacoes
        if p.get("status_extracao") == "SUCESSO"
    )

    erro = sum(
        1 for p in publicacoes
        if p.get("status_extracao") == "ERRO"
    )

    payload = {
        "data": data_execucao.isoformat(),
        "status": "FINALIZADO",
        "limite_publicacoes": limite_publicacoes,
        "max_concorrencia_extracao": max_concorrencia_extracao,
        "total_links_disponiveis": len(urls),
        "total_extraidas": len(publicacoes),
        "sucesso": sucesso,
        "erro": erro,
        "publicacoes": publicacoes,
    }

    salvar_json(caminho, payload)

    registrar_etapa(
        status_execucao,
        etapa="EXTRACAO_PUBLICACOES",
        status="CONCLUIDA",
        detalhes={
            "total_links_disponiveis": len(urls),
            "total_extraidas": len(publicacoes),
            "sucesso": sucesso,
            "erro": erro,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "arquivo": str(caminho),
        },
    )

    return payload


async def executar_base_auditavel(
    data_execucao: datetime.date,
    payload_publicacoes: dict,
    status_execucao: dict,
    forcar_reprocessamento: bool = False,
) -> list[dict]:
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=status_execucao.get("finalidade_config", "dou_diario"),
    )

    caminho = caminhos["base"]
    total_publicacoes_entrada = len(_extrair_publicacoes_payload(payload_publicacoes))

    if caminho.exists() and not forcar_reprocessamento:
        payload_base = carregar_json(caminho)
        registros = extrair_registros_base(payload_base)

        if registros or total_publicacoes_entrada == 0:
            registrar_etapa(
                status_execucao,
                etapa="BASE_AUDITAVEL",
                status="REUTILIZADA",
                detalhes={
                    "arquivo": str(caminho),
                    "total_registros": len(registros),
                },
            )

            return registros

        registrar_etapa(
            status_execucao,
            etapa="BASE_AUDITAVEL",
            status="ARTEFATO_ANTIGO_IGNORADO",
            detalhes={
                "arquivo": str(caminho),
                "motivo": "Base existente estava vazia, mas a entrada atual possui publicações INLABS.",
                "total_publicacoes_entrada": total_publicacoes_entrada,
            },
        )

    registrar_etapa(
        status_execucao,
        etapa="BASE_AUDITAVEL",
        status="INICIADA",
    )

    registros = montar_base_publicacoes(payload_publicacoes)

    caminho_salvo = salvar_base_publicacoes(
        data_referencia=data_execucao.isoformat(),
        registros=registros,
    )

    registrar_etapa(
        status_execucao,
        etapa="BASE_AUDITAVEL",
        status="CONCLUIDA",
        detalhes={
            "total_registros": len(registros),
            "arquivo": str(caminho_salvo),
        },
    )

    return registros


# ============================================================
# ETAPAS POR FINALIDADE
# ============================================================

async def executar_match(
    data_execucao: datetime.date,
    registros: list[dict],
    finalidade_config: str,
    status_execucao: dict,
    forcar_reprocessamento: bool = False,
) -> dict:
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=finalidade_config,
    )

    caminho = caminhos["match"]

    if caminho.exists() and not forcar_reprocessamento:
        payload_existente = carregar_json(caminho)
        registros_match = extrair_registros_match(payload_existente)

        if registros_match or not registros:
            total_com_match = sum(
                1 for r in registros_match
                if r.get("status_match") == "COM_MATCH"
            )

            total_sem_match = sum(
                1 for r in registros_match
                if r.get("status_match") == "SEM_MATCH"
            )

            payload_match = {
                "data_referencia": data_execucao.isoformat(),
                "finalidade_config": finalidade_config,
                "total_registros": len(registros_match),
                "total_com_match": total_com_match,
                "total_sem_match": total_sem_match,
                "registros": registros_match,
            }

            registrar_etapa(
                status_execucao,
                etapa="MATCH",
                status="REUTILIZADA",
                detalhes={
                    "finalidade_config": finalidade_config,
                    "total_registros": len(registros_match),
                    "com_match": total_com_match,
                    "sem_match": total_sem_match,
                    "arquivo": str(caminho),
                },
            )

            return payload_match

        registrar_etapa(
            status_execucao,
            etapa="MATCH",
            status="ARTEFATO_ANTIGO_IGNORADO",
            detalhes={
                "finalidade_config": finalidade_config,
                "arquivo": str(caminho),
                "motivo": "Match existente estava vazio, mas a base atual possui registros.",
                "total_registros_base": len(registros),
            },
        )

    registrar_etapa(
        status_execucao,
        etapa="MATCH",
        status="INICIADA",
        detalhes={
            "finalidade_config": finalidade_config,
        },
    )

    registros_match = aplicar_match_base(
        registros=registros,
        finalidade_config=finalidade_config,
    )

    caminho_salvo = salvar_resultado_match(
        data_referencia=data_execucao.isoformat(),
        registros=registros_match,
        finalidade_config=finalidade_config,
    )

    total_com_match = sum(
        1 for r in registros_match
        if r.get("status_match") == "COM_MATCH"
    )

    total_sem_match = sum(
        1 for r in registros_match
        if r.get("status_match") == "SEM_MATCH"
    )

    payload_match = {
        "data_referencia": data_execucao.isoformat(),
        "finalidade_config": finalidade_config,
        "total_registros": len(registros_match),
        "total_com_match": total_com_match,
        "total_sem_match": total_sem_match,
        "registros": registros_match,
    }

    registrar_etapa(
        status_execucao,
        etapa="MATCH",
        status="CONCLUIDA",
        detalhes={
            "finalidade_config": finalidade_config,
            "total_registros": len(registros_match),
            "com_match": total_com_match,
            "sem_match": total_sem_match,
            "arquivo": str(caminho_salvo),
        },
    )

    return payload_match


async def executar_auditoria_match(
    data_execucao: datetime.date,
    finalidade_config: str,
    payload_match: dict,
    status_execucao: dict,
    forcar_reprocessamento: bool = False,
) -> dict:
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=finalidade_config,
    )

    caminho = caminhos["auditoria"]
    total_match_atual = int(payload_match.get("total_registros") or len(extrair_registros_match(payload_match)))

    if caminho.exists() and not forcar_reprocessamento:
        auditoria = carregar_json(caminho)

        total_auditoria_existente = _total_publicacoes_auditoria(auditoria)

        if (total_auditoria_existente and total_auditoria_existente > 0) or total_match_atual == 0:
            resumo = auditoria.get("resumo_executivo", {})
            estatisticas = auditoria.get("estatisticas_match", {})
            suspeitos = auditoria.get("possiveis_falsos_positivos", [])

            registrar_etapa(
                status_execucao,
                etapa="AUDITORIA_MATCH",
                status="REUTILIZADA",
                detalhes={
                    "finalidade_config": finalidade_config,
                    "total_publicacoes": resumo.get("total_publicacoes"),
                    "com_match": resumo.get("com_match"),
                    "sem_match": resumo.get("sem_match"),
                    "total_matchs": resumo.get("total_matchs"),
                    "taxa_match": resumo.get("taxa_match"),
                    "score_publicacao": estatisticas.get("score_publicacao"),
                    "possiveis_falsos_positivos": len(suspeitos),
                    "arquivo": str(caminho),
                },
            )

            return auditoria

        registrar_etapa(
            status_execucao,
            etapa="AUDITORIA_MATCH",
            status="ARTEFATO_ANTIGO_IGNORADO",
            detalhes={
                "finalidade_config": finalidade_config,
                "arquivo": str(caminho),
                "motivo": "Auditoria existente estava vazia/zerada, mas o match atual possui registros.",
                "total_match_atual": total_match_atual,
            },
        )

    registrar_etapa(
        status_execucao,
        etapa="AUDITORIA_MATCH",
        status="INICIADA",
        detalhes={
            "finalidade_config": finalidade_config,
        },
    )

    auditoria = gerar_auditoria_match(payload_match)

    caminho_salvo = salvar_auditoria(
        data_referencia=data_execucao.isoformat(),
        auditoria=auditoria,
    )

    resumo = auditoria.get("resumo_executivo", {})
    estatisticas = auditoria.get("estatisticas_match", {})
    suspeitos = auditoria.get("possiveis_falsos_positivos", [])

    registrar_etapa(
        status_execucao,
        etapa="AUDITORIA_MATCH",
        status="CONCLUIDA",
        detalhes={
            "finalidade_config": finalidade_config,
            "total_publicacoes": resumo.get("total_publicacoes"),
            "com_match": resumo.get("com_match"),
            "sem_match": resumo.get("sem_match"),
            "total_matchs": resumo.get("total_matchs"),
            "taxa_match": resumo.get("taxa_match"),
            "score_publicacao": estatisticas.get("score_publicacao"),
            "possiveis_falsos_positivos": len(suspeitos),
            "arquivo": str(caminho_salvo),
        },
    )

    return auditoria


async def executar_relatorio_executivo(
    data_execucao: datetime.date,
    finalidade_config: str,
    status_execucao: dict,
    forcar_reprocessamento: bool = False,
) -> dict:
    caminhos = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=finalidade_config,
    )

    relatorio_txt = caminhos["relatorio_txt"]
    relatorio_modelo = caminhos["relatorio_modelo"]

    if (
        relatorio_txt.exists()
        and relatorio_modelo.exists()
        and not forcar_reprocessamento
    ):
        registrar_etapa(
            status_execucao,
            etapa="RELATORIO_EXECUTIVO",
            status="REUTILIZADO",
            detalhes={
                "finalidade_config": finalidade_config,
                "arquivo": str(relatorio_txt),
                "modelo_json": str(relatorio_modelo),
            },
        )

        return {
            "modelo_json": str(relatorio_modelo),
            "relatorio_txt": str(relatorio_txt),
        }

    registrar_etapa(
        status_execucao,
        etapa="RELATORIO_EXECUTIVO",
        status="INICIADA",
        detalhes={
            "finalidade_config": finalidade_config,
        },
    )

    resultado = gerar_relatorio_executivo_dou(
        data_referencia=data_execucao.isoformat(),
        finalidade=finalidade_config,
        salvar=True,
    )

    arquivos = resultado.get("arquivos", {})

    registrar_etapa(
        status_execucao,
        etapa="RELATORIO_EXECUTIVO",
        status="CONCLUIDA",
        detalhes={
            "finalidade_config": finalidade_config,
            "arquivo": arquivos.get("relatorio_txt"),
            "modelo_json": arquivos.get("modelo_json"),
        },
    )

    return arquivos


async def executar_retencao(
    data_execucao: datetime.date,
    status_execucao: dict,
    modo_simulacao: bool = False,
) -> dict:
    registrar_etapa(
        status_execucao,
        etapa="RETENCAO_DADOS",
        status="INICIADA",
        detalhes={
            "modo_simulacao": modo_simulacao,
        },
    )

    resultado = limpar_arquivos_antigos(
        data_referencia=data_execucao,
        modo_simulacao=modo_simulacao,
    )

    registrar_etapa(
        status_execucao,
        etapa="RETENCAO_DADOS",
        status="CONCLUIDA",
        detalhes={
            "status": resultado.get("status"),
            "retencao_dias": resultado.get("retencao_dias"),
            "data_limite": resultado.get("data_limite"),
            "total_encontrados": resultado.get("total_encontrados"),
            "total_processados": resultado.get("total_processados"),
            "total_erros": resultado.get("total_erros"),
        },
    )

    return resultado


# ============================================================
# STATUS
# ============================================================

def salvar_status_execucao(
    data_execucao: datetime.date,
    finalidade_config: str,
    status_execucao: dict,
) -> Path:
    caminho = caminhos_execucao(
        data_execucao=data_execucao,
        finalidade_config=finalidade_config,
    )["status"]

    salvar_json(caminho, status_execucao)
    return caminho


def salvar_status_execucao_multifinalidade(
    data_execucao: datetime.date,
    status_execucao: dict,
) -> Path:
    caminho = caminhos_status_multifinalidade(data_execucao)

    salvar_json(caminho, status_execucao)
    return caminho


# ============================================================
# PIPELINE BASE — UMA VEZ POR DATA/FONTE
# ============================================================

async def executar_pipeline_base_dou(
    data_execucao: datetime.date,
    max_paginas: int | None = None,
    limite_publicacoes: int | None = None,
    headless: bool = False,
    forcar_reprocessamento_base: bool = False,
    max_concorrencia_extracao: int | None = DEFAULT_MAX_CONCORRENCIA_EXTRACAO,
) -> dict:
    max_concorrencia_extracao = normalizar_max_concorrencia(
        max_concorrencia_extracao,
    )

    status_execucao = inicializar_status_execucao(
        data_execucao=data_execucao,
        pipeline="DOU_BASE",
        finalidade_config="_base_dou",
        forcar_reprocessamento={
            "base": forcar_reprocessamento_base,
        },
        parametros={
            "max_paginas": max_paginas,
            "limite_publicacoes": limite_publicacoes,
            "headless": headless,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "fonte_oficial": "INLABS",
        },
    )

    registros: list[dict] = []

    print("=" * 80)
    print("ORQUESTRADOR DOU — BASE ÚNICA DA DATA")
    print(f"Data: {data_execucao.isoformat()}")
    print(f"Forçar reprocessamento base: {forcar_reprocessamento_base}")
    print(f"Concorrência máxima extração: {max_concorrencia_extracao}")
    print("Fonte oficial: INLABS")
    print("=" * 80)

    try:
        payload_links = await executar_busca_links(
            data_execucao=data_execucao,
            max_paginas=max_paginas,
            headless=headless,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_reprocessamento_base,
        )

        payload_publicacoes = await executar_extracao_publicacoes(
            data_execucao=data_execucao,
            payload_links=payload_links,
            limite_publicacoes=limite_publicacoes,
            status_execucao=status_execucao,
            max_concorrencia_extracao=max_concorrencia_extracao,
            forcar_reprocessamento=forcar_reprocessamento_base,
        )

        registros = await executar_base_auditavel(
            data_execucao=data_execucao,
            payload_publicacoes=payload_publicacoes,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_reprocessamento_base,
        )

        caminhos = caminhos_execucao(
            data_execucao=data_execucao,
            finalidade_config="_base_dou",
        )

        status_execucao["resultado"] = {
            "total_registros_base": len(registros),
            "arquivos_comuns": {
                "links": str(caminhos["links"]),
                "publicacoes": str(caminhos["publicacoes"]),
                "base": str(caminhos["base"]),
            },
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "fonte_oficial": "INLABS",
        }

        status_execucao["status"] = "SUCESSO"

        print("=" * 80)
        print("BASE DOU FINALIZADA COM SUCESSO")
        print(f"Total registros base: {len(registros)}")
        print("=" * 80)

    except Exception as e:
        status_execucao["status"] = "ERRO"
        status_execucao["erro"] = {
            "mensagem": str(e),
            "traceback": traceback.format_exc(),
        }

        erro_path = caminhos_execucao(
            data_execucao=data_execucao,
            finalidade_config="_base_dou",
        )["erro"]

        erro_path.write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )

        print("=" * 80)
        print("ERRO NA BASE DOU")
        print(f"Erro: {e}")
        print(f"Traceback salvo em: {erro_path}")
        print("=" * 80)

        raise

    finally:
        status_execucao["fim"] = agora_iso()

        caminho_status = salvar_status_execucao(
            data_execucao=data_execucao,
            finalidade_config="_base_dou",
            status_execucao=status_execucao,
        )

        print(f"Status execução base DOU: {caminho_status}")

    return {
        "status_execucao": status_execucao,
        "registros": registros,
    }


# ============================================================
# PIPELINE POR FINALIDADE — REAPROVEITA BASE
# ============================================================

async def executar_pipeline_finalidade_dou(
    data_execucao: datetime.date,
    finalidade_config: str,
    registros: list[dict],
    forcar_reprocessamento_finalidade: bool = False,
    max_concorrencia_extracao: int | None = DEFAULT_MAX_CONCORRENCIA_EXTRACAO,
) -> dict:
    max_concorrencia_extracao = normalizar_max_concorrencia(
        max_concorrencia_extracao,
    )

    status_execucao = inicializar_status_execucao(
        data_execucao=data_execucao,
        pipeline="DOU_FINALIDADE",
        finalidade_config=finalidade_config,
        forcar_reprocessamento={
            "finalidade": forcar_reprocessamento_finalidade,
        },
        parametros={
            "total_registros_base_recebidos": len(registros),
            "max_concorrencia_extracao": max_concorrencia_extracao,
        },
    )

    print("=" * 80)
    print("ORQUESTRADOR DOU — FINALIDADE")
    print(f"Data: {data_execucao.isoformat()}")
    print(f"Finalidade: {finalidade_config}")
    print(f"Forçar reprocessamento finalidade: {forcar_reprocessamento_finalidade}")
    print("=" * 80)

    try:
        payload_match = await executar_match(
            data_execucao=data_execucao,
            registros=registros,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_reprocessamento_finalidade,
        )

        auditoria = await executar_auditoria_match(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            payload_match=payload_match,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_reprocessamento_finalidade,
        )

        # Quando a base atual possui registros, regeneramos o relatório para evitar
        # reutilização de relatório antigo criado com base zerada.
        forcar_relatorio = forcar_reprocessamento_finalidade or len(registros) > 0

        arquivos_relatorio = await executar_relatorio_executivo(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_relatorio,
        )

        status_execucao["resultado"] = montar_resultado_orquestrador(
            auditoria=auditoria,
            arquivos_relatorio=arquivos_relatorio,
            resultado_retencao=None,
            max_concorrencia_extracao=max_concorrencia_extracao,
        )

        status_execucao["status"] = "SUCESSO"

        print("=" * 80)
        print("FINALIDADE DOU FINALIZADA COM SUCESSO")
        print(f"Finalidade: {finalidade_config}")
        print("=" * 80)

    except Exception as e:
        status_execucao["status"] = "ERRO"
        status_execucao["erro"] = {
            "mensagem": str(e),
            "traceback": traceback.format_exc(),
        }

        erro_path = caminhos_execucao(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
        )["erro"]

        erro_path.write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )

        print("=" * 80)
        print("ERRO NA FINALIDADE DOU")
        print(f"Finalidade: {finalidade_config}")
        print(f"Erro: {e}")
        print(f"Traceback salvo em: {erro_path}")
        print("=" * 80)

        raise

    finally:
        status_execucao["fim"] = agora_iso()

        caminho_status = salvar_status_execucao(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
        )

        print(f"Status execução finalidade DOU: {caminho_status}")

    return status_execucao


# ============================================================
# PIPELINE MULTIFINALIDADE — NOVA ARQUITETURA
# ============================================================

async def executar_pipeline_dou_multifinalidade(
    data_execucao: datetime.date,
    finalidades_config: list[str] | tuple[str, ...] | str,
    max_paginas: int | None = None,
    limite_publicacoes: int | None = None,
    headless: bool = False,
    executar_limpeza: bool = True,
    limpeza_modo_simulacao: bool = False,
    forcar_reprocessamento_base: bool = False,
    forcar_reprocessamento_finalidades: bool = False,
    max_concorrencia_extracao: int | None = DEFAULT_MAX_CONCORRENCIA_EXTRACAO,
    continuar_se_finalidade_erro: bool = True,
) -> dict:
    max_concorrencia_extracao = normalizar_max_concorrencia(
        max_concorrencia_extracao,
    )

    finalidades = normalizar_finalidades_config(finalidades_config)

    status_execucao = inicializar_status_execucao(
        data_execucao=data_execucao,
        pipeline="DOU_MULTIFINALIDADE",
        finalidade_config="multifinalidade",
        forcar_reprocessamento={
            "base": forcar_reprocessamento_base,
            "finalidades": forcar_reprocessamento_finalidades,
        },
        parametros={
            "finalidades_config": finalidades,
            "max_paginas": max_paginas,
            "limite_publicacoes": limite_publicacoes,
            "headless": headless,
            "executar_limpeza": executar_limpeza,
            "limpeza_modo_simulacao": limpeza_modo_simulacao,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "continuar_se_finalidade_erro": continuar_se_finalidade_erro,
            "fonte_oficial": "INLABS",
        },
    )

    print("=" * 80)
    print("ORQUESTRADOR OFICIAL — DOU MULTIFINALIDADE")
    print(f"Data: {data_execucao.isoformat()}")
    print(f"Finalidades: {finalidades}")
    print(f"Forçar reprocessamento base: {forcar_reprocessamento_base}")
    print(f"Forçar reprocessamento finalidades: {forcar_reprocessamento_finalidades}")
    print(f"Concorrência máxima extração: {max_concorrencia_extracao}")
    print("Fonte oficial: INLABS")
    print("=" * 80)

    resultados_finalidades: dict[str, dict] = {}
    resultado_base_status: dict | None = None
    resultado_retencao = None

    try:
        registrar_etapa(
            status_execucao,
            etapa="BASE_DOU",
            status="INICIADA",
            detalhes={
                "forcar_reprocessamento_base": forcar_reprocessamento_base,
                "fonte_oficial": "INLABS",
            },
        )

        resultado_base = await executar_pipeline_base_dou(
            data_execucao=data_execucao,
            max_paginas=max_paginas,
            limite_publicacoes=limite_publicacoes,
            headless=headless,
            forcar_reprocessamento_base=forcar_reprocessamento_base,
            max_concorrencia_extracao=max_concorrencia_extracao,
        )

        resultado_base_status = resultado_base.get("status_execucao", {})
        registros = resultado_base.get("registros", [])

        registrar_etapa(
            status_execucao,
            etapa="BASE_DOU",
            status="CONCLUIDA",
            detalhes={
                "status_base": resultado_base_status.get("status"),
                "total_registros_base": len(registros),
            },
        )

        for indice, finalidade in enumerate(finalidades, start=1):
            registrar_etapa(
                status_execucao,
                etapa="FINALIDADE_DOU",
                status="INICIADA",
                detalhes={
                    "indice": indice,
                    "total_finalidades": len(finalidades),
                    "finalidade_config": finalidade,
                    "forcar_reprocessamento_finalidade": forcar_reprocessamento_finalidades,
                },
            )

            try:
                resultado_finalidade = await executar_pipeline_finalidade_dou(
                    data_execucao=data_execucao,
                    finalidade_config=finalidade,
                    registros=registros,
                    forcar_reprocessamento_finalidade=forcar_reprocessamento_finalidades,
                    max_concorrencia_extracao=max_concorrencia_extracao,
                )

                resultados_finalidades[finalidade] = resultado_finalidade

                registrar_etapa(
                    status_execucao,
                    etapa="FINALIDADE_DOU",
                    status="CONCLUIDA",
                    detalhes={
                        "finalidade_config": finalidade,
                        "status_finalidade": resultado_finalidade.get("status"),
                    },
                )

            except Exception as erro_finalidade:
                resultados_finalidades[finalidade] = {
                    "pipeline": "DOU_FINALIDADE",
                    "data_execucao": data_execucao.isoformat(),
                    "finalidade_config": finalidade,
                    "status": "ERRO",
                    "erro": {
                        "mensagem": str(erro_finalidade),
                        "traceback": traceback.format_exc(),
                    },
                    "resultado": {},
                }

                registrar_etapa(
                    status_execucao,
                    etapa="FINALIDADE_DOU",
                    status="ERRO",
                    detalhes={
                        "finalidade_config": finalidade,
                        "erro": str(erro_finalidade),
                    },
                )

                if not continuar_se_finalidade_erro:
                    raise

        if executar_limpeza:
            resultado_retencao = await executar_retencao(
                data_execucao=datetime.date.today(),
                status_execucao=status_execucao,
                modo_simulacao=limpeza_modo_simulacao,
            )

        total_erros = sum(
            1 for resultado in resultados_finalidades.values()
            if resultado.get("status") == "ERRO"
        )

        status_execucao["resultado"] = {
            "base": (
                resultado_base_status.get("resultado", {})
                if resultado_base_status else {}
            ),
            "finalidades": {
                finalidade: {
                    "status": resultado.get("status"),
                    "resultado": resultado.get("resultado", {}),
                }
                for finalidade, resultado in resultados_finalidades.items()
            },
            "total_finalidades": len(resultados_finalidades),
            "total_finalidades_sucesso": len(resultados_finalidades) - total_erros,
            "total_finalidades_erro": total_erros,
            "retencao": resultado_retencao,
        }

        status_execucao["status"] = (
            "SUCESSO" if total_erros == 0 else "ERRO_PARCIAL"
        )

        print("=" * 80)
        print("ORQUESTRADOR DOU MULTIFINALIDADE FINALIZADO")
        print(f"Status: {status_execucao['status']}")
        print("=" * 80)

    except Exception as e:
        status_execucao["status"] = "ERRO"
        status_execucao["erro"] = {
            "mensagem": str(e),
            "traceback": traceback.format_exc(),
        }

        erro_path = (
            DEBUG_DIR
            / f"erro_orquestrador_dou_{data_execucao.isoformat()}_multifinalidade.txt"
        )

        erro_path.write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )

        print("=" * 80)
        print("ERRO NO ORQUESTRADOR DOU MULTIFINALIDADE")
        print(f"Erro: {e}")
        print(f"Traceback salvo em: {erro_path}")
        print("=" * 80)

        raise

    finally:
        status_execucao["fim"] = agora_iso()

        caminho_status = salvar_status_execucao_multifinalidade(
            data_execucao=data_execucao,
            status_execucao=status_execucao,
        )

        print(f"Status execução multifinalidade: {caminho_status}")

    return status_execucao


# ============================================================
# PIPELINE LEGADO — UMA FINALIDADE
# Mantido para não quebrar runners existentes
# ============================================================

async def executar_pipeline_dou(
    data_execucao: datetime.date,
    finalidade_config: str = "dou_diario",
    max_paginas: int | None = None,
    limite_publicacoes: int | None = None,
    headless: bool = False,
    executar_limpeza: bool = True,
    limpeza_modo_simulacao: bool = False,
    forcar_reprocessamento: bool = False,
    max_concorrencia_extracao: int | None = DEFAULT_MAX_CONCORRENCIA_EXTRACAO,
    forcar_reprocessamento_base: bool | None = None,
    forcar_reprocessamento_finalidade: bool | None = None,
) -> dict:
    """
    Executa o pipeline DOU para uma única finalidade.
    Mantido para compatibilidade com runners antigos.
    Fonte oficial atual da base: INLABS.
    """

    max_concorrencia_extracao = normalizar_max_concorrencia(
        max_concorrencia_extracao,
    )

    forcar_base = (
        forcar_reprocessamento
        if forcar_reprocessamento_base is None
        else forcar_reprocessamento_base
    )

    forcar_finalidade = (
        forcar_reprocessamento
        if forcar_reprocessamento_finalidade is None
        else forcar_reprocessamento_finalidade
    )

    status_execucao = {
        "pipeline": "DOU",
        "data_execucao": data_execucao.isoformat(),
        "finalidade_config": finalidade_config,
        "inicio": agora_iso(),
        "fim": None,
        "status": "EM_EXECUCAO",
        "erro": None,
        "forcar_reprocessamento": forcar_reprocessamento,
        "forcar_reprocessamento_base": forcar_base,
        "forcar_reprocessamento_finalidade": forcar_finalidade,
        "parametros": {
            "max_paginas": max_paginas,
            "limite_publicacoes": limite_publicacoes,
            "headless": headless,
            "executar_limpeza": executar_limpeza,
            "limpeza_modo_simulacao": limpeza_modo_simulacao,
            "max_concorrencia_extracao": max_concorrencia_extracao,
            "fonte_oficial": "INLABS",
        },
        "etapas": [],
        "resultado": {},
    }

    print("=" * 80)
    print("ORQUESTRADOR OFICIAL — DOU")
    print(f"Data: {data_execucao.isoformat()}")
    print(f"Finalidade: {finalidade_config}")
    print(f"Forçar reprocessamento geral: {forcar_reprocessamento}")
    print(f"Forçar reprocessamento base: {forcar_base}")
    print(f"Forçar reprocessamento finalidade: {forcar_finalidade}")
    print(f"Concorrência máxima extração: {max_concorrencia_extracao}")
    print("Fonte oficial: INLABS")
    print("=" * 80)

    try:
        payload_links = await executar_busca_links(
            data_execucao=data_execucao,
            max_paginas=max_paginas,
            headless=headless,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_base,
        )

        payload_publicacoes = await executar_extracao_publicacoes(
            data_execucao=data_execucao,
            payload_links=payload_links,
            limite_publicacoes=limite_publicacoes,
            status_execucao=status_execucao,
            max_concorrencia_extracao=max_concorrencia_extracao,
            forcar_reprocessamento=forcar_base,
        )

        registros = await executar_base_auditavel(
            data_execucao=data_execucao,
            payload_publicacoes=payload_publicacoes,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_base,
        )

        payload_match = await executar_match(
            data_execucao=data_execucao,
            registros=registros,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_finalidade,
        )

        auditoria = await executar_auditoria_match(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            payload_match=payload_match,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_finalidade,
        )

        forcar_relatorio = forcar_finalidade or len(registros) > 0

        arquivos_relatorio = await executar_relatorio_executivo(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
            forcar_reprocessamento=forcar_relatorio,
        )

        resultado_retencao = None

        if executar_limpeza:
            resultado_retencao = await executar_retencao(
                data_execucao=datetime.date.today(),
                status_execucao=status_execucao,
                modo_simulacao=limpeza_modo_simulacao,
            )

        status_execucao["resultado"] = montar_resultado_orquestrador(
            auditoria=auditoria,
            arquivos_relatorio=arquivos_relatorio,
            resultado_retencao=resultado_retencao,
            max_concorrencia_extracao=max_concorrencia_extracao,
        )

        status_execucao["status"] = "SUCESSO"

        print("=" * 80)
        print("ORQUESTRADOR FINALIZADO COM SUCESSO")
        print("=" * 80)

    except Exception as e:
        status_execucao["status"] = "ERRO"
        status_execucao["erro"] = {
            "mensagem": str(e),
            "traceback": traceback.format_exc(),
        }

        erro_path = caminhos_execucao(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
        )["erro"]

        erro_path.write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )

        print("=" * 80)
        print("ERRO NO ORQUESTRADOR DOU")
        print(f"Erro: {e}")
        print(f"Traceback salvo em: {erro_path}")
        print("=" * 80)

        raise

    finally:
        status_execucao["fim"] = agora_iso()

        caminho_status = salvar_status_execucao(
            data_execucao=data_execucao,
            finalidade_config=finalidade_config,
            status_execucao=status_execucao,
        )

        print(f"Status execução: {caminho_status}")

    return status_execucao
