$ErrorActionPreference = "Stop"
$raiz = "C:\Projetos_Automacao_BA\DOU_Diario_PROD"
if (-not (Test-Path (Join-Path $raiz "backend\runners\painel_dia_prod.py"))) { throw "Painel PROD nao instalado" }
Set-Location $raiz
& "C:\Projetos_Automacao_BA\venv\Scripts\python.exe" -m backend.runners.painel_dia_prod
