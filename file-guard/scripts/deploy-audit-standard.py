#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把“项目开发审计标准”下发到登记表内的受管项目。

用法:
    python scripts/deploy-audit-standard.py                 # 默认 dry-run，只报告
    python scripts/deploy-audit-standard.py --apply         # 实际写入
    python scripts/deploy-audit-standard.py --project <名称或根> [--apply]
    python scripts/deploy-audit-standard.py --force         # 覆盖项目已改过的同名文件
    python scripts/deploy-audit-standard.py --include-kb    # 连 kb 项目也发（默认跳过）

规则:
- 跳过套件自身、kb/data 项目；
- 项目没有 docs 目录（或 meta.dirs 未登记 docs）→ 跳过并报告；
- 目标不存在 → 复制；
- 目标已存在且内容相同 → 跳过；
- 目标已存在但不同 → 备份到 _trash/backup_audit-standard_<时间戳>/ 后跳过；
  只有 --force 才覆盖；
- 不修改 project_meta.json，不改任何代码。
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import rules_dir  # noqa: E402

SUITE_ROOT = Path(__file__).resolve().parent.parent
REGISTRY = rules_dir() / "managed-projects.json"

TEMPLATES = [
    ("templates/开发审计标准.md", "docs/开发审计标准.md"),
    ("templates/审计报告模板.md", "docs/审计报告模板.md"),
]
SKIP_TYPES = {"kb", "data"}
SKIP_CATEGORIES = {"kb"}


def sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def meta_dirs(root: Path) -> set[str]:
    p = root / "project_meta.json"
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    dirs = meta.get("dirs")
    if isinstance(dirs, dict):
        return set(dirs.keys())
    if isinstance(dirs, list):
        return set(str(x) for x in dirs)
    return set()


def backup(root: Path, target: Path, stamp: str) -> Path | None:
    """备份到项目 _trash；_trash 不存在则不备份。"""
    trash = root / "_trash"
    if not trash.is_dir():
        return None
    rel = target.relative_to(root)
    dst = trash / f"backup_audit-standard_{stamp}" / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, dst)
    return dst


def deploy_one(root: Path, dry_run: bool, force: bool, stamp: str) -> list[tuple[str, str, str]]:
    """返回 [(status, rel_path, detail)]。"""
    rows = []
    for src_rel, dst_rel in TEMPLATES:
        src = SUITE_ROOT / src_rel
        dst = root / dst_rel
        if not src.is_file():
            rows.append(("FAIL", dst_rel, f"套件模板缺失: {src}"))
            continue
        src_hash = sha256(src)
        if not dst.exists():
            if dry_run:
                rows.append(("COPY", dst_rel, "目标不存在（dry-run）"))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                rows.append(("COPY", dst_rel, "已复制"))
            continue
        dst_hash = sha256(dst)
        if dst_hash == src_hash:
            rows.append(("SKIP-SAME", dst_rel, "内容一致"))
            continue
        # 内容不同：默认保护项目改动
        bak = None
        if not dry_run:
            bak = backup(root, dst, stamp)
        if not force:
            detail = "内容不同，已备份后跳过（--force 才覆盖）" if bak else "内容不同，项目无 _trash，未备份，跳过（--force 才覆盖）"
            rows.append(("SKIP-DIFF", dst_rel, detail))
            continue
        if dry_run:
            rows.append(("FORCE-COPY", dst_rel, "将覆盖（dry-run）"))
        else:
            if bak is None:
                rows.append(("FAIL", dst_rel, "需要覆盖但无 _trash 可备份；请人工处理"))
                continue
            shutil.copy2(src, dst)
            rows.append(("BACKUP+COPY", dst_rel, f"已备份到 {bak}"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="下发项目开发审计标准")
    ap.add_argument("--apply", action="store_true", help="实际写入；默认 dry-run")
    ap.add_argument("--project", default="", help="只处理指定项目（目录名或根路径）")
    ap.add_argument("--force", action="store_true", help="覆盖项目已改过的同名文件（先备份）")
    ap.add_argument("--include-kb", action="store_true", help="连 kb/data 项目也发")
    args = ap.parse_args()

    if not REGISTRY.is_file():
        print(f"[FAIL] 登记表不存在: {REGISTRY}", file=sys.stderr)
        return 1
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[FAIL] 登记表 JSON 解析失败: {e}", file=sys.stderr)
        return 1

    projects = registry.get("projects") or []
    if not projects:
        print("[FAIL] 登记表没有 projects", file=sys.stderr)
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"== 开发审计标准下发（{mode}）==")
    print(f"套件: {SUITE_ROOT}")
    print(f"登记表: {REGISTRY}")
    print("")

    counts = {"COPY": 0, "SKIP-SAME": 0, "SKIP-DIFF": 0, "FORCE-COPY": 0,
              "BACKUP+COPY": 0, "SKIP-KB": 0, "SKIP-NO-DOCS": 0,
              "SKIP-SELF": 0, "SKIP-MISSING": 0, "SKIP-FILTER": 0, "FAIL": 0}

    for p in projects:
        root = Path(str(p.get("root") or ""))
        name = root.name or str(root)
        ptype = str(p.get("type") or "")
        category = str(p.get("category") or "")

        if args.project:
            wanted = args.project.replace("\\", "/").rstrip("/").lower()
            if wanted not in (name.lower(), str(root).replace("\\", "/").rstrip("/").lower()):
                counts["SKIP-FILTER"] += 1
                continue

        if not root.is_dir():
            print(f"[SKIP-MISSING] {name} — 目录不存在: {root}")
            counts["SKIP-MISSING"] += 1
            continue

        try:
            if root.resolve() == SUITE_ROOT.resolve():
                print(f"[SKIP-SELF] {name} — 套件自身（模板源）: {root}")
                counts["SKIP-SELF"] += 1
                continue
        except OSError:
            pass

        if not args.include_kb and (ptype in SKIP_TYPES or category in SKIP_CATEGORIES):
            print(f"[SKIP-KB] {name} — {root} — type={ptype or '?'} category={category or '?'}（--include-kb 可发）")
            counts["SKIP-KB"] += 1
            continue

        dirs = meta_dirs(root)
        if "docs" not in dirs or not (root / "docs").is_dir():
            print(f"[SKIP-NO-DOCS] {name} — {root} — 无 docs 目录/白名单")
            counts["SKIP-NO-DOCS"] += 1
            continue

        print(f"[PROJECT] {name} ({ptype or '?'}) — {root}")
        rows = deploy_one(root, dry_run=not args.apply, force=args.force, stamp=stamp)
        for status, rel, detail in rows:
            print(f"  [{status}] {rel} — {detail}")
            counts[status] = counts.get(status, 0) + 1

    print("")
    print("== 汇总 ==")
    for k in ("COPY", "BACKUP+COPY", "FORCE-COPY", "SKIP-SAME", "SKIP-DIFF",
              "SKIP-KB", "SKIP-NO-DOCS", "SKIP-SELF", "SKIP-MISSING", "FAIL"):
        if counts.get(k):
            print(f"  {k}: {counts[k]}")
    if not args.apply:
        print("\n这是 dry-run；确认后加 --apply 实际写入。")
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
