# Проверка «как у жюри» одной командой (Windows PowerShell 5.1 и PowerShell 7): ключ и модель → прогон
# официального документа без кэша → verify → сверка с эталоном К1–К5, С1–С20 → сводка с воротами.
#
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1                  # Gemini, ключ в .env
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1 gemini gemini-3.6-flash
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1 claude_cli haiku
#   powershell -ExecutionPolicy Bypass -File scripts\jury_check.ps1 mock            # без сети: проверка установки
#
# Отчёт: out\jury\requirements.<провайдер>.md (+ .json, .html, score.<провайдер>.md). Код выхода 0 — все ворота
# пройдены. Пределы: $env:MAX_MINUTES (по умолчанию 6 для gemini, 15 для остальных), $env:MAX_CALLS (12).
# Файл сохранён в UTF-8 с BOM (иначе Windows PowerShell 5.1 искажает русский текст).

$Provider = if ($args.Count -ge 1) { [string]$args[0] } else { "gemini" }
$Model = if ($args.Count -ge 2) { [string]$args[1] } else { "" }

. (Join-Path $PSScriptRoot "_env.ps1")

$maxMinutes = if ($env:MAX_MINUTES) { $env:MAX_MINUTES } elseif ($Provider -eq "gemini") { "6" } else { "15" }
$maxCalls = if ($env:MAX_CALLS) { $env:MAX_CALLS } else { "12" }
$Doc = "release\input\requirements.md"
$outDir = "out\jury"
$report = Join-Path $outDir "requirements.$Provider.md"
$json = Join-Path $outDir "requirements.$Provider.json"
$modelArgs = @()
if ($Model) { $modelArgs = @("--model", $Model) }

$commit = "нет .git"
if (Get-Command git -ErrorAction SilentlyContinue) {
    $c = (& git rev-parse --short HEAD 2>$null)
    if ($LASTEXITCODE -eq 0 -and $c) { $commit = $c }
}
Write-Host "== коммит агента: $commit"

if ($Provider -ne "mock" -and $Provider -ne "offline") {
    Write-Host "== 1. ключ и пробный вызов модели"
    & $Py -m bcc_review doctor --live --provider $Provider @modelArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Модель не ответила — исправьте то, что написано в «Что исправить» выше, и запустите снова." -ForegroundColor Red
        exit 3
    }
}

Write-Host ""
Write-Host "== 2. прогон официального документа без кэша: $Doc -> $report"
if (Test-Path $json) { Remove-Item $json }
$sw = [Diagnostics.Stopwatch]::StartNew()
& $Py -m bcc_review $Doc $report --provider $Provider @modelArgs --no-cache --export jira
$code = $LASTEXITCODE
$seconds = [int]$sw.Elapsed.TotalSeconds
Write-Host "время: $seconds с, код выхода $code"
if (-not (Test-Path $json)) {
    Write-Host "Отчёт не записан." -ForegroundColor Red
    if ($code -eq 0) { $code = 1 }
    exit $code
}

Write-Host ""
Write-Host "== 3. verify"
& $Py -m bcc_review verify $json $Doc
$verify = $LASTEXITCODE

$scoreArgs = @()
if (Test-Path "evaluation\v2") {
    Write-Host ""
    Write-Host "== 4. сверка с эталоном (строгий счёт, без модели)"
    $scoreJson = Join-Path $outDir "score.$Provider.json"
    $scoreMd = Join-Path $outDir "score.$Provider.md"
    & $Py -m evaluation.v2.score $json --report-md $report --out $scoreJson --md $scoreMd | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $scoreArgs = @("--score", $scoreJson)
        Write-Host "разбор: $scoreMd"
    } else {
        Write-Host "счётчик эталона не отработал — пропускаю" -ForegroundColor Yellow
    }
}

& $Py scripts\run_summary.py $json @scoreArgs --verify-code $verify --seconds $seconds --max-minutes $maxMinutes --max-calls $maxCalls --check
exit $LASTEXITCODE
