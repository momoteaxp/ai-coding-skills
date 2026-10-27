#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — 重启前全链路一致性检查

检查本套件的不变量（2026-10-23 独立化完成）：

    R1 doctor.py D1-D12 全绿（插件挂载/钩子/核心复用/规则/登记/L3/L4/环境变量/版本/.comateignore/漏网项目/进度体系）
    R2 版本一致: plugin.json.version == project_meta.json.version
    R3 git 状态: 工作树 clean（有未提交改动则提醒，不阻断）
    R4 L4 comate 计划任务 3 个均已注册
    R5 规则文件存在且可解析（D:\\comate\\_rules\\global-rules.json，comate 独立规则）

用法: python scripts/pre-reboot-check.py
退出码: 0 = 全部通过；1 = 存在失败项（重启前应修复）
"""
import json
import os
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJ_ROOT = Path(__file__).parent.parent.resolve()
COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or r"D:\comate")
FAILS: list[str] = []


def ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"[FAIL] {msg}")


def main() -> int:
    print("=" * 70)
    print(" FileGuard (Comate) 重启前全链路一致性检查")
    print("=" * 70)

    # R1 doctor 全绿
    r = subprocess.run([sys.executable, str(PROJ_ROOT / "scripts" / "doctor.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode == 0:
        ok("R1 doctor.py D1-D12 全绿")
    else:
        fail("R1 doctor.py 存在失败项（见上）")

    # R2 版本一致
    try:
        mv = json.loads((PROJ_ROOT / "project_meta.json").read_text(encoding="utf-8")).get("version")
        pv = json.loads((PROJ_ROOT / "plugin.json").read_text(encoding="utf-8")).get("version")
        if mv == pv:
            ok(f"R2 版本一致: plugin.json={pv} == project_meta.json={mv}")
        else:
            fail(f"R2 版本不一致: plugin.json={pv} vs project_meta.json={mv}")
    except Exception as e:
        fail(f"R2 版本读取异常: {e}")

    # R3 git 状态
    r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=PROJ_ROOT)
    if r.stdout.strip():
        fail(f"R3 工作树有未提交改动（{len(r.stdout.splitlines())} 项）：重启前建议提交或暂存")
    else:
        ok("R3 工作树 clean")

    # R4 L4 comate 计划任务
    names = ["Comate Placement Guard", "Comate Placement Guard - ScanOnce", "Comate Placement Guard - Watchdog"]
    missing = []
    for n in names:
        q = subprocess.run(["schtasks", "/query", "/tn", n, "/fo", "LIST"],
                           capture_output=True, text=True, errors="replace")
        if q.returncode != 0:
            missing.append(n)
    if missing:
        fail(f"R4 L4 计划任务缺失: {missing}（跑 register-comate-guard-task.ps1）")
    else:
        ok("R4 L4 comate 计划任务 3 个均已注册")

    # R5 规则文件存在且可解析（comate 独立规则）
    rc = COMATE_FG_HOME / "_rules" / "global-rules.json"
    try:
        if rc.is_file():
            json.loads(rc.read_text(encoding="utf-8"))
            ok(f"R5 规则文件存在且可解析（comate 独立规则: {rc}）")
        else:
            fail(f"R5 规则文件缺失: {rc}")
    except Exception as e:
        fail(f"R5 规则文件检查异常: {e}")

    print()
    if FAILS:
        print(f"结果: {len(FAILS)} 个失败项（重启前应修复）", file=sys.stderr)
        return 1
    print("结果: 全部通过，可安全重启")
    return 0


if __name__ == "__main__":
    sys.exit(main())
