Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceRoot = Split-Path -Parent $root
Set-Location $root
$packageDir = Join-Path $workspaceRoot "package"

$pythonCandidates = @(
    $env:QIUAI_PYTHON,
    "D:\Program\PYTHON\python\python.exe",
    "python"
) | Where-Object { $_ -and $_.Trim() -ne "" }

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
    try {
        if ($candidate -eq "python") {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $pythonExe = $candidate
                break
            }
        } elseif (Test-Path $candidate) {
            $pythonExe = $candidate
            break
        }
    } catch {
    }
}

if (-not $pythonExe) {
    throw "No usable Python runtime found. Set QIUAI_PYTHON or install Python."
}

Write-Host "Using Python: $pythonExe"
Write-Host "Generating icon..."
& $pythonExe tools\generate_icon.py icon\Q1.png icon\Q1.ico
if ($LASTEXITCODE -ne 0) {
    throw "Icon generation failed."
}

Write-Host "Building QiuAiDatamaker with PyInstaller..."

if (-not (Test-Path $packageDir)) {
    New-Item -ItemType Directory -Path $packageDir | Out-Null
}

& $pythonExe -m PyInstaller --noconfirm --clean --distpath $packageDir QiuAiDatamaker.spec

Write-Host ""
Write-Host "Build complete."
Write-Host "App directory: $packageDir\QiuAiDatamaker"
Write-Host "Next step: build installer with Inno Setup using installer_windows.iss"
