# register-comate-guard-task.ps1 — 注册 FileGuard L4（comate 侧）计划任务
# Comate Placement Guard 任务注册脚本：
#   - 任务名 "Comate Placement Guard*"
#   - 动作指向本插件 scripts/ 下的 launcher（launcher 按 COMATE_FG_HOME 解析受管根）
# 注册 3 个任务（幂等，冲突即替换）：
#   1. "Comate Placement Guard"           常驻监视（登录 + 系统唤醒 Event 107）
#   2. "Comate Placement Guard - ScanOnce" 每 5 分钟兜底单次扫描
#   3. "Comate Placement Guard - Watchdog" 每 2 分钟看门狗（心跳过期且进程消失则重启 1）
# 用法:  powershell -ExecutionPolicy Bypass -File .\register-comate-guard-task.ps1
# 卸载:
#   Unregister-ScheduledTask -TaskName "Comate Placement Guard" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "Comate Placement Guard - ScanOnce" -Confirm:$false
#   Unregister-ScheduledTask -TaskName "Comate Placement Guard - Watchdog" -Confirm:$false

$ErrorActionPreference = "Stop"
$scriptsDir = $PSScriptRoot
$guardVbs   = Join-Path $scriptsDir "guard-launcher.vbs"
$watchdogVbs = Join-Path $scriptsDir "watchdog-launcher.vbs"
# 受管根：COMATE_FG_HOME 优先，兼容 FG_HOME，缺省 $env:USERPROFILE\comate
$fgHome = if ($env:COMATE_FG_HOME) { $env:COMATE_FG_HOME } elseif ($env:FG_HOME) { $env:FG_HOME } else { "$env:USERPROFILE\comate" }

function Test-Admin {
  $id   = [Security.Principal.WindowsIdentity]::GetCurrent()
  $prin = New-Object Security.Principal.WindowsPrincipal($id)
  return $prin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------- self-elevate ----------
if (-not (Test-Admin)) {
  Write-Host "[FileGuard-comate] Not elevated. Re-launching elevated..."
  $self = $MyInvocation.MyCommand.Path
  try {
    $p = Start-Process -FilePath "powershell.exe" `
      -ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File","`"$self`"") `
      -Verb RunAs -Wait -PassThru
    exit $p.ExitCode
  } catch {
    Write-Host "[FileGuard-comate] Elevation failed: $_"
    exit 1
  }
}
Write-Host "[FileGuard-comate] Elevated OK."

if (-not (Test-Path $guardVbs))   { Write-Host "[FileGuard-comate] FAIL: $guardVbs not found"; exit 1 }
if (-not (Test-Path $watchdogVbs)) { Write-Host "[FileGuard-comate] FAIL: $watchdogVbs not found"; exit 1 }

$sid = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$startBoundary = (Get-Date).AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss")

# ---------- stop existing instances ----------
foreach ($n in "Comate Placement Guard","Comate Placement Guard - ScanOnce","Comate Placement Guard - Watchdog") {
  if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
    try { Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue } catch { }
  }
}
Write-Host "[FileGuard-comate] Existing task instances stopped."

function Write-XmlTask([string]$name, [string]$xmlBody) {
  $guid = [guid]::NewGuid().ToString("N")
  $xmlFile = Join-Path $env:TEMP "fg-comate-task-$guid.xml"
  $header = '<?xml version="1.0" encoding="UTF-16"?>'
  [IO.File]::WriteAllText($xmlFile, $header + $xmlBody, [Text.Encoding]::Unicode)
  & schtasks.exe /create /tn $name /xml $xmlFile /f | Out-Null
  $rc = $LASTEXITCODE
  Remove-Item $xmlFile -Force -ErrorAction SilentlyContinue
  if ($rc -ne 0) {
    Write-Host "[FileGuard-comate] FAIL: schtasks($name) exit=$rc"
    exit 1
  }
}

$xmlTask1 = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>FileGuard L4 (comate) root-dir placement guard - resident monitor for $fgHome</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$sid</UserId>
    </LogonTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and EventID=107]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT15S</Delay>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$guardVbs"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$xmlTask2 = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>FileGuard L4 (comate) placement guard - ScanOnce fallback (every 5 min)</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>$startBoundary</StartBoundary>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$guardVbs" -ScanOnce</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$xmlTask3 = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>FileGuard L4 (comate) watchdog - restart guard if dead (every 2 min)</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>$startBoundary</StartBoundary>
      <Repetition>
        <Interval>PT2M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$watchdogVbs"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

Write-Host "[FileGuard-comate] Registering TASK1 (resident)..."
Write-XmlTask "Comate Placement Guard" $xmlTask1
Write-Host "[FileGuard-comate] Registering TASK2 (ScanOnce 5min)..."
Write-XmlTask "Comate Placement Guard - ScanOnce" $xmlTask2
Write-Host "[FileGuard-comate] Registering TASK3 (watchdog 2min)..."
Write-XmlTask "Comate Placement Guard - Watchdog" $xmlTask3

$t1 = Get-ScheduledTask -TaskName "Comate Placement Guard" -ErrorAction SilentlyContinue
$t2 = Get-ScheduledTask -TaskName "Comate Placement Guard - ScanOnce" -ErrorAction SilentlyContinue
$t3 = Get-ScheduledTask -TaskName "Comate Placement Guard - Watchdog" -ErrorAction SilentlyContinue
if (-not $t1 -or -not $t2 -or -not $t3) {
  Write-Host "[FileGuard-comate] FAIL: not all tasks present"
  exit 1
}
Write-Host "[FileGuard-comate] All 3 tasks registered OK:"
Write-Host "  1. Comate Placement Guard (State=$($t1.State), triggers=$($t1.Triggers.Count))"
Write-Host "  2. Comate Placement Guard - ScanOnce (State=$($t2.State))"
Write-Host "  3. Comate Placement Guard - Watchdog (State=$($t3.State))"

# ---------- immediate start: guard resident ----------
Start-ScheduledTask -TaskName "Comate Placement Guard"
Start-Sleep -Seconds 8
$fgPattern = [regex]::Escape($fgHome)
$alive = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'placement-guard\.ps1' -and $_.CommandLine -match $fgPattern -and $_.ProcessId -ne $PID } | Select-Object -First 1
if ($alive) {
  Write-Host "[FileGuard-comate] Guard process running PID=$($alive.ProcessId) (created $($alive.CreationDate.ToString('HH:mm:ss')))"
} else {
  Write-Host "[FileGuard-comate] WARN: guard process not detected after start (wait for trigger/restart policy)"
}
Write-Host "[FileGuard-comate] DONE."
