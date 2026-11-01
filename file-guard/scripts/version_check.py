#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — 版本一致性校验（发版门禁 + doctor D9 共用）

背景（2026-10-22 反馈）：发版时文档版本行（如 SKILL.md metadata.version）未与
project_meta.json 同步导致版本漂移（other-project v0.2.1 事件；同类遗漏历史
已有记录）。版本规范要求"文档版本行全部与 meta 同步"但缺校验器——本模块补上。

功能:
    check: 登记"版本行文件清单"，正则提取各文件版本号与 project_meta.json 对比，
           不一致即 FAIL 并列出差异文件与当前值（build-release 门禁 / doctor D9）。
    sync:  把清单内各文件的版本行改写为指定版本（bump 时自动调用，防漂移）。

清单语义:
    - path 相对项目根；regex 第 1 组 = 版本号（仅数字段，替换安全）
    - 文件不存在 → 跳过（新项目骨架未生成时容忍）
    - 文件存在但提取不到版本行 → FAIL（登记即声明其必须携带版本行，或从清单移除）
    - C0 global-rules.json 刻意不在清单：其 version 独立演进，
      comate 套件版本（v0.2.0）与之不同属正常，不参与比对

用法:
    python scripts/version_check.py [--project <项目根>]        # 校验（exit 0/1）
    python scripts/version_check.py --sync <版本> [--project <项目根>]  # 同步版本行
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Windows 中文环境：三件套 UTF-8（任何调用方式下不因 GBK 崩溃）
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SEMVER = r"(\d+\.\d+\.\d+(?:\+build\.\d+)?)"

# 文档版本行：只认 v 前缀或 版本/version 关键字 + 可选标记字符，避免误命中正文裸版本号
# （如 "Comate 4.13.4"、"Python 3.11"）；实测格式："> 版本：v0.2.2" / "- 当前版本：`v0.2.2`"
DOC_VERSION_RE = r"(?:v\s*|版本\s*[:：]?\s*|version\s*[:：]?\s*)[`'\" ]*" + SEMVER

# 版本行文件清单（新增带版本的文件时在此登记；regex 第 1 组须为纯版本号）
# 2026-10-23 P2c 泛化：移除硬编码 skills/fileguard-doctor，改为 skills/*/SKILL.md 通配
#（skill 版本行可选：无版本行跳过不判 FAIL，有则须与 meta 一致）
# 2026-10-26 回灌：README.md/_索引.md/docs/README.md 纳入（strict=False 可选语义——
# 有版本行须一致、无则跳过）；DOC_VERSION_RE 只认 v 前缀或 版本/version 关键字，
# 避免误命中正文里裸版本号（如 "Comate 4.13.4"）
VERSION_SOURCES = [
    {"path": "project_meta.json", "regex": r'"version"\s*:\s*"' + SEMVER + r'"', "label": "project_meta.json（真源）"},
    {"path": "plugin.json", "regex": r'"version"\s*:\s*"' + SEMVER + r'"', "label": "plugin.json"},
    {"path": "README.md", "regex": DOC_VERSION_RE, "label": "README.md（版本行可选）", "strict": False},
    {"path": "README.zh-CN.md", "regex": DOC_VERSION_RE, "label": "README.zh-CN.md（版本行可选）", "strict": False},
    {"path": "_索引.md", "regex": DOC_VERSION_RE, "label": "_索引.md（版本行可选）", "strict": False},
    {"path": "docs/README.md", "regex": DOC_VERSION_RE, "label": "docs/README.md（版本行可选）", "strict": False},
]
SKILL_MD_RE = r"^version\s*:\s*\"?v?" + SEMVER


def _skill_md_files(root: Path) -> list:
    """技能入口 SKILL.md：项目根 SKILL.md（skill/docgen 型）+ skills/*/SKILL.md（套件内嵌）。"""
    files = [root / "SKILL.md"] if (root / "SKILL.md").is_file() else []
    files += sorted(root.glob("skills/*/SKILL.md"))
    return files


def _first_version(text: str, regex: str) -> str | None:
    m = re.search(regex, text, re.MULTILINE)
    return m.group(1) if m else None


def check_version_consistency(project_root: str | Path) -> tuple[bool, list[str]]:
    """校验清单内各文件版本号与 project_meta.json 一致。返回 (ok, 明细)。"""
    root = Path(project_root)
    meta_path = root / "project_meta.json"
    if not meta_path.is_file():
        return False, [f"[FAIL] 未找到 project_meta.json: {meta_path}"]
    try:
        expected = str(json.loads(meta_path.read_text(encoding="utf-8")).get("version", ""))
    except Exception as e:
        return False, [f"[FAIL] project_meta.json 解析失败: {e}"]
    if not re.fullmatch(SEMVER, expected):
        return False, [f"[FAIL] project_meta.json version 格式异常: {expected!r}"]

    msgs: list[str] = []
    ok = True

    def _check_one(p: Path, regex: str, label: str, strict: bool) -> None:
        nonlocal ok
        if not p.is_file():
            msgs.append(f"  [skip] {label} 不存在（未生成，跳过）")
            return
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            ok = False
            msgs.append(f"  [FAIL] {label} 读取失败: {e}")
            return
        found = _first_version(text, regex)
        if found is None:
            if strict:
                ok = False
                msgs.append(f"  [FAIL] {label} 未找到版本行（登记即须携带版本，或从清单移除）")
            else:
                msgs.append(f"  [skip] {label} 无版本行（skill 版本可选，跳过）")
        elif found != expected:
            ok = False
            msgs.append(f"  [FAIL] {label} 版本 {found} ≠ meta {expected}")
        else:
            msgs.append(f"  [OK]   {label} = {found}")

    for src in VERSION_SOURCES:
        _check_one(root / src["path"], src["regex"], src.get("label", src["path"]),
                   strict=src.get("strict", True))
    for p in _skill_md_files(root):
        _check_one(p, SKILL_MD_RE, f"SKILL.md ({p.parent.name})", strict=False)
    return ok, msgs


def sync_version_lines(project_root: str | Path, new_version: str) -> list[str]:
    """把清单内各文件版本行改写为 new_version（project_meta.json 真源除外，由调用方写）。
    仅替换第一个匹配的版本号段；无版本行的文件不动（留给校验器提示）。返回变更文件列表。"""
    root = Path(project_root)
    changed: list[str] = []
    for src in VERSION_SOURCES:
        if src["path"] == "project_meta.json":
            continue
        p = root / src["path"]
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(src["regex"], text, re.MULTILINE)
        if not m:
            continue
        new_text = text[:m.start(1)] + new_version + text[m.end(1):]
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(src["path"])
    for p in _skill_md_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(SKILL_MD_RE, text, re.MULTILINE)
        if not m:
            continue
        new_text = text[:m.start(1)] + new_version + text[m.end(1):]
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(str(p.relative_to(root)))
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard (Comate) 版本一致性校验/同步")
    ap.add_argument("--project", "-p", default=str(Path(__file__).resolve().parent.parent),
                    help="项目根目录（默认：本脚本所在项目的根，即 tools/..）")
    ap.add_argument("--sync", metavar="VERSION", help="把清单内版本行同步为指定版本（project_meta.json 除外）")
    args = ap.parse_args()

    if args.sync:
        if not re.fullmatch(SEMVER, args.sync):
            print(f"[FAIL] 版本格式异常: {args.sync!r}（须 X.Y.Z）", file=sys.stderr)
            return 1
        changed = sync_version_lines(args.project, args.sync)
        print(f"[OK] 已同步 {len(changed)} 个文件: {', '.join(changed) or '(无变更)'}")
        return 0

    ok, msgs = check_version_consistency(args.project)
    print(f"版本一致性校验（项目根: {Path(args.project).resolve()}）")
    for m in msgs:
        print(m)
    print("[PASS] 版本一致" if ok else "[FAIL] 存在版本不一致", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
