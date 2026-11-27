# Проверка агента так, как его запустит жюри: doctor --live -> прогон официального документа -> verify -> сводка.
#
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1 -Provider claude_cli -Model haiku
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1 -Doc release\input\requirements.pdf
#
# Ключ Gemini: строка GEMINI_API_KEY=... в файле .env в корне репозитория (или $env:GEMINI_API_KEY).
# Файл сохранён в UTF-8 с BOM: иначе Windows PowerShell 5.1 покажет русский текст нечитаемым.
param(
    [string]$Provider = "gemini",
    [string]$Model = "",
    [string]$Doc = "release\input\requirements.md",
    [string]$OutDir = "out\jury_check"
)
Set-Location (Split-Path -Parent $PSScriptRoot)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "== подготовка: создаю .venv и ставлю зависимости (один раз)"
    $made = $false
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.12 -m venv .venv; $made = ($LASTEXITCODE -eq 0) }
    if (-not $made) { python -m venv .venv }
    & ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -e .
    if ($LASTEXITCODE -ne 0) { Write-Host "СТОП: установка зависимостей не удалась (см. сообщения pip выше)."; exit 1 }
}
$py = (Resolve-Path ".venv\Scripts\python.exe").Path
$mopt = @()
if ($Model) { $mopt = @("--model", $Model) }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$name = [System.IO.Path]::GetFileNameWithoutExtension($Doc)
$report = Join-Path $OutDir "$name.md"
$json = Join-Path $OutDir "$name.json"

Write-Host "== 1/4 проверка модели: doctor --live --provider $Provider"
& $py -m bcc_review doctor --live --provider $Provider @mopt
if ($LASTEXITCODE -ne 0) {
    Write-Host "СТОП: модель не ответила. Исправьте по подсказке «Что исправить» выше и запустите скрипт снова."
    exit 2
}

Write-Host "== 2/4 прогон: $Doc -> $report"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $py -m bcc_review $Doc $report --provider $Provider @mopt --no-cache
$code = $LASTEXITCODE
$sw.Stop()

Write-Host "== 3/4 verify: цитаты и паспорт отчёта"
& $py -m bcc_review verify $json $Doc
$vcode = $LASTEXITCODE

Write-Host "== 4/4 сводка"
& $py scripts\jury_summary.py $json ([int]$sw.Elapsed.TotalSeconds) $code $vcode
exit $LASTEXITCODE
