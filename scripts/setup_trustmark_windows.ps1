param(
    [string]$PythonVersion = "3.12",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cpu"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentPath = Join-Path $ProjectRoot ".venv-trustmark"
$EnvironmentPython = Join-Path $EnvironmentPath "Scripts\python.exe"
$env:PYTHONUTF8 = "1"
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot "tmp\pip-cache"

if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
    py "-$PythonVersion" -m venv $EnvironmentPath
}

& $EnvironmentPython -m pip install --upgrade pip
& $EnvironmentPython -m pip install `
    torch==2.5.1 `
    torchvision==0.20.1 `
    --index-url $TorchIndexUrl
& $EnvironmentPython -m pip install -e "${ProjectRoot}[trustmark,research,data,dev]"
& $EnvironmentPython -m watermark_lab status

Write-Host "TrustMark environment ready: $EnvironmentPath"
Write-Host "PyTorch index: $TorchIndexUrl"
Write-Host "Run the first model/weight check with:"
Write-Host "  $EnvironmentPython -m watermark_lab self-check --model trustmark_q"
Write-Host "Activate with: $EnvironmentPath\Scripts\Activate.ps1"
