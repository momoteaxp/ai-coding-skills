#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — PreCompact 压缩前钩子（归档通道，不含任务状态）

对齐 CHECKPOINT-SCHEMA 铁律：压缩自动通道只是「归档者」，不是「状态写者」——
latest.json 只写元信息（kind/project/session/cwd/timestamp），绝不写任务状态；压缩续接由客户端
自带摘要承担（此前"压缩后读 latest.json 恢复上下文"的说法已废弃）。跨窗口进度由 checkpoint-manager.py
save 显式写入（SKILL"跨窗口接续"节）；latest.json 已存在（存有真实进度）时绝不动，仅缺失时写最小占位。
当前项目根 = cwd 向上 ≤2 层找 project_meta.json（与 pre-tool-use.py 同口径）。

无论存档是否成功都 exit 0（绝不阻断压缩）；存不了只在 stderr 提示落盘 docs/。
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

    if not cwd:
        print("[file-guard] 压缩前提示: 未提供 cwd，跳过检查点存档。关键结论请落盘 docs/。", file=sys.stderr)
        return 0

    root = norm(str(COMATE_FG_HOME))
    target = norm(cwd)
    if not (target.startswith(root + "/") or target == root):
        print("[file-guard] 压缩前提示: cwd 在受管根外，跳过检查点存档。", file=sys.stderr)
        return 0

    meta = find_meta(Path(cwd))
    if meta is None:
        print("[file-guard] 压缩前提示: 当前项目未登记规则，跳过检查点存档。", file=sys.stderr)
        return 0

    project_root = meta.parent
    cp = project_root / CHECKPOINT_DIR
    try:
        cp.mkdir(parents=True, exist_ok=True)
        state = {
            "kind": "precompact-auto",
            "project": project_root.name,
            "session_id": session,
            "cwd": cwd,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": "PreCompact 自动归档（审计）：仅元信息，不含任务状态；跨窗口续接请用 checkpoint-manager.py save/load；关键结论请落盘 docs/",
        }
        latest = cp / LATEST_FILE
        if latest.exists():
            # 铁律（对齐 CHECKPOINT-SCHEMA）：已存在真实进度则绝不动，只追加历史归档
            print(f"[file-guard] 压缩前提示: latest.json 已有内容，不覆盖（仅归档历史）", file=sys.stderr)
        else:
            # 最小占位：v2 多窗口形状（windows 空）；跨窗口续接仍走 checkpoint-manager.py save/load
            placeholder = {
                "project": project_root.name,
                "schema": "v2-windows",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "windows": {},
            }
            latest.write_text(json.dumps(placeholder, ensure_ascii=False, indent=2), encoding="utf-8")
        hist_name = f"precompact_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
        hist = cp / hist_name
        hist.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        # 保留最近 MAX_HISTORY 份历史（对齐 checkpoint-manager compact 口径）
        files = sorted(cp.glob("precompact_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[MAX_HISTORY:]:
            old.unlink(missing_ok=True)
        print(f"[file-guard] 压缩前存档完成: {hist.relative_to(project_root)}（会话 {session or 'unknown'}）", file=sys.stderr)
    except Exception as e:
        print(f"[file-guard] 压缩前提示: 检查点存档失败（{e}），已放行。关键结论请落盘 docs/。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
