#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard checkpoint manager — 项目本地单文件运行时

设计（2026-10-28 收敛）:
- 项目根 = 本脚本上一级（放在 <项目>/tools/ 或套件 <项目>/scripts/ 都成立）
- 只操作 <项目>/_checkpoint/latest.json，不存在跨项目概念
- save 原子覆盖；load 读最新；旧 v2 windows 自动取最近窗口段（兼容，不写回）
- 没有 --project / bind / session-id / history / windows / compact / auto-session
- 多窗口完整对话由 _traces 归档负责；checkpoint 只保存最新一次交接状态

用法:
  python tools/checkpoint-manager.py save --current-task "一句话" \
      --completed-steps "步骤1,步骤2" --pending-tasks "待办1,待办2" \
      --key-decisions "决策1" --title "标题"
  python tools/checkpoint-manager.py load
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECKPOINT_DIR = "_checkpoint"
LATEST_FILE = "latest.json"
REQUIRED_LIST = ("completed_steps", "pending_tasks", "key_decisions")


def root() -> Path:
    """项目根：脚本上一级。tools/ 与 scripts/ 都在项目根下一层。"""
    return Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_meta(project_root: Path) -> dict:
    try:
        d = json.loads((project_root / "project_meta.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _disabled_reason(project_root: Path) -> str:
    """纯数据/显式关闭的项目不写 checkpoint；工作流本来就不会分发脚本。"""
    m = _read_meta(project_root)
    ptype = str(m.get("type") or "").strip().lower()
    if ptype in ("kb", "data"):
        return f"type={ptype}"
    cp = m.get("checkpoint_enabled", True)
    if cp is False or str(cp).strip().lower() == "false":
        return "checkpoint_enabled=false"
    if m.get("managed") is False:
        return "managed=false"
    return ""


def _json_list(s: str) -> list:
    """命令行字符串 → list：优先 JSON 数组，回退逗号分隔。"""
    if not s:
        return []
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]
    except json.JSONDecodeError:
        return [x.strip() for x in s.split(",") if x.strip()]


def _latest_path(project_root: Path) -> Path:
    return project_root / CHECKPOINT_DIR / LATEST_FILE


def _flatten(doc: dict) -> dict:
    """旧 v2 windows / legacy → 扁平段；正常单文件直接返回。"""
    if not isinstance(doc, dict):
        return {}
    wins = doc.get("windows")
    if isinstance(wins, dict) and wins:
        key = max(wins, key=lambda k: str((wins[k] or {}).get("updated_at") or ""))
        seg = dict(wins[key] or {})
        seg.setdefault("project", doc.get("project") or "")
        seg.setdefault("timestamp", seg.get("updated_at") or doc.get("updated_at") or "")
        seg["migrated_from_v2"] = True
        seg["migrated_from_window"] = key
        return seg
    legacy = doc.get("legacy")
    if isinstance(legacy, dict) and legacy:
        seg = dict(legacy)
        seg.setdefault("project", doc.get("project") or "")
        seg["migrated_from_v2"] = True
        return seg
    return dict(doc)


def _norm_seg(seg: dict, project_root: Path) -> dict:
    out = {
        "project": str(seg.get("project") or project_root.name),
        "timestamp": str(seg.get("timestamp") or seg.get("updated_at") or ""),
        "title": str(seg.get("title") or ""),
        "current_task": str(seg.get("current_task") or ""),
    }
    for k in REQUIRED_LIST:
        v = seg.get(k)
        out[k] = v if isinstance(v, list) else []
    for k in ("migrated_from_v2", "migrated_from_window"):
        if k in seg:
            out[k] = seg[k]
    return out


def load(project_root: Path | None = None) -> dict:
    r = project_root or root()
    latest = _latest_path(r)
    if not latest.is_file():
        return {
            "status": "not_found",
            "project": r.name,
            "path": str(latest),
            "message": "本项目还没有 checkpoint；用 tools/checkpoint-manager.py save 建立",
        }
    try:
        doc = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "project": r.name, "path": str(latest), "message": f"JSON 解析失败: {e}"}
    seg = _norm_seg(_flatten(doc), r)
    return {"status": "ok", "path": str(latest), **seg}


def save(project_root: Path | None = None, **kwargs) -> dict:
    r = project_root or root()
    reason = _disabled_reason(r)
    if reason:
        return {
            "status": "error",
            "project": r.name,
            "path": str(_latest_path(r)),
            "message": f"该项目不启用 checkpoint（{reason}）",
        }
    for k in REQUIRED_LIST:
        v = kwargs.get(k) or []
        if not isinstance(v, list):
            raise TypeError(f"{k} must be a list, got {type(v)}")
        kwargs[k] = [str(x) for x in v]
    state = {
        "project": r.name,
        "timestamp": _now(),
        "title": str(kwargs.get("title") or ""),
        "current_task": str(kwargs.get("current_task") or ""),
        "completed_steps": kwargs["completed_steps"],
        "pending_tasks": kwargs["pending_tasks"],
        "key_decisions": kwargs["key_decisions"],
    }
    latest = _latest_path(r)
    latest.parent.mkdir(parents=True, exist_ok=True)
    tmp = latest.with_name(latest.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, latest)
    return {"status": "saved", "project": r.name, "path": str(latest), "timestamp": state["timestamp"]}


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard checkpoint manager（项目本地单文件）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save", help="保存本项目最新 checkpoint")
    p_save.add_argument("--current-task", default="")
    p_save.add_argument("--completed-steps", type=_json_list, default=[])
    p_save.add_argument("--pending-tasks", type=_json_list, default=[])
    p_save.add_argument("--key-decisions", type=_json_list, default=[])
    p_save.add_argument("--title", default="")

    sub.add_parser("load", help="读取本项目最新 checkpoint")

    args = ap.parse_args()
    if args.cmd == "save":
        res = save(
            current_task=args.current_task,
            completed_steps=args.completed_steps,
            pending_tasks=args.pending_tasks,
            key_decisions=args.key_decisions,
            title=args.title,
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("status") == "saved" else 1

    res = load()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
