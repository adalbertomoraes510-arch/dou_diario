# Operação — DOU Diário

## Rodar processamento diário

A partir da raiz do projeto:

    C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m backend.runners.run_orquestrador_dou_periodo

## Publicar íntegras manualmente no Cloudflare

    .\publicar_integras_cloudflare.ps1

## Reenviar somente o e-mail de uma data

Criar script temporário com:

    import datetime
    from backend.services.email_dou_diario_service import enviar_email_dou_diario

    resultado = enviar_email_dou_diario(
        data_execucao=datetime.date(2026, 7, 8),
        modo_simulacao=False,
    )

    print(resultado)

## Observação

Scripts temporários de teste ou reenvio não devem ir para o Git.
