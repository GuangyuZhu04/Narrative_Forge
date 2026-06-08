$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
$Backend = Join-Path $Root "backend"

Write-Host "==> Building frontend"
Push-Location $Frontend
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run build
Pop-Location

Write-Host "==> Installing backend package and PyInstaller"
Push-Location $Backend
python -m pip install -e ".[dev]"
python -m pip install pyinstaller
Pop-Location

Write-Host "==> Building Windows executable"
Push-Location $Root
python -m PyInstaller --clean --noconfirm NarrativeForge.spec
Pop-Location

Write-Host ""
Write-Host "Done: $Root\dist\NarrativeForge.exe"
