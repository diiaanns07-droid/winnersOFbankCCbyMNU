# Общая часть scripts\run_official.ps1 и scripts\jury_check.ps1 (подключается через точку, сама не запускается).
# Переходит в корень репозитория, создаёт .venv (если его нет), ставит зависимости (если они изменились)
# и создаёт .env из .env.example. После неё в $Py — python из активированного окружения или из .venv.
# Файл сохранён в UTF-8 с BOM: без BOM Windows PowerShell 5.1 читает русский текст в кодировке ANSI.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONUTF8 = "1"
$env:PYMUPDF_SUGGEST_LAYOUT_ANALYZER = "0"
# код агента — из этой копии, даже если активно окружение другой копии (editable-установка другого каталога)
$src = Join-Path (Get-Location) "src"
if ($env:PYTHONPATH) { $env:PYTHONPATH = "$src;$($env:PYTHONPATH)" } else { $env:PYTHONPATH = $src }
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }

function Test-PythonVersion([string[]]$Command) {
    $exe = $Command[0]
    $pre = @($Command | Select-Object -Skip 1)
    & $exe @pre -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
}

$Py = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if ($env:VIRTUAL_ENV -and (Test-Path (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"))) {
    $Py = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"   # уже активированное окружение (шаг 1 README)
}
if (-not (Test-Path $Py)) {
    $base = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.12", "-3.13", "-3.11")) {
            if (Test-PythonVersion @("py", $v)) { $base = @("py", $v); break }
        }
    }
    if (-not $base -and (Get-Command python -ErrorAction SilentlyContinue)) {
        if (Test-PythonVersion @("python")) { $base = @("python") }
    }
    if (-not $base) {
        Write-Host "Нужен Python 3.11, 3.12 или 3.13: https://www.python.org/downloads/ (при установке отметьте «Add python.exe to PATH»)." -ForegroundColor Red
        exit 1
    }
    Write-Host "== создаю окружение .venv ($($base -join ' '))"
    $exe = $base[0]
    $pre = @($base | Select-Object -Skip 1)
    & $exe @pre -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Py)) {
        Write-Host "Не удалось создать .venv — сообщение Python выше." -ForegroundColor Red
        exit 1
    }
}

$stamp = Join-Path (Split-Path -Parent (Split-Path -Parent $Py)) ".bcc_requirements"
# метка установки — requirements.txt и constraints.txt вместе: изменился любой — ставим заново
$want = ((Get-FileHash requirements.txt -Algorithm SHA256).Hash + (Get-FileHash constraints.txt -Algorithm SHA256).Hash)
$have = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { "" }
& $Py -c "import bcc_review" *> $null
if ($have -ne $want -or $LASTEXITCODE -ne 0) {
    Write-Host "== установка зависимостей (1–2 минуты при первом запуске)"
    & $Py -m pip install -q --disable-pip-version-check -r requirements.txt -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Установка не удалась — сообщение pip выше." -ForegroundColor Red
        exit 1
    }
    Set-Content -Path $stamp -Value $want -Encoding ASCII
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "== создан .env из шаблона: впишите ключ в строку GEMINI_API_KEY= (https://aistudio.google.com/apikey)" -ForegroundColor Yellow
}
