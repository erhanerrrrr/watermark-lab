[CmdletBinding()]
param(
    [string]$PythonEnvironment = ".venv-trustmark"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
$pythonPath = Join-Path $projectRoot "$PythonEnvironment\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python environment does not exist: $pythonPath"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found."
}

Push-Location $projectRoot
try {
    Write-Host "[1/4] Python lint" -ForegroundColor Cyan
    Invoke-CheckedNative $pythonPath @("-m", "ruff", "check", "src", "tests", "scripts") "Python lint failed."

    Write-Host "[2/4] Python tests" -ForegroundColor Cyan
    Invoke-CheckedNative $pythonPath @("-m", "pytest", "-q") "Python tests failed."

    Push-Location (Join-Path $projectRoot "frontend")
    try {
        Write-Host "[3/4] Frontend lint" -ForegroundColor Cyan
        Invoke-CheckedNative "npm" @("run", "lint") "Frontend lint failed."

        Write-Host "[4/4] Frontend production build" -ForegroundColor Cyan
        Invoke-CheckedNative "npm" @("run", "build") "Frontend build failed."
    }
    finally {
        Pop-Location
    }
    Write-Host "All Watermark Lab showcase checks passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
