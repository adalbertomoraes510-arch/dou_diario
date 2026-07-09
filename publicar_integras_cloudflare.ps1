$ErrorActionPreference = "Stop"

$projeto = $PSScriptRoot
$deployRoot = Join-Path $projeto "cloudflare_deploy_dou_integras"
$siteDir = Join-Path $deployRoot "site"
$envPath = Join-Path $projeto ".env"

function Get-DotEnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$DefaultValue = ""
    )

    if (-not (Test-Path $Path)) {
        return $DefaultValue
    }

    $linha = Get-Content $Path | Where-Object {
        $_ -match ("^\s*" + [regex]::Escape($Key) + "\s*=")
    } | Select-Object -First 1

    if (-not $linha) {
        return $DefaultValue
    }

    $valor = $linha -replace ("^\s*" + [regex]::Escape($Key) + "\s*=\s*"), ""
    $valor = $valor.Trim().Trim('"').Trim("'")

    if ([string]::IsNullOrWhiteSpace($valor)) {
        return $DefaultValue
    }

    return $valor
}

$workerName = Get-DotEnvValue -Path $envPath -Key "DOU_CLOUDFLARE_WORKER_NAME" -DefaultValue "young-dew-314c"
$baseUrl = Get-DotEnvValue -Path $envPath -Key "DOU_INTEGRA_BASE_URL" -DefaultValue ("https://" + $workerName + ".adalbertomoraes510.workers.dev")

Write-Host "Preparando pasta limpa para deploy Cloudflare..." -ForegroundColor Cyan
Write-Host "Projeto: $projeto" -ForegroundColor Cyan
Write-Host "Worker: $workerName" -ForegroundColor Cyan
Write-Host "URL base: $baseUrl" -ForegroundColor Cyan

Remove-Item $deployRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $siteDir | Out-Null

$origemIntegras = Join-Path $projeto "backend\data\dou\integras\dou_diario"

if (-not (Test-Path $origemIntegras)) {
    throw "Pasta de integras nao encontrada: $origemIntegras"
}

Copy-Item $origemIntegras $siteDir -Recurse -Force

$wranglerConfig = @"
{
  "name": "$workerName",
  "compatibility_date": "2026-07-08",
  "assets": {
    "directory": "./site"
  }
}
"@

$wranglerConfig | Set-Content -Encoding UTF8 "$deployRoot\wrangler.jsonc"

cd $deployRoot

Write-Host "Publicando no Cloudflare..." -ForegroundColor Cyan

npx wrangler deploy

if ($LASTEXITCODE -ne 0) {
    throw "Falha no deploy Cloudflare. npx wrangler deploy retornou codigo $LASTEXITCODE."
}

Write-Host ""
Write-Host "Deploy Cloudflare concluido." -ForegroundColor Green
Write-Host "URL base:"
Write-Host $baseUrl
