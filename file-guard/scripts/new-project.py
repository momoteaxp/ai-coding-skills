#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — 一键新建受管项目

独立单源：直接调用本套件 scripts/init.py，
类型模板由 init.py 从 C0 rules.dir_type_map 派生（经 %USERPROFILE%\\comate\\_rules 独立规则文件）。

本脚本只做 comate 侧差异处理：
  1. 父目录默认 COMATE_FG_HOME\\products（即 %USERPROFILE%\\comate\\products）
  2. 项目名强制英文小写短横线（设计决策 #3：comate 侧不用中文目录名）
  3. 设置 FG_HOME=COMATE_FG_HOME 后透传 --type/--root/--force 给 init.py

用法:
    python new-project.py <name> --type software|skill|suite|web|docgen|ops [--root <父目录>] [--force]
    （旧别名 A/B/C 兼容：A→software B→skill C→docgen）
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8，任何调用方式下 print 不因 GBK 崩溃
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
DEFAULT_ROOT = COMATE_FG_HOME / "products"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard (Comate) 一键新建受管项目")
    ap.add_argument("name", help="项目名（英文小写短横线，comate 侧不用中文目录名）")
    ap.add_argument("--type", required=True, help="项目类型（software/skill/suite/web/docgen/ops；旧别名 A/B/C 兼容）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help=f"父目录（默认 {DEFAULT_ROOT}）")
    ap.add_argument("--force", action="store_true", help="已存在时仍补建缺失目录/meta")
    args = ap.parse_args()

    name = args.name.lower()
    if not NAME_RE.match(name):
        print(f"[FAIL] 项目名须为英文小写短横线（{NAME_RE.pattern}），收到: {args.name}", file=sys.stderr)
        return 2

    init = Path(__file__).resolve().parent / "init.py"
    if not init.is_file():
        print(f"[FAIL] 未找到本套件 init.py: {init}", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["FG_HOME"] = str(COMATE_FG_HOME)
    cmd = [sys.executable, str(init), name, "--type", args.type, "--root", args.root]
    if args.force:
        cmd.append("--force")
    print(f"[OK] 调用本套件 init.py（独立单源）")
    print(f"     FG_HOME={COMATE_FG_HOME} | root={args.root} | type={args.type}")
    return subprocess.run(cmd, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
