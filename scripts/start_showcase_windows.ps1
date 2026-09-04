[CmdletBinding()]
param(
    [ValidateSet("wam", "trustmark", "base")]
    [string]$Runtime = "wam",
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$SkipBuild,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-NativeCommand {
    param([string]$FilePath, [string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-CheckedNative {
    param([string]$FilePath, [string[]]$Arguments, [string]$FailureMessage)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) { throw $FailureMessage }
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$pythonCandidates = switch ($Runtime) {
    "wam" { @(".venv-wam-gpu\Scripts\python.exe", ".venv-wam\Scripts\python.exe") }
    "trustmark" { @(".venv-trustmark\Scripts\python.exe") }
    "base" { @(".venv\Scripts\python.exe", ".venv-trustmark\Scripts\python.exe") }
}
$pythonPath = $pythonCandidates |
    ForEach-Object { Join-Path $projectRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1

if (-not $pythonPath) {
    throw "No Python environment was found for runtime '$Runtime'. See docs\REPRODUCIBILITY.md."
}

Push-Location $projectRoot
try {
    $sourcePath = Join-Path $projectRoot "src"
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$sourcePath$([System.IO.Path]::PathSeparator)$env:PYTHONPATH"
    }
    else {
        $env:PYTHONPATH = $sourcePath
    }
    if (-not (Test-NativeCommand $pythonPath @("-c", "import fastapi, uvicorn, multipart, skimage"))) {
        Write-Host "Installing Web API dependencies in the $Runtime environment..." -ForegroundColor Cyan
        $apiDependencies = @(
            "-m", "pip", "install",
            "fastapi>=0.115,<1",
            "uvicorn[standard]>=0.32,<1",
            "python-multipart>=0.0.18,<1",
            "scikit-image>=0.22,<1"
        )
        Invoke-CheckedNative $pythonPath $apiDependencies "API dependency installation failed."
    }

    if (-not $SkipBuild) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            throw "npm was not found. Install Node.js 20 or newer."
        }
        Push-Location (Join-Path $projectRoot "frontend")
        try {
            if (-not (Test-Path -LiteralPath "node_modules" -PathType Container)) {
                Invoke-CheckedNative "npm" @("ci", "--prefer-offline", "--no-audit", "--no-fund") "Frontend dependency installation failed."
            }
            Invoke-CheckedNative "npm" @("run", "build") "Frontend production build failed."
        }
        finally {
            Pop-Location
        }
    }
    elseif (-not (Test-Path -LiteralPath "frontend\dist\index.html" -PathType Leaf)) {
        throw "frontend\dist is missing; -SkipBuild cannot be used."
    }

    Invoke-CheckedNative $pythonPath @("-m", "watermark_lab", "status") "Watermark Lab runtime check failed."

    $url = "http://127.0.0.1:$Port"
    if (-not $NoBrowser) {
        $browserCommand = "Start-Sleep -Seconds 2; Start-Process '$url'"
        Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
            "-NoProfile", "-WindowStyle", "Hidden", "-Command", $browserCommand
        ) | Out-Null
    }

    Write-Host ""
    Write-Host "Watermark Lab showcase: $url" -ForegroundColor Green
    Write-Host "API documentation: $url/docs" -ForegroundColor Green
    Write-Host "Runtime: $Runtime. Press Ctrl+C to stop." -ForegroundColor Yellow
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $pythonPath -m uvicorn watermark_lab.api.app:app --host 127.0.0.1 --port $Port
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}
finally {
    Pop-Location
}
