#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""register-data.py — 登记数据/资料目录（不建骨架、不建 checkpoint、不装 tools）

用途：用户明确说“某某目录是素材/资料目录”时使用。
只做两件事：
1. 确保目录有一个最小 project_meta.json（type=data, managed=false, checkpoint_enabled=false）
2. 写进中央登记表 managed-projects.json（type=data），让 D5/D11/D12/ignore-gen/audit 跳过它

不创建：_checkpoint、tools、README、docs、.gitignore、.comateignore、git 仓库。

用法:
    python register-data.py --path "D:\\my-data"
    python register-data.py --path "D:\\my-data" --create
    python register-data.py --path "D:\\已有目录" --force   # 已有 meta 时只加 managed:false/checkpoint_enabled:false
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _fg_home() -> Path:
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))


def _norm(p: str) -> str:
    return os.path.normpath(os.path.abspath(str(p))).replace("\\", "/").lower().rstrip("/")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description="登记数据/资料目录（跳过骨架/checkpoint/管理）")
    ap.add_argument("--path", "-p", required=True, help="数据/资料目录（绝对路径）")
    ap.add_argument("--create", action="store_true", help="目录不存在时创建")
    ap.add_argument("--force", action="store_true", help="已有 project_meta.json 时，只加 managed:false/checkpoint_enabled:false")
    ap.add_argument("--note", default="", help="登记表备注")
    args = ap.parse_args()

    path = Path(args.path).expanduser()
    if not path.is_absolute():
        print(f"[FAIL] 请传绝对路径: {path}", file=sys.stderr)
        return 2
    if not path.exists():
        if not args.create:
            print(f"[FAIL] 目录不存在: {path}（确认要创建请加 --create）", file=sys.stderr)
            return 1
        path.mkdir(parents=True, exist_ok=True)

    meta_p = path / "project_meta.json"
    if meta_p.is_file():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[FAIL] 已有 project_meta.json 无法解析，拒绝覆盖: {e}", file=sys.stderr)
            return 1
        if not args.force:
            print(f"[FAIL] 已有 project_meta.json: {meta_p}；确认它是数据目录请加 --force（只加 managed:false/checkpoint_enabled:false，不改 type）", file=sys.stderr)
            return 1
        meta["managed"] = False
        meta["checkpoint_enabled"] = False
        meta.setdefault("type", "data")
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 已标记为数据目录（保留原 type/字段）: {meta_p}")
    else:
        meta = {
            "name": path.name,
            "label": "数据/资料目录",
            "type": "data",
            "managed": False,
            "checkpoint_enabled": False,
            "version": "0.0.0",
            "dirs": {},
            "root_file_name_rule": ".*",
            "read_only_files": [],
            "read_only_dirs": [],
            "strict_mode": False,
            "note": "数据/资料目录：不生成骨架/checkpoint/tools；由 register-data.py 登记",
        }
        _write_json(meta_p, meta)
        print(f"[OK] 最小 project_meta.json -> {meta_p}")

    reg_p = _fg_home() / "_rules" / "managed-projects.json"
    try:
        reg = json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.is_file() else {"version": 1, "projects": []}
    except Exception:
        reg = {"version": 1, "projects": []}
    projects = reg.setdefault("projects", [])
    entry = next((p for p in projects if _norm(str(p.get("root") or "")) == _norm(str(path))), None)
    note = args.note or "数据/资料目录（跳过骨架/checkpoint/管理）"
    if entry is None:
        projects.append({
            "root": str(path),
            "type": "data",
            "category": "data",
            "window": "",
            "status": "active",
            "since": date.today().isoformat(),
            "note": note,
        })
        action = "registered"
    else:
        entry.update({"type": "data", "category": "data", "window": "", "status": "active", "note": note})
        action = "updated"
    reg["updated"] = date.today().isoformat()
    _write_json(reg_p, reg)
    print(f"[OK] 登记表 {action}: {reg_p}")
    print(f"[OK] 数据目录已登记，不生成骨架/checkpoint/.comateignore: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
