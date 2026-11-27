# BCC Review — запуск одной командой на Windows (PowerShell 5.1 и 7). Обычно его зовёт START.cmd:
#   двойной щелчок по START.cmd   или   .\START.cmd [--check] [--port 9000]
# Находит Python 3.11+, создаёт .venv, ставит зависимости (только когда изменились requirements.txt или
# constraints.txt) и открывает веб-интерфейс в браузере. Повторный запуск — за секунды.
# Из интернета скачивается только `pip install -r requirements.txt` (и Python через winget — только с вашего «Y»).
# Файл сохранён в UTF-8 с BOM: без BOM Windows PowerShell 5.1 читает русский текст в кодировке ANSI.

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYMUPDF_SUGGEST_LAYOUT_ANALYZER = "0"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
# код агента — из этой копии (без `pip install -e .`: ему нужен setuptools из интернета)
$src = Join-Path $Root "src"
if ($env:PYTHONPATH) { $env:PYTHONPATH = "$src;$($env:PYTHONPATH)" } else { $env:PYTHONPATH = $src }

function Test-Python([string[]]$Cmd) {
    $exe = $Cmd[0]
    $pre = @($Cmd | Select-Object -Skip 1)
    try {
        & $exe @pre -c "import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 16) else 1)" *> $null
    } catch {
        return $false
    }
    return ($LASTEXITCODE -eq 0)
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.12", "-3.11", "-3.13", "-3.14")) {
            if (Test-Python @("py", $v)) { return ,@("py", $v) }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Test-Python @("python")) { return ,@("python") }
    }
    # Python установлен, но не в PATH (или PATH этого окна ещё не знает о только что установленном)
    $places = @()
    foreach ($v in @("312", "311", "313", "314")) {
        if ($env:LOCALAPPDATA) { $places += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe" }
        if ($env:ProgramFiles) { $places += Join-Path $env:ProgramFiles "Python$v\python.exe" }
    }
    foreach ($p in $places) {
        if ((Test-Path -LiteralPath $p) -and (Test-Python @($p))) { return ,@($p) }
    }
    return $null
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath (Join-Path $Root ".venv")) {
    $ok = $false
    if (Test-Path -LiteralPath $Py) {
        & $Py -c "import sys" *> $null
        $ok = ($LASTEXITCODE -eq 0)
    }
    if (-not $ok) {
        Write-Host "Окружение .venv повреждено или создано другим Python — создаю заново."
        Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $Py)) {
    $base = Find-Python
    if (-not $base) {
        Write-Host "Не найден Python 3.11 или новее." -ForegroundColor Yellow
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            $ans = Read-Host "Установить Python 3.12 сейчас (winget install -e --id Python.Python.3.12)? [Y/N]"
            if ($ans -match "^\s*(y|yes|д|да|н)") {
                winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
                $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
                $base = Find-Python
            }
        }
    }
    if (-not $base) {
        Write-Host "Установите Python 3.12: https://www.python.org/downloads/ (отметьте «Add python.exe to PATH»), затем снова START.cmd" -ForegroundColor Red
        exit 1
    }
    Write-Host "Создаю окружение .venv ($($base -join ' '))…"
    $exe = $base[0]
    $pre = @($base | Select-Object -Skip 1)
    & $exe @pre -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Py)) {
        Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Не удалось создать .venv — сообщение Python выше." -ForegroundColor Red
        exit 1
    }
}

# метка установки: хеш requirements.txt + constraints.txt; совпал — pip не запускаем
$stamp = Join-Path $Root ".venv\.bcc-req"
$want = (Get-FileHash -LiteralPath (Join-Path $Root "requirements.txt") -Algorithm SHA256).Hash + (Get-FileHash -LiteralPath (Join-Path $Root "constraints.txt") -Algorithm SHA256).Hash
$have = ""
if (Test-Path -LiteralPath $stamp) { $have = ([string](Get-Content -LiteralPath $stamp -Raw)).Trim() }
if ($have -ne $want) {
    $t0 = Get-Date
    # пути относительно корня: в аргументах нет пробелов, даже если они есть в пути к папке
    $p = Start-Process -FilePath $Py -ArgumentList "-m pip install -q -r requirements.txt --log .venv\pip.log" -WorkingDirectory $Root -NoNewWindow -PassThru
    $null = $p.Handle  # без этого у Start-Process в PowerShell 5.1 пустой ExitCode
    while (-not $p.HasExited) {
        $s = [int]((Get-Date) - $t0).TotalSeconds
        Write-Host -NoNewline "`rУстанавливаю зависимости (только при первом запуске, 1–3 минуты)… $s с "
        Start-Sleep -Milliseconds 1000
    }
    $p.WaitForExit()
    Write-Host ""
    if ($p.ExitCode -ne 0) {
        Write-Host "Установка зависимостей не удалась (журнал: .venv\pip.log). Проверьте интернет и запустите START.cmd ещё раз." -ForegroundColor Red
        exit 1
    }
    $s = [int]((Get-Date) - $t0).TotalSeconds
    Write-Host "Зависимости установлены за $s с."
    Set-Content -LiteralPath $stamp -Value $want -Encoding ASCII
}

& $Py -m bcc_review.v2.web --open @args
exit $LASTEXITCODE
