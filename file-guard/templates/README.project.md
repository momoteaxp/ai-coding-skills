# {project_name}

> 版本：v{version}（SemVer 三段递进，规则见 docs/版本管理规范.md）
> 类型：Type {type} — {type_label}
> 项目根：`{project_name}\`（FileGuard 受管项目）

## 项目简介

（一句话说明本项目做什么、给谁用。）

## 目录速览

| 目录 | 用途 |
|---|---|
| {dirs} | 见 `_索引.md` 完整目录规则 |

## 强制规则（FileGuard 执行，非意愿）

- 目录白名单与扩展名校验：L2 插件按 project_meta.json 拦截违规写入
- 删除 = 先移 `_trash\` 30 天人工确认；Git 兜底可 `git checkout` 恢复
- 提交校验：L3 pre-commit（_v2 后缀 / 裸临时名 / 根散件三不变量）
- 根目录散件：L4 FSW 自动归位 `_scratch\auto\`

## 版本管理

- 当前版本：`v{version}`
- 版本号规则：X.Y.Z（主.次.修），递进决策与回滚规范见 `docs/版本管理规范.md`
- 发版：`python tools\build-release.py --bump patch|minor|major`（版本行校验 + git tag + release 打包一体）
