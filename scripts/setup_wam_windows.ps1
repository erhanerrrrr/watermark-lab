param(
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentPath = Join-Path $ProjectRoot ".venv-wam"
$EnvironmentPython = Join-Path $EnvironmentPath "Scripts\python.exe"
$SourceParent = Join-Path $ProjectRoot "third_party"
$SourcePath = Join-Path $SourceParent "wam-official"
$CheckpointDirectory = Join-Path $ProjectRoot "checkpoints\wam"
$CheckpointPath = Join-Path $CheckpointDirectory "wam_mit.pth"
$ExpectedCommit = "2c08af04d037d5667c02f6ddebbda9ff04581c3e"
$ExpectedWeightHash = "90EF232384E023BD63245EB0C131ABD69D2AFC7B8F17A71CCEDCEB542BF009E2"
$CommitMarker = Join-Path $SourcePath ".source-commit"
$env:PYTHONUTF8 = "1"
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot "tmp\pip-cache"

if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
    py "-$PythonVersion" -m venv $EnvironmentPath
}

& $EnvironmentPython -m pip install --upgrade pip
& $EnvironmentPython -m pip install `
    torch==2.5.1 `
    torchvision==0.20.1 `
    --index-url https://download.pytorch.org/whl/cpu
& $EnvironmentPython -m pip install -e "${ProjectRoot}[wam,research,data,dev]"

New-Item -ItemType Directory -Force -Path $SourceParent | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $SourcePath "watermark_anything"))) {
    if (Test-Path -LiteralPath $SourcePath) {
        throw "WAM source target exists but is incomplete: $SourcePath"
    }
    git clone https://github.com/facebookresearch/watermark-anything.git $SourcePath
    git -C $SourcePath checkout $ExpectedCommit
}

$GitDirectory = Join-Path $SourcePath ".git"
if (Test-Path -LiteralPath $GitDirectory) {
    $ActualCommit = git -C $SourcePath rev-parse HEAD
} elseif (Test-Path -LiteralPath $CommitMarker) {
    $ActualCommit = (Get-Content -Raw -LiteralPath $CommitMarker).Trim()
} else {
    throw "WAM source has no Git metadata or commit marker: $SourcePath"
}
if ($ActualCommit.Trim() -ne $ExpectedCommit) {
    throw "WAM source commit mismatch: $ActualCommit"
}

New-Item -ItemType Directory -Force -Path $CheckpointDirectory | Out-Null
if (-not (Test-Path -LiteralPath $CheckpointPath)) {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "https://dl.fbaipublicfiles.com/watermark_anything/wam_mit.pth" `
        -OutFile $CheckpointPath
}
$ActualWeightHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $CheckpointPath).Hash
if ($ActualWeightHash -ne $ExpectedWeightHash) {
    throw "WAM checkpoint SHA-256 mismatch: $ActualWeightHash"
}

& $EnvironmentPython -m watermark_lab status
Write-Host "WAM environment ready: $EnvironmentPath"
Write-Host "Pinned source commit: $ActualCommit"
Write-Host "Verified checkpoint: $CheckpointPath"
Write-Host "Run the first model/weight check with:"
Write-Host "  $EnvironmentPython -m watermark_lab self-check --model wam"
Write-Host "Activate with: $EnvironmentPath\Scripts\Activate.ps1"
