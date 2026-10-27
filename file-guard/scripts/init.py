#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard init —— 新项目初始化工具（F10）
用法:
    python init.py <项目名> --type A|B|C [--root D:\\comate\\products] [--force]
功能:
    1. 按类型模板创建骨架目录（只增不改，不物理移动任何既有文件）
    2. 写 project_meta.json（机器可读规则）
    3. 写 _索引.md 模板（人读入口）
说明:
    - 新项目 = 通用层八目录 + 类型特有目录
    - 既有项目不使用本工具（走"贴标渐进"，只补 meta + 索引）
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

# P1-5 收敛：根目录由 _paths 派生（FG_HOME 环境变量可覆盖，换机不硬编码）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import fg_home  # noqa: E402

# ---------- 类型模板 ----------
TYPE_TEMPLATES = {
    "software": {
        "label": "软件应用（src-layout）",
        "note": "Type software：主程序与一次性脚本物理隔离（src vs _scratch）；release 命名强制 SEMVER(vX.Y.Z)；根级清单文件（pyproject.toml/package.json/go.mod/Cargo.toml/requirements.txt）白名单放行",
        "root_file_name_rule": r"^(README|LICENSE|project_meta|_索引|_trash|pyproject\.toml|package\.json|go\.mod|Cargo\.toml|requirements\.txt)",
        "strict_mode": True,
        "read_only_dirs": [],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "src", "tests", "tests/fixtures", "config", "scripts", "docs", "tools", "assets", "data", "release", "backup", "output", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "src": ["*.js", "*.ts", "*.py", "*.java", "*.go", "*.rs", "*.cpp", "*.c", "*.h", "*.json", "*.toml", "*.yaml", "*.yml"],
            "tests": ["*.py", "*.js", "*.ts", "*.ps1", "*.sh"],
            "tests/fixtures": [],
            "config": ["*.json", "*.yaml", "*.yml", "*.toml", "*.ini", "*.env.example"],
            "scripts": ["*.ps1", "*.py", "*.sh", "*.bat", "*.cmd", "*.vbs", "pre-commit", "install-hooks.sh"],
            "docs": ["*.md", "*.txt", "*.rst"],
            "tools": ["*.py", "*.js", "*.ps1", "*.sh"],
            "assets": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.ico", "*.gif", "*.webp"],
            "data": ["*.json", "*.csv", "*.db", "*.sql", "*.log", "*.parquet"],
            "release": ["*.zip", "*.exe", "*.msi", "*.tgz", "*.tar.gz", "*.deb", "*.rpm"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db", "*.sql", "*.log"],
            "output": ["*.md", "*.xlsx", "*.pdf", "*.docx", "*.pptx", "*.html", "*.csv"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
    "skill": {
        "label": "客户端 skill（Agent Skills 规范）",
        "note": "Type skill：SKILL.md 必含 name+description frontmatter（name 小写短横线 ≤64 字符）；可选子目录 scripts/references/assets 渐进式披露；hooks/skills/tests/references 为规范新增目录；产品与数据分离（notes/ 客户数据永不进包）",
        "root_file_name_rule": r"^(SKILL|README|LICENSE|project_meta|_索引|deployment-guide|backup)",
        "strict_mode": True,
        "read_only_dirs": [],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "scripts", "hooks", "skills", "references", "tests", "config", "templates", "tools", "docs", "assets", "notes", "notes/敏感数据", "notes/公共资料", "notes/项目文档", "demo", "demo/源文件", "demo/交付", "版本包归档", "backup", "output", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "scripts": ["*.py", "*.ps1", "*.sh", "*.js", "*.bat"],
            "hooks": ["*.json"],
            "skills": ["*.md", "*.json"],
            "references": ["*.md", "*.txt", "*.pdf"],
            "tests": ["*.py", "*.js", "*.ts", "*.ps1"],
            "config": ["*.json", "*.yaml", "*.yml", "*.toml"],
            "templates": ["*.md", "*.json", "*.docx", "*.html"],
            "tools": ["*.py", "*.js", "*.ps1"],
            "docs": ["*.md", "*.txt"],
            "assets": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.ico", "*.webp", "*.gif"],
            "notes": [],
            "notes/敏感数据": [],
            "notes/公共资料": [],
            "notes/项目文档": [],
            "demo": [],
            "demo/源文件": [],
            "demo/交付": ["*.exe", "*.zip"],
            "版本包归档": ["*.zip"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db", "*.sql"],
            "output": ["*.md", "*.xlsx", "*.pdf", "*.docx"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
    "suite": {
        "label": "套件（插件+skill+规则组合）",
        "note": "Type suite：plugin.json 根级（comate 自动发现）；hooks/hooks.json 与全局 ~/.comate/hooks.json 一致口径；skills/ 每 SKILL.md 子目录；_rules/ 规则真源；.comateignore 由 ignore-gen 生成维护",
        "root_file_name_rule": r"^(plugin|SKILL|README|LICENSE|project_meta|_索引|deployment-guide|backup)",
        "strict_mode": True,
        "read_only_dirs": [],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "scripts", "skills", "hooks", "_rules", "config", "templates", "tools", "docs", "release", ".comate", "backup", "output", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "scripts": ["*.py", "*.ps1", "*.sh", "*.js", "*.bat", "*.vbs"],
            "skills": ["*.md", "*.json"],
            "hooks": ["*.json"],
            "_rules": ["*.json", "*.md"],
            "config": ["*.json", "*.yaml", "*.yml", "*.toml"],
            "templates": ["*.md", "*.json", "*.docx"],
            "tools": ["*.py", "*.js", "*.ps1"],
            "docs": ["*.md", "*.txt"],
            "release": ["*.zip", "*.exe", "*.msi", "*.tgz", "*.tar.gz"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db", "*.sql"],
            "output": ["*.md", "*.xlsx", "*.pdf", "*.docx"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
    "web": {
        "label": "网页开发",
        "note": "Type web：src/public/components/styles 前端约定；根级清单 package.json/tsconfig/vite|next 配置白名单放行；构建产物进 release/",
        "root_file_name_rule": r"^(README|LICENSE|project_meta|_索引|package\.json|tsconfig\.json|vite\.config\.(ts|js)|next\.config\.(ts|js))",
        "strict_mode": True,
        "read_only_dirs": [],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "src", "public", "components", "styles", "tests", "config", "scripts", "docs", "assets", "release", "backup", "output", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "src": ["*.js", "*.ts", "*.jsx", "*.tsx", "*.json"],
            "public": ["*"],
            "components": ["*.jsx", "*.tsx", "*.js", "*.ts"],
            "styles": ["*.css", "*.scss", "*.less"],
            "tests": ["*.js", "*.ts", "*.jsx", "*.tsx"],
            "config": ["*.json", "*.yaml", "*.yml", "*.toml"],
            "scripts": ["*.js", "*.ts", "*.ps1", "*.sh", "*.py"],
            "docs": ["*.md", "*.txt"],
            "assets": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.ico", "*.webp", "*.gif"],
            "release": ["*.zip", "*.html", "*.tgz", "*.tar.gz"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db", "*.sql"],
            "output": ["*.md", "*.html", "*.pdf"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
    "docgen": {
        "label": "文档生成/解析管线",
        "note": "Type docgen：input/ 只读防污染；内容三态单向管线 content/raw（不可变）→ admission（准入）→ pool（可用池）→ output/（交付）；templates/ 渲染模板",
        "root_file_name_rule": r"^(SKILL|README|LICENSE|project_meta|_索引)",
        "strict_mode": True,
        "read_only_dirs": ["input"],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "input", "intermediate", "templates", "content", "content/raw", "content/admission", "content/pool", "output", "scripts", "tools", "config", "docs", "samples", "assets", "backup", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "input": [],
            "intermediate": ["*.dxf", "*.json", "*.csv"],
            "templates": ["*.md", "*.json", "*.docx", "*.html"],
            "content": ["*.json", "*.md", "*.yaml", "*.yml"],
            "content/raw": ["*.json", "*.md"],
            "content/admission": ["*.json"],
            "content/pool": ["*.json"],
            "output": ["*.xlsx", "*.xls", "*.pdf", "*.docx", "*.md", "*.html"],
            "scripts": ["*.py", "*.ps1", "*.bat"],
            "tools": ["*.py", "*.js", "*.ps1", "*.sh"],
            "config": ["*.json", "*.yaml", "*.yml"],
            "docs": ["*.md", "*.txt", "*.rst", "*.pdf", "*.docx"],
            "samples": ["*.dwg", "*.docx", "*.pdf"],
            "assets": ["*.png", "*.jpg", "*.jpeg", "*.svg", "*.mp4", "*.mov", "*.mp3"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
    "ops": {
        "label": "运维/维护项目",
        "note": "Type ops：低频改动、以配置与数据为主；无 src/tests/release；backup 收项目级备份",
        "root_file_name_rule": r"^(README|project_meta|_索引)",
        "strict_mode": True,
        "read_only_dirs": [],
        "read_only_files": ["config/global-permission.json", "docs/README.md", "_索引.md"],
        "dirs": ["_checkpoint", "config", "data", "scripts", "tools", "docs", "backup", "output", "archive", "_scratch", "_trash"],
        "dirs_meta": {
            "_checkpoint": ["*.json"],
            "config": ["*.json", "*.yaml", "*.yml", "*.toml", "*.ini"],
            "data": ["*.json", "*.csv", "*.db", "*.sql", "*.log", "*.parquet"],
            "scripts": ["*.py", "*.ps1", "*.sh", "*.bat"],
            "tools": ["*.py", "*.ps1"],
            "docs": ["*.md", "*.txt"],
            "backup": ["*.zip", "*.tar.gz", "*.tgz", "*.db", "*.sql", "*.log"],
            "output": ["*.md", "*.xlsx", "*.pdf"],
            "archive": ["*.zip", "*.tar.gz", "*.tgz"],
            "_scratch": [],
            ".comate": ["*.json", "*.comateignore"],
            "_trash": [],
        },
    },
}

# P1-5：默认父目录 = FG_HOME/产品（FG_HOME env 可覆盖；缺省 D:/comate）
DEFAULT_ROOT = str(fg_home() / "产品")
C0_PATH_ENV = "FG_HOME"
C0_REL = "_rules/global-rules.json"
# 通用层（三种类型都包含）：docs, archive, backup, _scratch, _trash
COMMON_DIRS = ["docs", "archive", "backup", "_scratch", "_trash"]

# 类型模板唯一事实源 = C0 _rules/global-rules.json 的 rules.dir_type_map。
# 上面 TYPE_TEMPLATES 仅作为 C0 缺失/损坏时的内置兜底（fallback），
# 新目录/扩展名一律改 C0，禁止再改下面的硬编码块。
def load_type_templates() -> dict:
    """从 C0 rules.dir_type_map 派生类型模板；失败回退内置 TYPE_TEMPLATES。

    只读清单口径（read_only_files / read_only_dirs）从 C0 类型模板派生：
    - read_only_files 按 C0 read_only_semantics.never_blocked_files 白名单过滤
      （project_meta.json 永不进入只读清单，meta 承载版本号、发版必然写入）。
    - 内置 TYPE_TEMPLATES 仅作为 C0 缺失/损坏时的兜底，同样不含 meta。
    """
    try:
        fg_home = os.environ.get(C0_PATH_ENV, r"D:\comate")
        c0_path = Path(fg_home) / C0_REL
        c0 = json.loads(c0_path.read_text(encoding="utf-8"))
        source = c0["rules"]["dir_type_map"]
        semantics = c0["rules"].get("read_only_semantics", {})
        never_blocked = list(semantics.get("never_blocked_files", []))
        out = {}
        for ptype in source:
            t = source[ptype]
            ro_files = list(t.get("read_only_files", []))
            if never_blocked:
                ro_files = [f for f in ro_files if f not in never_blocked]
            out[ptype] = {
                "label": t["label"],
                "note": t["note"],
                "dirs": list(t["dirs"]),
                "dirs_meta": dict(t["dirs_meta"]),
                "root_file_name_rule": t["root_file_name_rule"],
                "strict_mode": t.get("strict_mode", True),
                "read_only_dirs": list(t.get("read_only_dirs", [])),
                "read_only_files": ro_files,
            }
        print(f"[OK] 类型模板从 C0 派生: {c0_path}")
        return out
    except Exception as e:
        print(f"[WARN] C0 读取失败，使用内置 TYPE_TEMPLATES 兜底: {e}")
        return TYPE_TEMPLATES


TEMPLATES = load_type_templates()

# 旧类型别名（与 C0 rules.type_aliases 一致；C0 读取失败时内置兜底）
ALIAS_FALLBACK = {"A": "software", "B": "skill", "C": "docgen"}


def type_aliases() -> dict:
    """C0 rules.type_aliases（旧 A/B/C → 新细类标识）；读取失败回退内置。"""
    try:
        fg_home = os.environ.get(C0_PATH_ENV, r"D:\comate")
        c0 = json.loads((Path(fg_home) / C0_REL).read_text(encoding="utf-8"))
        return c0["rules"].get("type_aliases") or ALIAS_FALLBACK
    except Exception:
        return ALIAS_FALLBACK


def resolve_type(t: str) -> str:
    """把旧别名（A/B/C）解析为新细类标识；未知值原样返回（由调用方校验）。"""
    return type_aliases().get(t, t)


# 细类 → 大类（登记表 category 字段）
TYPE_CATEGORY = {t: "dev" for t in ("software", "skill", "suite", "web", "docgen")}
TYPE_CATEGORY.update({"ops": "ops"})


def register_project(proj: Path, ptype: str) -> Path | None:
    """把新项目登记进中央登记表（D:\\comate\\_rules\\managed-projects.json）。
    登记表缺失/不可写时仅告警（不阻断建项目）；已登记则幂等跳过。"""
    try:
        reg_path = Path(os.environ.get(C0_PATH_ENV, r"D:\comate")) / "_rules" / "managed-projects.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else {"version": 1, "updated": "", "projects": []}
        roots = [str(Path(p["root"]).resolve()) for p in reg.get("projects", [])]
        if str(proj.resolve()) in roots:
            return reg_path
        reg.setdefault("projects", []).append({
            "root": str(proj.resolve()),
            "type": ptype,
            "category": TYPE_CATEGORY.get(ptype, "dev"),
            "window": "",
            "status": "active",
            "since": date.today().isoformat(),
            "note": "",
        })
        reg["updated"] = date.today().isoformat()
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return reg_path
    except Exception as e:
        print(f"[WARN] 自动登记失败（不阻断）: {e}")
        return None


def project_meta(name: str, ptype: str, label: str, note: str, root_rel: str) -> dict:
    t = TEMPLATES[ptype]
    meta = {
        "name": name,
        "label": label,
        "type": ptype,
        "description": note,
        "version": "0.1.0",  # 初始版本；SemVer 三段 X.Y.Z，递进规则见 docs/版本管理规范.md §二
        "dirs": t["dirs_meta"],
        "root_file_name_rule": t["root_file_name_rule"],
        "read_only_files": list(t.get("read_only_files", [])),
        "read_only_dirs": list(t.get("read_only_dirs", [])),
        "reuse_dirs": ["src", "scripts", "tests", "config", "docs", "tools", "assets"],
        "trash_dir": "_trash",
        "trash_ttl_days": 30,
        "strict_mode": t.get("strict_mode", True),
        "note": "修改本文件需经用户确认；AI 放置规则由 FileGuard L2 插件读取",
    }
    return meta


def index_md(name: str, ptype: str, label: str, dirs: list, note: str,
             version: str = "0.1.0") -> str:
    today = date.today().isoformat()
    rows = "\n".join(f"| {d}\\ | {d.rsplit('/', 1)[-1]} | 见模板 |" for d in dirs)
    return f"""# {name}（{label}）— 项目索引

> 类型：Type {ptype} — {TEMPLATES[ptype]['label']}
> 版本：v{version}（SemVer 三段递进，规则见 docs/版本管理规范.md）
> 创建日期：{today}
> 项目根：`{name}\\`（FileGuard 受管项目）

## 目录规则（{ptype} 类型模板）

| 目录 | 用途 | 状态 |
|---|---|---|
{rows}

## 强制规则（由 FileGuard 代码执行，非意愿）

- 目录白名单与扩展名校验：L2 插件按 project_meta.json 拦截，违规写路径直接报错
- 删除 = 先移 `_trash\\` 30 天人工确认；版本保护由 Git 兜底，误删可 `git checkout` 恢复
- 提交校验：L3 pre-commit（_v2 后缀 / 裸临时名 / 根散件三不变量）
- 根目录散件：L4 FSW 自动归位 `_scratch\\auto\\`

{note}
"""


# ---------- 装配器化（D）：新建项目自动装配套件组件 ----------
# 组件口径与 config/sync-manifest.json 一致；渲染口径与 sync-projects.render_template 一致。
# 规则：目标目录不在 meta 白名单（dirs 键）内则跳过该组件（同 sync 的 skip-no-tools 语义）。

# T9B：SSOT 契约 L2 最小路径派生模板（FG_HOME env 优先，禁止项目脚本硬编码路径）。
# 模板内联于此（templates/ 白名单无 .py），项目内生成 tools/_paths.py；Type 无 tools 目录则跳过。
MINI_PATHS_PY = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
\"\"\"项目私有最小路径派生（SSOT 契约 L2：FG_HOME env 优先，禁止硬编码路径）。

用法: from _paths import fg_home, rules_dir; 项目内脚本一律经此派生路径。
规则见 docs/SSOT-契约.md（L0 全局层 / L2 项目层）。
\"\"\"
import os
from pathlib import Path

FALLBACK_HOME = "D:/comate"


def fg_home() -> Path:
    \"\"\"受管根目录: env COMATE_FG_HOME 优先, 兼容 FG_HOME, 缺省 D:/comate。\"\"\"
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or FALLBACK_HOME)


def rules_dir() -> Path:
    \"\"\"C0 规则目录（全局唯一规则真源）: fg_home()/_rules。\"\"\"
    return fg_home() / "_rules"


def suite_dir() -> Path:
    \"\"\"套件目录: env FILEGUARD_SUITE_SUBDIR / FG_SUITE_REL 覆盖, 缺省 产品/file-guard。\"\"\"
    rel = (os.environ.get("FILEGUARD_SUITE_SUBDIR")
           or os.environ.get("FG_SUITE_REL")
           or "产品/file-guard")
    return fg_home() / rel
"""

ASSEMBLY_SPEC = [
    # (kind, src_rel, dst_rel)
    ("mkdir",  None,                            "_checkpoint/"),
    ("paths",  None,                            "tools/_paths.py"),
    ("copy",   "scripts/checkpoint-manager.py", "tools/checkpoint-manager.py"),
    ("copy",   "scripts/trash-cli.py",          "tools/trash-cli.py"),
    ("copy",   "scripts/git-watchdog.py",       "tools/git-watchdog.py"),
    ("copy",   "scripts/version_check.py",      "tools/version_check.py"),
    ("copy",   "scripts/build-release.py",      "tools/build-release.py"),
    ("tmpl",   "templates/README.project.md",   "README.md"),
    ("tmpl",   "templates/docs-README.md",      "docs/README.md"),
    ("tmpl",   "templates/版本管理规范.md",      "docs/版本管理规范.md"),
    ("tmpl",   "templates/global-permission.json", "config/global-permission.json"),
    ("hook",   "scripts/git-hooks/pre-commit",  ".git/hooks/pre-commit"),
]

# mkdir 类组件的白名单扩展名（与 C0 rules.dir_type_map 的 dirs_meta 同口径）。
# 该目录未登记时必须补登记，否则 L2 插件会拒绝向该目录写入（见 assemble 的"登记即建"）。
ASSEMBLY_MKDIR_EXTS = {
    "_checkpoint": ["*.json"],
}

TYPE_LABEL_SHORT = {
    "software": "软件应用（src+scripts+tests+docs+config）",
    "skill": "客户端 skill（SKILL.md+scripts+references+assets）",
    "suite": "套件（plugin+skills+hooks+_rules）",
    "web": "网页开发（src+public+components+styles）",
    "docgen": "文档管线（templates+content+output）",
    "ops": "运维/维护（config+data+scripts+docs）",
}


def render_template(text: str, ptype: str, name: str, meta: dict) -> str:
    """与 sync-projects.py render_template 同口径的占位符渲染"""
    label = TYPE_LABEL_SHORT.get(ptype, f"Type {ptype}")
    today = date.today().isoformat()
    dirs = meta.get("dirs") or {}
    dir_list = ", ".join(dirs.keys() if isinstance(dirs, dict) else dirs) or "_scratch"
    return (text
            .replace("{project_name}", name)
            .replace("{type}", ptype)
            .replace("{type_label}", label)
            .replace("{version}", str(meta.get("version", "0.1.0")))
            .replace("{date}", today)
            .replace("{dirs}", dir_list))


def assemble(proj: Path, ptype: str, meta: dict, suite_root: Path) -> tuple[list, list, list, list]:
    """装配套件组件；返回 (已装, 跳过, 失败, 补登记) 明细。目标文件已存在则不覆盖。

    登记即建：mkdir 类目录必须落在 meta.dirs 白名单内；未登记时先补登记并回写
    project_meta.json，杜绝"目录实物存在但白名单缺项"的错位（L2 会拒写未登记目录）。
    """
    done, skipped, failed, fixed = [], [], [], []
    # skill/docgen/suite 类型额外装配 SKILL.md（Agent Skills 规范入口文件）
    spec = list(ASSEMBLY_SPEC)
    if ptype in ("skill", "docgen", "suite"):
        spec.append(("tmpl", "templates/SKILL.project.md", "SKILL.md"))
    dirs_keys = list((meta.get("dirs") or {}).keys()) if isinstance(meta.get("dirs"), dict) else list(meta.get("dirs") or [])
    for kind, src_rel, dst_rel in spec:
        if kind == "mkdir":
            key = dst_rel.rstrip("/")
            if key not in dirs_keys:
                if isinstance(meta.get("dirs"), dict):
                    meta["dirs"][key] = list(ASSEMBLY_MKDIR_EXTS.get(key, []))
                    meta_file = proj / "project_meta.json"
                    if meta_file.exists():
                        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    dirs_keys.append(key)
                    fixed.append(f"{dst_rel} 已补登记进 project_meta.json")
                else:
                    skipped.append(f"{dst_rel}（未登记且 meta.dirs 非字典，无法补登记）")
                    continue
        if kind in ("copy", "tmpl", "paths"):
            # 目标父目录须在白名单（同 sync skip-no-tools 语义；README.md 属根级不在 dirs）
            # hook 写 .git/hooks/ 属 git 内部路径，豁免白名单检查
            parent = str(Path(dst_rel).parent).replace("\\", "/")
            if parent not in ("", ".") and not any(parent == d or parent.startswith(d + "/") for d in dirs_keys):
                skipped.append(f"{dst_rel}（父目录不在白名单）")
                continue
        dst = proj / dst_rel
        if dst.exists() and kind != "mkdir":
            skipped.append(f"{dst_rel}（已存在）")
            continue
        try:
            if kind == "mkdir":
                dst.mkdir(parents=True, exist_ok=True)
            elif kind == "paths":
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(MINI_PATHS_PY, encoding="utf-8")
            elif kind == "copy":
                dst.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(suite_root / src_rel, dst)
            elif kind == "tmpl":
                dst.parent.mkdir(parents=True, exist_ok=True)
                text = (suite_root / src_rel).read_text(encoding="utf-8")
                dst.write_text(render_template(text, ptype, str(proj.name), meta), encoding="utf-8")
            elif kind == "hook":
                if not (proj / ".git").exists():
                    skipped.append("pre-commit（未初始化 Git）")
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(suite_root / src_rel, dst)
                import os as _os
                try:
                    _os.chmod(dst, 0o755)
                except OSError:
                    pass
            done.append(dst_rel)
        except OSError as e:
            failed.append(f"{dst_rel}（{e}）")
    # 写指纹 .fileguard-sync.json（同 sync-projects 口径：copy/hook 用二进制哈希，tmpl 用规范化文本哈希）
    import hashlib
    comp_ids = {
        "checkpoint-dir": ("mkdir", "_checkpoint/"),
        "paths-py": ("paths", "tools/_paths.py"),
        "checkpoint-manager": ("copy", "tools/checkpoint-manager.py"),
        "trash-cli": ("copy", "tools/trash-cli.py"),
        "git-watchdog": ("copy", "tools/git-watchdog.py"),
        "readme-root": ("tmpl", "README.md"),
        "readme-docs": ("tmpl", "docs/README.md"),
        "version-rules": ("tmpl", "docs/版本管理规范.md"),
        "permission-config": ("tmpl", "config/global-permission.json"),
        "version-check": ("copy", "tools/version_check.py"),
        "build-release": ("copy", "tools/build-release.py"),
        "skill-md": ("tmpl", "SKILL.md"),
    }
    # 套件版本唯一事实源 = project_meta.json（防发版后指纹残留旧版，doctor 12/12 会静态核对）
    try:
        _ver = json.loads((suite_root / "project_meta.json").read_text(encoding="utf-8")).get("version", "0.0.0")
    except Exception:
        _ver = "0.0.0"
    fingerprint = {"suite_version": _ver, "synced_at": date.today().strftime("%Y%m%d"),
                   "components": {}}
    for cid, (kind, rel) in comp_ids.items():
        dst = proj / rel
        if kind == "mkdir":
            continue  # 目录不参与指纹哈希（同 sync-projects：无 source 组件不记指纹）
        if not dst.exists():
            continue
        if kind in ("tmpl", "paths"):
            h = hashlib.sha256(dst.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        else:
            h = hashlib.sha256(dst.read_bytes()).hexdigest()
        fingerprint["components"][cid] = h
    (proj / ".fileguard-sync.json").write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8")
    return done, skipped, failed, fixed


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard 新项目初始化")
    ap.add_argument("name", help="项目名（英文小写短横线，或 ≤8 字中文名）")
    ap.add_argument("--type", required=True, help="项目类型（software/skill/suite/web/docgen/ops；旧别名 A/B/C 兼容）")
    ap.add_argument("--root", default=DEFAULT_ROOT, help=f"父目录（默认 {DEFAULT_ROOT}）")
    ap.add_argument("--force", action="store_true", help="已存在时仍补建缺失目录/meta")
    args = ap.parse_args()

    ptype = resolve_type(args.type)
    if ptype not in TEMPLATES:
        print(f"[FAIL] 未知项目类型: {args.type}（可选: {', '.join(TEMPLATES)} / 别名 A|B|C）", file=sys.stderr)
        return 2

    root = Path(args.root)
    if not root.is_dir():
        print(f"[FAIL] 父目录不存在: {root}")
        return 1

    proj = root / args.name
    t = TEMPLATES[ptype]

    # 已存在且非 --force：拒绝（避免覆盖既有项目）
    meta_file = proj / "project_meta.json"
    if proj.exists() and not args.force:
        print(f"[FAIL] 项目已存在: {proj}（既有项目请走贴标渐进，不要用 init 重建）")
        return 1

    # 1) 建骨架
    dirs = sorted(set(t["dirs"]))
    for d in dirs:
        (proj / d).mkdir(parents=True, exist_ok=True)

    # 2) 写 project_meta.json（已存在则不覆盖，除非 --force）
    if meta_file.exists() and not args.force:
        print(f"[SKIP] project_meta.json 已存在: {meta_file}")
    else:
        meta = project_meta(args.name, ptype, t["label"], t["note"], str(root))
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] project_meta.json -> {meta_file}")

    # 3) 写 _索引.md（已存在则不覆盖）
    idx = proj / "_索引.md"
    if idx.exists() and not args.force:
        print(f"[SKIP] _索引.md 已存在: {idx}")
    else:
        # 版本行以刚写入/已有的 project_meta.json 为唯一真源（消除新建项目索引版本与 meta 脱节根源）
        _meta_version = ""
        try:
            _meta_version = str(json.loads(meta_file.read_text(encoding="utf-8")).get("version", "0.1.0"))
        except Exception:
            _meta_version = "0.1.0"
        idx.write_text(index_md(args.name, ptype, t["label"], dirs, t["note"], version=_meta_version), encoding="utf-8")
        print(f"[OK] _索引.md -> {idx}")

    # 4) 初始化 Git 仓库（仅 init，装配完成后统一 commit）
    import shutil
    has_git = shutil.which("git") is not None
    if has_git and not (proj / ".git").exists():
        import subprocess
        try:
            subprocess.run(["git", "init"], cwd=str(proj), check=True, capture_output=True, text=True)
            print(f"[OK] Git 仓库初始化完成: {proj}")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Git init 失败（非阻塞）: {e.stderr.strip() or e.stdout.strip()}")
    elif (proj / ".git").exists():
        print(f"[SKIP] 已是 Git 仓库: {proj}")

    # 5) 装配套件组件（_checkpoint/、checkpoint 三工具、四模板、L3 hook 与指纹）
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else None
    if meta:
        suite_root = Path(__file__).resolve().parent.parent
        done, skipped, failed, fixed = assemble(proj, ptype, meta, suite_root)
        for d in done:
            print(f"[OK] 装配 {d}")
        for s in skipped:
            print(f"[SKIP] 装配 {s}")
        for f in failed:
            print(f"[WARN] 装配失败 {f}")
        for x in fixed:
            print(f"[FIX] {x}")
    else:
        print(f"[WARN] 无 project_meta.json，跳过组件装配")

    # 6) git add + commit（骨架、装配产物与指纹一并入仓）
    if has_git and (proj / ".git").exists():
        import subprocess
        try:
            subprocess.run(["git", "add", "-A"], cwd=str(proj), check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "chore: init project skeleton"], cwd=str(proj), check=True, capture_output=True, text=True)
            print(f"[OK] Git 首次提交完成: {proj}")
        except subprocess.CalledProcessError as e:
            print(f"[WARN] Git 提交失败（非阻塞）: {e.stderr.strip() or e.stdout.strip()}")

    # 7) 登记 + 引擎级兜底（新建一步建齐闭环：登记表 + .comateignore）
    reg = register_project(proj, ptype)
    if reg:
        print(f"[OK] 已登记进受管登记表: {reg}")
    import subprocess
    try:
        ig = Path(__file__).resolve().parent / "ignore-gen.py"
        r = subprocess.run([sys.executable, str(ig), "--write"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("[OK] .comateignore 已生成（引擎级拦截兜底）")
        else:
            print(f"[WARN] .comateignore 生成失败: {r.stderr.strip() or r.stdout.strip()}")
    except Exception as e:
        print(f"[WARN] .comateignore 生成异常（不阻断）: {e}")

    print(f"[OK] Type {ptype} 骨架创建完成: {proj}")
    print(f"[NEXT] 1) 检查目录/改 meta；2) 用 doctor.py 自检；3) 启用 L2 插件后规则即生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())