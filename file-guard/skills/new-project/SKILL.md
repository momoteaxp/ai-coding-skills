---
name: new-project
description: 当用户说要"新建一个项目 / 新项目 / 建个项目 / 创建一个项目 / 做一个xxx项目"并说明用途时触发。按 FileGuard 受管项目体系（docs/受管项目体系设计-20261023.md）走统一建项目流程：识别细类 → new-project.py 建骨架 → 自动登记 → 验收。半道接手的既有项目不走本流程，走"接手审计"流程。
---

# 新建项目（FileGuard 受管项目体系）

目标：任何窗口的助手听到"新建项目"即可可靠地建出规范骨架，不依赖碰运气。

## 第一步：确定细类

按用户说的用途对号入座：

| 细类 | 用途（用户说） | 骨架要点 |
|---|---|---|
| `software` | 软件应用 / 桌面程序 / 挂件 / 后端服务 | src-layout：src/ tests/ config/ scripts/ docs/ |
| `skill` | 客户端 skill / 文档生成 skill / 工具 skill | SKILL.md + scripts/ references/ assets/ hooks/ skills/ |
| `suite` | 套件（插件+skill+规则组合，像 FileGuard 自己） | plugin.json + skills/ hooks/ _rules/ .comate/ |
| `web` | 网页 / 前端 / 站点 | src/ public/ components/ styles/ |
| `docgen` | 图纸/文档解析 / 内容管线 | input/（只读）templates/ content/ output/ |
| `ops` | 运维 / 维护 / 配置管理 | config/ data/ scripts/ docs/ |

拿不准就选最贴近的，或问用户一句话。

## 第二步：执行建骨架命令

命名规则：**英文小写短横线**（如 `travel-guide-ppt`、`weak-current-ops`）；new-project.py 会强制校验。

```bash
python %USERPROFILE%\comate\products\file-guard\scripts\new-project.py <项目名> --type <细类>
```

示例：
```bash
python %USERPROFILE%\comate\products\file-guard\scripts\new-project.py travel-guide-ppt --type skill
```

默认父目录 `%USERPROFILE%\comate\products`；可用 `--root <父目录>` 改。旧别名 `A/B/C` 兼容（A→software、B→skill、C→docgen）。

## 第三步：建完自动做的事（脚本已内置，无需手动）

1. 按细类模板建全部目录 + 初始文件（project_meta.json、_索引.md、README、版本规范、checkpoint 三件套、L3 pre-commit、版本工具 version_check/build-release）
2. git init + 首次提交
3. **自动登记**进 `%USERPROFILE%\comate\_rules\managed-projects.json`（中央登记表）
4. **自动生成** `.comateignore`（引擎级拦截兜底）

## 第四步：验收清单（向用户汇报）

- [ ] doctor 对项目自检（若装了套件组件）
- [ ] 目录齐全、project_meta.json 类型/版本正确
- [ ] 已登记 + .comateignore 已生成
- [ ] 交付用户使用（此后项目在自身窗口内自管理：写前拦截 + 引擎兜底 + 版本门禁）

## 注意事项

- 项目名撞车（已存在）会拒绝；半道接手项目不要用本流程重建，走"接手审计"（审计现状 → 回填 → 掰正 → 登记 → 复检）。
- 版本号：初始 0.1.0 自动写入；后续发版用项目内 `tools/build-release.py --bump patch|minor|major`。