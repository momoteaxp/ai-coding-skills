<div align="center">

# GitHub 发版工具

**统一发版通道：源只读 + 构建区净化 + 一键发布到 GitHub Releases**

**Works with**: Comate

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.1.5-green.svg)](https://github.com/momoteaxp/ai-coding-skills/releases)
[![Client](https://img.shields.io/badge/client-comate-purple.svg)](#requirements)
[![Platform](https://img.shields.io/badge/platform-Cross-platform-lightgrey.svg)](#requirements)

[English](README.md) | [中文](README.zh-CN.md)

</div>

## What is it

GitHub 发版工具：按用户节奏逐个把自研套件/skill/插件/工具发布到单一 GitHub 仓库 Releases（gh CLI 封装 + 发版清单 + 打 tag + release notes + 上传资产）；用户 2026-10-27 建项目时定：单仓库形态

**Who is it for**: 想把自研套件 / skill / 插件安全公开，又不想手工整理文档和脱敏的开发者

## Features

- 源文件只读：发布流程绝不写源（不 bump、不 commit、不 tag）
- 构建区净化：从源生成独立副本（_build），可随时重建，默认排除内部文档与机器配置
- 发布保险锁：默认关闭，只允许预演；确认准备就绪后才放行
- 预演模式：--dry-run 只构建与校验，不碰线上
- 自动门面：缺失时在构建区生成中英双语 README 与 LICENSE
- 版本纪律：内容指纹比对 + 版本必须递增 + 禁止同版本重复发布
- 单仓库多产品：tag 用 产品名-v版本 区分，源码与 zip 同源
- 发布历史可追溯：manifest 记录源指纹 / 版本 / tag / 链接
- 国内网络自适应：自动探测本地代理 + 失败重试 + 下载镜像写进 README

## Why this one

- 发布物与源隔离：源永不被发布流程污染
- 内部文档默认不公开（docs/**），可按项目白名单
- 一条命令完成 净化 → 打包 → 发布；预演不碰线上
- 任意项目接入：skill / suite / plugin / 工具统一通道
- 规则可配置：黑名单词 / 项目排除 / 镜像前缀

## Quick Start

1. 填写 config/release-config.json（owner / default_repo / license.holder）
2. 环境自检：python scripts/doctor.py
3. 预演：python scripts/publish.py <源项目根> --dry-run
4. 确认无误后把 publish.enabled 改为 true，再正式发布

## Usage

scan.py 看全貌 → publish.py --dry-run 预演 → 确认后 publish.py 发布；audit / sanitize / fix 可按需单独诊断（详见 README 与 SKILL.md）。

## Requirements

- Windows / Linux / macOS（脚本为 Python，发布流程跨平台）
- Python 3.10+
- GitHub CLI（gh）并完成 gh auth login
- 国内上传需代理（脚本自动探测，或配置 china_network.proxy）

## FAQ

<details>
<summary>Something went wrong during install or run. What should I do?</summary>

Open an issue in this repository with the error output, your OS version, and reproduction steps. See [Releases](https://github.com/momoteaxp/ai-coding-skills/releases) for changes in each version.

</details>

<details>
<summary>Will this project modify my files?</summary>

Check the "Requirements / Usage" sections of this README; projects that involve hooks or scripted writes say so explicitly. Read the rules and keep a backup before first use.

</details>

<details>
<summary>How do I know I am on the latest version?</summary>

Check the [Releases](https://github.com/momoteaxp/ai-coding-skills/releases) page; the version badge at the top of this README also shows the current version.

</details>

## Changelog

Every release ships with bilingual release notes on the [Releases](https://github.com/momoteaxp/ai-coding-skills/releases) page.

## Contact

- Issues: https://github.com/momoteaxp/ai-coding-skills/issues

## Project structure

```
github-release-tool/
├─ scripts/   scan / audit / sanitize / fix / publish / doctor
├─ skills/    github-publish（客户端 skill）
├─ config/    release-config / publish-projects
├─ data/      release-manifest（发布历史）
└─ _build/    构建区（不上传，可随时重建）
```

## Download (China mirror)

- If GitHub Releases is slow in mainland China, prefix the URL with a mirror such as `https://ghproxy.net/`

- https://ghproxy.net/
- https://ghfast.top/
- https://cdn.jsdelivr.net/gh/momoteaxp/ai-coding-skills@

## License

MIT © momoteaxp
