# github-release-tool - deploy script (mount as comate plugin via junction)
# Usage: PowerShell  .\deploy.ps1
# ASCII-only messages to stay safe under PowerShell 5.1 (GBK) encoding.

$ErrorActionPreference = "Stop"

$src   = "D:\comate\products\github-release-tool"
$link  = Join-Path $env:USERPROFILE ".comate\plugins\github-release-tool"

if (-not (Test-Path $src)) {
    Write-Error "Source dir missing: $src"
    exit 1
}

if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction") {
        cmd /c rmdir "$link"
        Write-Host "Removed old junction: $link"
    } else {
        Write-Error "Plugin dir exists but is not a junction; handle manually: $link"
        exit 1
    }
}

$pluginsDir = Split-Path $link -Parent
New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null

cmd /c mklink /J "$link" "$src"
Write-Host "Mounted: $link  ->  $src"

if (Test-Path (Join-Path $link "plugin.json")) {
    Write-Host "Deploy OK: plugin.json visible; comate will auto-discover github-release-tool."
    Write-Host "Note: open a new session for the github-publish skill to take effect."
} else {
    Write-Error "Deploy verification failed: plugin.json not visible"
    exit 1
}
