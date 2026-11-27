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
try { $Host.UI.RawUI.WindowTitle = "BCC Review" } catch { }

# Экран: одна тихая строка состояния, которая обновляется на месте (без переноса), ошибки — красным
function Get-Width {
    $w = 80
    try { $w = [Console]::WindowWidth } catch { }
    if ($w -lt 20) { $w = 80 }
    return $w
}
function Show-Status([string]$Text) {
    $w = Get-Width
    $Text = "  " + $Text  # тот же отступ, что у реплик BCC AI
    if ($Text.Length -gt $w - 1) { $Text = $Text.Substring(0, $w - 1) }
    Write-Host -NoNewline ("`r" + $Text.PadRight($w - 1)) -ForegroundColor DarkGray
}
function Clear-Status {
    $w = Get-Width
    Write-Host -NoNewline ("`r" + "".PadRight($w - 1) + "`r")
}
function Say([string]$Text) {
    Clear-Status
    Write-Host ("  " + $Text) -ForegroundColor DarkGray
}
function Fail([string]$Text) {
    Clear-Status
    Write-Host ("  " + $Text) -ForegroundColor Red
    exit 1
}

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

function Get-PipStep([string]$Path) {
    # какой пакет сейчас: последняя строка pip «Collecting …» / «Downloading …»
    $lines = @()
    try { $lines = @(Get-Content -LiteralPath $Path -Tail 40 -ErrorAction Stop) } catch { return "" }
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        $l = [string]$lines[$i]
        if ($l -match "^Collecting ([A-Za-z0-9_.\-]+)") { return $Matches[1] }
        if ($l -match "^\s*Downloading ([A-Za-z0-9_.]+)-[0-9]") { return $Matches[1] }
        if ($l -match "^Installing collected") { return "раскладываю пакеты" }
        if ($l -match "^Successfully installed") { return "почти готово" }
    }
    return ""
}

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath (Join-Path $Root ".venv")) {
    $ok = $false
    if (Test-Path -LiteralPath $Py) {
        & $Py -c "import sys" *> $null
        $ok = ($LASTEXITCODE -eq 0)
    }
    if (-not $ok) {
        Say "BCC Review · окружение .venv повреждено или создано другим Python — создаю заново"
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
        Fail "Установите Python 3.12: https://www.python.org/downloads/ (отметьте «Add python.exe to PATH»), затем снова START.cmd"
    }
    Show-Status "BCC Review · первый запуск: создаю окружение ($($base -join ' '))"
    $exe = $base[0]
    $pre = @($base | Select-Object -Skip 1)
    $venvOut = @(& $exe @pre -m venv (Join-Path $Root ".venv") 2>&1)  # вывод — только при ошибке, не поверх строки
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Py)) {
        Remove-Item -LiteralPath (Join-Path $Root ".venv") -Recurse -Force -ErrorAction SilentlyContinue
        Clear-Status
        foreach ($l in $venvOut) { Write-Host ([string]$l) }
        Fail "Не удалось создать .venv — сообщение Python выше."
    }
}

# метка установки: хеш requirements.txt + constraints.txt; совпал — pip не запускаем
$stamp = Join-Path $Root ".venv\.bcc-req"
$want = (Get-FileHash -LiteralPath (Join-Path $Root "requirements.txt") -Algorithm SHA256).Hash + (Get-FileHash -LiteralPath (Join-Path $Root "constraints.txt") -Algorithm SHA256).Hash
$have = ""
if (Test-Path -LiteralPath $stamp) { $have = ([string](Get-Content -LiteralPath $stamp -Raw)).Trim() }
if ($have -ne $want) {
    $t0 = Get-Date
    $out = Join-Path $Root ".venv\pip.log"
    $err = Join-Path $Root ".venv\pip-errors.log"
    # пути относительно корня: в аргументах нет пробелов, даже если они есть в пути к папке
    $p = Start-Process -FilePath $Py -ArgumentList "-m pip install -r requirements.txt" -WorkingDirectory $Root -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle  # без этого у Start-Process в PowerShell 5.1 пустой ExitCode
    while (-not $p.HasExited) {
        $s = [int]((Get-Date) - $t0).TotalSeconds
        $step = Get-PipStep $out
        if ($step) { $step = " · $step" }
        Show-Status "BCC Review · первый запуск: ставлю зависимости$step · $s с"
        Start-Sleep -Milliseconds 1000
    }
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) {
        Clear-Status
        $lines = @()
        try { $lines = @(Get-Content -LiteralPath $err -Tail 15 -ErrorAction Stop) } catch { }
        foreach ($l in $lines) { Write-Host $l }
        Fail "Установка зависимостей не удалась (журнал: .venv\pip.log и .venv\pip-errors.log). Проверьте интернет и запустите START.cmd ещё раз."
    }
    $s = [int]((Get-Date) - $t0).TotalSeconds
    Say "BCC Review · зависимости установлены за $s с"
    Set-Content -LiteralPath $stamp -Value $want -Encoding ASCII
}

& $Py -m bcc_review.v2.web --open @args
exit $LASTEXITCODE
