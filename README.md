# DOU Diario - Automacao INLAB / Diario Oficial da Uniao

Sistema para processamento diario do Diario Oficial da Uniao, com foco na finalidade dou_diario.

O sistema le os dados do DOU, aplica regras de palavras-chave e match, identifica publicacoes relevantes, gera relatorio executivo, gera paginas de integra, publica as integras no Cloudflare e envia e-mail diario com os links de acesso.

## 1. Escopo funcional

Fluxo principal do sistema:

1. Processar publicacoes do Diario Oficial da Uniao.
2. Aplicar regras de palavras-chave, match e criterios de relevancia.
3. Gerar dados intermediarios da execucao.
4. Gerar relatorios de resultado.
5. Gerar integras em HTML/TXT para as publicacoes relevantes.
6. Publicar as integras no Cloudflare.
7. Enviar e-mail diario com resumo e link Ver integra.

## 2. Ambientes

DEV:
C:\Projetos_Automacao_BA\DOU_Diario_DEV

PROD:
C:\Projetos_Automacao_BA\DOU_Diario_PROD

Python / venv:
C:\Projetos_Automacao_BA\venv\Scripts\python.exe

## 3. Comando principal

Executar a partir da raiz do ambiente:

cd C:\Projetos_Automacao_BA\DOU_Diario_DEV
C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m backend.runners.run_orquestrador_dou_periodo

Em PROD, trocar apenas a pasta:

cd C:\Projetos_Automacao_BA\DOU_Diario_PROD
C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m backend.runners.run_orquestrador_dou_periodo

## 4. Estrutura principal

backend/        Codigo principal, configuracoes, drivers, runners e services.
frontend/       Arquivos de interface, quando aplicavel.
tests/          Testes do projeto.
docs/           Documentacao operacional.
README.md       Documentacao geral do projeto.
requirements.txt Dependencias Python.
.env.example    Modelo de configuracao por ambiente.
.gitignore      Regras do que nao deve subir para o Git.
.gitattributes  Regras de tratamento de arquivos no Git.
publicar_integras_cloudflare.ps1 Script de publicacao das integras no Cloudflare.

## 5. Palavras-chave

Os arquivos de palavras-chave fazem parte da configuracao e da regra de negocio do sistema.

Eles devem subir para o Git e para PROD quando estiverem dentro de backend/config/finalidades/.

Exemplos:
backend/config/finalidades/<finalidade>/palavras_chave.xlsx
backend/config/finalidades/<finalidade>/monitoramentos/<monitoramento>/palavras_chave.xlsx

Nao devem subir arquivos temporarios do Excel, como arquivos iniciados por ~$ .

## 6. Arquivo .env

O arquivo .env nao deve subir para o Git.

Cada ambiente deve ter seu proprio .env:

DOU_Diario_DEV\.env
DOU_Diario_PROD\.env

O arquivo versionado deve ser apenas .env.example.

O .env.example serve como modelo, sem senhas reais, sem tokens reais e sem dados sensiveis.

Variaveis importantes:
DOU_INTEGRA_BASE_URL
DOU_PUBLICAR_INTEGRAS_CLOUDFLARE
DOU_CLOUDFLARE_SCRIPT=publicar_integras_cloudflare.ps1
DOU_PUBLICAR_INTEGRAS_BLOQUEAR_EMAIL_SE_FALHAR

Em DEV, podem ser usados destinatarios de teste.
Em PROD, devem ser usados destinatarios oficiais.

## 7. Dados gerados

A pasta backend/data/dou/ e usada para dados de execucao.

Somente backend/data/dou/.gitkeep deve ficar versionado.

Nao devem subir para o Git:
backend/data/dou/base/
backend/data/dou/bruto/
backend/data/dou/auditoria/
backend/data/dou/match/
backend/data/dou/relatorios/
backend/data/dou/integras/
backend/data/dou/inlabs/
backend/data/dou/logs_execucao/
backend/data/dou/links_resolvidos/
backend/data/dou/cache/
backend/data/dou/tmp/

Essas pastas sao recriadas durante as execucoes.

## 8. Publicacao das integras

O script de publicacao das integras no Cloudflare e publicar_integras_cloudflare.ps1.

Ele publica os arquivos gerados em backend/data/dou/integras/.

A URL base das integras e definida no .env pela variavel DOU_INTEGRA_BASE_URL.

## 9. Validacao antes de commit

Antes de versionar ou promover para PROD, executar:

C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m py_compile .\backend\services\email_dou_diario_service.py
C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m py_compile .\backend\services\dou_integra_html_service.py
C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m py_compile .\backend\runners\run_orquestrador_dou_periodo.py
C:\Projetos_Automacao_BA\venv\Scripts\python.exe -m compileall -q .\backend

## 10. Politica de versionamento

Deve subir para o Git:
backend/
frontend/
tests/
docs/
README.md
requirements.txt
.env.example
.gitignore
.gitattributes
publicar_integras_cloudflare.ps1

Nao deve subir:
.env
backend/data/dou/*, exceto backend/data/dou/.gitkeep
cloudflare_deploy_dou_integras/
.wrangler/
wrangler.jsonc
__pycache__/
*.pyc
backup_*/
scripts temporarios
arquivos de diagnostico
arquivos gerados de execucao

## 11. Observacao para PROD

Depois de clonar ou atualizar o PROD via Git, criar ou ajustar manualmente o .env do ambiente PROD antes de executar o orquestrador.
