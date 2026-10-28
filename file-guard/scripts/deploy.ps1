# FileGuard (Comate) - one-click deploy (portable, interactive)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -FgHome "$env:USERPROFILE\comate" -NonInteractive
#
# What it does:
#   1) mount this suite directory as ~/.comate/plugins/file-guard (junction)
#   2) ask/accept the managed root, persist it as user env COMATE_FG_HOME
#   3) generate hooks/hooks.json from hooks.template.json with the real plugin path
#   4) seed global rules/registry/products on first install (portable)
#   5) install L3 pre-commit when the suite directory is a git repo
#
# No hardcoded drive letters: everything is derived and asked at install time.

param(
    [string]$FgHome = "",
    [switch]$NonInteractive,
    [switch]$NoEnvPersist
)

$ErrorActionPreference = "Stop"

$src  = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$link = Join-Path $env:USERPROFILE ".comate\plugins\file-guard"

if (-not (Test-Path (Join-Path $src "plugin.json"))) {
    Write-Error "plugin.json not found under: $src"
    exit 1
}

# --- 1) managed root (asked unless provided) ---
if (-not $FgHome) {
    if ($NonInteractive) {
        $FgHome = Join-Path $env:USERPROFILE "comate"
    } else {
        $answer = Read-Host "Managed root directory (where managed projects live) [$env:USERPROFILE\comate]"
        if ($answer) { $FgHome = $answer } else { $FgHome = Join-Path $env:USERPROFILE "comate" }
    }
}
$FgHome = $FgHome.TrimEnd('\')
New-Item -ItemType Directory -Force -Path $FgHome | Out-Null
if (-not $NoEnvPersist) {
    [Environment]::SetEnvironmentVariable("COMATE_FG_HOME", $FgHome, "User")
    Write-Host "Managed root: $FgHome (saved as user env COMATE_FG_HOME)"
} else {
    Write-Host "Managed root: $FgHome (env persist skipped: -NoEnvPersist)"
}

# --- 1.5) seed global rules (C0) if missing ---
$rulesDir = Join-Path $FgHome "_rules"
$rulesFile = Join-Path $rulesDir "global-rules.json"
$rulesTpl = Join-Path $src "rules\global-rules.template.json"
$registryFile = Join-Path $rulesDir "managed-projects.json"
New-Item -ItemType Directory -Force -Path $rulesDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $FgHome "products") | Out-Null
if (-not (Test-Path $rulesFile) -and (Test-Path $rulesTpl)) {
    Copy-Item $rulesTpl $rulesFile
    Write-Host "Seeded global rules: $rulesFile"
}
if (-not (Test-Path $registryFile)) {
    $empty = '{"version":1,"updated":"' + (Get-Date -Format 'yyyy-MM-dd') + '","projects":[]}'
    [System.IO.File]::WriteAllText($registryFile, $empty, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Created empty project registry: $registryFile"
}

# --- 2) junction ---
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction") {
        cmd /c rmdir "$link"
        Write-Host "Removed old junction: $link"
    } else {
        Write-Error "Plugin dir exists but is not a junction: $link"
        exit 1
    }
}
$pluginsDir = Split-Path $link -Parent
New-Item -ItemType Directory -Force -Path $pluginsDir | Out-Null
cmd /c mklink /J "$link" "$src"
Write-Host "Mounted: $link -> $src"

# --- 3) hooks.json from template (real plugin path) ---
$tpl = Join-Path $src "hooks\hooks.template.json"
$out = Join-Path $src "hooks\hooks.json"
if (-not (Test-Path $tpl)) {
    Write-Error "Missing hooks template: $tpl"
    exit 1
}
$pluginPath = $link -replace '\\', '/'
$content = [System.IO.File]::ReadAllText($tpl, [System.Text.Encoding]::UTF8)
$content = $content.Replace("{PLUGIN_DIR}", $pluginPath)
[System.IO.File]::WriteAllText($out, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Generated hooks.json with plugin path: $pluginPath"

# --- 3.5) merge hook paths into global user hooks (~/.comate/hooks.json) ---
# Preserve other projects' hooks (e.g. knowledge-base Stop hook):
#   - our hook already present -> rewrite command to the current plugin path
#   - our hook missing         -> append it under the right event/matcher
$globalHooks = Join-Path $env:USERPROFILE ".comate\hooks.json"
# Derive entries from the generated hooks.json (single source for matcher/timeout)
$gen = $content | ConvertFrom-Json
$ours = @()
foreach ($ev in @("PreToolUse", "PreCompact")) {
    foreach ($m in @($gen.hooks.$ev)) {
        foreach ($h in @($m.hooks)) {
            if ($h.command -match '([^/\\]+\.py)') {
                $ours += @{ Event = $ev; Matcher = $m.matcher; Key = $Matches[1]; Command = $h.command; Timeout = $h.timeout }
            }
        }
    }
}
if (Test-Path $globalHooks) {
    $raw = [System.IO.File]::ReadAllText($globalHooks, [System.Text.Encoding]::UTF8)
    $gj = $raw | ConvertFrom-Json
    if (-not $gj.hooks) {
        $gj | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{}) -Force
    }
    $changed = $false
    foreach ($o in $ours) {
        $entries = @()
        if ($gj.hooks.PSObject.Properties.Name -contains $o.Event) {
            $entries = @($gj.hooks.($o.Event))
        } else {
            $gj.hooks | Add-Member -NotePropertyName $o.Event -NotePropertyValue @() -Force
        }

        $found = $false
        foreach ($m in $entries) {
            foreach ($h in @($m.hooks)) {
                if ($h.command -and $h.command.Contains($o.Key)) {
                    $found = $true
                    if ($h.command -ne $o.Command) {
                        $h.command = $o.Command
                        $changed = $true
                    }
                }
            }
        }

        if (-not $found) {
            $target = $entries | Where-Object { $_.matcher -eq $o.Matcher } | Select-Object -First 1
            if (-not $target) {
                $target = [pscustomobject]@{ matcher = $o.Matcher; hooks = @() }
                $entries = @($entries) + $target
                $gj.hooks | Add-Member -NotePropertyName $o.Event -NotePropertyValue $entries -Force
            }
            $target.hooks = @($target.hooks) + [pscustomobject]@{
                type = "command"; command = $o.Command; timeout = $o.Timeout
            }
            $changed = $true
        }
    }
    if ($changed) {
        $outJson = $gj | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($globalHooks, $outJson, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Merged hooks into global hooks: $globalHooks"
    } else {
        Write-Host "Global hooks already up to date: $globalHooks"
    }
} else {
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $globalHooks -Parent)
    [System.IO.File]::WriteAllText($globalHooks, $content, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Created global hooks: $globalHooks"
}

# --- 3.6) install L3 pre-commit when this is a git repo ---
$l3Src = Join-Path $src "scripts\git-hooks\pre-commit"
$gitDir = Join-Path $src ".git"
if ((Test-Path $gitDir) -and (Test-Path $l3Src)) {
    $l3Dst = Join-Path $gitDir "hooks\pre-commit"
    New-Item -ItemType Directory -Force -Path (Split-Path $l3Dst -Parent) | Out-Null
    Copy-Item $l3Src $l3Dst -Force
    Write-Host "Installed L3 pre-commit: $l3Dst"
} else {
    Write-Host "L3 skipped (no .git): run 'git init' then re-run deploy to enable"
}

# --- 4) verify ---
if ((Test-Path (Join-Path $link "plugin.json")) -and (Test-Path $out)) {
    Write-Host "Deploy OK. Restart Comate / open a new session to load hooks."
    Write-Host "Next: python $src\scripts\doctor.py"
} else {
    Write-Error "Deploy verification failed"
    exit 1
}
