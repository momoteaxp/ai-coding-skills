#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — JSON 只读查询（引号根治 A：杜绝 python -c 内联读取 JSON）

背景（2026-10-23）：命令内联代码经"命令行→PowerShell→解释器"多层解析必吞引号
（引号铁律）。本工具让"读 JSON"类操作零引号零内联：
    python scripts/cquery.py <文件> [<点分键路径>]
    python scripts/cquery.py %USERPROFILE%\\comate\\_rules\\global-rules.json rules.dir_type_map
    python scripts/cquery.py project_meta.json dirs
    python scripts/cquery.py project_meta.json dirs.src        # 数组元素支持索引
"""
import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard JSON 只读查询（零引号）")
    ap.add_argument("file", help="JSON 文件路径")
    ap.add_argument("path", nargs="?", default="", help="点分键路径（如 rules.dir_type_map.software.dirs.0）")
    ap.add_argument("--raw", action="store_true", help="紧凑输出（不美化）")
    args = ap.parse_args()

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[FAIL] 读取失败: {args.file} — {e}", file=sys.stderr)
        return 1

    cur = data
    if args.path:
        for part in args.path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                print(f"[FAIL] 路径 {args.path} 不存在（位于 {part}）", file=sys.stderr)
                return 2

    sys.stdout.write(json.dumps(cur, ensure_ascii=False, indent=None if args.raw else 2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
