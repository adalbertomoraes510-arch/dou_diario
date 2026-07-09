$ErrorActionPreference = "Stop"

$projeto = $PSScriptRoot
$deployRoot = Join-Path $projeto "cloudflare_deploy_dou_integras"
$siteDir = Join-Path $deployRoot "site"

Write-Host "Preparando pasta limpa para deploy Cloudflare..." -ForegroundColor Cyan

Remove-Item $deployRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $siteDir | Out-Null

$origemIntegras = Join-Path $projeto "backend\data\dou\integras\dou_diario"

if (-not (Test-Path $origemIntegras)) {
    throw "Pasta de integras não encontrada: $origemIntegras"
}

Copy-Item $origemIntegras $siteDir -Recurse -Force

$wranglerConfig = @(
'{',
'  "name": "young-dew-314c",',
'  "compatibility_date": "2026-07-08",',
'  "assets": {',
'    "directory": "./site"',
'  }',
'}'
)

$wranglerConfig | Set-Content -Encoding UTF8 "$deployRoot\wrangler.jsonc"

cd $deployRoot

Write-Host "Publicando no Cloudflare..." -ForegroundColor Cyan

npx wrangler deploy

Write-Host ""
Write-Host "Deploy Cloudflare concluido." -ForegroundColor Green
Write-Host "URL base:"
Write-Host "https://young-dew-314c.adalbertomoraes510.workers.dev"
