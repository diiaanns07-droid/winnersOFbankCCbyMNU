# Прогон агента на бесплатном Gemini в Windows PowerShell — так, как его повторит жюри.
#
#   powershell -ExecutionPolicy Bypass -File scripts\gemini_report.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\gemini_report.ps1 -Doc release\input\requirements.pdf -Name requirements_pdf.gemini
#
# Ключ: строка GEMINI_API_KEY=... в файле .env в корне репозитория или переменная окружения $env:GEMINI_API_KEY.
# Скрипт создаёт .venv (если его нет), ставит зависимости, запускает агента, verify и печатает паспорт прогона.
param(
    [string]$Doc = "release\input\requirements.md",
    [string]$Name = "requirements.gemini",
    [string]$Model = "",
    [string]$OutDir = "reports"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

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

Write-Host "== проверка настройки"
& $py -m bcc_review doctor --provider gemini

$report = Join-Path $OutDir "$Name.md"
$json = Join-Path $OutDir "$Name.json"
$runArgs = @($Doc, $report, "--provider", "gemini", "--no-cache", "--export", "jira")
if ($Model) { $runArgs += @("--model", $Model) }

Write-Host "== прогон: $Doc -> $report"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
& $py -m bcc_review @runArgs
$code = $LASTEXITCODE
$sw.Stop()
Write-Host ("время: {0:N0} с, код выхода {1}" -f $sw.Elapsed.TotalSeconds, $code)

Write-Host "== verify"
& $py -m bcc_review verify $json $Doc
$verify = $LASTEXITCODE

Write-Host "== паспорт"
& $py -c "import json,sys; r=json.load(open(sys.argv[1],encoding='utf-8'))['run']; print({k: r.get(k) for k in ('status','provider','models_used','calls','duration_s','commit','dirty')})" $json

if ($verify -ne 0) { exit $verify }
exit $code
