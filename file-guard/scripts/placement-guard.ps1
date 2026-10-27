# placement-guard.ps1 —— FileGuard L4：受管根目录散装文件自动归位守卫
# 兜底层：即使 L1/L2/L3 全部失效，根目录散装文件那一刻被系统搬走并记录。
# 用法：
#   -DryRun   预览模式：只报告不移动（部署前先跑一周）
#   -ScanOnce 单次扫描后退出（降级模式：可配计划任务周期跑，替代常驻监视）
#   默认      常驻文件系统监视（注册为开机自启，见 register-guard-task.ps1）
# 注意：Register-ObjectEvent 的 -Action 运行在独立会话状态，只能访问 $global: 变量
#       与 global: 函数，故本脚本全部使用 $global: 提升。
param([switch]$DryRun, [switch]$ScanOnce)

$global:FG_DRYRUN = [bool]$DryRun
# 根目录从环境变量读取：COMATE_FG_HOME 优先，兼容 FG_HOME，缺省 D:\comate（comate 套件独立，2026-10-23）
$global:FG_ROOT = if ($env:COMATE_FG_HOME) { $env:COMATE_FG_HOME } elseif ($env:FG_HOME) { $env:FG_HOME } else { "D:\comate" }
$global:FG_SCRATCH = Join-Path $FG_ROOT "_scratch\auto"
$global:FG_LOG     = Join-Path $FG_ROOT "_rules\placement-log.md"

# 动态加载 C0 白名单（避免中文硬编码被 PowerShell 5.1 编码问题破坏）
$rulesPath = Join-Path $FG_ROOT "_rules\global-rules.json"
if (Test-Path $rulesPath) {
  $rulesJson = Get-Content -Path $rulesPath -Encoding UTF8 | ConvertFrom-Json
  $global:FG_ALLOWED = $rulesJson.rules.allowed_root_dirs
} else {
  # fallback: 最小英文安全集（规则源缺失时的安全降级；与 C0 17 项白名单对齐，
  # temp/备份 已移出；中文目录（产品/设计思路等）由下面的 FG_PROJECTS 动态识别补入）
  $global:FG_ALLOWED = @("_rules","_scratch","_trash","_archive","scripts","inbox")
}

# 动态识别项目目录：D:\comate 一级目录中带 project_meta.json 的即为受管项目（规则是数据）
$global:FG_PROJECTS = Get-ChildItem -LiteralPath $FG_ROOT -Directory -ErrorAction SilentlyContinue |
  Where-Object { Test-Path (Join-Path $_.FullName "project_meta.json") } |
  ForEach-Object { $_.Name }
$global:FG_ALLOWED += $FG_PROJECTS

function global:FG-Write-Log([string]$line) {
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -Path $FG_LOG -Value ("- {0} | {1}" -f $stamp, $line) -Encoding UTF8
}

function global:FG-Move-To-Scratch([string]$path) {
  $name = Split-Path $path -Leaf
  New-Item -ItemType Directory -Force -Path $FG_SCRATCH | Out-Null
  $dest = Join-Path $FG_SCRATCH ((Get-Date -Format "yyyyMMdd_HHmmss_") + $name)
  # 文件可能正被占用（AI 刚写完），最多重试 8 次 * 间隔 250ms = 2 秒
  for ($i = 0; $i -lt 8; $i++) {
    try { Move-Item -LiteralPath $path -Destination $dest -ErrorAction Stop; break }
    catch {
      if ($i -eq 7) { throw ("移动失败（可能被占用）: {0} -> {1}" -f $path, $dest) }
      Start-Sleep -Milliseconds 250
    }
  }
  return $dest
}

# 判定根一级散件：不在白名单内的新文件
function global:FG-Test-Disallowed([string]$name) {
  if ($name -match '^(\.|~|\$)') { return $false }        # 隐藏/临时系统文件不管
  $first = $name.Split([IO.Path]::DirectorySeparatorChar)[0]
  return -not ($FG_ALLOWED -contains $first)
}

# 心跳（P1-6 轻量探活）：每 60 秒写一次，watchdog 读 mtime 判断本进程存活。
# 心跳文件放在 $FG_ROOT\_rules 下（该目录属 C0 白名单且常驻存在）。
$global:FG_HB = Join-Path $FG_ROOT "_rules\placement-guard.heartbeat"
function global:FG-Write-Heartbeat {
  $hbDir = Split-Path $FG_HB
  if (Test-Path $hbDir) {
    Set-Content -Path $FG_HB -Value (Get-Date -Format "yyyy-MM-dd HH:mm:ss") -Encoding ascii
  }
}

# 单次扫描现存散件（ScanOnce / 启动预热共用）
function Invoke-OneScan {
  Get-ChildItem -LiteralPath $FG_ROOT -File -ErrorAction SilentlyContinue |
    Where-Object { FG-Test-Disallowed $_.Name } | ForEach-Object {
      if ($FG_DRYRUN) {
        Write-Host ("[preview] 根目录散件: {0}" -f $_.FullName)
      } else {
        $dest = FG-Move-To-Scratch $_.FullName
        FG-Write-Log ("自动归位 {0} -> {1}" -f $_.FullName, $dest)
        Write-Host ("[moved] {0} -> {1}" -f $_.FullName, $dest)
      }
    }
}

# 启动先扫一遍存量（正式模式下归位既有散件，不留死角）
Invoke-OneScan

if ($ScanOnce) {
  FG-Write-Heartbeat   # 单次运行也写心跳，watchdog 只信心跳新鲜度
  Write-Host ("[placement-guard] 单次扫描完成 (DryRun={0})" -f $FG_DRYRUN)
  exit 0
}

# 常驻文件系统监视（不递归，只盯根一级）
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $FG_ROOT
$watcher.IncludeSubdirectories = $false
$watcher.Filter = "*.*"
$watcher.NotifyFilter = [System.IO.NotifyFilters]::FileName
$action = {
  $path = $Event.SourceEventArgs.FullPath
  $name = $Event.SourceEventArgs.Name
  if ($Event.SourceEventArgs.ChangeType -ne "Created") { return }
  if (-not (Test-Path $path)) { return }
  if (-not (FG-Test-Disallowed $name)) { return }
  if ($FG_DRYRUN) {
    Write-Host ("[preview] 发现根目录散件: {0}" -f $path)
    return
  }
  try {
    $dest = FG-Move-To-Scratch $path
    FG-Write-Log ("自动归位 {0} -> {1}" -f $path, $dest)
  } catch { Write-Host ("[error] {0}" -f $_.Exception.Message) }
}
Register-ObjectEvent -InputObject $watcher -EventName "Created" -Action $action | Out-Null
Write-Host ("[placement-guard] 监视中: {0}  (DryRun={1})" -f $FG_ROOT, $FG_DRYRUN)
# 常驻等待（计划任务停止时由系统终止）；每 12 次 * 5s = 60s 写一次心跳
$hbTick = 0
while ($true) {
  Start-Sleep -Seconds 5
  $hbTick++
  if ($hbTick -ge 12) { FG-Write-Heartbeat; $hbTick = 0 }
}