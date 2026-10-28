# placement-watchdog.ps1 - Every 2 min: ensure guard resident process is alive.
# If the "Comate Placement Guard" process died (sleep-kill, crash, manual kill),
# reset the task (Stop clears zombie Running state, Start pulls it back).
# Runs as a scheduled task with RunLevel=HighestAvailable so it sees the
# guard's CommandLine (non-admin callers cannot read it).
# Logs only on action (alive -> exit silently) to avoid log spam.
# Schedule: TimeTrigger every 2 minutes (registered by register-guard-task.ps1)

$ErrorActionPreference = "SilentlyContinue"

# Shared L4 config (dot-sourced): $global:L4WatchdogIntervalMin + $global:FG_HOME
. "$PSScriptRoot\guard-config.ps1"
$fgRoot = $global:FG_HOME
$log  = Join-Path $fgRoot "_rules\placement-watchdog-log.md"
# FileGuard L4 (comate 侧)：Comate Placement Guard 看门狗
# 探活 Comate Placement Guard 任务进程，异常时重启。
$task = "Comate Placement Guard"

# --- heartbeat (P1-6 轻量探活): 每次运行写时间戳，用于验证计划任务未被删除/挂起 ---
$hbDir = Join-Path $fgRoot "_rules"
if (Test-Path $hbDir) {
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Set-Content -Path (Join-Path $hbDir "placement-watchdog-heartbeat.txt") -Value $stamp -Encoding ascii
}

# --- guard 心跳优先判活（P1-6 D4 方案）：guard 每 60s 写 placement-guard.heartbeat，
#     mtime 新鲜（<3min）→ guard 活着，零枚举、零管理员需求直接退出 ---
$guardHb = Join-Path $hbDir "placement-guard.heartbeat"
if (Test-Path $guardHb) {
  $hbAgeMin = ((Get-Date) - (Get-Item $guardHb).LastWriteTime).TotalMinutes
  if ($hbAgeMin -lt 3) {
    exit 0   # heartbeat fresh - guard alive, nothing to do
  }
}

# --- detect guard process (exclude self) ---
# 仅心跳过期才走枚举确认（需要管理员才能读到 CommandLine），确认后再决定是否重启
$procs = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'placement-guard\.ps1' -and $_.ProcessId -ne $PID }

if ($procs) {
  exit 0   # alive - nothing to do
}

# --- dead: reset zombie state and restart ---
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
try {
  Stop-ScheduledTask -TaskName $task -ErrorAction Stop
} catch { }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $task
Start-Sleep -Seconds 6

$after = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'placement-guard\.ps1' -and $_.ProcessId -ne $PID }
if ($after) {
  $line = "`n[$stamp] WATCHDOG: guard was dead, restarted PID=$($after.ProcessId)"
} else {
  $line = "`n[$stamp] WATCHDOG: guard was dead, restart FAILED (task state=$((Get-ScheduledTask -TaskName $task).State))"
}
Add-Content -Path $log -Value $line -Encoding utf8