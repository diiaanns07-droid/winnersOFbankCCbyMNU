# Одна команда: окружение, проверка документа, verify, сводка (Windows PowerShell 5.1 и PowerShell 7).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1 C:\Документы\ТЗ.pdf
#   powershell -ExecutionPolicy Bypass -File scripts\run_official.ps1 release\input\requirements.md --provider mock
#
# Без пути — официальный документ кейса; модель — по ключу в .env (GEMINI_API_KEY → Gemini). Параметры агента
# пишутся после пути. Отчёт: reports\my\<имя документа>.md (для PDF, DOCX и др. — <имя>_<расширение>.md),
# рядом .json и .html. Первый запуск сам создаёт .venv и ставит зависимости.
# Файл сохранён в UTF-8 с BOM (иначе Windows PowerShell 5.1 искажает русский текст).

$rest = @($args)
$Doc = "release\input\requirements.md"
if ($rest.Count -gt 0 -and -not ([string]$rest[0]).StartsWith("-")) {
    $Doc = [string]$rest[0]
    $rest = @($rest | Select-Object -Skip 1)
    # путь от текущего каталога: дальше скрипт работает из корня репозитория
    if (Test-Path -LiteralPath $Doc -PathType Leaf) { $Doc = (Resolve-Path -LiteralPath $Doc).Path }
}

. (Join-Path $PSScriptRoot "_env.ps1")

if (-not (Test-Path -LiteralPath $Doc -PathType Leaf)) {
    Write-Host "Файл не найден: $Doc" -ForegroundColor Red
    exit 2
}
$stem = [IO.Path]::GetFileNameWithoutExtension($Doc)
$ext = [IO.Path]::GetExtension($Doc).TrimStart(".").ToLower()
if ($ext -and $ext -ne "md") { $stem = "$($stem)_$ext" }
$outDir = if ($env:OUT) { $env:OUT } else { "reports\my" }
$report = Join-Path $outDir "$stem.md"
$json = Join-Path $outDir "$stem.json"

Write-Host "== проверка документа: $Doc -> $report"
$sw = [Diagnostics.Stopwatch]::StartNew()
& $Py -m bcc_review $Doc $report @rest
$code = $LASTEXITCODE
$seconds = [int]$sw.Elapsed.TotalSeconds
if (-not (Test-Path $json)) { exit $code }

Write-Host ""
Write-Host "== verify: каждая цитата ищется в документе заново"
& $Py -m bcc_review verify $json $Doc
$verify = $LASTEXITCODE

& $Py scripts\run_summary.py $json --verify-code $verify --seconds $seconds
if ($verify -ne 0) { exit $verify }
exit $code
