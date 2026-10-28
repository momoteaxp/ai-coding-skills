---
name: takeover-project
description: 当用户说"接手一个项目 / 接管 XX / 把 XX 纳入管理 / 纳入受管 / 把这个半道项目纳入体系"时触发。走 FileGuard 接手流程（docs/受管项目体系设计-20261023.md §5.2）：审计→回填→掰正→登记→复检，把既有项目完整纳入受管体系（完整整理深度：每项改动清单确认后执行）。新建项目不触发本 skill（走 new-project）。
---

# 接手项目（既有项目纳入受管体系）

目标：任何窗口的助手听到"接手一个项目"即可规范接管，不依赖碰运气。**半道项目说"接手"= 进入受管体系并接受整理；说"新建"= 走 new-project 建新骨架。**

## 第一步：定位目录

- 用户明确给了目录 → 用它
- 没给 → 用当前窗口 cwd 上溯最近的 project_meta.json 所在根

## 第二步：审计（只读，不写任何东西）

检查并出报告：
1. `project_meta.json` 存在？类型（A/B/C 或新细类）？版本？
2. 结构缺口：README/_索引/docs/版本管理规范/.git/.comateignore 有无
3. 违规命名：tmp_/新建文本文档/_v2/裸临时名（对照 C0 黑名单）
4. 白名单缺口：meta.dirs 是否覆盖实际目录；`.comate` 白名单是否含 `.comateignore`
5. 版本一致性：meta 与版本行文件（SKILL.md 等）
6. **进度档案**（2026-10-27 加）：根级是否有自创进度档案（CHECKPOINT.md 等 md）→ 列为迁移项

工具：`python scripts/cquery.py <文件> <键路径>` 读 JSON（零引号）；复杂检查写 `_scratch\tmp-*.py`。

## 第三步：定类型

按实际结构映射细类（software/skill/suite/web/docgen/ops）；现有 A/B/C 是合法别名，不必强行改（除非结构明显属于另一细类，作为掰正项提出）。

## 第四步：回填 + 掰正（列清单，逐项确认后执行）

- 回填：补 README/_索引/版本规范/`.comate` 白名单（**不覆盖既有内容**，只增不改）
- 掰正：命名/白名单/版本号——每项列**确切改动路径与内容**，用户确认后改；**未经确认不做任何代码级改动**
- 类型若需掰正（如 B→docgen）单独列为确认项
- **硬规则（2026-10-27 incident 教训 + kb 豁免）**：有辅助窗口/进度需求的项目，meta.dirs 白名单 = **实际目录 ∪ 标准目录**——`_checkpoint`/`docs`/`_scratch`/`_trash`/`.comate` 必登记；**纯数据项目（type=kb 或 `checkpoint_enabled: false`）豁免 `_checkpoint`**，不要强行回填管理骨架（没有 checkpoint 消费方，只会产生死配置）。
- **进度档案迁移**（审计第 6 项命中时，且项目未豁免 checkpoint）：拆两份——机器可读字段（版本/阶段/测试结果/下一步/待确认）→ `_checkpoint/latest.json`（`checkpoint-manager.py save`，需显式 `--session-id`）；人读档案（文件清单/设计决策/未验证假设/交付物/变更记录）→ `docs/进度档案.md`（内容保真，只加迁移头注）；迁移后删根级自创文件并从 `root_file_name_rule` 移除对应例外。

## 第五步：登记（受管转正）

1. 写 `%USERPROFILE%\comate\_rules\managed-projects.json`（root/type/category/window/status/since/note）
2. `python %USERPROFILE%\comate\products\file-guard\scripts\ignore-gen.py --write`（给全部登记项目生成 .comateignore）

## 第六步：复检 + 汇报

- `python %USERPROFILE%\comate\products\file-guard\scripts\doctor.py` 全绿（D5 含新项目；**D12 校验适用项目 _checkpoint 白名单，type=kb / checkpoint_enabled=false 豁免**）
- 汇报：登记条目、.comateignore、掰正明细、进度档案迁移明细、后续自管理说明

## 注意

- test/实验性目录要不要登记，先问用户（登记 = 套件服务覆盖，含体检）。
- 一个目录只要有 project_meta.json，第一层拦截（hooks）已自动生效；登记补的是 .comateignore 兜底 + doctor 体检 + 身份 + 整理。
- 注销（移出登记表）= 用户明确指令后执行。
