---
name: {project_name}
description: {type_label} 项目 {project_name}，由 FileGuard 骨架生成（{date}）。用途/用法说明见 README.md。
version: {version}
---

# {project_name}

{type_label}。骨架按 FileGuard 受管项目体系生成（docs/受管项目体系设计-20261023.md）。

## 目录速览

| 目录 | 用途 |
|---|---|
| {dirs} | 见 `_索引.md` 完整目录规则 |

## 使用方式

（本 skill 何时触发、完成什么任务、产出什么格式——按 Agent Skills 规范补全。）

## 注意

- 版本单一来源：`project_meta.json`；发版用 `tools/build-release.py --bump <级别>`
- 目录放置规则由 FileGuard 拦截强制执行（project_meta.json 白名单）
