param(
    [string]$FgHome = "",
    [switch]$Yes,
    [switch]$NoDeploy
)

$ErrorActionPreference = "Stop"
$suite = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = "arg"

if (-not $FgHome) {
    if ($env:COMATE_FG_HOME) {
        $FgHome = $env:COMATE_FG_HOME
        $source = "env:COMATE_FG_HOME"
    } elseif ($env:FG_HOME) {
        $FgHome = $env:FG_HOME
        $source = "env:FG_HOME"
    } elseif (Test-Path (Join-Path $suite "portable.flag")) {
        $FgHome = Join-Path $suite "managed"
        $source = "portable"
    } else {
        $FgHome = Join-Path $env:USERPROFILE "comate"
        $source = "default"
    }
}

$FgHome = $FgHome.TrimEnd('\')
if (-not $Yes) {
    $answer = Read-Host "Managed root [$FgHome]"
    if ($answer) {
        $FgHome = $answer.TrimEnd('\')
        $source = "interactive"
    }
}

New-Item -ItemType Directory -Force -Path $FgHome | Out-Null
[Environment]::SetEnvironmentVariable("COMATE_FG_HOME", $FgHome, "User")
$env:COMATE_FG_HOME = $FgHome

$configDir = Join-Path $env:APPDATA "FileGuard"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$config = [ordered]@{
    managed_root = $FgHome
    source       = $source
    updated      = (Get-Date).ToString("s")
}
$config | ConvertTo-Json | Set-Content -Path (Join-Path $configDir "config.json") -Encoding UTF8

Write-Host "[OK] managed root: $FgHome (source: $source)"
Write-Host "[OK] config: $(Join-Path $configDir 'config.json')"

if (-not $NoDeploy) {
    & (Join-Path $PSScriptRoot "deploy.ps1") -FgHome $FgHome -NonInteractive
}

Write-Host "Next: python scripts\doctor.py"
