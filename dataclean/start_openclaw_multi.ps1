param(
    [Parameter(Mandatory = $true)]
    [string]$OpenClawExe,

    [Parameter()]
    [ValidateRange(1, 32)]
    [int]$InstanceCount = 4,

    [Parameter()]
    [string]$LaunchRoot = (Join-Path $PSScriptRoot "runs"),

    [Parameter()]
    [string]$TemplateProfileDir = "",

    [Parameter()]
    [string[]]$OpenClawArgs = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Save-EnvState {
    param([string[]]$Names)
    $state = @{}
    foreach ($name in $Names) {
        $state[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
    }
    return $state
}

function Restore-EnvState {
    param([hashtable]$State)
    foreach ($name in $State.Keys) {
        [System.Environment]::SetEnvironmentVariable($name, $State[$name], "Process")
    }
}

function Set-InstanceEnv {
    param(
        [Parameter(Mandatory = $true)][string]$ProfileRoot,
        [Parameter(Mandatory = $true)][string]$OpenClawRoot,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
        [Parameter(Mandatory = $true)][string]$TempRoot
    )

    $drive = [System.IO.Path]::GetPathRoot($ProfileRoot).TrimEnd('\')
    $homePath = $ProfileRoot.Substring($drive.Length)

    [System.Environment]::SetEnvironmentVariable("USERPROFILE", $ProfileRoot, "Process")
    [System.Environment]::SetEnvironmentVariable("HOME", $ProfileRoot, "Process")
    [System.Environment]::SetEnvironmentVariable("HOMEDRIVE", $drive, "Process")
    [System.Environment]::SetEnvironmentVariable("HOMEPATH", $homePath, "Process")
    [System.Environment]::SetEnvironmentVariable("APPDATA", (Join-Path $ProfileRoot "AppData\Roaming"), "Process")
    [System.Environment]::SetEnvironmentVariable("LOCALAPPDATA", (Join-Path $ProfileRoot "AppData\Local"), "Process")
    [System.Environment]::SetEnvironmentVariable("TEMP", $TempRoot, "Process")
    [System.Environment]::SetEnvironmentVariable("TMP", $TempRoot, "Process")
    [System.Environment]::SetEnvironmentVariable("OPENCLAW_HOME", $OpenClawRoot, "Process")
    [System.Environment]::SetEnvironmentVariable("OPENCLAW_WORKSPACE", $WorkspaceRoot, "Process")
}

$openClawExePath = Get-AbsolutePath $OpenClawExe
if (-not (Test-Path -LiteralPath $openClawExePath)) {
    throw "OpenClawExe not found: $openClawExePath"
}

$templateRoot = ""
if ($TemplateProfileDir) {
    $templateRoot = Get-AbsolutePath $TemplateProfileDir
    if (-not (Test-Path -LiteralPath $templateRoot)) {
        throw "TemplateProfileDir not found: $templateRoot"
    }
}

$launchRootPath = Get-AbsolutePath $LaunchRoot
New-Item -ItemType Directory -Path $launchRootPath -Force | Out-Null

$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$runRoot = Join-Path $launchRootPath "openclaw-multi-$runStamp"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null

$envNames = @(
    "USERPROFILE",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "OPENCLAW_HOME",
    "OPENCLAW_WORKSPACE"
)

$manifest = [ordered]@{
    created_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    openclaw_exe = $openClawExePath
    instance_count = $InstanceCount
    launch_root = $runRoot
    instances = @()
}

for ($i = 1; $i -le $InstanceCount; $i++) {
    $slotName = "slot{0:D2}" -f $i
    $slotRoot = Join-Path $runRoot $slotName
    $profileRoot = Join-Path $slotRoot "profile"
    $openClawRoot = Join-Path $profileRoot ".openclaw"
    $workspaceRoot = Join-Path $openClawRoot "workspace"
    $sessionsRoot = Join-Path $openClawRoot "agents\main\sessions"
    $tempRoot = Join-Path $slotRoot "temp"
    $logsRoot = Join-Path $slotRoot "logs"

    foreach ($path in @($profileRoot, $openClawRoot, $workspaceRoot, $sessionsRoot, $tempRoot, $logsRoot)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }

    if ($templateRoot) {
        $templateItems = Get-ChildItem -LiteralPath $templateRoot -Force
        foreach ($item in $templateItems) {
            Copy-Item -LiteralPath $item.FullName -Destination $profileRoot -Recurse -Force
        }
    }

    $savedEnv = Save-EnvState -Names $envNames
    try {
        Set-InstanceEnv -ProfileRoot $profileRoot -OpenClawRoot $openClawRoot -WorkspaceRoot $workspaceRoot -TempRoot $tempRoot
        $proc = Start-Process -FilePath $openClawExePath -ArgumentList $OpenClawArgs -WorkingDirectory $workspaceRoot -PassThru
        $manifest.instances += [ordered]@{
            slot = $slotName
            pid = $proc.Id
            profile_root = $profileRoot
            openclaw_root = $openClawRoot
            workspace_root = $workspaceRoot
            temp_root = $tempRoot
            logs_root = $logsRoot
        }
        Write-Host ("[{0}] PID={1} {2}" -f $slotName, $proc.Id, $profileRoot)
    }
    finally {
        Restore-EnvState -State $savedEnv
    }
}

$manifestPath = Join-Path $runRoot "launch-manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host ""
Write-Host "Launch root: $runRoot"
Write-Host "Manifest: $manifestPath"

