#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 扫描客户端下所有受管项目，出就绪度清单

数据源（无需手动登记）:
    1. 受管中央登记表 D:\\comate\\_rules\\managed-projects.json（status=active 自动纳入）
    2. 本工具 data/release-manifest.json 的 registered[]（补充登记未纳入受管的项目）

对每个项目调 scripts/audit.py --json，汇总为就绪度看板:
    READY   = 无 FAIL，可直接发版
    FIXABLE = 仅存在 fix.py 可自动修复的 FAIL
    BLOCKED = 存在不可自动修复的 FAIL

用法:
    python scripts/scan.py [--json] [--register <项目根> [--repo owner/repo]]

退出码: 0 = 无 BLOCKED；1 = 存在 BLOCKED。
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from _paths import PROJ_ROOT, managed_projects_path, manifest_path  # noqa: E402

AUDIT = PROJ_ROOT / "scripts" / "audit.py"


def load_manifest() -> dict:
    p = manifest_path()
    if not p.is_file():
        return {"version": 1, "updated": str(date.today()), "registered": [], "releases": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(m: dict):
    m["updated"] = str(date.today())
    manifest_path().write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def managed_roots() -> list:
    """受管登记表 active 项目 → (root, type)。"""
    p = managed_projects_path()
    if not p.is_file():
        print(f"[WARN] 受管登记表缺失: {p}（只扫描补充登记）")
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] 受管登记表不可解析: {e}")
        return []
    return [(Path(pr["root"]), pr.get("type", "")) for pr in data.get("projects", [])
            if pr.get("status") == "active" and Path(pr["root"]).is_dir()]


def registered_roots(manifest: dict) -> list:
    """补充登记（未纳入受管的项目）→ root。"""
    return [Path(r["root"]) for r in manifest.get("registered", [])]


def audit_one(root: Path):
    r = subprocess.run([sys.executable, str(AUDIT), str(root), "--json", "--fix-hint"],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and not r.stdout:
        return {"root": str(root), "error": r.stderr.strip() or "audit 执行失败"}
    return json.loads(r.stdout)


def classify(results: list) -> str:
    fails = [x for x in results if x["status"] == "FAIL"]
    if not fails:
        return "READY"
    if all(x["fixable"] for x in fails):
        return "FIXABLE"
    return "BLOCKED"


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 发版就绪度扫描")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--register", metavar="项目根", help="补充登记一个项目（未纳入受管时）")
    ap.add_argument("--repo", default="", help="登记时指定目标仓库 owner/repo")
    args = ap.parse_args()

    manifest = load_manifest()

    if args.register:
        rp = Path(args.register).resolve()
        if not rp.is_dir():
            print(f"[FAIL] 目录不存在: {rp}")
            return 1
        regs = manifest["registered"]
        if not any(r["root"] == str(rp) for r in regs):
            regs.append({"root": str(rp), "repo": args.repo, "added": str(date.today())})
            save_manifest(manifest)
            print(f"[OK] 已补充登记: {rp}")
        else:
            print(f"[SKIP] 已在补充登记中: {rp}")

    roots = managed_roots()
    reg_roots = [(rp, "") for rp in registered_roots(manifest)]
    print(f"[INFO] 受管项目 {len(roots)} 个 + 补充登记 {len(reg_roots)} 个，逐个审计...\n")

    rows = []
    for root, ptype in roots + reg_roots:
        data = audit_one(root)
        if "error" in data:
            rows.append({"root": data["root"], "type": ptype, "ver": "-", "verdict": "ERROR", "fail": data["error"]})
            continue
        res = data["results"]
        fails = [x for x in res if x["status"] == "FAIL"]
        verdict = classify(res)
        missing = [x["code"] for x in fails]
        meta_v = "-"
        for x in res:
            if x["code"] == "A2" and x["status"] == "PASS":
                meta_v = x["message"].split("v")[-1]
        rows.append({"root": data["root"], "type": ptype, "ver": meta_v,
                     "verdict": verdict, "fail": missing})

    if args.json:
        print(json.dumps({"projects": rows,
                          "summary": {"ready": sum(1 for r in rows if r["verdict"] == "READY"),
                                      "fixable": sum(1 for r in rows if r["verdict"] == "FIXABLE"),
                                      "blocked": sum(1 for r in rows if r["verdict"] in ("BLOCKED", "ERROR"))}},
                         ensure_ascii=False, indent=2))
    else:
        print("=== 发版就绪度看板 ===")
        print(f"{'项目':<42} {'类型':<9} {'版本':<8} 结论")
        for r in rows:
            name = r["root"].replace("\\", "/").rstrip("/").split("/")[-1]
            fails = ",".join(r["fail"]) if r["fail"] else "-"
            print(f"{name:<42} {r['type'] or '-':<9} {r['ver']:<8} {r['verdict']:<8} {fails}")
        s = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("READY", "FIXABLE", "BLOCKED")}
        print(f"\n--- 汇总: READY {s['READY']} / FIXABLE {s['FIXABLE']} / BLOCKED {s['BLOCKED']} ---")
        print("下一步: 对 FIXABLE 跑 fix.py；对 BLOCKED 看 fail 列逐项处理；READY 直接 publish.py")

    blocked = any(r["verdict"] in ("BLOCKED", "ERROR") for r in rows)
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
