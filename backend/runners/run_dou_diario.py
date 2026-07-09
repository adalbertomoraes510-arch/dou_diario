# ============================================================
# RUNNER — Teste do Núcleo de Auditoria DOU
# Atividade 2
# ============================================================

import datetime

from backend.services.status_service import (
    iniciar_execucao,
    atualizar_etapa,
    atualizar_resumo,
    finalizar_execucao,
    obter_status,
)

from backend.services.checkpoint_service import (
    salvar_checkpoint,
    carregar_checkpoint,
    etapa_ja_concluida,
    definir_pendencias,
)

from backend.services.audit_service import (
    registrar_evento_auditoria,
    registrar_erro,
    gerar_resumo_erros,
    obter_erros,
)


DATA_TESTE = datetime.date.today()


def main():
    print("=" * 80)
    print("TESTE — NÚCLEO DE AUDITORIA DOU")
    print(f"Data teste: {DATA_TESTE.isoformat()}")
    print("=" * 80)

    iniciar_execucao(DATA_TESTE, perfil="dou_teste")

    atualizar_etapa(
        DATA_TESTE,
        etapa="CARREGAR_CONFIGURACOES",
        status_etapa="CONCLUIDO",
        progresso=10,
        detalhes={"arquivos_config": 2}
    )
    salvar_checkpoint(
        DATA_TESTE,
        etapa="CARREGAR_CONFIGURACOES",
        detalhes={"status": "ok"}
    )

    atualizar_etapa(
        DATA_TESTE,
        etapa="BUSCAR_PUBLICACOES_DOU",
        status_etapa="CONCLUIDO",
        progresso=30,
        detalhes={"links_coletados": 25}
    )
    salvar_checkpoint(
        DATA_TESTE,
        etapa="BUSCAR_PUBLICACOES_DOU",
        detalhes={"links_coletados": 25}
    )

    atualizar_etapa(
        DATA_TESTE,
        etapa="EXTRAIR_TEXTOS_INTEGRAIS",
        status_etapa="EM_EXECUCAO",
        progresso=55,
        detalhes={"processadas": 10, "total": 25}
    )

    registrar_evento_auditoria(
        DATA_TESTE,
        evento="TESTE_EVENTO_AUDITORIA",
        detalhes={"mensagem": "Evento de teste registrado com sucesso"}
    )

    try:
        raise RuntimeError("ERRO_TESTE_CONTROLADO")
    except Exception as e:
        registrar_erro(
            DATA_TESTE,
            etapa="EXTRAIR_TEXTOS_INTEGRAIS",
            erro=e,
            detalhes={
                "url": "https://www.in.gov.br/teste",
                "tentativa": 1,
                "acao": "simulação de erro controlado"
            }
        )

    atualizar_resumo(
        DATA_TESTE,
        publicacoes_coletadas=25,
        publicacoes_processadas=10,
        falhas=1,
        matches_diario=3,
        matches_mensal=5,
        arquivos_gerados=[
            "base_bruta_teste.json",
            "matches_diario_teste.json",
            "matches_mensal_teste.json"
        ]
    )

    definir_pendencias(
        DATA_TESTE,
        pendencias=[
            "EXTRAIR_TEXTOS_INTEGRAIS",
            "SALVAR_BASE_BRUTA",
            "APLICAR_MATCH_DIARIO",
            "APLICAR_MATCH_MENSAL"
        ]
    )

    finalizar_execucao(
        DATA_TESTE,
        sucesso=True,
        com_alertas=True,
        detalhes={"motivo": "teste finalizado com erro controlado"}
    )

    status = obter_status(DATA_TESTE)
    checkpoint = carregar_checkpoint(DATA_TESTE)
    resumo_erros = gerar_resumo_erros(DATA_TESTE)
    erros = obter_erros(DATA_TESTE)

    print("\n" + "=" * 80)
    print("RESUMO DO TESTE")
    print("=" * 80)
    print(f"Status final: {status.get('status')}")
    print(f"Etapa atual: {status.get('etapa_atual')}")
    print(f"Progresso: {status.get('progresso')}%")
    print(f"Última etapa concluída: {checkpoint.get('ultima_etapa_concluida')}")
    print(f"Pendências: {checkpoint.get('pendencias')}")
    print(f"Total de erros: {resumo_erros.get('total_erros')}")
    print(f"Erros por etapa: {resumo_erros.get('por_etapa')}")

    if erros:
        print("\nÚltimo erro:")
        ultimo = erros[-1]
        print(f"- Etapa: {ultimo.get('etapa')}")
        print(f"- Tipo: {ultimo.get('tipo')}")
        print(f"- Erro: {ultimo.get('erro')}")

    print("=" * 80)
    print("TESTE FINALIZADO")
    print("=" * 80)


if __name__ == "__main__":
    main()