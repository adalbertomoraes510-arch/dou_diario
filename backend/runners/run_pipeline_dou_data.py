# ============================================================
# RUNNER — Pipeline DOU por Data
# Executa: busca → extração → base → match → auditoria
# ============================================================

import asyncio
import datetime
import json
import traceback
from pathlib import Path

from playwright.async_api import async_playwright

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


# ============================================================
# CONFIGURAÇÃO DA EXECUÇÃO
# ============================================================

DATA_EXECUCAO = datetime.date(2026, 5, 6)
FINALIDADE_CONFIG = "dou_diario"

# None = todas as páginas
MAX_PAGINAS = None

# None = todas as publicações
LIMITE_PUBLICACOES = None

# Produção atual: False, porque o DOU tem instabilidade em headless
HEADLESS = False


ROOT_DIR = Path(__file__).resolve().parents[2]

BRUTO_DIR = ROOT_DIR / "backend" / "data" / "dou" / "bruto"
BASE_DIR = ROOT_DIR / "backend" / "data" / "dou" / "base"
DEBUG_DIR = ROOT_DIR / "backend" / "data" / "dou" / "debug"

BRUTO_DIR.mkdir(parents=True, exist_ok=True)
BASE_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def salvar_json(caminho: Path, payload: dict) -> None:
    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def imprimir_resumo_confianca(auditoria: dict) -> None:
    estatisticas = auditoria.get("estatisticas_match", {})

    scores = estatisticas.get(
        "score_confianca",
        {}
    ) or {}

    scores_publicacao = estatisticas.get(
        "score_publicacao",
        {}
    ) or {}

    if not scores and not scores_publicacao:
        print(
            "\nScore de confiança: "
            "nenhum match classificado."
        )
        return

    ordem = [
        "ALTO",
        "MEDIO",
        "BAIXO",
        "CRITICO",
        "DESCONHECIDO"
    ]

    print("=" * 80)
    print("RESUMO EXECUTIVO — MATCHES")
    print("=" * 80)

    for score in ordem:
        if score in scores:
            print(f"{score}: {scores.get(score)}")

    print("=" * 80)
    print("RESUMO EXECUTIVO — PUBLICAÇÕES")
    print("=" * 80)

    for score in ordem:
        if score in scores_publicacao:
            print(f"{score}: {scores_publicacao.get(score)}")


def imprimir_publicacoes_com_match(auditoria: dict) -> None:
    publicacoes = auditoria.get("publicacoes_com_match", [])

    if not publicacoes:
        print("Nenhuma publicação com match encontrada.")
        return

    ordem_prioridade = {
        "ALTO": 1,
        "MEDIO": 2,
        "BAIXO": 3,
        "CRITICO": 4,
        "DESCONHECIDO": 5,
    }

    publicacoes = sorted(
        publicacoes,
        key=lambda p: ordem_prioridade.get(
            p.get("score_publicacao", "DESCONHECIDO"),
            999
        )
    )

    explicacao_scores = {
        "ALTO": {
            "significado": "Match muito confiável",
            "interpretacao": (
                "Forte evidência de relevância. "
                "Pode seguir fluxo operacional com alta segurança."
            )
        },
        "MEDIO": {
            "significado": "Match razoavelmente confiável",
            "interpretacao": (
                "Publicação provavelmente relevante, "
                "mas merece validação dependendo do cenário."
            )
        },
        "BAIXO": {
            "significado": "Match pouco confiável",
            "interpretacao": (
                "Possui baixa evidência textual. "
                "Recomendado validar antes de ações automáticas."
            )
        },
        "CRITICO": {
            "significado": "Possível falso positivo",
            "interpretacao": (
                "Fortes indícios de ruído ou match incorreto. "
                "Necessita revisão prioritária."
            )
        },
        "DESCONHECIDO": {
            "significado": "Classificação indefinida",
            "interpretacao": (
                "O sistema não conseguiu classificar a confiança."
            )
        },
    }

    print("=" * 80)
    print("PUBLICAÇÕES COM MATCH")
    print("=" * 80)

    grupo_atual = None
    contador_global = 0

    for pub in publicacoes:
        score_pub = pub.get(
            "score_publicacao",
            "DESCONHECIDO"
        )

        if score_pub != grupo_atual:
            grupo_atual = score_pub

            info = explicacao_scores.get(
                score_pub,
                explicacao_scores["DESCONHECIDO"]
            )

            print("\n" + "=" * 80)
            print(f"SCORE: {score_pub}")
            print("=" * 80)

            print("Significado Operacional:")
            print(info["significado"])

            print("\nInterpretação:")
            print(info["interpretacao"])

            print("=" * 80)

        contador_global += 1

        print(f"\n#{contador_global}")
        print(f"Título: {pub.get('titulo')}")
        print(f"Órgão: {pub.get('orgao')}")
        print(f"URL: {pub.get('url')}")
        print(f"Quantidade de matchs: {pub.get('quantidade_matchs')}")

        print(
            f"Score consolidado da publicação: "
            f"{score_pub}"
        )

        print(
            "Scores dos matches: "
            f"{', '.join(pub.get('scores_confianca', []))}"
        )

        motivos_score_publicacao = pub.get(
            "motivos_score_publicacao",
            []
        )

        if motivos_score_publicacao:
            print(
                "Motivo do score da publicação: "
                f"{'; '.join(motivos_score_publicacao)}"
            )

        if pub.get("tem_suspeita_falso_positivo"):
            print(
                "⚠️ Risco: possui match com suspeita "
                "de falso positivo"
            )

        for termo in pub.get("termos", []):
            encontrados = termo.get("encontrados", [])
            motivos = termo.get("motivos_confianca", [])

            print(
                f"  - Termo: {termo.get('termo')} | "
                f"Tipo: {termo.get('tipo')} | "
                f"Score: {termo.get('score_confianca')} | "
                f"Encontrado: {', '.join(encontrados)}"
            )

            if termo.get("suspeita_falso_positivo"):
                print("    ⚠️ Suspeita de falso positivo")

            if motivos:
                print(
                    f"    Motivos: {'; '.join(motivos)}"
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
        print(f"Score: {item.get('score_confianca')}")
        print(f"Encontrado: {', '.join(item.get('encontrados', []))}")
        print(f"Motivos: {'; '.join(item.get('motivos', []))}")


async def etapa_1_buscar_links() -> dict:
    print("=" * 80)
    print("ETAPA 1 — BUSCA DE LINKS DOU")
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Headless: {HEADLESS}")
    print(f"Max páginas: {MAX_PAGINAS}")
    print("=" * 80)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
            ]
        )

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768}
        )

        page = await context.new_page()

        try:
            resultado = await coletar_links_dou_diario(
                page=page,
                data_alvo=DATA_EXECUCAO,
                max_paginas=MAX_PAGINAS
            )

        finally:
            await context.close()
            await browser.close()

    caminho = BRUTO_DIR / f"links_dou_{DATA_EXECUCAO.isoformat()}.json"
    salvar_json(caminho, resultado)

    print("BUSCA FINALIZADA")
    print(f"Status busca: {resultado.get('status_busca')}")
    print(f"Total links: {resultado.get('total_links')}")
    print(f"Arquivo: {caminho}")

    return resultado


async def etapa_2_extrair_publicacoes(payload_links: dict) -> dict:
    print("=" * 80)
    print("ETAPA 2 — EXTRAÇÃO TEXTO INTEGRAL")
    print("=" * 80)

    links = payload_links.get("links", [])

    urls = [
        item.get("url")
        for item in links
        if item.get("url")
    ]

    if not urls:
        payload = {
            "data": DATA_EXECUCAO.isoformat(),
            "status": "SEM_LINKS",
            "total_links_disponiveis": 0,
            "total_extraidas": 0,
            "sucesso": 0,
            "erro": 0,
            "publicacoes": []
        }

        caminho = BRUTO_DIR / f"publicacoes_{DATA_EXECUCAO.isoformat()}.json"
        salvar_json(caminho, payload)

        print("Nenhum link disponível para extração.")
        print(f"Arquivo: {caminho}")

        return payload

    publicacoes = await extrair_multiplas_publicacoes(
        urls=urls,
        limite=LIMITE_PUBLICACOES
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
        "data": DATA_EXECUCAO.isoformat(),
        "status": "FINALIZADO",
        "limite_publicacoes": LIMITE_PUBLICACOES,
        "total_links_disponiveis": len(urls),
        "total_extraidas": len(publicacoes),
        "sucesso": sucesso,
        "erro": erro,
        "publicacoes": publicacoes
    }

    caminho = BRUTO_DIR / f"publicacoes_{DATA_EXECUCAO.isoformat()}.json"
    salvar_json(caminho, payload)

    print("EXTRAÇÃO FINALIZADA")
    print(f"Total extraídas: {payload['total_extraidas']}")
    print(f"Sucesso: {payload['sucesso']}")
    print(f"Erro: {payload['erro']}")
    print(f"Arquivo: {caminho}")

    return payload


async def etapa_3_gerar_base(payload_publicacoes: dict) -> list[dict]:
    print("=" * 80)
    print("ETAPA 3 — BASE AUDITÁVEL")
    print("=" * 80)

    registros = montar_base_publicacoes(payload_publicacoes)

    caminho = salvar_base_publicacoes(
        data_referencia=DATA_EXECUCAO.isoformat(),
        registros=registros
    )

    print("BASE GERADA")
    print(f"Total registros: {len(registros)}")
    print(f"Arquivo: {caminho}")

    return registros


async def etapa_4_aplicar_match(registros: list[dict]) -> dict:
    print("=" * 80)
    print("ETAPA 4 — MATCH")
    print(f"Finalidade: {FINALIDADE_CONFIG}")
    print("=" * 80)

    registros_match = aplicar_match_base(registros)

    caminho = salvar_resultado_match(
        data_referencia=DATA_EXECUCAO.isoformat(),
        registros=registros_match
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
        "data_referencia": DATA_EXECUCAO.isoformat(),
        "total_registros": len(registros_match),
        "total_com_match": total_com_match,
        "total_sem_match": total_sem_match,
        "registros": registros_match
    }

    print("MATCH FINALIZADO")
    print(f"Total registros: {len(registros_match)}")
    print(f"Com match: {total_com_match}")
    print(f"Sem match: {total_sem_match}")
    print(f"Arquivo: {caminho}")

    return payload_match


async def etapa_5_auditar_match(payload_match: dict) -> dict:
    print("=" * 80)
    print("ETAPA 5 — AUDITORIA MATCH")
    print("=" * 80)

    auditoria = gerar_auditoria_match(payload_match)

    caminho = salvar_auditoria(
        data_referencia=DATA_EXECUCAO.isoformat(),
        auditoria=auditoria
    )

    resumo = auditoria.get("resumo_executivo", {})
    estatisticas = auditoria.get("estatisticas_match", {})
    suspeitos = auditoria.get("possiveis_falsos_positivos", [])

    print("AUDITORIA GERADA")
    print(f"Total publicações: {resumo.get('total_publicacoes')}")
    print(f"Com match: {resumo.get('com_match')}")
    print(f"Sem match: {resumo.get('sem_match')}")
    print(f"Total matchs: {resumo.get('total_matchs')}")
    print(f"Taxa match: {resumo.get('taxa_match')}%")
    print(f"Tipos de match: {estatisticas.get('tipos_match')}")
    print(f"Score confiança dos matches: {estatisticas.get('score_confianca')}")
    print(f"Score consolidado das publicações: {estatisticas.get('score_publicacao')}")
    print(f"Possíveis falsos positivos: {len(suspeitos)}")
    print(f"Arquivo: {caminho}")

    imprimir_resumo_confianca(auditoria)
    imprimir_publicacoes_com_match(auditoria)
    imprimir_possiveis_falsos_positivos(auditoria)

    return auditoria


async def main():
    print("=" * 80)
    print("PIPELINE DOU POR DATA")
    print(f"Data: {DATA_EXECUCAO.isoformat()}")
    print(f"Finalidade: {FINALIDADE_CONFIG}")
    print("=" * 80)

    try:
        payload_links = await etapa_1_buscar_links()
        payload_publicacoes = await etapa_2_extrair_publicacoes(payload_links)
        registros = await etapa_3_gerar_base(payload_publicacoes)
        payload_match = await etapa_4_aplicar_match(registros)
        await etapa_5_auditar_match(payload_match)

        print("=" * 80)
        print("PIPELINE FINALIZADO COM SUCESSO")
        print("=" * 80)

    except Exception as e:
        erro_path = DEBUG_DIR / f"erro_pipeline_{DATA_EXECUCAO.isoformat()}.txt"

        erro_path.write_text(
            traceback.format_exc(),
            encoding="utf-8"
        )

        print("=" * 80)
        print("ERRO NO PIPELINE")
        print(f"Erro: {e}")
        print(f"Traceback salvo em: {erro_path}")
        print("=" * 80)

        raise


if __name__ == "__main__":
    asyncio.run(main())