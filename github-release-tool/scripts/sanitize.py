#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 发版前净化审核（S1-S6）

目的：公开源码前，检查"能不能给别人看/用"。纯正则 + 词表，无 AI。
FAIL 阻塞发布；WARN 需人工确认（可加入 config.sanitize.allow_paths 静默）。

用法:
    python scripts/sanitize.py <项目根> [--json]

检查项:
    S1 产物/缓存混入（zip/exe/log/db/pyc 等散落在源码树）
    S2 盘符/绝对路径（D:\\... /Users/... /home/... %USERPROFILE%）
    S3 跨套件引用（file-guard / FG_HOME / D:\\comate 等，需声明依赖或内联）
    S4 黑名单词（config.sanitize.denylist：公司名/人名/内部文件名）
    S5 README 结构（特性/快速开始/环境要求/联系 小节）
    S6 敏感文件（.env / key / pem / credentials 等）
退出码: 0 = 无 FAIL；1 = 存在 FAIL。
"""
import argparse
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from _paths import PROJ_ROOT, config_path  # noqa: E402

EXCLUDE_DIRS = {".git", "_trash", "_scratch", "_checkpoint", "node_modules",
                "__pycache__", "release", "output", "data", "backup", "archive",
                ".pytest_cache", ".comate"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".exe",
              ".msi", ".pdf", ".docx", ".pptx", ".xlsx", ".db", ".pyc", ".so",
              ".dll", ".woff", ".woff2", ".ttf", ".7z", ".gz", ".tar"}
ARTIFACT_EXT = {".zip", ".exe", ".msi", ".log", ".db", ".pyc", ".7z", ".tar", ".gz"}

ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]:[\\/][^\s\"'`<>|]*)")
HOME_PATH_RE = re.compile(r"(/Users/[^\s\"'`]+|/home/[^\s\"'`]+|%USERPROFILE%|\$HOME/)")
CROSS_RE = re.compile(r"(file-guard|FileGuard|FG_HOME|D:\\\\?comate)", re.IGNORECASE)
SENSITIVE_NAME = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "credentials*.json",
    "secrets.*", "id_rsa", "id_ed25519", "*.npmrc", "*.p8",
]

SECTION_PATTERNS = {
    "README.md": [("Features", "## Features"), ("Quick Start", "## Quick Start"),
                  ("Requirements", "## Requirements"), ("Contact", "## Contact")],
    "README.zh-CN.md": [("核心特性", "## 核心特性"), ("快速开始", "## 快速开始"),
                        ("环境要求", "## 环境要求"), ("联系", "## 反馈与联系")],
}


def item(code, status, message):
    return {"code": code, "status": status, "message": message}


def load_config() -> dict:
    p = config_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def iter_text_files(root: Path, allow_paths: list):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in BINARY_EXT:
            continue
        if any(fnmatch(str(rel).replace("\\", "/"), pat) for pat in allow_paths):
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        yield rel, p, text


def scan_lines(text: str, regex, limit: int = 15):
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if regex.search(line):
            hits.append((i, line.strip()[:120]))
            if len(hits) >= limit:
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 发版前净化审核")
    ap.add_argument("root", help="项目根目录")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 目录不存在: {root}", file=sys.stderr)
        return 1

    cfg = load_config()
    san = cfg.get("sanitize", {}) or {}
    allow_paths = san.get("allow_paths", []) or []
    denylist = [w for w in (san.get("denylist", []) or []) if w]
    meta = {}
    try:
        meta = json.loads((root / "project_meta.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    self_name = meta.get("name", "")
    results = []

    # S1 产物/缓存混入
    art = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in ARTIFACT_EXT:
            art.append(str(rel).replace("\\", "/"))
    if art:
        results.append(item("S1", "WARN", f"源码树发现产物/缓存 {len(art)} 个（发布时会排除，但建议清理）: {art[:8]}"))
    else:
        results.append(item("S1", "PASS", "无产物/缓存混入"))

    # S2 盘符/绝对路径
    abs_hits = []
    for rel, p, text in iter_text_files(root, allow_paths):
        for ln, line in scan_lines(text, ABS_PATH_RE, 3):
            abs_hits.append(f"{rel}:{ln}: {line}")
        for ln, line in scan_lines(text, HOME_PATH_RE, 3):
            abs_hits.append(f"{rel}:{ln}: {line}")
    if abs_hits:
        results.append(item("S2", "WARN", f"发现绝对路径 {len(abs_hits)} 处（公开前建议改相对路径/配置项）:\n      " + "\n      ".join(abs_hits[:10])))
    else:
        results.append(item("S2", "PASS", "无盘符/绝对路径"))

    # S3 跨套件引用
    self_key = (self_name or "").lower().replace("-", "").replace("_", "")
    cross = []
    for rel, p, text in iter_text_files(root, allow_paths):
        for ln, line in scan_lines(text, CROSS_RE, 3):
            norm = line.lower().replace("-", "").replace("_", "")
            if self_key and self_key in norm:
                continue
            cross.append(f"{rel}:{ln}: {line}")
    if cross:
        results.append(item("S3", "WARN", f"发现跨套件引用 {len(cross)} 处（需在 README 声明依赖，或把规则内联）:\n      " + "\n      ".join(cross[:10])))
    else:
        results.append(item("S3", "PASS", "无跨套件引用"))

    # S4 黑名单词
    deny_hits = []
    for rel, p, text in iter_text_files(root, allow_paths):
        low = text.lower()
        for w in denylist:
            if w.lower() in low:
                for ln, line in scan_lines(text, re.compile(re.escape(w), re.IGNORECASE), 2):
                    deny_hits.append(f"{rel}:{ln}: {line}")
    if deny_hits:
        results.append(item("S4", "FAIL", f"命中黑名单词 {len(deny_hits)} 处（必须脱敏后再发布）:\n      " + "\n      ".join(deny_hits[:10])))
    else:
        results.append(item("S4", "PASS", f"无黑名单词命中（词表 {len(denylist)} 个）"))

    # S5 README 结构
    missing = []
    for readme, checks in SECTION_PATTERNS.items():
        p = root / readme
        if not p.is_file():
            missing.append(f"{readme} 不存在")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for label, heading in checks:
            if heading not in text:
                missing.append(f"{readme} 缺小节「{label}」")
    if missing:
        results.append(item("S5", "WARN", f"README 结构不完整（fix.py 可生成模板）: {missing}"))
    else:
        results.append(item("S5", "PASS", "README 结构完整（特性/快速开始/环境要求/联系）"))

    # S6 敏感文件
    sens = []
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        name = p.name.lower()
        if any(fnmatch(name, pat.lower()) for pat in SENSITIVE_NAME):
            sens.append(str(rel).replace("\\", "/"))
    if sens:
        results.append(item("S6", "FAIL", f"发现敏感文件 {len(sens)} 个（禁止公开）: {sens[:8]}"))
    else:
        results.append(item("S6", "PASS", "无敏感文件"))

    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]

    if args.json:
        print(json.dumps({"root": str(root), "results": results,
                          "pass": len(results) - len(fails) - len(warns),
                          "warn": len(warns), "fail": len(fails)}, ensure_ascii=False, indent=2))
    else:
        print(f"=== 净化审核: {root} ===")
        for r in results:
            mark = {"PASS": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r["status"]]
            print(f"{mark} {r['code']} {r['message']}")
        print(f"--- 汇总: PASS {len(results)-len(fails)-len(warns)} / WARN {len(warns)} / FAIL {len(fails)} ---")
        print("结论: " + ("可公开（WARN 需人工确认）" if not fails else "存在阻塞项，脱敏后再发布"))

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
