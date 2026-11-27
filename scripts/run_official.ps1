# Одна команда: установить агента и проверить официальный документ кейса (Windows PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1 -Provider gemini
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1 -Doc release\input\requirements.pdf
#
# Скрипт создаёт .venv (если его нет), ставит зависимости, проверяет настройку (doctor), запускает агента,
# сверяет отчёт с документом (verify) и печатает, где лежат файлы. Отчёт — в reports\my\ (не попадает в git).
param(
    [string]$Provider = "auto",
    [string]$Model = "",
    [string]$Doc = "release\input\requirements.md",
    [string]$Out = ""
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $Out) { $Out = Join-Path "reports\my" ([System.IO.Path]::GetFileNameWithoutExtension($Doc) + ".md") }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "== создаю .venv"
    $made = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv .venv
        $made = ($LASTEXITCODE -eq 0)
    }
    if (-not $made) { python -m venv .venv }
}
$py = (Resolve-Path ".venv\Scripts\python.exe").Path

Write-Host "== установка"
& $py -m pip install -q -r requirements.txt -e .
if ($LASTEXITCODE -ne 0) { throw "установка не удалась" }

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "создан .env из .env.example — впишите ключ в строку GEMINI_API_KEY="
}

Write-Host "== проверка настройки"
& $py -m bcc_review doctor --provider $Provider

$runArgs = @($Doc, $Out, "--provider", $Provider)
if ($Model) { $runArgs += @("--model", $Model) }

Write-Host ""
Write-Host "== прогон: $Doc -> $Out"
& $py -m bcc_review @runArgs
$code = $LASTEXITCODE

$base = $Out -replace '\.md$', ''
$json = "$base.json"
if (-not (Test-Path $json)) {
    Write-Host "отчёт не записан (код выхода $code)"
    if ($code -eq 0) { $code = 1 }
    exit $code
}

Write-Host ""
Write-Host "== verify"
& $py -m bcc_review verify $json $Doc
$verify = $LASTEXITCODE

Write-Host ""
Write-Host "Отчёт: $Out"
foreach ($f in @("$base.html", $json)) { if (Test-Path $f) { Write-Host "       $f" } }
if ($code -eq 3) {
    Write-Host "Модель недоступна: отчёт собран только правилами. Проверьте ключ: $py -m bcc_review doctor --live"
}
if ($verify -ne 0) { exit $verify }
exit $code
