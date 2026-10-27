---
name: github-publish
version: 0.1.3
description: 统一 GitHub 发版通道（一条龙）：扫描客户端下所有受管项目 → 审计发版资格（文件/结构/版本/内容）→ 补齐纠正（双语 README/License/版本对齐）→ 脚本化发布到 GitHub Releases（打 tag + 双语 release notes + 源码包/资产，公开可下载）。适用于：发版、发布、发个 release、审核发版资格、检查能不能发版、缺 README/LICENSE、补齐后发布、把项目发布到 GitHub、发布套件/skill/插件等场景。
---

# GitHub 发版工具 — 统一发版通道（github-publish）

把客户端下所有受管项目（套件 / skill / 插件 / 工具）逐个发布到用户 GitHub 仓库 Releases 的一条龙流水线。**纯脚本执行，无 AI 参与发布过程**；AI 只负责驱动命令与处置结果。

## 发布架构（源只读 → 构建区 → 发布区）

```
源项目（只读）  →  _build/<产品>（净化副本）  →  momoteaxp/free/<产品> + Releases
```

- **源项目零写入**：发布流程不 bump、不 commit、不 tag 源项目
- **构建区每次从源重建**，默认排除 `docs/**`（内部文档）、`.comate/`、`.fileguard-sync.json`、`_索引.md` 与产物目录
- **zip 资产从构建区打**，与仓库源码同源（不会混入内部文件）
- 项目级排除/白名单：`config/publish-projects.json`（源文件不改）

## 流水线

| 步骤 | 命令 | 作用 |
|---|---|---|
| 0 自检 | `python scripts\doctor.py` | D1-D8 环境自检（gh/认证/scopes/代理+API/配置/MCP/git身份/受管项目），发版前先跑 |
| 1 扫描 | `python scripts\scan.py` | 自动发现受管项目，出就绪度看板 READY / FIXABLE / BLOCKED |
| 2 审计 | `python scripts\audit.py <源项目根>` | A1-A12 资格检查（建议性；权威门禁在构建区净化） |
| 3 预演 | `python scripts\publish.py <源项目根> --dry-run` | 建构建区 → 净化 → 指纹/版本 → 打包，不推送 |
| 4 发布 | `python scripts\publish.py <源项目根>` | 构建区净化门禁 → 指纹门禁 → zip → push+tag → gh release |
| 手动补齐 | `python scripts\fix.py <项目根> [--force-readme]` | 需要改进源项目自身文档时手动用；发布流程会自动在构建区补齐缺失项 |

> 环境事实、账号、路径、网络、认证步骤、FAQ 全部固化在 `docs/环境与配置.md`，排查先看它。

## 关键事实（方案依据，2026-10-27 调研）

- **源码类项目发布零门槛**：公开仓库放源码即可；每个 tag 的 Release 由 GitHub **自动附带 "Source code (zip / tar.gz)"**，纯源码项目可以不传任何资产。
- **README 双语最通用做法**：`README.md`（英文）+ `README.zh-CN.md`（中文），GitHub 按访问者浏览器语言自动切换渲染。结构照 standard-readme：简介 → 特性 → 安装 → 使用 → 下载 → License。
- **License 默认 MIT**：`LICENSE` 文件必须放仓库根，版权署名在 `config/release-config.json` 配置。
- **认证（标准方式，无兜底 hack）**：token 需 `repo` + `read:org` + `gist`；`gh auth login --with-token` 登录（存 Windows 凭据管理器）→ `gh auth setup-git` 配置 git 凭据 → `doctor.py` 验证。
- **国内网络**：发布（上传方向）只能走用户自己的梯子。`publish.py` 会**自动探测本地代理端口**（v2rayN 10808/10809、Clash 7890/7897 等）并注入 `HTTPS_PROXY`；也可在 `config/release-config.json` 的 `china_network.proxy` 显式指定。注意：浏览器能上 GitHub ≠ 命令行能上，必须让代理软件在运行（或开 TUN/全局模式）。国内朋友下载走 ghproxy 等镜像前缀或 jsDelivr，已写进生成的 README"国内加速下载"小节。
- **gh 定位**：正式版 `E:\Program Files\GitHub CLI\gh.exe`（系统 PATH）；`publish.py` 优先 PATH，找不到按固定路径兜底（便携版备份 `D:\comate\tools\gh`）。
- **单仓库多产品**：`config/release-config.json` 的 `publish.tag_pattern` 默认 `{name}-v{version}`，避免多个产品共用仓库时 tag 冲突（如 `file-guard-v0.5.2`）。若某产品独享仓库，改成 `v{version}`。

## 使用流程（AI 驱动）

1. `scan.py` 看全貌：READY / FIXABLE / BLOCKED。
2. 需要修源项目时，跑 `fix.py` 补齐文档（这是**有意的源修改**；发布流程本身不会写源）。
3. `publish.py <源项目根> --dry-run` 预演：建构建区 → 净化 → 补齐 → 指纹/版本 → 打包，不推送。
4. 确认无误后 `publish.py <源项目根>` 正式发布（每次一个，节奏用户掌握）。
5. 发布历史自动登记进 `data/release-manifest.json`（含源指纹）。
6. **保险锁**：`config/release-config.json` 的 `publish.enabled=false` 时只允许 dry-run；确认准备就绪后改 `true`。

## 版本纪律（代码强制，非自觉）

- **指纹比对**：构建区内容与上次发布完全一致 → 拒绝重复发布
- **有变化必须递增**：构建内容有变化但源版本未大于上次发布 → 拒绝（请先在源项目有意升级版本；本流程不写源）
- **版本回退拒绝**：源版本小于上次发布版本直接拒绝
- **发布历史真源**：`data/release-manifest.json`（root/version/tag/repo/url/日期/`source_fingerprint`）
- **审计提示**：`audit.py` A12 提示"自上次发布以来有几个文件未发版"

## README 版面（模板已固化，fix.py 生成）

两套模板（`templates/README.en.md` / `README.zh-CN.md`）按开源门面最佳实践组织：
居中标题 + 一句话定位 + 徽章（License/Version/Platform）+ 中英切换 → **这是什么/适合谁** → **核心特性** → **与同类相比** → **快速开始** → **使用说明** → **环境要求** → **常见问题（折叠）** → **更新记录** → **联系（Issues）** → **项目结构** → **国内下载加速** → License。

渲染数据来源（`project_meta.json` 可选字段，缺省用占位提示）：
`tagline` / `audience` / `features`(数组) / `highlights` / `quickstart` / `usage` / `requirements` / `platform` / `structure` / `publish_exclude`(数组，同步时排除的文件)；英文可加 `_en` 后缀变体。

## 配置（config/release-config.json）

- `github.owner`：已回填 `momoteaxp`
- `github.default_repo`：已回填 `free`（单仓库形态，所有产物发往 `momoteaxp/free`）
- `license.holder`：已回填 `momoteaxp`
- `publish.enabled`：发布保险锁（默认 `false`，只允许 dry-run）
- `publish.docs_policy`：`internal`（默认，`docs/**` 不进公开副本）
- `publish.tag_pattern`：单仓库多产品时用 `{name}-v{version}`
- `sanitize.denylist`：公开前必须脱敏的词（公司名/人名/内部文件名），命中即 FAIL
- `sanitize.allow_paths`：豁免净化检查的文件 glob
- `china_network.proxy` / `download_mirrors`：上传代理（留空自动探测）与 README 国内加速镜像
- `config/publish-projects.json`：逐项目排除/白名单（不改源文件）

## 新项目登记机制

- **自动发现**：受管登记表 `managed-projects.json` 里 status=active 的项目（含 new-project 新建的）scan.py 自动纳入，**无需手动登记**。
- **补充登记**：未纳入受管的项目用 `python scripts\scan.py --register <项目根> [--repo owner/repo]` 登记进 `data/release-manifest.json`。

## 与 GitHub MCP 的关系（2026-10-27 实测）

客户端能力扩展里的 GitHub MCP（`@modelcontextprotocol/server-github`，NPX，26 个工具）**不含任何 release 工具**：只有文件读写、建仓库/分支、推文件、issue/PR、搜索。因此：

- **发布环节**：MCP 替代不了，必须用 gh CLI（或带 token 的 REST 直连）。
- **辅助环节**：MCP 可用于建目标仓库、推文件、管理 issue/PR（AI 驱动通道）。
- **安装范围**：添加时选「**个人**」= 所有项目生效（统一通道需要这个）；选「**项目**」= 仅当前项目生效，会破坏跨项目统一通道。

## 注意事项

- `publish.py` 只写构建区（`_build/`），**绝不写源项目**；权威门禁是"构建区净化 + 指纹/版本纪律"。
- `audit.py` / `sanitize.py` 可单独对源项目运行，作为诊断/预检（建议性）。
- `fix.py` 只创建缺失文件，绝不覆盖已有内容；`--force-readme` 会把旧 README 移入 `_trash/`。
- 源项目有内容变化时，必须先在源项目**有意升级版本**，否则发布会被拒绝（流程不代改源）。
- 构建区默认排除 `docs/**`、`.comate/`、`.fileguard-sync.json`、`_索引.md` 与产物目录；需要公开某份文档时用 `config/publish-projects.json` 的 `include` 白名单。
- 目标仓库未确定时用 `--repo owner/repo` 指定；`--draft` 可先发草稿供检查；`--force` 仅用于紧急绕过保险锁。
- 源项目自带的 `build-release.py` **只用于本地升版本/打包**，不参与发布；发布由本工具在构建区统一完成。
