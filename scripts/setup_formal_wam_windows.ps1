[CmdletBinding()]
param(
    [string]$PythonVersion = "3.13",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$environmentPath = Join-Path $projectRoot ".venv-wam-formal"
$environmentPython = Join-Path $environmentPath "Scripts\python.exe"
$sourceParent = Join-Path $projectRoot "third_party"
$sourcePath = Join-Path $sourceParent "wam-official"
$checkpointDirectory = Join-Path $projectRoot "checkpoints\wam"
$checkpointPath = Join-Path $checkpointDirectory "wam_mit.pth"
$expectedCommit = "2c08af04d037d5667c02f6ddebbda9ff04581c3e"
$expectedWeightHash = "90EF232384E023BD63245EB0C131ABD69D2AFC7B8F17A71CCEDCEB542BF009E2"
$commitMarker = Join-Path $sourcePath ".source-commit"
$env:PYTHONUTF8 = "1"
$env:PIP_CACHE_DIR = Join-Path $projectRoot "tmp\pip-cache"

if (-not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
    py "-$PythonVersion" -m venv $environmentPath
}

& $environmentPython -m pip install --upgrade pip
& $environmentPython -m pip install `
    torch==2.11.0 `
    torchvision==0.26.0 `
    --index-url $TorchIndexUrl
& $environmentPython -m pip install `
    numpy==2.4.4 `
    Pillow==11.3.0 `
    PyYAML==6.0.3 `
    omegaconf==2.3.0 `
    einops==0.8.1 `
    opencv-python==4.13.0.92 `
    scikit-learn==1.7.1 `
    scipy==1.16.1 `
    pandas==2.3.2
& $environmentPython -m pip install -e "${projectRoot}[wam,research,data,api,dev]"

New-Item -ItemType Directory -Force -Path $sourceParent | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath "watermark_anything") -PathType Container)) {
    if (Test-Path -LiteralPath $sourcePath) {
        throw "WAM source target exists but is incomplete: $sourcePath"
    }
    git clone https://github.com/facebookresearch/watermark-anything.git $sourcePath
    git -C $sourcePath checkout $expectedCommit
}

$gitDirectory = Join-Path $sourcePath ".git"
if (Test-Path -LiteralPath $gitDirectory) {
    $actualCommit = git -C $sourcePath rev-parse HEAD
}
elseif (Test-Path -LiteralPath $commitMarker -PathType Leaf) {
    $actualCommit = (Get-Content -Raw -LiteralPath $commitMarker).Trim()
}
else {
    throw "WAM source has no Git metadata or commit marker: $sourcePath"
}
if ($actualCommit.Trim() -ne $expectedCommit) {
    throw "WAM source commit mismatch: $actualCommit"
}

New-Item -ItemType Directory -Force -Path $checkpointDirectory | Out-Null
if (-not (Test-Path -LiteralPath $checkpointPath -PathType Leaf)) {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "https://dl.fbaipublicfiles.com/watermark_anything/wam_mit.pth" `
        -OutFile $checkpointPath
}
$actualWeightHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $checkpointPath).Hash
if ($actualWeightHash -ne $expectedWeightHash) {
    throw "WAM checkpoint SHA-256 mismatch: $actualWeightHash"
}

& $environmentPython -c `
    "import numpy, torch, torchvision; assert torch.cuda.is_available(); print(numpy.__version__, torch.__version__, torchvision.__version__)"
& $environmentPython -m watermark_lab self-check --model wam
Write-Host "Formal WAM compatibility environment ready: $environmentPath" -ForegroundColor Green
Write-Host "This profile reproduces the core Python/NumPy/PyTorch versions captured for formal-v1."
