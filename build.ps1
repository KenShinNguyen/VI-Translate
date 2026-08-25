<#
.SYNOPSIS
    Build the Windows desktop app into dist\PDFTranslate and zip it for release.

.PARAMETER SkipAssets
    Skip downloading the layout model and font. The build still works, but the
    packaged app downloads them on its first translation instead of running offline.
#>
[CmdletBinding()]
param(
    [switch]$SkipAssets
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No virtual environment found. Run: python -m venv .venv"
}

Write-Host "==> Installing app and packaging dependencies" -ForegroundColor Cyan
& $python -m pip install -r (Join-Path $root "requirements-app.txt")

if (-not $SkipAssets) {
    Write-Host "==> Fetching the layout model and font to bundle" -ForegroundColor Cyan
    & $python (Join-Path $root "scripts\fetch_assets.py")
}

$fonts = Join-Path $root "app\fonts"
if (-not (Test-Path (Join-Path $fonts "*.ttf"))) {
    Write-Warning "No fonts in app\fonts - the app will fall back to Segoe UI. See app\fonts\README.md."
}

Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean (Join-Path $root "app.spec")

$output = Join-Path $root "dist\PDFTranslate"
if (-not (Test-Path $output)) {
    throw "PyInstaller did not produce $output"
}

$archive = Join-Path $root "dist\PDFTranslate-windows.zip"
Write-Host "==> Zipping to $archive" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $output "*") -DestinationPath $archive -Force

$size = (Get-ChildItem $output -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("==> Done. Folder {0:N0} MB, archive {1:N0} MB" -f $size, ((Get-Item $archive).Length / 1MB)) -ForegroundColor Green
Write-Host "Test on a machine with no Python before publishing." -ForegroundColor Yellow
