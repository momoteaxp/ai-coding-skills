#!/usr/bin/env python3
"""checkpoint-manager.py — FileGuard 状态检查点管理器（v2.0 多窗口）

设计原则：
1. 纯文件操作，零外部依赖（不读客户端 db、不读环境变量、不动态导入）
2. 内容通过命令行参数传入，脚本负责格式化和校验
3. 跨客户端通用：只要有 Python + 文件系统就能跑
4. AI 只提供内容，脚本决定格式和位置

v2.0（2026-10-23）：同一项目多窗口。
- latest.json 结构改为 windows:{<conversation_id>:{...}}，每窗口独立段互不覆盖；
- 保存只更新自己那段，其他段不动；写入用文件锁 + 原子替换；
- 读取返回本窗口段 + 其他窗口一行摘要（标题/最后更新/当前任务）；
- 内容 hash 相同不写；历史版本按窗口保留最近 5 个；
- 旧扁平结构（v1.0）迁移为 legacy 段，不丢内容；
- save/load 增加 --session-id；缺省时按活跃会话标记
  （_checkpoint/.active-session.json，由 pre-tool-use / pre-compact 钩子写入）推断；
  save 无法推断时明确报错（绝不写错窗口），load 无法推断时取最近更新窗口（只读安全）。

用法：
  save --project <项目根目录>
       --current-task <文本>
       --completed-steps <JSON数组>
       --pending-tasks <JSON数组>
       [--key-decisions <JSON数组>]
       [--title <文本>]
       [--session-id <会话id>]
  load --project <项目根目录> [--session-id <会话id>] [--flat]
        # load 稳定 JSON 契约（2026-10-26 定案，消费方按此解析）:
        #   { status, project, schema, session_id, window, window_missing, others[], legacy }
        #   window_missing=true 表示"该会话还没有窗口段"（≠ 没有数据，legacy 可能仍有）；
        #   --flat 输出旧 v1 扁平形状（本窗口段优先，无则 legacy）：消费方无需理解 v2
  compact --project <项目根目录> [--prune-windows-days <天数>]
  windows --project <项目根目录>     # 列出所有窗口段（标题/最后更新/当前任务）
  remove-window --project <项目根目录> --session-id <会话id>   # 显式删除窗口段（不可恢复）
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import msvcrt  # Windows 文件锁；非 Windows 回退无锁（本套件目标平台 Windows）
except ImportError:  # pragma: no cover
    msvcrt = None

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8。
# 修复（2026-10-26）：GBK 控制台下 load 打印含 emoji/生僻字内容会 UnicodeEncodeError
# （'gbk' codec can't encode），reconfigure 覆盖继承的 PYTHONIOENCODING/控制台编码。
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CHECKPOINT_DIR = "_checkpoint"
LATEST_FILE = "latest.json"
LOCK_FILE = "latest.json.lock"
ACTIVE_SESSION_FILE = ".active-session.json"
HISTORY_DIR = "history"
SCHEMA = "v2-windows"
MAX_WINDOW_HISTORY = 5
MAX_LEGACY_HISTORY = 5  # 旧扁平结构（v1 历史文件）compact 时保留份数

REQUIRED_STR = ("current_task", "title")
REQUIRED_LIST = ("completed_steps", "pending_tasks", "key_decisions")
_WINDOW_FIELDS = ("title", "updated_at", "current_task", "completed_steps", "pending_tasks", "key_decisions")


def _ensure_dir(project_root: str) -> Path:
    cp = Path(project_root) / CHECKPOINT_DIR
    cp.mkdir(parents=True, exist_ok=True)
    return cp


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seg_hash(seg: dict) -> str:
    """窗口段内容 hash（title/current_task/三列表，排除 updated_at）。相同内容不写。"""
    core = {k: seg.get(k) for k in ("title", "current_task", "completed_steps", "pending_tasks", "key_decisions")}
    blob = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _is_v2(doc: dict) -> bool:
    return isinstance(doc.get("windows"), dict)


def _migrate(doc: dict) -> dict:
    """旧扁平 v1 结构 → v2：原内容整体进 legacy 段，windows 空。"""
    legacy = {k: doc.get(k) for k in ("project", "timestamp", "current_task", "completed_steps",
                                      "pending_tasks", "key_decisions", "title")}
    return {
        "project": doc.get("project", ""),
        "schema": SCHEMA,
        "updated_at": _now(),
        "windows": {},
        "legacy": legacy,
    }


def _load_raw(latest: Path) -> dict | None:
    try:
        if not latest.exists():
            return None
        return json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_doc(latest: Path, project_root: Path) -> dict:
    """读取 latest.json；缺失 → 空 v2；扁平 v1 → 迁移为 v2（不写盘，写盘由 save 决定）。
    返回 (doc, migrated_flag)。"""
    raw = _load_raw(latest)
    if raw is None:
        return {
            "project": project_root.resolve().name,
            "schema": SCHEMA,
            "updated_at": _now(),
            "windows": {},
        }, False
    if not _is_v2(raw):
        return _migrate(raw), True
    return raw, False


def _atomic_write(latest: Path, doc: dict) -> None:
    """文件锁 + 原子替换：tmp 同目录写后 os.replace。"""
    tmp = latest.with_name(latest.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(latest))


def _with_lock(latest: Path, fn):
    """进程级文件锁（msvcrt 字节锁）；非 Windows 或无锁能力时直接执行。"""
    if msvcrt is None:
        return fn()
    lock_path = latest.with_name(LOCK_FILE)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        for _ in range(50):  # 重试 5 秒
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("无法获取检查点锁（另一窗口正在保存，重试后仍失败）")
        try:
            return fn()
        finally:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        os.close(fd)


def _norm(p: str) -> str:
    s = os.path.normpath(os.path.abspath(p)).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].upper() + s[1:]
    return s.lower().rstrip("/")


def _active_session(project_root: Path) -> str | None:
    """活跃会话 id：标记文件里 conversation_id 优先（会话 uuid），回退 session_id。
    2026-10-27 硬化：标记的 cwd 字段若不属于目标项目（引擎 cwd 漂移时钩子会把标记
    写进错误项目的 _checkpoint），视为漂移残留忽略——防错项目 marker 被当真。"""
    try:
        d = json.loads((project_root / CHECKPOINT_DIR / ACTIVE_SESSION_FILE).read_text(encoding="utf-8"))
        cwd = str(d.get("cwd") or "")
        if cwd:
            n_cwd = _norm(cwd)
            n_root = _norm(str(project_root))
            if not (n_cwd == n_root or n_cwd.startswith(n_root + "/")):
                return None  # 漂移 cwd 写的标记，非本项目的活跃会话
        return str(d.get("conversation_id") or d.get("session_id") or "").strip() or None
    except Exception:
        return None


def _resolve_session_id(project_root: Path, doc: dict, sid: str, for_save: bool) -> str | None:
    if sid:
        return sid
    sid = _active_session(project_root)
    if sid:
        return sid
    windows = doc.get("windows") or {}
    if len(windows) == 1:
        return next(iter(windows))
    if not for_save and windows:
        # 只读场景：无标记时取最近更新的窗口（安全猜测）
        return max(windows, key=lambda k: str(windows[k].get("updated_at") or ""))
    return None


def _write_window_history(project_root: Path, session_id: str, seg: dict) -> Path:
    """按窗口写历史版本，保留最近 MAX_WINDOW_HISTORY 份。"""
    hdir = Path(project_root) / CHECKPOINT_DIR / HISTORY_DIR / session_id
    hdir.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    hist = hdir / name
    hist.write_text(json.dumps(seg, ensure_ascii=False, indent=2), encoding="utf-8")
    files = sorted(hdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[MAX_WINDOW_HISTORY:]:
        old.unlink(missing_ok=True)
    return hist


def save(project_root: str, session_id: str = "", **kwargs) -> dict:
    cp = _ensure_dir(project_root)
    latest = cp / LATEST_FILE
    seg = {
        "title": kwargs.get("title", ""),
        "updated_at": _now(),
        "current_task": kwargs.get("current_task", ""),
        "completed_steps": kwargs.get("completed_steps") or [],
        "pending_tasks": kwargs.get("pending_tasks") or [],
        "key_decisions": kwargs.get("key_decisions") or [],
    }
    for k in REQUIRED_LIST:
        if not isinstance(seg[k], list):
            raise TypeError(f"{k} must be a list, got {type(seg[k])}")

    def _do() -> dict:
        doc, _ = _load_doc(latest, Path(project_root).resolve())
        sid = _resolve_session_id(Path(project_root).resolve(), doc, session_id, for_save=True)
        if sid is None:
            return {
                "status": "error",
                "message": f"无法推断当前窗口：请传 --session-id，或确认 {cp / ACTIVE_SESSION_FILE} 存在"
                           f"（由钩子写入）后重试",
            }
        windows = doc.setdefault("windows", {})
        prev = windows.get(sid)
        if prev is not None and _seg_hash(prev) == _seg_hash(seg):
            return {"status": "unchanged", "session_id": sid, "message": "内容未变化，不写入"}
        windows[sid] = seg
        doc["updated_at"] = _now()
        _atomic_write(latest, doc)
        hist = _write_window_history(Path(project_root).resolve(), sid, seg)
        return {
            "status": "saved",
            "session_id": sid,
            "path": str(latest),
            "history": str(hist),
        }

    return _with_lock(latest, _do)


def load(project_root: str, session_id: str = "", flat: bool = False) -> dict:
    """读取 checkpoint。flat=True 时输出旧 v1 扁平形状（本窗口段优先，无则 legacy）。"""
    latest = Path(project_root) / CHECKPOINT_DIR / LATEST_FILE
    doc, migrated = _load_doc(latest, Path(project_root).resolve())
    if migrated:
        # 读到旧扁平结构：迁移写盘（锁 + 原子），保证"旧文件迁移后完整"
        _with_lock(latest, lambda: _atomic_write(latest, doc))

    windows = doc.get("windows") or {}
    sid = _resolve_session_id(Path(project_root).resolve(), doc, session_id, for_save=False)
    window = windows.get(sid) if sid else None
    others = [
        {
            "session_id": k,
            "title": (v or {}).get("title", ""),
            "updated_at": (v or {}).get("updated_at", ""),
            "current_task": (v or {}).get("current_task", ""),
        }
        for k, v in windows.items()
        if k != sid
    ]
    others.sort(key=lambda o: str(o.get("updated_at") or ""), reverse=True)
    if flat:
        # 消费方兼容输出：摊平成 v1 扁平形状（本窗口段优先，无则 legacy）
        src = window if window is not None else (doc.get("legacy") or {})
        return {
            "status": "ok",
            "project": doc.get("project", Path(project_root).resolve().name),
            "schema": doc.get("schema", SCHEMA),
            "timestamp": (src.get("updated_at") or src.get("timestamp") or ""),
            "title": src.get("title", ""),
            "current_task": src.get("current_task", ""),
            "completed_steps": src.get("completed_steps") or [],
            "pending_tasks": src.get("pending_tasks") or [],
            "key_decisions": src.get("key_decisions") or [],
        }
    return {
        "status": "ok",
        "project": doc.get("project", Path(project_root).resolve().name),
        "schema": doc.get("schema", SCHEMA),
        "session_id": sid or "",
        "window": window,
        # window_missing: 该会话还没有窗口段（≠ 没有数据，legacy 可能仍有）
        "window_missing": bool(sid) and window is None,
        "others": others,
        "legacy": doc.get("legacy"),
    }


def list_windows(project_root: str) -> dict:
    doc, _ = _load_doc(Path(project_root) / CHECKPOINT_DIR / LATEST_FILE, Path(project_root).resolve())
    windows = doc.get("windows") or {}
    rows = [
        {
            "session_id": k,
            "title": (v or {}).get("title", ""),
            "updated_at": (v or {}).get("updated_at", ""),
            "current_task": (v or {}).get("current_task", ""),
        }
        for k, v in windows.items()
    ]
    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return {"status": "ok", "schema": doc.get("schema", SCHEMA), "windows": rows,
            "archived_count": len(doc.get("archived_windows") or {}),
            "has_legacy": "legacy" in doc}


def _parse_iso(s: str):
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def compact(project_root: str, prune_windows_days: int | None = 30) -> dict:
    """清理：按窗口历史保留最近 MAX_WINDOW_HISTORY 份；旧 v1 扁平历史保留 MAX_LEGACY_HISTORY 份；
    prune_windows_days 非空且 >0 时，把超过该天数未更新的窗口段移入 archived_windows
    （保留内容、移出活跃视图，防孤儿段只增不减；默认 30，对齐 trash_ttl_days，传 0 关闭）。
    返回 {removed, archived}。latest.json 与活跃会话标记不动。"""
    cp = _ensure_dir(project_root)
    removed: list[str] = []
    archived: list[str] = []

    hdir = cp / HISTORY_DIR
    if hdir.is_dir():
        for wdir in hdir.iterdir():
            if not wdir.is_dir():
                continue
            files = sorted(wdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[MAX_WINDOW_HISTORY:]:
                removed.append(str(old.relative_to(cp)))
                old.unlink(missing_ok=True)

    # 旧 v1 扁平历史（_checkpoint 根下非 latest/lock/precompact/active-session 的 .json）
    flat = [f for f in cp.iterdir()
            if f.is_file() and f.name != LATEST_FILE and f.suffix == ".json"
            and not f.name.startswith("precompact_") and f.name != ACTIVE_SESSION_FILE]
    flat.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in flat[MAX_LEGACY_HISTORY:]:
        removed.append(old.name)
        old.unlink(missing_ok=True)

    # 超期未更新窗口段 → archived_windows（保留内容，移出活跃视图）
    if prune_windows_days and prune_windows_days > 0:
        latest = cp / LATEST_FILE
        doc, _ = _load_doc(latest, Path(project_root).resolve())
        windows = doc.get("windows") or {}
        if windows:
            cutoff = datetime.now(timezone.utc) - timedelta(days=prune_windows_days)
            arch = doc.setdefault("archived_windows", {})
            stale = []
            for sid, seg in list(windows.items()):
                ts = _parse_iso(str((seg or {}).get("updated_at") or ""))
                if ts is None or ts < cutoff:
                    stale.append(sid)
            for sid in stale:
                arch[sid] = windows.pop(sid)
                archived.append(sid)
            if stale:
                doc["updated_at"] = _now()
                _atomic_write(latest, doc)

    return {"removed": removed, "archived": archived}


def remove_window(project_root: str, session_id: str) -> dict:
    """显式删除一个窗口段（及其历史目录）。仅凭 --session-id 精确删除，内容不可恢复——确需再删。"""
    cp = _ensure_dir(project_root)
    latest = cp / LATEST_FILE

    def _do() -> dict:
        doc, _ = _load_doc(latest, Path(project_root).resolve())
        windows = doc.get("windows") or {}
        if session_id not in windows:
            return {"status": "not_found", "session_id": session_id, "message": "未找到该窗口段"}
        seg = windows.pop(session_id)
        doc["updated_at"] = _now()
        _atomic_write(latest, doc)
        hdir = cp / HISTORY_DIR / session_id
        gone: list[str] = []
        if hdir.is_dir():
            for f in hdir.glob("*.json"):
                gone.append(f.name)
                f.unlink(missing_ok=True)
            try:
                hdir.rmdir()
            except OSError:
                pass
        return {"status": "removed", "session_id": session_id,
                "title": (seg or {}).get("title", ""), "history_removed": gone}

    return _with_lock(latest, _do)


def _json_list(s: str):
    if not s:
        return []
    try:
        v = json.loads(s)
        if isinstance(v, list):
            return v
        return [str(v)]
    except json.JSONDecodeError:
        return [x.strip() for x in s.split(",") if x.strip()]


def main():
    parser = argparse.ArgumentParser(description="FileGuard Checkpoint Manager (v2 multi-window)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser("save")
    p_save.add_argument("--project", "-p", required=True)
    p_save.add_argument("--current-task", default="")
    p_save.add_argument("--completed-steps", type=_json_list, default=[])
    p_save.add_argument("--pending-tasks", type=_json_list, default=[])
    p_save.add_argument("--key-decisions", type=_json_list, default=[])
    p_save.add_argument("--title", default="")
    p_save.add_argument("--session-id", default="")

    p_load = sub.add_parser("load")
    p_load.add_argument("--project", "-p", required=True)
    p_load.add_argument("--session-id", default="")
    p_load.add_argument("--flat", action="store_true", help="输出旧 v1 扁平形状（本窗口段优先，无则 legacy）")

    p_compact = sub.add_parser("compact")
    p_compact.add_argument("--project", "-p", required=True)
    p_compact.add_argument("--prune-windows-days", type=int, default=30,
                           help="超过该天数未更新的窗口段移入 archived_windows（0=关闭）")

    p_remove = sub.add_parser("remove-window")
    p_remove.add_argument("--project", "-p", required=True)
    p_remove.add_argument("--session-id", required=True)

    p_windows = sub.add_parser("windows")
    p_windows.add_argument("--project", "-p", required=True)

    args = parser.parse_args()

    if args.cmd == "save":
        r = save(args.project, session_id=args.session_id,
                 current_task=args.current_task, completed_steps=args.completed_steps,
                 pending_tasks=args.pending_tasks, key_decisions=args.key_decisions,
                 title=args.title)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "load":
        print(json.dumps(load(args.project, session_id=args.session_id, flat=args.flat),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "compact":
        print(json.dumps({"status": "compacted", **compact(args.project, args.prune_windows_days)},
                         ensure_ascii=False, indent=2))
    elif args.cmd == "remove-window":
        print(json.dumps(remove_window(args.project, args.session_id), ensure_ascii=False, indent=2))
    elif args.cmd == "windows":
        print(json.dumps(list_windows(args.project), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
