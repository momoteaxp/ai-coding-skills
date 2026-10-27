# guard-config.ps1 - FileGuard L4 shared configuration (dot-sourced)
# Single source of truth for L4 scheduled-task intervals.
# Both register-guard-task.ps1 (XML) and placement-watchdog.ps1 consume these
# values. Defaults below are identical to the historical hardcoded values;
# changing them here re-configures the whole L4 layer.
# Usage from another script:  . "$PSScriptRoot\guard-config.ps1"
# ASCII-only on purpose: PowerShell 5.1 may garble UTF-8 without BOM.

$global:L4ScanIntervalMin   = 5   # ScanOnce fallback task repetition interval
$global:L4WatchdogIntervalMin = 2  # watchdog task repetition interval
# 注：原 L4ScratchCleanTime / L4TrashCleanTime 为历史声明（comate 侧从未实现对应任务/脚本），
#     2026-10-23 蒸馏时移除；_scratch/_trash 当前手动管理。

# FG root: COMATE_FG_HOME first, FG_HOME legacy, fallback D:\comate (comate 套件独立，2026-10-23)
if (-not $global:FG_HOME) {
    if ($env:COMATE_FG_HOME) { $global:FG_HOME = $env:COMATE_FG_HOME }
    elseif ($env:FG_HOME) { $global:FG_HOME = $env:FG_HOME }
    else { $global:FG_HOME = "D:\comate" }
}