---
name: fileguard-doctor
version: 0.6.2
description: FileGuard 套件体检与受管项目管理。当用户想检查 FileGuard(comate) 插件是否正常工作、想对新项目做"套件体检"（登记目录白名单/命名规则/只读清单）、想在 comate 侧一键新建受管项目、或想了解当前受管项目状态时使用。
---

# FileGuard 套件体检与新建项目

## 职责
1. 检查 FileGuard(comate) 插件是否被 comate 加载、钩子是否生效（D1-D12 全项）。
2. 对 comate 受管根（默认 `<managed-root>`）下的项目做体检：是否已登记 `project_meta.json`、规则是否合理。
3. 一键新建受管项目（骨架 + project_meta.json + 版本规范），登记后写前拦截自动生效。
4. 未登记项目：生成 `project_meta.json`（参考本套件 `scripts/init.py` 类型模板），放到项目根目录。

## 一键新建受管项目
```
python <managed-root>\products\file-guard\scripts\new-project.py <name> --type A|B|C [--root <managed-root>\products] [--force]
```
- 项目名必须英文小写短横线（comate 侧不用中文目录名）；类型 A=软件应用 / B=插件/skill / C=文档解析。
- 调用本套件 `scripts/init.py`（独立单源，2026-10-23 复制自原基准后独立演进），类型模板从 C0 `dir_type_map` 派生（`<managed-root>\_rules\global-rules.json` 独立规则）。
- 产物：类型骨架目录 + project_meta.json + _索引.md + git init + 首提交 + 套件组件装配（含 L3 pre-commit）。
- 登记即保护：写前拦截按 project_meta.json 规则自动生效。

## 套件体检（D1-D12）
```
python <managed-root>\products\file-guard\scripts\doctor.py
```
检查项：D1 插件挂载（junction + plugin.json）｜D2 钩子配置（PreToolUse 引擎工具名 + PreCompact，命令无引号）｜D3 核心复用（scripts/enforcer.py 存在）｜D4 规则层（`_rules\global-rules.json` 存在且可解析）｜D5 项目登记（meta 可解析；空表=WARN，新装机正常）｜D6 L3 pre-commit（git 仓库适用；zip 安装=WARN）｜D7 L4 FSW 计划任务（可选增强，未注册=WARN 不阻断）｜D8 环境变量生效值（显示实际受管根）｜D9 版本一致性（版本行清单全一致）｜D10 引擎级拦截（.comateignore 与 ignore-gen.py 一致）｜D11 漏网项目扫描（受管根无 meta 目录 / 有 meta 未登记 / 登记失效）｜D12 进度体系前提（登记项目 meta 含 `_checkpoint` 白名单）。退出码 0=无失败项（告警不阻断），1=存在失败项。

## 拦截通道（2026-10-23 校准后双通道）
- **hooks 通道**：PreToolUse → `scripts/pre-tool-use.py` → `scripts/enforcer.py`（写前拦截：C0 黑名单 / _trash / 只读 / 目录白名单）+ checkpoint 跨项目读取拦截。引擎工具名必须用小写 Agent 名（write_file/edit_file/delete_file/apply_patch/read_file/grep_content/glob_path/list_dir/read_lints/run_command），command 必须无内层引号（Node spawn cmd /s /c 会搞乱引号）。
- **引擎级通道（兜底，不依赖 hooks）**：`scripts/ignore-gen.py` 生成 `.comateignore`（引擎 FsPermissionService 在非 sandboxAuto 也生效、热更新、拦读+拦写）。改规则后跑 `ignore-gen.py --write [--global]` 重新生成。

## 跨窗口接续（进度真源 = _checkpoint/latest.json，2026-10-23 分层定案）
- **保存进度**（会话结束/开新窗口前）：`python <managed-root>\products\file-guard\scripts\checkpoint-manager.py save --project <项目根> --current-task "<一句话>" --pending-tasks "待办1,待办2"`——只写 3-5 行字段，latest.json 即跨窗口接续真源。注：数组参数（--completed-steps/--pending-tasks/--key-decisions）接受 JSON 数组，但 **PowerShell 5.1 原生参数会剥掉含空格 JSON 的内层引号**，故约定用逗号分隔形式（项内不能含逗号）。
- **接续**（新窗口）：读 `<项目根>\_checkpoint\latest.json`（几行）+ `docs/交接文档-YYYYMMDD.md` 顶部指针区；背景细节按需读正文，不自动全量加载（省 token）。
- **压缩自动归档**（PreCompact 钩子）：只写元信息审计（kind/project/cwd/timestamp），**不含任务状态**——续接不依赖它；对齐 CHECKPOINT-SCHEMA 铁律"自动通道只是归档者，不是状态写者"，latest.json 已有内容绝不动。
- 跨项目读 checkpoint 仍受拦截（C0 read_scope=current_project_only），显式逃生通道：`checkpoint-manager.py load --project <目标项目根>`。

## 发版 / 重启检查 / L4 运维（P5-P7）
- **发版门禁**：`python scripts/build-release.py --bump patch|minor|major`（升版本+提交+tag+打包）或 `--pack-current`（补发当前版本）。门禁：doctor D1-D12 全绿 + 自举合规 0 违规（git 跟踪文件逐个过 enforcer）+ 版本一致（`version_check.py`：project_meta/plugin/README/README.zh-CN/_索引/docs-README/SKILL.md frontmatter 的版本行全部一致，不一致拒绝发版）。bump 会自动同步各版本行。产物 `release/file-guard-comate-vX.Y.Z.zip`（不入库，遵守 meta.publish_exclude）。
- **版本一致性**：`python scripts/version_check.py`（校验，exit 0/1）；`--sync <版本>`（同步版本行，真源 project_meta.json 除外）。新增带版本的文件时在 version_check.py 的 VERSION_SOURCES 登记。
- **重启前检查**：`python scripts/pre-reboot-check.py`（R1 doctor 全绿 / R2 版本一致 / R3 工作树 clean / R4 L4 任务已注册 / R5 规则文件存在可解析），exit 0 才建议重启。
- **L1 权限（sandbox.json）**：已按官方 schema 落盘（`.comate/sandbox.json` + 全局），但 **Comate 4.13.4 Windows 端 sandboxAuto 不可选**（UI 隐藏），denyRead/denyWrite 不生效；敏感隔离由 `.comateignore` 承担（见上）。
- **L4 comate 归位**：`powershell -ExecutionPolicy Bypass -File scripts/register-comate-guard-task.ps1`（自提升管理员）注册 3 个任务：Comate Placement Guard（常驻，登录+唤醒触发）/ - ScanOnce（5min 兜底）/ - Watchdog（2min 探活重启）。launcher 内置 `FG_HOME=<managed-root>`，guard 心跳 `<managed-root>\_rules\placement-guard.heartbeat`。卸载：Unregister-ScheduledTask 三个任务（见脚本头注释）。
- **_scratch / _trash 清理**：comate 侧未做自动 TTL 清理（原基准的 scratch-clean/trash-cli 未迁移；guard-config 中 L4ScratchCleanTime/L4TrashCleanTime 为历史声明，2026-10-23 已移除）。当前手动管理：`_scratch` 临时文件随手清、`_trash` 丢弃文件定期清。

## 体检步骤
1. 首次装机先跑 `scripts/deploy.ps1`（生成 hooks.json、合并全局 hooks；有 `.git` 时自动装 L3）；D2 依赖 deploy 的产物，否则会报“先 deploy 再 doctor”。确认插件位置：`<managed-root>\products\file-guard`（junction 挂到 `~/.comate/plugins/file-guard`）。
2. 确认核心复用：`scripts/enforcer.py` 存在（独立单源）。
3. 跑 `doctor.py` 做 D1-D12 体检；列出受管根 `<managed-root>` 下的项目（可调 `python <managed-root>\products\file-guard\scripts\enforcer.py list --root <managed-root>`）。
4. 未登记项目：生成 `project_meta.json`（参考本套件 init.py 模板：dirs 白名单 / root_file_name_rule / read_only_files / read_only_dirs / strict_mode），放到项目根目录。
5. 汇报：每个项目 已登记/未登记、规则摘要、D1-D12 失败项与修复建议。

## 注意事项
- 只检查、只生成 meta / 新建项目，不改动本套件核心文件（修改需用户确认）。
- 登记 meta / 新建项目属于"受用户确认"动作，执行前先给用户看项目名、类型与目标根目录。
- 若 D4 报"规则文件缺失/不可解析"，检查 `<managed-root>\_rules\global-rules.json`（独立规则文件，与任何其他套件无关）。
- 若 hooks 通道失效（拦截不生效），先查 hooks.json 的 matcher 是否引擎工具名、command 是否无引号；`.comateignore` 兜底通道不受影响。
