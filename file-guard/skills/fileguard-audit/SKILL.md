---
name: fileguard-audit
description: FileGuard 套件/项目自审计（只读）。当用户要求审计套件或某个 skill/项目有没有过度设计、死代码、冗余、矛盾、漂移死角、失效引用、白名单内乱放文件时使用；也用于新建/接手项目后的结构与一致性复检。只报告，不自动修改。
---

# FileGuard Audit（只读自审计）

目标：把“设计层面”的问题查出来，和 `fileguard-doctor`（运行时健康）分开。

## 用法

```powershell
# 审计整个套件
python <套件根>\scripts\audit.py --suite

# 审计单个项目/skill
python <套件根>\scripts\audit.py --project <项目根>

# 审计登记表全部项目
python <套件根>\scripts\audit.py --registry

# 生成报告
python <套件根>\scripts\audit.py --project <项目根> --out _scratch\audit.md
python <套件根>\scripts\audit.py --project <项目根> --json

# 深度审计（按需，只读；不在 doctor/pre-reboot/build-release 日常门禁里）
python <套件根>\scripts\audit.py --suite --deep
python <套件根>\scripts\audit.py --project <项目根> --deep --out _scratch\audit-deep.md
```

退出码：有 P0 → 1；否则 0。**这是审计，不是门禁**，P1/P2 需要人判断。`--deep` 也只输出候选，绝不自动改。

## 检查维度

1. **结构/生命周期**：meta、dirs、`.gitignore`、L3、`.comateignore`、本地 tools、版本行
2. **引用完整性**：硬编码绝对路径、失效文件引用、跨项目路径、本机用户路径
3. **一致性**：meta/plugin/README/SKILL/索引版本、registry type vs meta type
4. **死代码/未用功能**：无活跃调用方的命令/模板/状态文件（heuristic）
5. **checkpoint 契约**：单文件扁平结构、字段完整、project 与目录一致、旧 v2 结构提示、纯数据项目死配置
6. **管理目录乱放**：根目录、`_checkpoint`、`_rules`、`tools` 的未登记文件
7. **套件已知风险**：`init --force` 覆盖、commit/ignore-gen 顺序、web 空 checkpoint
8. **跨项目 wrapper**：本地 checkpoint 副本与套件不一致且存在回退逻辑（本地副本应为标准版原样）

### 深度审计（`--deep`，按需）

- **U 类（未使用/可合并）**：CLI 子命令/参数无调用、配置键无读取、函数/类无引用、重复脚本、只写不读的数据/字段。
- **O 类（覆盖/删除风险）**：整文件覆盖写、copy/move 覆盖已有目标无备份、`--force` 跳过 merge、`_trash` 外删除/移动、非原子写。
- **证据链**：定义位置 + 代码/文档/外部引用数 + 置信度；跨登记表全部项目、hooks、全局规则扫描。
- **可靠性**：只报候选，不自动删；高置信度才建议移除，中置信度只提示；分发副本/升级覆盖等有意行为有 allowlist。
- 审计只回答“像不像没用/有没有覆盖风险”，**最终改不改由人确认**。

## 汇报规则

- 先报 P0/P1，再列 P2/P3；每条给证据、影响、建议。
- **不要自动修**；需要修时先给用户看改动清单，确认后再动。
- 审计结果只写 `_scratch/` 或用户指定位置，不写入项目受管目录。
