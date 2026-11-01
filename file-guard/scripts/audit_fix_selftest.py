#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_fix.py 自测：precheck 分类 + apply + rollback。

用法:
    python scripts/audit_fix_selftest.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SUITE = Path(__file__).resolve().parent.parent
TOOL = SUITE / "scripts" / "audit_fix.py"
PY = sys.executable


def run_tool(args: list[str], cwd: Path | None = None):
    return subprocess.run([PY, str(TOOL), *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def git(proj: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(proj), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def fail(msg: str, r=None):
    print(f"[FAIL] {msg}")
    if r is not None:
        print("--- stdout ---")
        print(r.stdout)
        print("--- stderr ---")
        print(r.stderr)
    return 1


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fg-audit-fix-"))
    proj = tmp / "proj"
    for d in ("src", "docs", "tools", "_trash"):
        (proj / d).mkdir(parents=True, exist_ok=True)

    meta = {
        "name": "audit-fix-test",
        "type": "software",
        "version": "0.1.0",
        "dirs": {"src": ["*.py"], "docs": ["*.md"], "tools": ["*.py"], "_trash": [], "_scratch": []},
        "read_only_files": ["docs/README.md", "_索引.md"],
        "root_file_name_rule": "^(README|project_meta|_索引)",
    }
    (proj / "project_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (proj / "src" / "x.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (proj / "docs" / "README.md").write_text("# docs\n", encoding="utf-8")
    (proj / "tools" / "checkpoint-manager.py").write_text("# fake\n", encoding="utf-8")
    (proj / "_trash" / ".gitkeep").write_text("", encoding="utf-8")

    findings = {
        "findings": [
            {"id": "F-001", "title": "A", "file": "src/x.py", "change_type": "A"},
            {"id": "F-002", "title": "B", "file": "project_meta.json", "change_type": "A"},
            {"id": "F-003", "title": "D", "file": "tools/checkpoint-manager.py", "change_type": "A"},
            {"id": "F-004", "title": "C", "file": "tests/test_x.py", "change_type": "C"},
            {"id": "F-005", "title": "B", "file": "_trash/x.py", "change_type": "A"},
            {"id": "F-006", "title": "B", "file": "docs/README.md", "change_type": "A"},
            {"id": "F-007", "title": "E", "file": "_rules/global-rules.json", "change_type": "A"},
            {"id": "F-008", "title": "C", "file": "random.txt", "change_type": "A"},
            {"id": "F-010", "title": "隐藏配置", "file": ".fileguard-sync.json", "change_type": "B"},
            {"id": "F-011", "title": "隐藏配置2", "file": ".gitignore", "change_type": "A"},
        ]
    }
    fjson = tmp / "findings.json"
    fjson.write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    r = run_tool(["precheck", "--project", str(proj), "--findings", str(fjson), "--out-plan", str(tmp / "plan.json")])
    if r.returncode != 1 or "可修=1 不可修=9" not in r.stdout:
        return fail("precheck 结果不符合预期（应为 可修=1 不可修=9, exit=1）", r)
    print("[PASS] precheck 可修/不可修分类")

    for args in (("init",), ("config", "user.email", "test@example.com"),
                 ("config", "user.name", "test"), ("add", "."),
                 ("commit", "--no-verify", "-m", "init")):
        g = git(proj, *args)
        if g.returncode != 0:
            return fail(f"git {' '.join(args)} 失败", g)

    patch = tmp / "fix.patch"
    patch.write_text(
        "diff --git a/src/x.py b/src/x.py\n"
        "--- a/src/x.py\n"
        "+++ b/src/x.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a + b\n"
        "+    return a - b\n",
        encoding="utf-8",
    )
    plan = json.loads((tmp / "plan.json").read_text(encoding="utf-8"))
    plan["patch"] = str(patch)
    plan["verify_commands"] = [f'"{PY}" src/x.py']
    (tmp / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    r = run_tool(["apply", "--project", str(proj), "--plan", str(tmp / "plan.json"), "--write", "--no-audit"])
    if r.returncode != 0:
        return fail("apply 失败", r)
    if "return a - b" not in (proj / "src" / "x.py").read_text(encoding="utf-8"):
        return fail("apply 后文件内容未变化")
    print("[PASS] apply + 备份 + enforcer")

    baks = sorted((proj / "_trash").glob("audit-fix-backup-*"))
    if not baks:
        return fail("没有找到备份目录")
    r = run_tool(["rollback", "--project", str(proj), "--backup", str(baks[0])])
    if r.returncode != 0:
        return fail("rollback 失败", r)
    if "return a + b" not in (proj / "src" / "x.py").read_text(encoding="utf-8"):
        return fail("rollback 后文件未恢复")
    print("[PASS] rollback")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
