$ErrorActionPreference = "Stop"

Set-Location "C:\Projetos_Automacao_BA\DOU_Diario_PROD"
$env:DOU_ENV = "PROD"

& "C:\Projetos_Automacao_BA\venv\Scripts\python.exe" `
  -m uvicorn backend.operacao.app:app `
  --host 127.0.0.1 `
  --port 8010
