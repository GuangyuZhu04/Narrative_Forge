$ErrorActionPreference = "Stop"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$CommandArgs
    )

    & $Command @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($CommandArgs -join ' ')"
    }
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
$Backend = Join-Path $Root "backend"

Write-Host "==> Building frontend"
Push-Location $Frontend
if (-not (Test-Path "node_modules")) {
    Invoke-Native "npm.cmd" @("install")
}
Invoke-Native "npm.cmd" @("run", "build")
Pop-Location

Write-Host "==> Installing backend package and PyInstaller"
Push-Location $Backend
Invoke-Native "python" @("-m", "pip", "install", "setuptools>=68", "wheel")
Invoke-Native "python" @("-m", "pip", "install", "--no-build-isolation", "-e", ".[dev]")
Invoke-Native "python" @("-m", "pip", "install", "pyinstaller")
Pop-Location

Write-Host "==> Building Windows executable"
Push-Location $Root
Invoke-Native "python" @("-m", "PyInstaller", "--clean", "--noconfirm", "NarrativeForge.spec")
Pop-Location

Write-Host ""
Write-Host "Done: $Root\dist\NarrativeForge.exe"
