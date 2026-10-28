#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — PreCompact 压缩前提示（不写归档）

2026-10-28 清理：PreCompact 自动归档没有消费方，停用写盘，只提示显式 save。
- 不用 payload cwd；只认 FILEGUARD_CURRENT_DIR
- type=kb / checkpoint_enabled=false 的项目直接跳过
- 无论是否提示都 exit 0（绝不阻断压缩）；跨窗口进度由 checkpoint-manager.py save 显式写入。
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
META_NAME = "project_meta.json"
MAX_META_DEPTH = 2
CHECKPOINT_DIR = "_checkpoint"
LATEST_FILE = "latest.json"
MAX_HISTORY = 5


def norm(p: str) -> str:
    s = os.path.normpath(os.path.abspath(p)).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].upper() + s[1:]
    return s.lower().rstrip("/")


def find_meta(target: Path) -> Path | None:
    d = target.resolve()
    for _ in range(MAX_META_DEPTH + 1):
        cand = d / META_NAME
        if cand.is_file():
            return cand
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or ""
    session = payload.get("session_id") or ""

    # 2026-10-28 根治：payload cwd 不可靠，绝不用它决定项目；只认 FILEGUARD_CURRENT_DIR
    env_dir = os.environ.get("FILEGUARD_CURRENT_DIR") or ""
    if not env_dir:
        print("[file-guard] 压缩前提示: 未提供 FILEGUARD_CURRENT_DIR，跳过检查点存档。关键结论请落盘 docs/。", file=sys.stderr)
        return 0

    root = norm(str(COMATE_FG_HOME))
    target = norm(env_dir)
    if not (target.startswith(root + "/") or target == root):
        print("[file-guard] 压缩前提示: FILEGUARD_CURRENT_DIR 在受管根外，跳过检查点存档。", file=sys.stderr)
        return 0

    meta = find_meta(Path(env_dir))
    if meta is None:
        print("[file-guard] 压缩前提示: 当前项目未登记规则，跳过检查点存档。", file=sys.stderr)
        return 0

    # 纯数据/显式关闭 checkpoint 的项目不写（与 D12/checkpoint-manager 豁免一致）
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        cp_enabled = m.get("checkpoint_enabled", True)
        if cp_enabled is False or str(cp_enabled).strip().lower() == "false" \
                or str(m.get("type") or "").strip().lower() == "kb":
            print("[file-guard] 压缩前提示: 纯数据/关闭 checkpoint 项目，跳过存档。", file=sys.stderr)
            return 0
    except Exception:
        pass

    # 2026-10-28 清理：PreCompact 自动归档没有消费方，停用写盘，只提示显式 save。
    print("[file-guard] 压缩前提示: 自动归档通道已停用（无消费方）；请用 checkpoint-manager.py save 显式保存进度，关键结论落盘 docs/。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
