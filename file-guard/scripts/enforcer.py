#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard Enforcer — Python CLI 规则校验器

用途：让任何 Python 脚本 / CI / VS Code 插件都能调用同一套 project_meta.json 规则。
核心校验逻辑与 L2 插件（file-guard-enforcer.js）保持一致。

用法:
    python enforcer.py check <文件路径> [--project <项目根目录>]
    python enforcer.py info <项目根目录>
    python enforcer.py list <受管根目录>     # 列出所有项目及其规则摘要

返回码:
    0 — 路径合规（或 info/list 成功）
    1 — 路径违规（stderr 输出原因）
    2 — 参数/文件错误
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---- 常量（COMATE_FG_HOME 优先，兼容 FG_HOME，缺省回退 %USERPROFILE%/comate——2026-10-23 独立化） ----
ROOT = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
META_NAME = "project_meta.json"
MAX_META_DEPTH = 2
TRASH_PATTERN = re.compile(r"/_trash(/|$)")
GLOBAL_RULES_PATH = ROOT / "_rules" / "global-rules.json"

# ---- C0 全局黑名单（与 JS getBlacklistedPatterns 对齐） ----
# C0 失效兜底：与 C0 blacklisted_names.file 13 条保持一致 + 额外 __pycache__/pyc，防止全系统停摆
BLACKLIST_FALLBACK = [
    re.compile(r"^~\$"),
    re.compile(r"^新建[文本文档]*\."),
    re.compile(r"\.tmp$"),
    re.compile(r"\.bak$"),
    re.compile(r"_v2\."),
    re.compile(r"_v3\."),
    re.compile(r"_v4\."),
    re.compile(r"_v5\."),
    re.compile(r"_v6\."),
    re.compile(r"^test[-_]?(deploy|demo|reboot)\.txt$"),
    re.compile(r"^tmp_"),
    re.compile(r"^temp_"),
    re.compile(r"^nul$"),
    re.compile(r"__pycache__"),
    re.compile(r"\.pyc$"),
]

_blacklist_cache: list[re.Pattern] | None = None


def get_blacklisted_patterns() -> list[re.Pattern]:
    """C0 全局黑名单：优先读 _rules/global-rules.json 的 blacklisted_names.file，失败用内置兜底。

    与 JS file-guard-enforcer.js L143-166 对齐（C0 有效时忽略大小写，兜底保持原样）。
    """
    global _blacklist_cache
    if _blacklist_cache is not None:
        return _blacklist_cache
    rules: list[re.Pattern] = []
    try:
        with open(GLOBAL_RULES_PATH, encoding="utf-8") as f:
            g = json.load(f)
        file_pats = ((g.get("rules") or {}).get("blacklisted_names") or {}).get("file") or []
        if file_pats:
            rules = [re.compile(p, re.IGNORECASE) for p in file_pats]
    except Exception:
        rules = []
    _blacklist_cache = rules if rules else list(BLACKLIST_FALLBACK)
    return _blacklist_cache

# ---- 只读豁免白名单（read_only_semantics，与 JS getNeverBlockedFiles 对齐） ----
# C0 read_only_semantics.never_blocked_files 定义"永不拦截"文件（如 project_meta.json：
# meta 承载版本号、发版必然写入，仅受「用户确认 + 写前备份」约束）。
# C0 失效兜底：project_meta.json（与 JS 插件硬编码豁免口径一致，防止全系统停摆）。
NEVER_BLOCKED_FALLBACK = ["project_meta.json"]

_never_blocked_cache: list[str] | None = None


def get_never_blocked_files() -> list[str]:
    """只读豁免白名单：优先读 C0 read_only_semantics.never_blocked_files，失败用内置兜底。"""
    global _never_blocked_cache
    if _never_blocked_cache is not None:
        return _never_blocked_cache
    nb: list[str] = []
    try:
        with open(GLOBAL_RULES_PATH, encoding="utf-8") as f:
            g = json.load(f)
        nb = list(((g.get("rules") or {}).get("read_only_semantics") or {}).get("never_blocked_files") or [])
    except Exception:
        nb = []
    _never_blocked_cache = nb if nb else list(NEVER_BLOCKED_FALLBACK)
    return _never_blocked_cache

# ---- 路径归一化（与 JS 插件保持一致） ----
def norm_path(p: str) -> str:
    if not p:
        return ""
    # resolve + normalize 防穿越
    s = os.path.normpath(os.path.abspath(str(p)))
    # 统一正斜杠
    s = s.replace("\\", "/")
    # Windows 盘符统一大写
    if len(s) >= 2 and s[1] == ":":
        s = s[0].upper() + s[1:]
    # 全路径小写（Windows 不区分大小写）
    s = s.lower()
    # 去掉末尾 /
    s = s.rstrip("/")
    return s

# ---- 查找 project_meta.json ----
def find_meta(target_dir: Path) -> Path | None:
    """从目标目录向上查找 project_meta.json，最多 MAX_META_DEPTH 层。"""
    d = target_dir.resolve()
    for _ in range(MAX_META_DEPTH + 1):
        candidate = d / META_NAME
        if candidate.is_file():
            return candidate
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None

# ---- 加载 meta ----
def load_meta(meta_path: Path) -> dict:
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _match_readonly_glob(rel: str, pat: str) -> bool:
    """对齐 JS matchGlobPattern（src/file-guard-enforcer.js L118-124）：
    ** 跨目录、* 不跨目录，其余正则特殊字符转义。"""
    if pat == rel:
        return True
    esc = re.escape(pat)
    esc = esc.replace("\\*\\*", "__DS__").replace("\\*", "[^/]*").replace("__DS__", ".*")
    return re.search("^" + esc + "$", rel) is not None

# ---- 核心校验 ----
def check_path(file_path: str, project_root: Path | None = None) -> tuple[bool, str]:
    """
    校验文件路径是否合规。
    返回 (is_ok, message)。
    """
    norm = norm_path(file_path)
    norm_root = norm_path(str(ROOT))

    # 1. 是否受管区域内
    if not norm.startswith(norm_root + "/") and norm != norm_root:
        return True, "路径在受管区域外，不拦截"

    # 1.1 全局 _scratch 宽容区（与 JS L12/L184 对齐：FG_HOME/_scratch 任意放行）
    scratch_root = norm_root + "/_scratch"
    if norm.startswith(scratch_root + "/") or norm == scratch_root:
        return True, "PASS — 全局 _scratch 宽容区放行（任意文件/命名）"

    # 1.2 C0 全局黑名单（与 JS L190-195 对齐：文件名命中即拦截，__pycache__/.pyc 全路径命中）
    base_name = Path(norm).name
    for rx in get_blacklisted_patterns():
        if rx.search(base_name) or re.search(r"(__pycache__|\.pyc$)", norm):
            return False, f"文件名 {base_name} 命中 C0 全局黑名单"

    # 2. 定位项目
    target = Path(file_path).resolve()
    if project_root:
        meta_path = project_root / META_NAME
    else:
        meta_path = find_meta(target.parent if target.is_file() or not target.exists() else target)

    if not meta_path:
        return False, f"未找到 {META_NAME}，无法校验（预期在目标目录向上 ≤{MAX_META_DEPTH} 层内）"

    try:
        meta = load_meta(meta_path)
    except Exception as e:
        return False, f"{META_NAME} 解析失败: {e}"

    project_dir = meta_path.parent
    norm_project = norm_path(str(project_dir))

    # 3. 是否本项目内
    if not norm.startswith(norm_project + "/") and norm != norm_project:
        return False, f"路径不在项目 {meta.get('name', project_dir.name)} 目录内"

    # 4. _trash 黑名单
    if TRASH_PATTERN.search(norm):
        return False, "_trash 目录禁止 AI/脚本 直接写入（请走 trash-cli.py 或系统删除流程）"

    # 5. 相对路径分析
    rel = Path(norm).relative_to(Path(norm_project))
    rel_parts = rel.parts

    # 5.0 只读豁免白名单（与 JS L254-257 对齐：basename 命中 never_blocked 即完全放行，
    # 如 project_meta.json 承载版本号、发版必然写入，仅受「用户确认 + 写前备份」约束）
    never_blocked = get_never_blocked_files()
    if rel_parts and rel_parts[-1] in never_blocked:
        return True, f"PASS — {rel_parts[-1]} 命中只读豁免白名单（永不拦截）"

    # 5.1 只读文件检查（与 JS L237-243 对齐：优先于根一级与目录检查）
    read_only = meta.get("read_only_files", []) or []
    if read_only and rel_parts:
        rel_str = rel.as_posix()
        name = rel_parts[-1]
        for pat in read_only:
            p_norm = norm_path(str(Path(norm_project) / pat))
            if norm == p_norm or norm.startswith(p_norm + "/") or _match_readonly_glob(rel_str, pat.replace("\\", "/")):
                return False, f"{name} 是只读文件（{pat}）"

    # 5.2 只读目录检查（对齐 JS：read_only_dirs 命中即拦截，如 Type C input/ 防污染）
    read_only_dirs = meta.get("read_only_dirs", []) or []
    for d in read_only_dirs:
        d_norm = norm_path(str(Path(norm_project) / d))
        if norm == d_norm or norm.startswith(d_norm + "/"):
            return False, f"路径命中只读目录（{d}）"

    # 6. 根一级散件检查（R6）
    # 如果文件直接放在项目根（rel_parts 长度为 1）且不在 root_file_name_rule 允许列表
    if len(rel_parts) == 1:
        filename = rel_parts[0]
        # 点开头隐藏文件（.gitignore 等）直接放行（与 JS L263-266 对齐）
        if filename.startswith("."):
            return True, "PASS — 根一级点开头隐藏文件放行（.gitignore 等）"
        root_rule = meta.get("root_file_name_rule", "")
        exempt = [str(x) for x in (meta.get("root_exempt_files") or [])]
        if root_rule:
            try:
                if not re.search(root_rule, filename, re.IGNORECASE) and filename not in exempt:
                    return False, f"根目录禁止散落文件（{filename}），请放入 {list(meta.get('dirs', {}).keys())} 之一"
            except re.error:
                pass  # 规则语法错误则放行，由 git hooks 兜底
            else:
                # root_file_name_rule 匹配或 root_exempt_files 显式豁免则放行（与 JS 一致：根一级文件不进 dirs 检查）
                return True, f"合规 — 根目录允许文件（{filename}，匹配 root_file_name_rule 或 root_exempt_files 豁免）"
        else:
            if filename in exempt:
                return True, f"合规 — 根目录允许文件（{filename}，root_exempt_files 豁免）"
            return False, f"根目录禁止散落文件（{filename}），请放入白名单目录"

    # 7. 目录白名单 + 扩展名检查
    dirs = meta.get("dirs", {})
    # 找到文件所在的（或要创建的）目录
    target_dir_rel = "/".join(rel_parts[:-1]) if len(rel_parts) > 1 else ""
    # 如果目标路径本身是目录（创建目录场景），target_dir_rel 需要调整
    # 这里 file_path 可能是文件也可能是目录，我们取父目录做校验
    check_dir = target_dir_rel
    if not check_dir:
        check_dir = "."  # 根目录

    # 匹配目录白名单（支持嵌套如 tests/fixtures；按 Key 长度降序，与 JS L93 对齐）
    allowed_exts = None
    for d_pattern, exts in sorted(dirs.items(), key=lambda kv: len(kv[0]), reverse=True):
        d_norm = d_pattern.replace("\\", "/").lower().rstrip("/")
        if check_dir == d_norm or check_dir.startswith(d_norm + "/"):
            allowed_exts = exts
            break

    if allowed_exts is None:
        return False, f"目录 '{check_dir}' 不在白名单内，允许目录: {list(dirs.keys())}"

    # 空名单目录：任意文件/命名放行（与 JS L101 对齐，覆盖 _scratch/tests/fixtures/_trash 等，
    # _trash 已在第 4 步被 TRASH_PATTERN 先行拦截，不会因此绕过禁写）
    if not allowed_exts:
        return True, f"PASS — 空名单目录放行（{check_dir}，任意文件/命名）"

    # 扩展名检查（目录本身创建不检查扩展名）
    if target.is_file() or (not target.exists() and "." in target.name):
        ext_ok = False
        filename = target.name.lower()
        for e in allowed_exts:
            e = e.lower()
            if e == "*" or e == "*.*":
                ext_ok = True
                break
            elif e.startswith("*."):
                if filename.endswith(e[1:]):
                    ext_ok = True
                    break
            elif filename == e.lower():
                ext_ok = True
                break
        if not ext_ok:
            return False, f"扩展名不在白名单（{target.name}），允许: {allowed_exts}"

    return True, f"合规 — 项目: {meta.get('name', project_dir.name)}"

# ---- CLI ----
def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard Enforcer — 规则校验 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # check
    p_check = sub.add_parser("check", help="校验文件路径是否合规")
    p_check.add_argument("path", help="要校验的文件/目录路径")
    p_check.add_argument("--project", "-p", default=None, help="指定项目根目录（含 project_meta.json）")

    # info
    p_info = sub.add_parser("info", help="显示项目规则摘要")
    p_info.add_argument("project", help="项目根目录")

    # list
    p_list = sub.add_parser("list", help="列出受管根目录下的所有项目")
    p_list.add_argument("--root", "-r", default=str(ROOT), help="受管根目录（默认 %USERPROFILE%\\comate）")

    args = ap.parse_args()

    if args.cmd == "check":
        proj = Path(args.project) if args.project else None
        ok, msg = check_path(args.path, proj)
        if ok:
            print(f"[PASS] {msg}")
            return 0
        else:
            print(f"[FAIL] {msg}", file=sys.stderr)
            return 1

    elif args.cmd == "info":
        meta_path = Path(args.project) / META_NAME
        if not meta_path.is_file():
            print(f"[FAIL] 未找到 {meta_path}", file=sys.stderr)
            return 2
        try:
            meta = load_meta(meta_path)
        except Exception as e:
            print(f"[FAIL] 解析失败: {e}", file=sys.stderr)
            return 2

        print(f"项目: {meta.get('name', 'unknown')}")
        print(f"类型: {meta.get('type', 'unknown')} | strict_mode: {meta.get('strict_mode', False)}")
        print(f"版本: {meta.get('version', 'unknown')}")
        print(f"\n目录白名单（dirs）:")
        for d, exts in meta.get("dirs", {}).items():
            print(f"  {d}: {exts or ['(任意)']}")
        print(f"\n根文件命名规则: {meta.get('root_file_name_rule', '无')}")
        print(f"只读文件: {meta.get('read_only_files', [])}")
        return 0

    elif args.cmd == "list":
        root = Path(args.root)
        metas = list(root.glob("*/project_meta.json"))
        metas += list(root.glob("*/*/project_meta.json"))
        if not metas:
            print(f"[INFO] {root} 下未找到项目")
            return 0
        print(f"受管根目录: {root}")
        print(f"发现 {len(metas)} 个项目:\n")
        for m in sorted(metas, key=lambda p: str(p)):
            try:
                meta = load_meta(m)
                name = meta.get("name", m.parent.name)
                print(f"  {name:20s}  {m.parent}")
            except Exception:
                print(f"  [解析失败]  {m.parent}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
