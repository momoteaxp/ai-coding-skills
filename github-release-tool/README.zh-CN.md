<div align="center">

# GitHub 发版工具

**统一发版通道：源只读 + 构建区净化 + 一键发布到 GitHub Releases**

**适用客户端**：Comate

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v0.1.3-green.svg)](https://github.com/momoteaxp/free/releases)
[![Client](https://img.shields.io/badge/client-comate-purple.svg)](#环境要求)
[![Platform](https://img.shields.io/badge/platform-Cross-platform-lightgrey.svg)](#环境要求)

[中文](README.zh-CN.md) | [English](README.md)

</div>

## 这是什么

GitHub 发版工具：按用户节奏逐个把自研套件/skill/插件/工具发布到单一 GitHub 仓库 Releases（gh CLI 封装 + 发版清单 + 打 tag + release notes + 上传资产）；用户 2026-10-27 建项目时定：单仓库形态

**适合谁**：想把自研套件 / skill / 插件安全公开，又不想手工整理文档和脱敏的开发者

## 核心特性

- 源文件只读：发布流程绝不写源（不 bump、不 commit、不 tag）
- 构建区净化：从源生成独立副本（_build），可随时重建，默认排除内部文档与机器配置
- 发布保险锁：默认关闭，只允许预演；确认准备就绪后才放行
- 预演模式：--dry-run 只构建与校验，不碰线上
- 自动门面：缺失时在构建区生成中英双语 README 与 LICENSE
- 版本纪律：内容指纹比对 + 版本必须递增 + 禁止同版本重复发布
- 单仓库多产品：tag 用 产品名-v版本 区分，源码与 zip 同源
- 发布历史可追溯：manifest 记录源指纹 / 版本 / tag / 链接
- 国内网络自适应：自动探测本地代理 + 失败重试 + 下载镜像写进 README

## 与同类相比

- 发布物与源隔离：源永不被发布流程污染
- 内部文档默认不公开（docs/**），可按项目白名单
- 一条命令完成 净化 → 打包 → 发布；预演不碰线上
- 任意项目接入：skill / suite / plugin / 工具统一通道
- 规则可配置：黑名单词 / 项目排除 / 镜像前缀

## 快速开始

1. 填写 config/release-config.json（owner / default_repo / license.holder）
2. 环境自检：python scripts/doctor.py
3. 预演：python scripts/publish.py <源项目根> --dry-run
4. 确认无误后把 publish.enabled 改为 true，再正式发布

## 使用说明

scan.py 看全貌 → publish.py --dry-run 预演 → 确认后 publish.py 发布；audit / sanitize / fix 可按需单独诊断（详见 README 与 SKILL.md）。

## 环境要求

- Windows / Linux / macOS（脚本为 Python，发布流程跨平台）
- Python 3.10+
- GitHub CLI（gh）并完成 gh auth login
- 国内上传需代理（脚本自动探测，或配置 china_network.proxy）

## 常见问题

<details>
<summary>安装或运行遇到问题怎么办？</summary>

先在仓库提 Issue，附上报错信息、操作系统版本和复现步骤。每次发版的变更说明见 [Releases](https://github.com/momoteaxp/free/releases)。

</details>

<details>
<summary>这个项目会修改我的文件吗？</summary>

以本 README 的「环境要求 / 使用说明」为准；涉及钩子、脚本写入的项目会在相应小节明确说明。首次使用前请先阅读规则并做好备份。

</details>

<details>
<summary>如何确认自己用的是最新版本？</summary>

打开 [Releases](https://github.com/momoteaxp/free/releases) 页面，最新版本即当前推荐版本；本 README 顶部徽章也会显示版本号。

</details>

## 更新记录

每次发版都会在 [Releases](https://github.com/momoteaxp/free/releases) 页面附中英双语变更说明。

## 反馈与联系

- 问题反馈：https://github.com/momoteaxp/free/issues

## 项目结构

```
github-release-tool/
├─ scripts/   scan / audit / sanitize / fix / publish / doctor
├─ skills/    github-publish（客户端 skill）
├─ config/    release-config / publish-projects
├─ data/      release-manifest（发布历史）
└─ _build/    构建区（不上传，可随时重建）
```

## 国内下载加速

- GitHub Releases 直链若较慢，可在链接前加镜像前缀（如 `https://ghproxy.net/`）

- https://ghproxy.net/
- https://ghfast.top/
- https://cdn.jsdelivr.net/gh/momoteaxp/free@

## License

MIT © momoteaxp
