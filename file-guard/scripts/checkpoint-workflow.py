#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard checkpoint 分发工作流

把标准版 scripts/checkpoint-manager.py 分发到项目（新建 / 接手 / 升级同一套步骤）:
1. 读目标 project_meta.json，判断是否适用（kb/data/disabled 跳过）
2. 复制标准版 → <项目>/tools/checkpoint-manager.py（覆盖 = 升级）
3. 确保 <项目>/_checkpoint/ 存在
4. 确保 project_meta.json 的 dirs.tools / dirs._checkpoint 白名单存在
5. 编译检查复制品

不修改 checkpoint 数据；旧 v2 windows 由运行时 load 自动取最近段。

用法:
  python scripts/checkpoint-workflow.py --project <项目根>
  python scripts/checkpoint-workflow.py --all
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Windows 中文环境：强制 stdout/stderr UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SUITE_ROOT = Path(__file__).resolve().parent.parent
SOURCE = SUITE_ROOT / "scripts" / "checkpoint-manager.py"


def fg_home() -> Path:
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))


def _read_meta(proj: Path) -> dict | None:
    p = proj / "project_meta.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _disabled_reason(meta: dict) -> str:
    ptype = str(meta.get("type") or "").strip().lower()
    if ptype in ("kb", "data"):
        return f"type={ptype}"
    cp = meta.get("checkpoint_enabled", True)
    if cp is False or str(cp).strip().lower() == "false":
        return "checkpoint_enabled=false"
    if meta.get("managed") is False:
        return "managed=false"
    return ""


def _ensure_meta_dirs(meta_path: Path, meta: dict) -> bool:
    """补 tools/_checkpoint 白名单；只补缺，不重写其它字段。返回是否改动。"""
    required = {"tools": ["*.py"], "_checkpoint": ["*.json"]}
    dirs = meta.get("dirs")
    changed = False
    if isinstance(dirs, dict):
        for key, exts in required.items():
            if key not in dirs:
                dirs[key] = list(exts)
                changed = True
    elif isinstance(dirs, list):
        for key in required:
            if key not in dirs:
                dirs.append(key)
                changed = True
    else:
        return False
    if changed:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def distribute(proj: Path, meta: dict | None = None) -> dict:
    """分发到单个项目；不碰数据。返回 {action, project, ...}。"""
    proj = proj.resolve()
    meta_path = proj / "project_meta.json"
    if meta is None:
        meta = _read_meta(proj)
    if meta is None:
        return {"action": "skipped", "project": proj.name, "reason": "no project_meta.json"}
    reason = _disabled_reason(meta)
    if reason:
        return {"action": "skipped", "project": proj.name, "reason": reason}
    if not SOURCE.is_file():
        return {"action": "failed", "project": proj.name, "reason": f"missing source {SOURCE}"}

    (proj / "tools").mkdir(parents=True, exist_ok=True)
    (proj / "_checkpoint").mkdir(parents=True, exist_ok=True)
    dst = proj / "tools" / "checkpoint-manager.py"
    shutil.copy2(SOURCE, dst)

    # 编译检查（不生成 __pycache__）
    try:
        compile(dst.read_text(encoding="utf-8"), str(dst), "exec")
    except Exception as e:
        return {"action": "failed", "project": proj.name, "reason": f"compile {dst}: {e}"}

    meta_updated = _ensure_meta_dirs(meta_path, meta)
    return {
        "action": "installed",
        "project": proj.name,
        "root": str(proj),
        "manager": str(dst),
        "meta_updated": meta_updated,
    }


def _registry_projects() -> list[Path]:
    p = fg_home() / "_rules" / "managed-projects.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return [Path(x.get("root", "")) for x in d.get("projects", []) if x.get("root")]
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard checkpoint 分发工作流")
    ap.add_argument("--project", "-p", default="", help="项目根")
    ap.add_argument("--all", action="store_true", help="分发登记表内全部适用项目")
    args = ap.parse_args()
    if not args.project and not args.all:
        ap.error("必须指定 --project <项目根> 或 --all")

    targets = _registry_projects() if args.all else [Path(args.project)]
    if not targets:
        print("[FAIL] 没有可分发项目", file=sys.stderr)
        return 1
    failed = 0
    seen = set()
    for proj in targets:
        key = str(proj.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        if not proj.is_dir():
            print(f"[SKIP] {proj}（目录不存在）")
            continue
        r = distribute(proj)
        act = r.get("action")
        if act == "installed":
            extra = "，meta 白名单已补" if r.get("meta_updated") else ""
            print(f"[OK]   {r['project']}: tools/checkpoint-manager.py + _checkpoint/{extra}")
        elif act == "skipped":
            print(f"[SKIP] {r['project']}: {r.get('reason')}")
        else:
            failed += 1
            print(f"[FAIL] {r['project']}: {r.get('reason')}", file=sys.stderr)
    print(f"\n结果: {len(seen) - failed} 成功/跳过，{failed} 失败")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
