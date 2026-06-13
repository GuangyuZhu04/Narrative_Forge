$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Frontend = Join-Path $Root "frontend"
$Backend = Join-Path $Root "backend"
$SpecFile = Join-Path $Root "NarrativeForge.spec"
$DistDir = Join-Path $Root "dist"
$BuildDir = Join-Path $Root "build"

function Get-RequiredCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Names,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }

    throw "Missing required command '$($Names -join "' or '")'. $InstallHint"
}

$NpmCommand = Get-RequiredCommand @("npm.cmd", "npm") "Install Node.js LTS and reopen PowerShell."
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonPrefixArguments = @()
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $PythonPrefixArguments = @("-3")
}
if (-not $PythonCommand) {
    throw "Missing required command 'python' or 'py'. Install Python 3.11+ and reopen PowerShell."
}
$PythonCommand = $PythonCommand.Source

function Invoke-Npm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & $script:NpmCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "npm $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    $AllArguments = @($script:PythonPrefixArguments) + @($Arguments)
    & $script:PythonCommand @AllArguments
    if ($LASTEXITCODE -ne 0) {
        throw "python $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Test-FrontendTool {
    param([Parameter(Mandatory = $true)][string]$Name)

    return (
        (Test-Path (Join-Path $Frontend "node_modules\.bin\$Name.cmd")) -or
        (Test-Path (Join-Path $Frontend "node_modules\.bin\$Name.ps1")) -or
        (Test-Path (Join-Path $Frontend "node_modules\.bin\$Name"))
    )
}

function Test-FrontendDependencies {
    return (
        (Test-Path (Join-Path $Frontend "node_modules")) -and
        (Test-Path (Join-Path $Frontend "node_modules\typescript\package.json")) -and
        (Test-FrontendTool "tsc") -and
        (Test-FrontendTool "vite")
    )
}

Write-Host "==> Building frontend"
Push-Location $Frontend
try {
    if (-not (Test-FrontendDependencies)) {
        if (Test-Path "package-lock.json") {
            Invoke-Npm ci
        } else {
            Invoke-Npm install
        }
    }

    Invoke-Npm run build

    $FrontendIndex = Join-Path $Frontend "dist\index.html"
    if (-not (Test-Path $FrontendIndex)) {
        throw "Frontend build did not create $FrontendIndex."
    }
} finally {
    Pop-Location
}

Write-Host "==> Installing backend package and PyInstaller"
Push-Location $Backend
try {
    Invoke-Python -Arguments @(
        "-m",
        "pip",
        "install",
        "--no-build-isolation",
        "-e",
        ".[dev]"
    )
    Invoke-Python -Arguments @("-m", "pip", "install", "pyinstaller")
} finally {
    Pop-Location
}

Write-Host "==> Building Windows executable"
Push-Location $Root
try {
    Invoke-Python -Arguments @(
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        $DistDir,
        "--workpath",
        $BuildDir,
        $SpecFile
    )
} finally {
    Pop-Location
}

$ExePath = Join-Path $DistDir "NarrativeForge.exe"
if (-not (Test-Path $ExePath)) {
    throw "PyInstaller finished, but $ExePath was not created."
}

Write-Host ""
Write-Host "Done: $ExePath"
