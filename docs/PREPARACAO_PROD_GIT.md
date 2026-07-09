# Preparação DEV para PROD via Git

## Antes de subir

Validar compilação:

    C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m py_compile .\backend\services\email_dou_diario_service.py
    C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m py_compile .\backend\services\dou_integra_html_service.py

## Não versionar

Não enviar ao Git:

- .env
- backups
- arquivos temporários de teste
- relatórios gerados
- logs
- dados baixados/processados
- cache
- pasta cloudflare_deploy_dou_integras

## Versionar

Enviar ao Git:

- código Python
- publicar_integras_cloudflare.ps1
- .gitignore
- .gitattributes
- .env.example
- README.md
- docs/
