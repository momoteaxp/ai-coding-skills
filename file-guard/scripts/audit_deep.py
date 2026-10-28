#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard 深度审计（只读，按需触发）

目标不是“自动删代码”，而是产出可人工复核的候选清单：
- U*：未使用/可合并的功能（CLI 子命令、配置键、函数、重复副本、只写不读）
- O*：本该增量却变成覆盖的风险（整文件覆盖、copy 覆盖、force、删除、非原子写）

可靠性约定：
- 只读：不执行目标代码、不修改任何项目文件
- 证据链：定义位置 + 代码/文档/外部引用数 + 置信度
- 跨项目：默认扫描登记表全部项目、hooks、全局规则，避免误杀外部消费者
- 输出 P2/P3 建议，不进入 doctor/pre-reboot/build-release 门禁
"""
import ast
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "_trash", "_scratch", "release", "__pycache__", ".venv", "venv",
             "node_modules", "backup", "archive", "blobs", "_checkpoint", "_traces",
             "output", "deliverables", "publish-ready"}
TEXT_EXTS = {".py", ".ps1", ".md", ".json", ".jsonl", ".cmd", ".bat", ".sh",
             ".txt", ".yml", ".yaml", ".toml", ".vbs", ".template"}
CODE_EXTS = {".py", ".ps1", ".cmd", ".bat", ".sh", ".vbs"}
MAX_SIZE = 512_000
MAX_FILES = 1500
MAX_TOTAL_BYTES = 30_000_000

IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{5,}\b")
FLAG_RE = re.compile(r"--[a-z][a-z0-9-]{1,40}")
FILE_RE = re.compile(r"\b[A-Za-z0-9_.-]+\.(?:py|json|md|ps1|cmd|vbs|template)\b")

GENERIC_FLAGS = {"--help", "--version", "--force", "--json", "--out", "--project", "-p"}
GENERIC_NAMES = {"__init__", "main", "__main__", "run", "load", "save", "test"}
GENERIC_KEYS = {"rules", "dirs", "label", "usage", "names", "type", "version", "title",
                "description", "features", "note", "extra", "schema", "options"}


def _add(findings, sev, category, title, evidence, impact, recommendation):
    findings.append({
        "id": f"{category}-{len(findings) + 1:03d}",
        "severity": sev,
        "category": category,
        "title": title,
        "evidence": evidence,
        "impact": impact,
        "recommendation": recommendation,
        "auto_fix": False,
    })


def _fg_home() -> Path:
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))


def _roots(suite_root: Path) -> list[Path]:
    roots = [suite_root]
    reg = _fg_home() / "_rules" / "managed-projects.json"
    try:
        d = json.loads(reg.read_text(encoding="utf-8"))
        for p in d.get("projects", []):
            if str(p.get("type") or "").lower() in ("kb", "data"):
                continue  # 纯数据目录不做引用扫描，避免把笔记库当代码库
            r = Path(p.get("root", ""))
            if r.is_dir() and r not in roots:
                roots.append(r)
    except Exception:
        pass
    return roots


def _iter_files(roots: list[Path]):
    seen = set()
    count = 0
    total = 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
            for name in filenames:
                if count >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                    return
                p = Path(dirpath) / name
                if p.suffix.lower() not in TEXT_EXTS:
                    continue
                try:
                    size = p.stat().st_size
                except OSError:
                    continue
                if size > MAX_SIZE:
                    continue
                key = str(p.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                total += size
                yield p


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _build_index(roots: list[Path]):
    """token -> [(path, lineno, kind)]；同时返回 corpus 供短 CLI token 精确检索。"""
    index = defaultdict(list)
    corpus = []
    for p in _iter_files(roots):
        ext = p.suffix.lower()
        kind = "code" if ext in CODE_EXTS else ("doc" if ext == ".md" else "config")
        text = _read(p)
        corpus.append((p, text, kind))
        for i, line in enumerate(text.splitlines(), 1):
            for m in IDENT_RE.finditer(line):
                index[m.group(0)].append((p, i, kind))
            for m in FLAG_RE.finditer(line):
                index[m.group(0)].append((p, i, kind))
            for m in FILE_RE.finditer(line):
                index[m.group(0)].append((p, i, kind))
    return index, corpus


def _count(index, token, exclude: Path | None = None):
    hits = index.get(token, [])
    if exclude is None:
        return len(hits), hits
    filtered = [h for h in hits if h[0].resolve() != exclude.resolve()]
    return len(filtered), filtered


def _count_cli(corpus, token: str, py: Path) -> tuple[int, int, int]:
    """CLI token 精确计数：排除定义文件本身；返回 (code, doc, external)。"""
    py_r = py.resolve()
    code = doc = ext = 0
    pat = re.compile(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])")
    for p, text, kind in corpus:
        if p.resolve() == py_r:
            continue
        n = text.count(token) if token.startswith("--") else len(pat.findall(text))
        if not n:
            continue
        if kind == "code":
            code += n
        elif kind == "doc":
            doc += n
        if p.resolve().parent.parent != py_r.parent.parent:
            ext += n
    return code, doc, ext


def _check_cli(root: Path, corpus, findings):
    """U1：argparse 子命令/参数无调用（排除定义文件本身）。"""
    for py in sorted((root / "scripts").glob("*.py")):
        try:
            tree = ast.parse(_read(py))
        except Exception:
            continue
        defs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if name == "add_parser" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        defs.append((arg.value, "子命令", node.lineno))
                if name == "add_argument" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                        defs.append((arg.value, "参数", node.lineno))
        for token, kind, lineno in defs:
            if token in GENERIC_FLAGS:
                continue
            code_n, doc_n, ext_n = _count_cli(corpus, token, py)
            if code_n == 0 and doc_n == 0 and ext_n == 0:
                _add(findings, "P3", "unused", f"CLI {kind}无任何调用：{token}",
                     f"{py}:{lineno} 定义；代码/文档/外部引用均为 0",
                     "可能是残留命令；删除前需确认无 AI/人工习惯调用",
                     "人工确认后移除；或保留并在文档标注兼容")


def _walk_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            yield key, k
            yield from _walk_keys(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, prefix)


def _check_config(root: Path, index, findings):
    """U2：配置键无代码读取（只查可静态判断的叶子键，跳过动态 map）。"""
    dynamic_prefixes = ("rules.dir_type_map", "rules.trigger_words", "rules.dangerous_commands",
                        "rules.read_only_semantics", "dirs.")
    configs = [root / "rules" / "global-rules.template.json", root / "project_meta.json"]
    for cfg in configs:
        if not cfg.is_file():
            continue
        try:
            data = json.loads(_read(cfg))
        except Exception:
            continue
        seen = set()
        for full, key in _walk_keys(data):
            if key in seen or len(key) < 6 or key in GENERIC_KEYS:
                continue
            seen.add(key)
            if full.startswith(dynamic_prefixes) or ".dirs_meta." in full:
                continue  # 动态 map，静态无法判断
            hits = [h for h in index.get(key, []) if h[0].resolve() != cfg.resolve()]
            code_n = sum(1 for h in hits if h[2] == "code")
            doc_n = sum(1 for h in hits if h[2] == "doc")
            if code_n == 0 and doc_n == 0:
                _add(findings, "P3", "unused", f"配置键无读取：{full}",
                     f"{cfg.name} 定义；代码/文档引用 0",
                     "可能是死配置（写而不读）；删除前确认没有动态 get/外部读取",
                     "人工确认后删除该键；或补读取方")


def _count_name(index, name: str, py: Path, lineno: int) -> tuple[int, int]:
    """排除定义行后的代码/文档引用数（同文件调用算引用）。"""
    py_r = py.resolve()
    hits = [h for h in index.get(name, [])
            if not (h[0].resolve() == py_r and h[1] == lineno)]
    return (sum(1 for h in hits if h[2] == "code"),
            sum(1 for h in hits if h[2] == "doc"))


def _check_functions(root: Path, index, findings):
    """U4：顶层函数/类零引用（只报较长/带下划线的名字，降低误报）。"""
    for py in sorted((root / "scripts").glob("*.py")):
        try:
            tree = ast.parse(_read(py))
        except Exception:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            if name in GENERIC_NAMES or name.startswith("__") or len(name) < 8:
                continue
            if "_" not in name and not name.islower():
                continue
            code_n, doc_n = _count_name(index, name, py, node.lineno)
            if code_n == 0 and doc_n == 0:
                _add(findings, "P3", "unused", f"函数/类无引用：{name}",
                     f"{py}:{node.lineno} 定义；代码/文档引用 0",
                     "可能是死代码；动态调用/反射需人工排除",
                     "人工确认后删除；或补调用方")


def _check_duplicates(roots: list[Path], findings):
    """U5：同一项目内 scripts/ 与 tools/ 的同名同内容脚本（跨项目分发副本不算）。"""
    allow = {"checkpoint-manager.py", "version_check.py", "build-release.py",
             "trash-cli.py", "_paths.py", "pre-tool-use.py", "pre-compact.py",
             "enforcer.py", "ignore-gen.py"}
    for root in roots:
        groups = defaultdict(list)
        for sub in ("scripts", "tools"):
            d = root / sub
            if not d.is_dir():
                continue
            for p in d.glob("*.py"):
                groups[p.name].append(p)
        for name, paths in groups.items():
            if name in allow or len(paths) < 2:
                continue
            hashes = {}
            for p in paths:
                try:
                    hashes.setdefault(hashlib.sha256(p.read_bytes()).hexdigest(), []).append(p)
                except OSError:
                    continue
            for h, same in hashes.items():
                if len(same) > 1:
                    _add(findings, "P3", "simplify", f"项目内重复脚本：{name}（{len(same)} 份完全相同）",
                         "、".join(str(x) for x in same[:5]),
                         "同一项目里出现两份相同实现；分发副本需登记 allowlist",
                         "确认保留哪一份；不要直接删，先确认没有脚本路径依赖")


def _call_name(node) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


class _WriteVisitor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.stack = []
        self.ops = []

    def visit_FunctionDef(self, node):
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        name = _call_name(node.func)
        target = ""
        op = ""
        if name in ("write_text", "write_bytes") and node.args:
            op = name
            target = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
        elif name == "open" and node.args:
            mode = ""
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if "w" in mode or "a" in mode:
                op = "open-write"
                target = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
        elif name == "dump" and node.args:
            op = "json.dump"
            target = ast.unparse(node.args[1]) if len(node.args) > 1 and hasattr(ast, "unparse") else ""
        elif name in ("copy2", "copy", "move") and len(node.args) > 1:
            op = f"shutil.{name}"
            target = ast.unparse(node.args[1]) if hasattr(ast, "unparse") else ""
        elif name == "replace" and len(node.args) > 1:
            op = "os.replace"
            target = ast.unparse(node.args[1]) if hasattr(ast, "unparse") else ""
        elif name in ("remove", "unlink", "rmtree") and node.args:
            op = f"delete.{name}"
            target = ast.unparse(node.args[0]) if hasattr(ast, "unparse") else ""
        if op:
            self.ops.append((node.lineno, op, target, self.stack[-1] if self.stack else None))
        self.generic_visit(node)


def _func_guard(fn, source: str) -> dict:
    if fn is None:
        seg = source
    else:
        try:
            seg = ast.get_source_segment(source, fn) or ""
        except Exception:
            seg = source
    return {
        "read": any(x in seg for x in ("read_text", "json.load", "read_bytes")),
        "exists": "exists()" in seg or ".is_file()" in seg,
        "backup": "_trash" in seg or "backup" in seg.lower() or "copy2" in seg,
        "atomic": "os.replace" in seg or ".tmp" in seg,
        "merge": "update(" in seg or "merge" in seg.lower() or "setdefault" in seg,
    }


def _sensitive(target: str) -> str:
    t = target.lower()
    for name in ("project_meta", "_索引", "global-rules", "managed-projects",
                 "skill.md", "readme", "config", "latest.json", "hooks.json",
                 "_rules", "plugin.json"):
        if name in t:
            return name
    return ""


def _check_write_ops(root: Path, findings):
    """O1-O6：覆盖/删除风险（只报配置、元数据、文档、删除类目标）。"""
    for py in sorted((root / "scripts").glob("*.py")):
        src = _read(py)
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        v = _WriteVisitor(py)
        v.visit(tree)
        for lineno, op, target, fn in v.ops:
            g = _func_guard(fn, src)
            try:
                seg = ast.get_source_segment(src, fn) if fn is not None else src
            except Exception:
                seg = src
            sens = _sensitive(target) or _sensitive(seg or "")
            fname = py.name.lower()

            # 允许项：分发升级/版本写入/生成物
            if fname in ("checkpoint-workflow.py",) and "checkpoint-manager" in target.lower():
                continue
            if fname in ("build-release.py", "version_check.py") and op in ("write_text", "open-write", "json.dump"):
                continue
            if "_trash" in target.lower() or "_scratch" in target.lower():
                continue

            if op in ("write_text", "open-write", "json.dump") and sens:
                if not g["read"] and not g["merge"] and not g["exists"]:
                    _add(findings, "P2", "overwrite", f"疑似整文件覆盖：{sens}",
                         f"{py}:{lineno} {op} → {target}；同函数无读取/合并/存在检查",
                         "可能丢掉用户已有字段或手改内容",
                         "改为 read-modify-write + 备份；人工确认调用场景")
                elif not g["atomic"] and sens == "latest.json":
                    _add(findings, "P2", "overwrite", "数据文件非原子写：latest.json",
                         f"{py}:{lineno} {op} → {target}；未见 tmp + os.replace",
                         "中断可能留下半文件",
                         "用 tmp + os.replace")
            if op in ("shutil.copy2", "shutil.copy", "shutil.move") and not g["backup"] and not g["exists"]:
                _add(findings, "P2", "overwrite", f"复制/移动覆盖风险：{op}",
                     f"{py}:{lineno} → {target}；未见备份/_trash/存在检查",
                     "目标若已有用户修改会被覆盖",
                     "覆盖前备份到 _trash；或改为 merge-only")
            if op.startswith("delete.") and fname not in ("trash-cli.py", "build-release.py") \
                    and not any(x in target.lower() for x in ("_trash", "_scratch", "tmp")):
                _add(findings, "P2", "overwrite", f"删除操作需确认：{op}" + (f"（{sens}）" if sens else ""),
                     f"{py}:{lineno} → {target}；目标不是 _trash/tmp",
                     "可能删除用户数据或项目文件",
                     "移到 _trash；或加 --confirm/存在检查")
            if "--force" in src and sens and not g["merge"] and not g["exists"]:
                _add(findings, "P1", "overwrite", "force 分支可能覆盖：" + sens,
                     f"{py}:{lineno} {op} → {target}；文件含 --force 且无 exists/merge",
                     "force 语义可能把增量变覆盖",
                     "改为 merge-only + 备份；人工确认 force 分支")

    # PowerShell：只看敏感目标和删除/覆盖
    for ps in sorted((root / "scripts").glob("*.ps1")):
        for i, line in enumerate(_read(ps).splitlines(), 1):
            low = line.lower()
            sens = _sensitive(line)
            if not sens:
                continue
            if re.search(r"\b(set-content|out-file)\b", low):
                _add(findings, "P2", "overwrite", f"PowerShell 覆盖写：{sens}",
                     f"{ps}:{i} {line.strip()[:160]}",
                     "可能覆盖配置/文档；PowerShell 层同样需要 merge/备份",
                     "改为读取后合并；或备份到 _trash")
            if re.search(r"\b(remove-item|move-item)\b", low) and "_trash" not in low:
                _add(findings, "P2", "overwrite", f"PowerShell 删除/移动：{sens}",
                     f"{ps}:{i} {line.strip()[:160]}",
                     "可能删除/移动项目文件",
                     "移到 _trash；或加确认")


def run(root: Path, suite_root: Path, findings: list) -> None:
    """入口：只读深度审计，结果追加到 findings（P2/P3）。"""
    root = root.resolve()
    roots = _roots(suite_root)
    index, corpus = _build_index(roots)
    _check_cli(root, corpus, findings)
    _check_config(root, index, findings)
    _check_functions(root, index, findings)
    _check_duplicates(roots, findings)
    _check_write_ops(root, findings)
