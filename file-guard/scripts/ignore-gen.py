#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — .comateignore 生成器（引擎级拦截通道，不依赖 hooks）

背景（2026-10-23 定案）：Comate 4.13.4 hooks 系统未激活，PreToolUse 钩子空转。
引擎内置 FsPermissionService 在每个文件工具执行前调用 canRead/canWrite，
其 evaluateRead/evaluateWrite 第一优先检查 .comateignore（读+写均拦，
非 sandboxAuto 也生效，热监听改后即生效）。此通道成为 FileGuard 当前唯一
不依赖客户端的拦截层。

用法:
  python ignore-gen.py             # 生成内容到 stdout
  python ignore-gen.py --write     # 写项目级 <FG_HOME 下登记项目>/.comate/.comateignore
  python ignore-gen.py --global    # 同时写全局 ~/.comate/.comateignore
  python ignore-gen.py --check     # 校验已生成文件与当前规则是否一致（doctor D10 用）

规则来源（单一真源）:
  - C0: %USERPROFILE%\\comate\\_rules\\global-rules.json -> rules.blacklisted_names.file（正则，启发式转 glob）
  - 内置敏感文件清单（原沙箱 denyRead 语义）
  - _trash / .git 隔离

注意: .comateignore 同时拦截读和写（引擎设计），只读保护类（project_meta.json 等）
不可用此通道（会连读都拦掉），仍依赖 hooks 恢复。
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
RULES_PATH = COMATE_FG_HOME / "_rules" / "global-rules.json"  # 2026-10-27 去硬编码：随 COMATE_FG_HOME 派生
REGISTRY_PATH = RULES_PATH.parent / "managed-projects.json"  # 受管登记表（P1 定案 2026-10-23）
USERPROFILE = Path(os.environ.get("USERPROFILE", ""))

HEADER = """# FileGuard 引擎级拦截规则（.comateignore，不依赖 Comate hooks）
# 由 scripts/ignore-gen.py 生成维护；单一真源：%USERPROFILE%\\comate\\_rules\\global-rules.json (C0)
# 注意：.comateignore 同时拦截读和写（引擎 FsPermissionService，热更新生效）
"""

# 内置敏感文件/目录（原沙箱 denyRead 语义 + 运维隔离）
BUILTIN_GLOBS = [
    # ---- _trash 完全隔离（禁读写）----
    "**/_trash/**",
    # ---- 敏感/密钥文件 ----
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/credentials.json",
    "**/credentials*.json",
    "**/secrets.*",
    "**/id_rsa",
    "**/id_ed25519",
    "**/.npmrc",
    # ---- .git 内部隔离 ----
    "**/.git/**",
]

# C0 正则模式字符串 -> glob 的精确映射（与 C0 blacklisted_names.file 对齐）
_GLOB_BY_REGEX = {
    r"^~\$": "**/~$*",
    r"^新建[文本文档]*\.": "**/新建文本文档*",
    r"\.tmp$": "**/*.tmp",
    r"\.bak$": "**/*.bak",
    r"_v2\.": "**/*_v2.*",
    r"_v3\.": "**/*_v3.*",
    r"_v4\.": "**/*_v4.*",
    r"_v5\.": "**/*_v5.*",
    r"_v6\.": "**/*_v6.*",
    r"^test[-_]?(deploy|demo|reboot)\.txt$": "**/test-*.txt",
    r"^tmp_": "**/tmp_*",
    r"^temp_": "**/temp_*",
    r"^nul$": "**/nul",
}


def c0_blacklist_globs() -> list[str]:
    """从 C0 单一真源读取 blacklisted_names.file，按映射表转 glob。"""
    try:
        g = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        pats = ((g.get("rules") or {}).get("blacklisted_names") or {}).get("file") or []
    except Exception:
        return []
    out: list[str] = []
    for p in pats:
        if not isinstance(p, str):
            continue
        glob = _GLOB_BY_REGEX.get(p)
        if glob:
            out.append(glob)
    # 去重保序
    return list(dict.fromkeys(out))


def build_content() -> str:
    lines = [HEADER, ""]
    black = c0_blacklist_globs()
    if black:
        lines.append("# ---- C0 黑名单文件（blacklisted_names.file）----")
        lines.extend(black)
        lines.append("")
    for g in BUILTIN_GLOBS:
        if not g.startswith("#"):
            lines.append(g)
    return "\n".join(lines).rstrip() + "\n"


def managed_projects() -> list[Path]:
    """受管项目根：优先读中央登记表 managed-projects.json（P1 定案，2026-10-23）；
    登记表缺失/损坏/为空时回退 FG_HOME 两层扫描（保兼容，对齐 doctor D5）。"""
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        roots = [Path(p["root"]) for p in (reg.get("projects") or []) if p.get("root")]
        if roots:
            return list(dict.fromkeys(roots))
    except Exception:
        pass
    found = []
    for pattern in ("*/project_meta.json", "*/*/project_meta.json"):
        for meta in COMATE_FG_HOME.glob(pattern):
            root = meta.parent
            if root not in found:
                found.append(root)
    return found


def write_project() -> list[Path]:
    """写所有登记项目（引擎实际加载的 workspaceRoots）的 .comateignore。"""
    content = build_content()
    written = []
    for root in managed_projects():
        target = root / ".comate" / ".comateignore"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def write_global() -> Path:
    target = USERPROFILE / ".comate" / ".comateignore"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_content(), encoding="utf-8")
    return target


def check_ok() -> tuple[bool, list[str]]:
    content = build_content()
    problems = []
    targets = [root / ".comate" / ".comateignore" for root in managed_projects()]
    # 全局副本存在则比对；缺失不判失败（可选部署，需用户确认后 --global 生成）
    g = USERPROFILE / ".comate" / ".comateignore"
    if g.is_file() and g.read_text(encoding="utf-8") != content:
        problems.append(f"全局副本与生成器不一致: {g}")
    for t in targets:
        if not t.is_file():
            problems.append(f"缺失: {t}")
        elif t.read_text(encoding="utf-8") != content:
            problems.append(f"与生成器不一致: {t}")
    return (not problems, problems)


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard .comateignore 生成器")
    ap.add_argument("--write", action="store_true", help="写项目级（FG_HOME 及登记项目）")
    ap.add_argument("--global", dest="gwrite", action="store_true", help="同时写全局 ~/.comate/.comateignore")
    ap.add_argument("--check", action="store_true", help="校验一致性（doctor D10）")
    args = ap.parse_args()

    if args.check:
        ok, problems = check_ok()
        for p in problems:
            print(p, file=sys.stderr)
        return 0 if ok else 1

    if args.write:
        written = write_project()
        for w in written:
            print(f"[PASS] 已写入 {w}")
        if args.gwrite:
            w = write_global()
            print(f"[PASS] 已写入 {w}")
        return 0

    # 默认 stdout 输出
    sys.stdout.write(build_content())
    return 0


if __name__ == "__main__":
    sys.exit(main())
