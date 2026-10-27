#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 发版资格审计（A1-A11）

对单个受管项目做发版前资格检查，输出每项 PASS/FAIL/WARN 与修复建议。
纯代码执行，无 AI 参与；是发布流水线的前置门禁（publish.py 调用）。

用法:
    python scripts/audit.py <项目根> [--json]
    python scripts/audit.py <项目根> --fix-hint    # 附带 fix.py 可自动修复的标记

退出码: 0 = 无 FAIL（WARN 不阻塞）；1 = 存在 FAIL（不可发）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from _paths import manifest_path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
SENSITIVE = [
    ".env", "*.env", "*.env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "credentials.json", "credentials*.json", "secrets.*", "secrets*.json",
    "id_rsa", "id_ed25519", "*.npmrc", "*.p8",
]
EXCLUDE_DIRS = {".git", "_trash", "_checkpoint", "node_modules", "__pycache__"}


def item(code, status, message, fixable=False, fix=None):
    return {"code": code, "status": status, "message": message,
            "fixable": fixable, "fix": fix}


def run(cmd, cwd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def has_meta(root: Path):
    p = root / "project_meta.json"
    if not p.is_file():
        return item("A1", "FAIL", "缺 project_meta.json（受管身份凭证）", fixable=True,
                    fix="fix.py 可创建占位 meta；或走接管审计回填")
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return item("A1", "FAIL", f"project_meta.json 不可解析: {e}", fixable=False)
    return item("A1", "PASS", f"project_meta.json 有效（name={meta.get('name')}, type={meta.get('type')}）",
                fixable=False, fix=None)


def version_ok(root: Path):
    p = root / "project_meta.json"
    if not p.is_file():
        return item("A2", "WARN", "无 meta，跳过版本检查", fixable=True)
    try:
        v = json.loads(p.read_text(encoding="utf-8")).get("version", "")
    except Exception:
        return item("A2", "FAIL", "meta 不可解析", fixable=False)
    if not SEMVER_RE.match(v):
        return item("A2", "FAIL", f"版本号非 SemVer（X.Y.Z）: {v!r}", fixable=True,
                    fix="fix.py --version X.Y.Z 对齐")
    return item("A2", "PASS", f"版本号 SemVer 合规: v{v}", fixable=False)


def git_present(root: Path):
    if not (root / ".git").exists():
        return item("A3", "FAIL", "不是 git 仓库（发布需要 git）", fixable=False)
    return item("A3", "PASS", "git 仓库存在", fixable=False)


def git_clean(root: Path):
    r = run(["git", "status", "--porcelain"], root)
    if r.returncode != 0:
        return item("A4", "FAIL", "git status 执行失败", fixable=False)
    dirty = r.stdout.strip()
    if dirty:
        files = dirty.splitlines()
        return item("A4", "FAIL", f"工作树不 clean（{len(files)} 个未提交改动，发版纪律要求 clean）",
                    fixable=True, fix="提交或 stash 后重试")
    return item("A4", "PASS", "工作树 clean", fixable=False)


def tag_matches(root: Path):
    r = run(["git", "tag", "-l", "v*"], root)
    tags = [t for t in r.stdout.split() if t.startswith("v")]
    if not tags:
        return item("A5", "WARN", "尚无 v* tag（首次发版前正常）", fixable=False)
    try:
        meta_v = json.loads((root / "project_meta.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        return item("A5", "WARN", "meta 不可解析，跳过 tag 对齐检查", fixable=False)
    latest = sorted(tags, key=lambda t: [int(x) for x in t[1:].split(".") if x.isdigit()])[-1]
    if latest != f"v{meta_v}":
        return item("A5", "FAIL", f"最新 tag {latest} 与 meta 版本 v{meta_v} 不一致",
                    fixable=False)
    return item("A5", "PASS", f"最新 tag {latest} 与 meta 版本一致", fixable=False)


def readme_en(root: Path):
    if not (root / "README.md").is_file():
        return item("A6", "FAIL", "缺 README.md（英文主文档，开源门面）", fixable=True,
                    fix="fix.py 自动生成")
    return item("A6", "PASS", "README.md 存在", fixable=False)


def readme_zh(root: Path):
    if not (root / "README.zh-CN.md").is_file():
        return item("A7", "FAIL", "缺 README.zh-CN.md（中文说明，GitHub 按语言自动切换）",
                    fixable=True, fix="fix.py 自动生成")
    return item("A7", "PASS", "README.zh-CN.md 存在", fixable=False)


def license_ok(root: Path):
    if not (root / "LICENSE").is_file():
        return item("A8", "FAIL", "缺 LICENSE（开源协议声明）", fixable=True,
                    fix="fix.py 自动生成 MIT")
    return item("A8", "PASS", "LICENSE 存在", fixable=False)


def secrets_scan(root: Path):
    hits = []
    for p in root.rglob("*"):
        if p.is_dir() and p.name in EXCLUDE_DIRS:
            continue
        if not p.is_file() or any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        name = p.name.lower()
        if name in SENSITIVE or any(re.match(s.replace("*", ".*").lower(), name) for s in SENSITIVE):
            hits.append(str(p.relative_to(root)))
    if hits:
        return item("A9", "FAIL", f"检测到敏感文件 {len(hits)} 个（禁止入库发布）: {hits[:5]}",
                    fixable=True, fix="移除或移入 _trash，并加入 .comateignore")
    return item("A9", "PASS", "无敏感文件", fixable=False)


def version_line(root: Path):
    p = root / "README.md"
    if not p.is_file():
        return item("A10", "WARN", "无 README，跳过版本行检查", fixable=True)
    try:
        meta_v = json.loads((root / "project_meta.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        return item("A10", "WARN", "meta 不可解析，跳过", fixable=False)
    head = "\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[:15])
    if f"v{meta_v}" not in head:
        return item("A10", "FAIL", f"README 头部未标注版本 v{meta_v}（发版门面应自报版本）",
                    fixable=True, fix="fix.py 生成或手工补版本行")
    return item("A10", "PASS", f"README 版本行 v{meta_v} 一致", fixable=False)


def assets_present(root: Path):
    meta = {}
    try:
        meta = json.loads((root / "project_meta.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    rel_dir = root / (meta.get("release_dir") or "release")
    zips = sorted(rel_dir.glob("*.zip")) if rel_dir.is_dir() else []
    if zips:
        return item("A11", "PASS", f"源内历史 zip {len(zips)} 个（不参与发布，发布资产由构建区统一打包）",
                    fixable=False)
    return item("A11", "PASS", "源内无历史 zip（发布资产由构建区统一打包）", fixable=False)


def unreleased_changes(root: Path):
    """A12 发版纪律：自上次发布以来源码是否有未发版变更。"""
    try:
        m = json.loads(manifest_path().read_text(encoding="utf-8"))
    except Exception:
        return item("A12", "WARN", "无发布登记，跳过未发版变更检查", fixable=False)
    rels = [r for r in m.get("releases", []) if r.get("root") == str(root) and not r.get("draft")]
    if not rels:
        return item("A12", "WARN", "尚未发布过（首次发版）", fixable=False)

    def key(r):
        v = r.get("version", "0.0.0").split(".")
        return tuple(int(x) if x.isdigit() else 0 for x in v)

    last = max(rels, key=key)
    tag = f"v{last['version']}"
    if not run(["git", "tag", "-l", tag], root).stdout.strip():
        return item("A12", "WARN", f"上次发布 v{last['version']} 的本地 tag 不存在，无法比对", fixable=False)
    d = run(["git", "diff", "--name-only", f"{tag}..HEAD"], root)
    files = [f for f in d.stdout.splitlines() if f.strip()]
    if files:
        return item("A12", "WARN",
                    f"自 v{last['version']} 发布以来有 {len(files)} 个文件未发版 → 下次发版须 --bump（示例: {files[:3]}）",
                    fixable=False)
    return item("A12", "PASS", f"自 v{last['version']} 发布以来无变更", fixable=False)


CHECKS = [
    has_meta, version_ok, git_present, git_clean, tag_matches,
    readme_en, readme_zh, license_ok, secrets_scan, version_line, assets_present,
    unreleased_changes,
]


def audit(root: Path, fix_hint: bool = False) -> list:
    out = []
    for fn in CHECKS:
        it = fn(root)
        if fix_hint and it["fixable"]:
            it["hint"] = it.pop("fix", None)
        out.append(it)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 发版资格审计")
    ap.add_argument("root", help="项目根目录")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--fix-hint", action="store_true", help="标注可自动修复项")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 目录不存在: {root}", file=sys.stderr)
        return 1

    results = audit(root, fix_hint=args.fix_hint)
    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]

    if args.json:
        print(json.dumps({"root": str(root), "results": results,
                          "pass": len(results) - len(fails) - len(warns),
                          "warn": len(warns), "fail": len(fails)}, ensure_ascii=False, indent=2))
    else:
        print(f"=== 发版资格审计: {root} ===")
        for r in results:
            mark = {"PASS": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r["status"]]
            print(f"{mark} {r['code']} {r['message']}")
            if r["status"] == "FAIL" and r.get("hint"):
                print(f"      修复: {r['hint']}")
        print(f"--- 汇总: PASS {len(results)-len(fails)-len(warns)} / WARN {len(warns)} / FAIL {len(fails)} ---")
        if fails:
            print("结论: 未达发版资格（红色项阻塞）")
        else:
            print("结论: 具备发版资格（黄色为提示项，不阻塞）")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
