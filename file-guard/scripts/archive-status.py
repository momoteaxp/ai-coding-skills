#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archive-status.py — 只读查看窗口聊天归档状态

用途：删窗口前确认该窗口的聊天记录已经归档（session.json + tracecard.json）。
不修改任何文件；不依赖客户端 db。

用法:
    python archive-status.py --project <项目根>
    python archive-status.py --project <项目根> --workspace <workspace路径>
    python archive-status.py --traces-root <.../_traces/comate> --workspace <workspace路径>
    python archive-status.py --project <项目根> --json

状态:
    OK       session.json + tracecard.json 都在
    PARTIAL  只有 session.json / tracecard.json / snapshot 之一
    MISSING  没有会话正文或 tracecard

提示：PARTIAL 可先跑 trace-collect.py --session-id <sid> 补齐，再删窗口。
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _norm(p) -> str:
    if not p:
        return ""
    try:
        return os.path.normpath(os.path.abspath(str(p))).replace("\\", "/").lower().rstrip("/")
    except Exception:
        return str(p).replace("\\", "/").lower().rstrip("/")


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _collect(traces: Path, workspace_filter: str = ""):
    target = _norm(workspace_filter) if workspace_filter else ""
    rows = []
    for d in sorted(traces.iterdir()):
        if not d.is_dir():
            continue
        sess = {}
        for name in ("session.json", "session.snapshot.json"):
            p = d / name
            if p.is_file():
                sess = _load(p)
                if sess:
                    break
        ws = str(sess.get("workspaceDirectory") or "")
        if target and _norm(ws) != target:
            continue
        sid = str(sess.get("sessionUuid") or d.name)
        has_session = (d / "session.json").is_file()
        has_card = (d / "tracecard.json").is_file()
        has_snap = (d / "session.snapshot.json").is_file()
        blobs = 0
        bdir = d / "blobs"
        if bdir.is_dir():
            blobs = sum(1 for p in bdir.iterdir() if p.is_file())
        times = []
        for p in (d / "session.json", d / "tracecard.json", d / "session.snapshot.json"):
            if p.is_file():
                times.append(p.stat().st_mtime)
        last = max(times) if times else d.stat().st_mtime
        if has_session and has_card:
            status = "OK"
        elif has_session or has_card or has_snap:
            status = "PARTIAL"
        else:
            status = "MISSING"
        rows.append({
            "session_id": sid,
            "status": status,
            "workspace": ws,
            "title": str(sess.get("title") or ""),
            "last_write": datetime.fromtimestamp(last).isoformat(timespec="seconds"),
            "has_session": has_session,
            "has_tracecard": has_card,
            "has_snapshot": has_snap,
            "blobs": blobs,
            "dir": str(d),
        })
    rows.sort(key=lambda r: r["last_write"], reverse=True)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="只读查看窗口聊天归档状态")
    ap.add_argument("--project", "-p", default="", help="项目根（读 <根>/_traces/comate）")
    ap.add_argument("--traces-root", default="", help="直接指定 _traces/comate 目录")
    ap.add_argument("--workspace", default="", help="只看某个 workspace 的窗口")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.traces_root:
        traces = Path(args.traces_root)
    elif args.project:
        traces = Path(args.project) / "_traces" / "comate"
    else:
        print("[FAIL] 需要 --project 或 --traces-root", file=sys.stderr)
        return 2
    if not traces.is_dir():
        print(f"[FAIL] 归档目录不存在: {traces}", file=sys.stderr)
        return 1

    rows = _collect(traces, args.workspace)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("OK", "PARTIAL", "MISSING")}
    if args.json:
        print(json.dumps({"traces_root": str(traces), "counts": counts, "windows": rows},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"归档目录: {traces}")
    print(f"窗口数: {len(rows)} | OK={counts['OK']} PARTIAL={counts['PARTIAL']} MISSING={counts['MISSING']}")
    print("-" * 100)
    for r in rows:
        sid = r["session_id"]
        short = sid if len(sid) <= 12 else sid[:8] + "…"
        print(f"[{r['status']:7}] {short:14} {r['last_write']}  blobs={r['blobs']:<4} {r['workspace']}")
        if r["title"]:
            print(f"          {r['title'][:80]}")
    if counts["PARTIAL"] or counts["MISSING"]:
        print("\n提示：PARTIAL/MISSING 的窗口先跑 trace-collect.py --session-id <sid> 补齐，再删窗口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
