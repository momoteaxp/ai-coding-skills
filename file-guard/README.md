<div align="center">

# FileGuard (Comate) 插件套件

**Comate 版 FileGuard：写前拦截 + 跨窗口续接 + 一条龙受管项目体系**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.6.3+build.1-green.svg)](https://github.com/momoteaxp/free/releases)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#requirements)

[English](README.md) | [中文](README.zh-CN.md)

</div>

## What is it

comate 版 FileGuard 套件（PreToolUse 写前拦截 + PreCompact + 体检 skill + .comateignore 引擎级兜底 + new-project skill），独立单源（2026-10-23 脱离原基准，enforcer.py/init.py/checkpoint-manager.py/规则文件均在 comate 侧）

**Who is it for**: 在 Comate 中做 AI 辅助开发、希望文件写入有护栏、项目结构统一、跨窗口不丢进度的开发者


<!-- MESSAGE-STRATEGY:START -->
## 这个项目解决什么问题

> 一句话定位：面向 Comate 开发者，FileGuard 是一套项目管理套件：写前拦截 + 引擎兜底，让 AI 写不进不该写的地方。

在 Comate 中做 AI 辅助开发、希望文件写入有护栏、项目结构统一、跨窗口不丢进度的开发者，下面这些场景可能很熟悉：

- **文件落错地方**：AI 写代码很快，但它不知道你的目录规则。FileGuard 在写入前检查目录白名单、只读清单和敏感文件，违规直接拒绝；就算 hooks 被关掉，还有 .comateignore 引擎层兜底。
- **版本号对不上**：版本号散落在 meta、plugin、README、SKILL 里，手工同步迟早出错。FileGuard 在体检和发版门禁里逐个文件比对版本，不一致就拒绝发版。
- **项目串台 / 端口冲突**：多个项目并行时，目录、端口、配置最容易串。FileGuard 给每个项目独立的规则和路径派生，跨项目读取默认拦截，需要时走显式通道，避免 AI 把两个项目混在一起。

<!-- MESSAGE-STRATEGY:END -->

## Features

- 写前拦截：PreToolUse 钩子按 project_meta.json 规则拦截违规写入（目录白名单/只读/敏感文件）
- .comateignore 引擎级兜底：不依赖 hooks，引擎层拦读+拦写，热更新
- 跨窗口续接：checkpoint save/load + 压缩自动归档，进度真源 latest.json
- 一条龙建项目：new-project / takeover-project skill（骨架→登记→验收）
- 套件体检：doctor D1-D12 自检 + 发版门禁（版本一致 / 自举合规）
- 本地优先：数据不出本机，无需云端

## Why this one

- 规则即代码：project_meta.json 驱动的写前拦截，不靠 AI 自觉
- 安装自适应：部署时询问受管根、按实际路径生成 hooks，不写死盘符
- Windows 深度集成：junction 挂载 + 计划任务归位，开箱即用

## Quick Start

1. 挂载并配置：powershell -ExecutionPolicy Bypass -File scripts/first-run.ps1（自动检测受管根，可 -Yes 跳过确认）
2. 体检：python scripts/doctor.py（D1-D12 全绿）
3. 新建受管项目：python scripts/new-project.py <name> --type skill

> 首次装机顺序：先 `deploy.ps1`（生成 hooks.json 并合并全局 hooks），再 `doctor.py`——D2 依赖 deploy 的产物。L4 计划任务属可选增强，未注册只告警不阻断体检；zip 安装无 `.git` 时 L3 也属可选，`git init` 后重跑 deploy 会自动安装。

## Usage

日常使用 /new-project 建项目、/takeover-project 接手项目、/fileguard-doctor 体检。发布统一走 github-publish，本套件自身不含上传能力。

## Requirements

- Windows 10/11（hooks、计划任务、junction 依赖 Windows）
- Comate 客户端（插件目录 ~/.comate/plugins）
- Python 3.10+ / PowerShell 5.1+
- 受管根安装时询问（默认 %USERPROFILE%/comate，保存为用户环境变量 COMATE_FG_HOME）
- 安装 L4 计划任务需管理员权限

## FAQ

<details>
<summary>Something went wrong during install or run. What should I do?</summary>

Open an issue in this repository with the error output, your OS version, and reproduction steps. See [Releases](https://github.com/momoteaxp/free/releases) for changes in each version.

</details>

<details>
<summary>How do I know I am on the latest version?</summary>

Check the [Releases](https://github.com/momoteaxp/free/releases) page; the version badge at the top of this README also shows the current version.

</details>

## Changelog

Every release ships with bilingual release notes on the [Releases](https://github.com/momoteaxp/free/releases) page.

## Contact

- Issues: https://github.com/momoteaxp/free/issues

## Project structure

```
file-guard/
├─ hooks/        hooks.template.json（公开；hooks.json 部署时生成）
├─ scripts/      enforcer / doctor / new-project / build-release 等
├─ skills/       new-project / takeover-project / fileguard-doctor
├─ rules/ templates/ docs/ _checkpoint/ release/
```

## Download (China mirror)

- If GitHub Releases is slow in mainland China, prefix the URL with a mirror such as `https://ghproxy.net/`

- https://ghproxy.net/
- https://ghfast.top/
- https://cdn.jsdelivr.net/gh/momoteaxp/free@

## License

MIT © momoteaxp