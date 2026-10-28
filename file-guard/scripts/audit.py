#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard Audit v1 — 只读设计/引用/死代码/漂移审计

定位：doctor 管“运行时是否健康”，audit 管“设计是否合理、引用是否断裂、
有没有死代码/过度设计/多真源/白名单内乱放”。

用法:
    python audit.py --suite
    python audit.py --project <项目根>
    python audit.py --registry
    python audit.py --project <根> --json
    python audit.py --project <根> --out _scratch/audit.json
    python audit.py --suite --deep          # 按需深度只读审计（未使用/覆盖风险）

原则:
- 只读，不修改任何文件；
- 规则保守，宁可漏报不误报；
- 每条发现带 severity(P0-P3)、证据 file:line、影响、建议；
- 退出码：有 P0 → 1，否则 0。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EXCLUDE_DIRS = {
    ".git", "_checkpoint", "_traces", "_build", "publish-ready", "release",
    "_trash", "_scratch", "__pycache__", "node_modules", ".pytest_cache",
    "data", "archive", "backup", "output", "venv", ".venv",
}
TEXT_EXTS = {".py", ".ps1", ".md", ".json", ".vbs", ".cmd", ".bat",
             ".sh", ".txt", ".yml", ".yaml", ".template", ".toml"}
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

DEAD_FEATURES = [
    ("trash-cli", "回收站 CLI"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p)


def _norm(s) -> str:
    if not s:
        return ""
    try:
        return os.path.normpath(os.path.abspath(str(s))).replace("\\", "/").lower().rstrip("/")
    except Exception:
        return str(s).replace("\\", "/").lower().rstrip("/")


def _excluded(p: Path, root: Path) -> bool:
    try:
        parts = p.relative_to(root).parts
    except Exception:
        parts = p.parts
    return any(part in EXCLUDE_DIRS for part in parts)


def _iter_files(root: Path, exts=None):
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if not p.is_file() or _excluded(p, root):
            continue
        if exts is not None and p.suffix.lower() not in exts:
            continue
        yield p


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _load_json(p: Path):
    try:
        return json.loads(_read(p))
    except Exception:
        return None


def _add(findings, sev, category, title, evidence, impact, recommendation, auto_fix=False):
    findings.append({
        "id": f"{category}-{len(findings) + 1:03d}",
        "severity": sev,
        "category": category,
        "title": title,
        "evidence": evidence,
        "impact": impact,
        "recommendation": recommendation,
        "auto_fix": auto_fix,
    })


def _meta(root: Path) -> dict:
    p = root / "project_meta.json"
    if not p.is_file():
        return {}
    return _load_json(p) or {}


def _checkpoint_disabled(meta: dict) -> str:
    cp = meta.get("checkpoint_enabled", True)
    if cp is False or str(cp).strip().lower() == "false":
        return "checkpoint_enabled=false"
    if str(meta.get("type") or "").strip().lower() == "kb":
        return "type=kb"
    return ""


# ---------------------------------------------------------------- structure
def audit_structure(root: Path, findings, suite_root: Path | None):
    meta = _meta(root)
    if not meta:
        _add(findings, "P0", "structure", "缺少或无法解析 project_meta.json",
             f"{root}/project_meta.json", "项目没有规则真源，写前拦截/体检/登记都会失效",
             "补 project_meta.json（走 new-project/takeover 流程）")
        return meta
    ptype = str(meta.get("type") or "").strip().lower()
    disabled = _checkpoint_disabled(meta)

    if ptype in ("kb", "data") or disabled:
        if (root / "_checkpoint").is_dir():
            _add(findings, "P2", "checkpoint", "纯数据项目仍存在 _checkpoint",
                 f"{root}/_checkpoint", "无 checkpoint 消费方，属于死配置",
                 "删除 _checkpoint；D12 已豁免该类项目", auto_fix=False)
        if (root / "tools" / "checkpoint-manager.py").is_file():
            _add(findings, "P2", "checkpoint", "纯数据项目仍带本地 checkpoint 工具",
                 f"{root}/tools/checkpoint-manager.py", "无消费方，增加同步负担",
                 "从装配清单移除；如确需保留，在 meta 写 checkpoint_enabled=true")
        return meta

    # 有 checkpoint 需求的项目
    if "_checkpoint" not in (meta.get("dirs") or {}):
        _add(findings, "P1", "checkpoint", "适用项目 meta 缺 _checkpoint 白名单",
             f"{root}/project_meta.json:dirs", "标准 checkpoint 流程会被自己拦截",
             "把 _checkpoint 加进 dirs（仅补缺，不重写整个 meta）")

    if ptype == "web" and not (root / "tools" / "checkpoint-manager.py").is_file():
        _add(findings, "P2", "checkpoint", "web 项目缺本地 checkpoint 工具",
             f"{root}/tools/checkpoint-manager.py", "web 模板有 _checkpoint 但没有 tools，属于空壳配置",
             "用 init --force 补装配，或把 web 纳入 checkpoint 豁免")

    if not (root / ".gitignore").is_file():
        _add(findings, "P1", "structure", "缺少 .gitignore",
             f"{root}/.gitignore", "新项目首次 commit 后，生成物会让 L3 防漏检查失败",
             "补 .gitignore 模板；init 生成骨架时一并写入")
    if not (root / ".comate" / ".comateignore").is_file():
        _add(findings, "P2", "structure", "缺少 .comateignore",
             f"{root}/.comate/.comateignore", "引擎级拦截通道未生效",
             "跑 ignore-gen.py --write")

    if (root / ".git").is_dir() and not (root / ".git" / "hooks" / "pre-commit").is_file():
        _add(findings, "P2", "structure", "git 仓库未安装 L3 pre-commit",
             f"{root}/.git/hooks/pre-commit", "L3 放置规则检查缺失",
             "复制 scripts/git-hooks/pre-commit 到 .git/hooks/")

    local_cm = root / "tools" / "checkpoint-manager.py"
    if suite_root and suite_root != root and not local_cm.is_file():
        _add(findings, "P1", "structure", "项目没有本地 checkpoint-manager.py",
             str(local_cm), "checkpoint 运行时未分发，项目无法本地 save/load",
             "跑 scripts/checkpoint-workflow.py --project <根>（或 --all）")
    if suite_root and local_cm.is_file():
        src = suite_root / "scripts" / "checkpoint-manager.py"
        if src.is_file():
            try:
                if local_cm.read_bytes() != src.read_bytes():
                    _add(findings, "P2", "structure", "本地 checkpoint 工具与套件不一致",
                         f"{local_cm} ≠ {src}", "项目副本仍是旧版本（可能带 --project/bind）",
                         "跑 checkpoint-workflow.py --project <根> 覆盖为最新标准版")
            except Exception:
                pass
    return meta


# ---------------------------------------------------------------- versions
def audit_versions(root: Path, findings, suite_root: Path | None):
    meta = _meta(root)
    expected = str(meta.get("version") or "").strip()
    if not expected:
        return
    sources = []
    plugin = _load_json(root / "plugin.json") if (root / "plugin.json").is_file() else None
    if plugin is not None:
        sources.append(("plugin.json", str(plugin.get("version") or "")))
    for name in ("README.md", "README.zh-CN.md", "_索引.md", "docs/README.md"):
        p = root / name
        if p.is_file():
            m = re.search(r"(?:v|版本\s*[:：]?\s*|version\s*[:：]?\s*)[`'\" ]*(\d+\.\d+\.\d+)", _read(p))
            if m:
                sources.append((name, m.group(1)))
    for p in sorted(root.glob("skills/*/SKILL.md")):
        m = re.search(r"^version\s*:\s*\"?v?(\d+\.\d+\.\d+)", _read(p), re.MULTILINE)
        if m:
            sources.append((_rel(p, root), m.group(1)))
    for name, found in sources:
        if found and found != expected:
            _add(findings, "P2", "versions", f"{name} 版本行与 meta 不一致",
                 f"{name}: {found} ≠ project_meta: {expected}",
                 "版本漂移，发版/文档会不一致",
                 "用 version_check.py --sync 或手工对齐")

    if suite_root and suite_root != root:
        reg = _load_registry()
        entry = next((p for p in reg.get("projects", []) if _norm(p.get("root")) == _norm(str(root))), None)
        if entry:
            rtype = str(entry.get("type") or "").strip().lower()
            mtype = str(meta.get("type") or "").strip().lower()
            if rtype and mtype and rtype != mtype:
                _add(findings, "P2", "versions", "登记表 type 与 meta type 不一致",
                     f"registry={rtype} vs meta={mtype}", "两套类型真源，D5/D11/D12 判断可能分叉",
                     "以 meta 为准；registry 只保留 root/status 等检索字段")


# ---------------------------------------------------------------- management files
def audit_management_files(root: Path, findings):
    meta = _meta(root)
    rule = str(meta.get("root_file_name_rule") or r"^(README|LICENSE|project_meta|_索引|_trash)")
    for p in root.iterdir():
        if p.is_dir() or p.name.startswith("."):
            continue
        if p.name in ("README.md", "README.zh-CN.md", "LICENSE", "plugin.json", "project_meta.json"):
            continue
        try:
            ok = re.match(rule, p.name) is not None
        except re.error:
            ok = True
        if not ok:
            _add(findings, "P2", "management", "根目录存在未登记文件",
                 f"{p.name}（{p.stat().st_size} bytes，{datetime.fromtimestamp(p.stat().st_mtime).isoformat()}）",
                 "根目录散落文件，L3 可能拦截；也可能绕过规则悄悄堆物",
                 "归位到 docs/scripts/output 等目录，或更新 root_file_name_rule")

    cp = root / "_checkpoint"
    if cp.is_dir():
        allowed = {"latest.json"}
        bad = []
        for p in cp.iterdir():
            if p.is_dir():
                continue
            if p.name in allowed:
                continue
            bad.append(f"{p.name}({p.stat().st_size}B,{datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d')})")
        if bad:
            _add(findings, "P2", "management", f"_checkpoint 根存在 {len(bad)} 个未登记文件",
                 "、".join(bad[:6]) + (" ..." if len(bad) > 6 else ""),
                 "旧扁平历史/临时文件混入；单文件模型只保留 latest.json",
                 "确认无消费方后移到 _trash 或删除")


    rules = root / "_rules"
    if rules.is_dir():
        allowed = {"global-rules.json", "managed-projects.json",
                   "placement-guard.heartbeat", "placement-watchdog-heartbeat.txt",
                   "placement-log.md", "placement-watchdog-log.md"}
        for p in rules.iterdir():
            if p.name in allowed or p.name.startswith("."):
                continue
            if p.suffix.lower() in (".log", ".md", ".txt"):
                continue
            _add(findings, "P3", "management", "_rules 存在未登记文件",
                 f"{_rel(p, root)}", "规则目录混入未知文件，来源难追溯",
                 "确认来源后归档/删除，并在审计规则里登记")

    tools = root / "tools"
    if tools.is_dir():
        expected = {"_paths.py", "checkpoint-manager.py", "trash-cli.py",
                    "git-watchdog.py", "version_check.py", "build-release.py"}
        for p in tools.iterdir():
            if p.is_file() and p.name not in expected and p.suffix in (".py", ".ps1", ".sh"):
                _add(findings, "P3", "management", "tools/ 存在未登记脚本",
                     f"{_rel(p, root)}", "装配清单外的脚本，可能是遗留/临时文件",
                     "确认用途；无用则删除，有用则加入装配清单")


# ---------------------------------------------------------------- references
def audit_references(root: Path, findings):
    abs_re = re.compile(r"\b([A-Za-z]:[\\/][^\s\"'`<>|]+)")
    missing = []
    personal = []
    hardcoded = {}
    seen = set()
    file_exts = {".py", ".ps1", ".json", ".md", ".vbs", ".cmd", ".bat",
                 ".sh", ".txt", ".yml", ".yaml", ".toml", ".exe", ".dll"}

    def looks_like_path(raw: str) -> bool:
        if any(ch in raw for ch in "，。；：（）【】[]{}<>*?\"'`|"):
            return False
        if any(ord(ch) > 127 for ch in raw):
            return False
        if len(raw) < 4 or ":" not in raw:
            return False
        return True

    for p in _iter_files(root, TEXT_EXTS):
        if p.name == "audit.py":
            continue
        text = _read(p)
        for m in abs_re.finditer(text):
            raw = m.group(1).rstrip(").,;，。；")
            if raw in seen:
                continue
            seen.add(raw)
            if not looks_like_path(raw):
                continue
            low = raw.replace("\\", "/").lower()
            if low.startswith("c:/users/"):
                personal.append((p, raw))
                continue
            if ("d:/" + "comate") in low or ("d:/" + "project") in low:
                hardcoded.setdefault(p, []).append(raw)
                continue
            suffix = Path(raw).suffix.lower()
            if suffix in file_exts and not Path(raw).exists():
                missing.append((p, raw))

    by_file = {}
    for p, raw in missing:
        by_file.setdefault(p, []).append(raw)
    for p, raws in list(by_file.items())[:15]:
        _add(findings, "P2", "references", "引用了不存在的绝对文件路径",
             f"{_rel(p, root)}: {', '.join(raws[:4])}",
             "路径已失效，AI/用户按文档执行会失败",
             "改成相对路径或 COMATE_FG_HOME 派生；发布前统一清理")
    for p, raws in list(hardcoded.items())[:20]:
        _add(findings, "P2", "references", "包含硬编码受管根路径",
             f"{_rel(p, root)}: {len(raws)} 处，如 {raws[0]}",
             "换机/换盘/发布时会失效；也容易把项目身份写死",
             "改成 COMATE_FG_HOME/FG_HOME 派生；发布副本替换")
    for p, raw in personal[:10]:
        _add(findings, "P2", "references", "包含本机用户绝对路径",
             f"{_rel(p, root)}: {raw}", "换机/公开发布会暴露或失效",
             "发布副本里替换；开发版可用但需登记为发布排除项")



# ---------------------------------------------------------------- dead features
def audit_dead_features(root: Path, findings):
    text_by_file = {}
    for p in _iter_files(root, TEXT_EXTS):
        if p.name == "audit.py":
            continue  # 不把审计器自身的规则表当成调用方
        text_by_file[p] = _read(p)
    for needle, label in DEAD_FEATURES:
        hits = []
        for p, text in text_by_file.items():
            if needle in text:
                hits.append(_rel(p, root))
        if len(hits) <= 1:
            _add(findings, "P3", "deadcode", f"可能没有活跃调用方：{label}",
                 f"仅出现在 {', '.join(hits) if hits else '无'}（heuristic 扫描）",
                 "功能可能从未被使用，增加维护/认知成本",
                 "确认无外部消费者后从装配/文档移除；不确定则标记为可选维护工具")


# ---------------------------------------------------------------- checkpoint
def audit_checkpoint(root: Path, findings):
    meta = _meta(root)
    disabled = _checkpoint_disabled(meta)
    latest = root / "_checkpoint" / "latest.json"
    if not latest.is_file():
        if not disabled:
            _add(findings, "P1", "checkpoint", "适用项目没有 _checkpoint/latest.json",
                 str(latest), "无法跨窗口接续；也可能是项目从未 save",
                 "用 tools/checkpoint-manager.py save 建立；或确认项目是否真的需要 checkpoint")
        return
    doc = _load_json(latest)
    if doc is None:
        _add(findings, "P0", "checkpoint", "latest.json 无法解析",
             str(latest), "进度真源损坏，所有窗口都会读失败",
             "修复 JSON；必要时从聊天归档重建")
        return
    is_v2 = isinstance(doc.get("windows"), dict)
    if is_v2:
        _add(findings, "P2", "checkpoint", "latest.json 仍是旧 v2 多窗口结构",
             "windows={...}", "运行时 load 会自动取最近段，但结构不再维护",
             "用 tools/checkpoint-manager.py save 一次即可转为单文件")
    if str(doc.get("project") or "") and str(doc.get("project")).strip().lower() != root.name.strip().lower():
        _add(findings, "P1", "checkpoint", "latest.json 的 project 与目录名不一致",
             f"latest.project={doc.get('project')} vs dir={root.name}",
             "可能复制/迁移过文件，接续时容易误判",
             "确认项目身份；必要时修正 project 字段")
    if is_v2:
        return
    required = ("project", "timestamp", "title", "current_task",
                "completed_steps", "pending_tasks", "key_decisions")
    missing = [k for k in required if k not in doc]
    if missing:
        _add(findings, "P2", "checkpoint", "checkpoint 缺字段",
             f"缺 {missing}", "旧版本写入/手工编辑导致字段不全",
             "补字段或重新 save")
    for k in ("completed_steps", "pending_tasks", "key_decisions"):
        if k in doc and not isinstance(doc[k], list):
            _add(findings, "P2", "checkpoint", "checkpoint 字段类型错误",
                 f"{k} 不是 list", "消费方可能崩溃", "改为数组或重新 save")


# ---------------------------------------------------------------- hooks / suite
def audit_hooks(root: Path, findings):
    local = _load_json(root / "hooks" / "hooks.json") if (root / "hooks" / "hooks.json").is_file() else None
    userprofile = Path(os.environ.get("USERPROFILE", ""))
    global_hooks = userprofile / ".comate" / "hooks.json"
    gh = _load_json(global_hooks) if global_hooks.is_file() else None
    if local and gh:
        def cmds(doc):
            out = []
            for entries in (doc.get("hooks") or {}).values():
                for m in entries or []:
                    for h in m.get("hooks") or []:
                        if h.get("command"):
                            out.append(h["command"])
            return out
        lc, gc = cmds(local), cmds(gh)
        dup = sorted(set(lc) & set(gc))
        if dup:
            _add(findings, "P2", "hooks", "同一 hook 同时注册在插件和全局",
                 f"{len(dup)} 条重复：{dup[:3]}", "若客户端两者都执行，会双跑 hook/enforcer",
                 "二选一：插件 hooks.json 或全局 hooks.json；doctor D2 不再强制两份")


# ---------------------------------------------------------------- registry
def _fg_home() -> Path:
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))


def _load_registry() -> dict:
    p = _fg_home() / "_rules" / "managed-projects.json"
    return _load_json(p) or {"projects": []}


def audit_registry(findings, suite_root: Path):
    reg = _load_registry()
    roots = []
    for item in reg.get("projects", []):
        if not item.get("root"):
            continue
        root = Path(str(item.get("root") or ""))
        if not root.is_dir():
            _add(findings, "P1", "registry", "登记表指向不存在的目录",
                 str(root), "D5/D11 会持续报错或静默失效", "更新/删除登记项")
            continue
        if _norm(str(root)) in {_norm(str(r)) for r in roots}:
            _add(findings, "P2", "registry", "登记表存在重复 root",
                 str(root), "同一项目被重复管理", "去重")
            continue
        roots.append(root)
        m = _meta(root)
        if str(m.get("type") or "").strip().lower() == "data" or m.get("managed") is False:
            continue  # 数据/资料目录不参与受管审计
        audit_project(root, findings, suite_root)


def audit_known_suite_risks(root: Path, findings):
    init_p = root / "scripts" / "init.py"
    t = _read(init_p)
    if "if meta_file.exists() and not args.force:" in t and "meta_file.write_text" in t:
        _add(findings, "P1", "known-risk", "init --force 可能覆盖已有 project_meta.json/_索引.md",
             f"{_rel(init_p, root)}: 旧的 force 覆盖分支仍存在",
             "接手/回填时可能丢掉自定义 dirs、版本和白名单",
             "改为 merge-only：只补缺失 dirs/文件，不重写已有 meta/索引")
    i_commit = t.find('"commit"')
    i_ignore = t.find("ignore-gen.py")
    if 0 <= i_commit < i_ignore:
        _add(findings, "P1", "known-risk", "init 首次提交早于 .comateignore 生成",
             f"{_rel(init_p, root)}: commit 在 ignore-gen 之前",
             "生成物会让 L3 防漏检查在第二次提交时失败",
             "把 ignore-gen 前移到 commit 之前，并生成 .gitignore")
    pre = root / "scripts" / "pre-compact.py"
    tp = _read(pre)
    if 'payload.get("cwd")' in tp and "checkpoint_enabled" not in tp:
        _add(findings, "P1", "known-risk", "pre-compact 仍用 payload cwd 且无 checkpoint 豁免",
             f"{_rel(pre, root)}: payload.get(\"cwd\")",
             "压缩时可能把归档写到漂移项目/纯数据项目",
             "改用可靠项目根（本地脚本位置/FILEGUARD_CURRENT_DIR），并加 kb/disabled 豁免")


def audit_wrapper_fallback(root: Path, findings, suite_root: Path | None):
    if not suite_root or suite_root == root:
        return
    local = root / "tools" / "checkpoint-manager.py"
    src = suite_root / "scripts" / "checkpoint-manager.py"
    if not local.is_file() or not src.is_file():
        return
    try:
        if local.read_bytes() == src.read_bytes():
            return
    except Exception:
        return
    for p in _iter_files(root, {".py"}):
        text = _read(p)
        if ("回退本地副本" in text or "_local_module" in text) and "checkpoint" in text.lower():
            _add(findings, "P1", "checkpoint", "项目存在旧 checkpoint 副本且代码会回退使用",
                 f"{_rel(p, root)} 回退到 {_rel(local, root)}（与套件不一致）",
                 "套件正确拒绝错误项目后，wrapper 可能用旧副本继续读，绕过防护",
                 "fallback 改为 fail-closed；同步或删除旧副本")
            return


def audit_project(root: Path, findings, suite_root: Path | None = None):
    root = root.resolve()
    if not root.is_dir():
        _add(findings, "P0", "structure", "项目根不存在", str(root), "无法审计", "确认路径")
        return findings
    meta = _meta(root)
    if str(meta.get("type") or "").strip().lower() == "data" or meta.get("managed") is False:
        return findings  # 数据/资料目录：不按受管项目管理
    audit_structure(root, findings, suite_root)
    audit_versions(root, findings, suite_root)
    audit_management_files(root, findings)
    audit_references(root, findings)
    audit_checkpoint(root, findings)
    audit_wrapper_fallback(root, findings, suite_root)
    if suite_root and suite_root == root:
        audit_hooks(root, findings)
        audit_dead_features(root, findings)
        audit_known_suite_risks(root, findings)
    return findings


# ---------------------------------------------------------------- output
def _md(findings, root: Path) -> str:
    lines = [f"# FileGuard Audit — {root}", ""]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("P0", "P1", "P2", "P3")}
    lines.append(f"P0={counts['P0']} P1={counts['P1']} P2={counts['P2']} P3={counts['P3']}")
    lines.append("")
    for f in sorted(findings, key=lambda x: (SEV_ORDER.get(x["severity"], 9), x["category"])):
        lines += [f"## [{f['severity']}] {f['title']}", "",
                  f"- 类别：{f['category']}",
                  f"- 证据：{f['evidence']}",
                  f"- 影响：{f['impact']}",
                  f"- 建议：{f['recommendation']}",
                  f"- 可自动修：{'是' if f['auto_fix'] else '否'}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard Audit v1（只读）")
    ap.add_argument("--project", "-p", default="", help="项目根")
    ap.add_argument("--suite", action="store_true", help="审计本套件")
    ap.add_argument("--registry", action="store_true", help="审计登记表全部项目")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", default="", help="写入报告文件（.json 或 .md）")
    ap.add_argument("--deep", action="store_true",
                    help="深度只读审计：未使用/可合并候选 + 覆盖/删除风险（不影响日常门禁）")
    args = ap.parse_args()

    suite_root = Path(__file__).resolve().parent.parent
    findings = []
    if args.registry:
        audit_registry(findings, suite_root)
        target = _fg_home()
    else:
        root = suite_root if args.suite or not args.project else Path(args.project)
        if not root.is_dir():
            print(f"[FAIL] 目录不存在: {root}", file=sys.stderr)
            return 2
        audit_project(root, findings, suite_root)
        target = root

    if args.deep:
        # 按需触发的只读深度审计：不自动改、不进入日常门禁
        try:
            import importlib.util
            deep_path = Path(__file__).resolve().parent / "audit_deep.py"
            spec = importlib.util.spec_from_file_location("audit_deep", deep_path)
            deep = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(deep)
            deep_root = target if target.is_dir() and target != _fg_home() else suite_root
            deep.run(deep_root, suite_root, findings)
        except Exception as e:
            _add(findings, "P3", "deep", "深度审计未完成",
                 f"audit_deep 执行失败: {e}", "本次只输出浅层审计结果",
                 "修好 audit_deep 后重跑；不要据此删代码")

    findings.sort(key=lambda x: (SEV_ORDER.get(x["severity"], 9), x["category"], x["id"]))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("P0", "P1", "P2", "P3")}
    data = {"ts": _now(), "target": str(target), "counts": counts, "findings": findings}

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_md(findings, target) if out.suffix.lower() == ".md"
                       else json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 报告已写入 {out}")

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"=== FileGuard Audit — {target} ===")
        print(f"P0={counts['P0']} P1={counts['P1']} P2={counts['P2']} P3={counts['P3']}")
        for f in findings:
            print(f"[{f['severity']}] {f['title']}")
            print(f"      {f['evidence']}")
            print(f"      -> {f['recommendation']}")
    return 1 if counts["P0"] else 0


if __name__ == "__main__":
    sys.exit(main())
