#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换机自检（隔离环境模拟安装）

用途：在隔离的 USERPROFILE + 受管根下，对发布副本执行安装/自检/建项目，
发现"换台电脑能不能用"的问题。不触碰当前真实环境。

用法:
    python scripts/clean_test.py <发布副本目录> [--json]

退出码: 0 = 模拟完成（无论有无 FAIL）；1 = 前置条件缺失。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJ_ROOT = Path(__file__).resolve().parent.parent
BASE = PROJ_ROOT / "_build" / "clean-test"


def run(cmd, cwd, env, timeout=120):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              cwd=str(cwd), env=env, timeout=timeout)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def main() -> int:
    ap = argparse.ArgumentParser(description="换机自检（隔离模拟）")
    ap.add_argument("suite", help="发布副本目录（publish-ready/<产品>）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    suite = Path(args.suite).resolve()
    if not suite.is_dir():
        print(f"[FAIL] 目录不存在: {suite}")
        return 1
    deploy = suite / "scripts" / "deploy.ps1"
    doctor = suite / "scripts" / "doctor.py"
    init = suite / "scripts" / "init.py"
    if not deploy.is_file() or not doctor.is_file() or not init.is_file():
        print("[SKIP] 该产品不是套件型（缺 deploy.ps1/doctor.py/init.py），跳过换机模拟")
        return 0

    base = BASE / suite.name
    if base.exists():
        shutil.rmtree(base)
    (base / "profile").mkdir(parents=True)
    (base / "root").mkdir(parents=True)
    suite_copy = base / "suite" / suite.name
    shutil.copytree(suite, suite_copy)

    env = dict(os.environ)
    env["USERPROFILE"] = str(base / "profile")
    env["COMATE_FG_HOME"] = str(base / "root")
    env["FG_HOME"] = str(base / "root")

    result = {"suite": str(suite), "deploy": None, "doctor_fails": [],
              "init_ok": False, "notes": []}

    d = run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(suite_copy / "scripts" / "deploy.ps1"),
             "-FgHome", str(base / "root"), "-NonInteractive", "-NoEnvPersist"], base, env)
    result["deploy"] = d.returncode
    print(f"[DEPLOY] exit={d.returncode}")

    dr = run([sys.executable, str(suite_copy / "scripts" / "doctor.py")], base, env)
    fails = [ln.strip() for ln in (dr.stdout or "").splitlines() if "[FAIL]" in ln]
    result["doctor_fails"] = fails
    for f in fails:
        print(f"[FAIL] {f}")

    if init.is_file():
        ir = run([sys.executable, str(suite_copy / "scripts" / "init.py"), "demo",
                  "--type", "skill", "--root", str(base / "root" / "products")], base, env)
        result["init_ok"] = (base / "root" / "products" / "demo" / "project_meta.json").is_file()
        print(f"[INIT] exit={ir.returncode} project_created={result['init_ok']}")

    result["notes"].append("D7 计划任务为机器级检查，隔离环境无法真实验证")
    (base / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[SUMMARY] deploy={result['deploy']} doctor_fails={len(fails)} init_ok={result['init_ok']}")
        print(f"[INFO] 详细结果: {base / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
