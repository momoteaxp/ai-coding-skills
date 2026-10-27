#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 发版补齐/纠正（fix）

缺哪个补哪个：按模板生成缺失的 README.md（英文）/ README.zh-CN.md（中文）/
LICENSE（MIT），并支持版本行对齐。绝不覆盖已有内容（已存在一律 SKIP 并提示）。

用法:
    python scripts/fix.py <项目根> [--version X.Y.Z] [--check-only]

流程: 读 meta + config → 生成缺失文件 → 自动复检 audit.py → 汇总。
退出码: 0 = 全部补齐/无缺项；1 = 存在不可自动修复项。
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from _paths import config_path, templates_dir  # noqa: E402

EN_TEMPLATE = "README.en.md"
ZH_TEMPLATE = "README.zh-CN.md"
MIT_TEMPLATE = "LICENSE-MIT"


def load_config() -> dict:
    p = config_path()
    if not p.is_file():
        print(f"[WARN] 配置缺失: {p}（使用默认值）")
        return {"github": {}, "license": {"spdx": "MIT", "holder": ""}}
    return json.loads(p.read_text(encoding="utf-8"))


def render(template: str, ctx: dict) -> str:
    tpl = templates_dir() / template
    if not tpl.is_file():
        raise FileNotFoundError(f"模板缺失: {tpl}")
    text = tpl.read_text(encoding="utf-8")
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def make(root: Path, rel: str, content: str, check_only: bool, created: list, skipped: list, force: bool = False):
    p = root / rel
    if p.exists():
        if not force:
            skipped.append(rel)
            return
        if check_only:
            print(f"  [WOULD-REPLACE] {rel}（旧文件移入 _trash）")
            created.append(f"{rel}(replace)")
            return
        trash = root / "_trash"
        trash.mkdir(exist_ok=True)
        p.replace(trash / f"{rel.replace('/', '_')}.{date.today().strftime('%Y%m%d')}.bak")
        print(f"  [BACKUP] {rel} -> _trash/")
    if check_only:
        print(f"  [WOULD-CREATE] {rel}")
        created.append(rel)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    print(f"  [CREATED] {rel}")
    created.append(rel)


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 发版补齐/纠正")
    ap.add_argument("root", help="项目根目录")
    ap.add_argument("--version", default="", help="版本号（对齐 README 版本行用）")
    ap.add_argument("--check-only", action="store_true", help="只预览将创建的文件")
    ap.add_argument("--force-readme", action="store_true", help="用模板重写 README（旧文件移入 _trash）")
    ap.add_argument("--no-recheck", action="store_true", help="补齐后不自动复检（供构建区调用）")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 目录不存在: {root}")
        return 1

    meta_p = root / "project_meta.json"
    if not meta_p.is_file():
        print(f"[FAIL] 缺 project_meta.json（先回填受管身份，fix.py 不代造）")
        return 1
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    cfg = load_config()

    mirrors = "\n".join(f"- {m}" for m in cfg.get("china_network", {}).get("download_mirrors", []))
    mirrors = mirrors.replace("{owner}", cfg.get("github", {}).get("owner", "")).replace(
        "{repo}", cfg.get("github", {}).get("default_repo") or root.name)

    def pick(key: str, default: str, en: bool = False) -> str:
        if en:
            return meta.get(f"{key}_en") or meta.get(key) or default
        return meta.get(key) or default

    def bullet(value, default: str) -> str:
        if isinstance(value, list) and value:
            return "\n".join(f"- {x}" for x in value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    def client_display() -> str:
        v = meta.get("clients") or meta.get("client")
        if isinstance(v, list):
            return " / ".join(str(x) for x in v if x) or "Any"
        return str(v) if v else "Any"

    def client_badge() -> str:
        v = meta.get("clients") or meta.get("client")
        first = v[0] if isinstance(v, list) and v else (v or "Any")
        slug = re.sub(r"[^a-z0-9]+", "-", str(first).lower()).strip("-")
        return slug or "any"

    base = {
        "name": meta.get("name", root.name),
        "label": meta.get("label", meta.get("name", root.name)),
        "type": meta.get("type", "software"),
        "version": args.version or meta.get("version", "0.1.0"),
        "license": cfg.get("license", {}).get("spdx", "MIT"),
        "owner": cfg.get("github", {}).get("owner", "your-github-username"),
        "repo": cfg.get("github", {}).get("default_repo") or root.name,
        "holder": cfg.get("license", {}).get("holder", "your-name"),
        "year": str(date.today().year),
        "mirrors": mirrors,
        "platform": pick("platform", "Any"),
        "client": client_display(),
        "client_badge": client_badge(),
        "tree": meta.get("structure") or "（待补充：目录结构）",
    }

    ctx_zh = dict(base)
    ctx_zh.update({
        "description": pick("description", "（待补充描述）"),
        "tagline": pick("tagline", pick("description", "")),
        "audience": pick("audience", "（待补充：适合谁使用）"),
        "features": bullet(meta.get("features"), "（待补充：3-5 条核心特性）"),
        "highlights": bullet(meta.get("highlights"), "（待补充：与同类相比的独特价值）"),
        "quickstart": pick("quickstart", "（待补充：3-4 步跑通）"),
        "usage": pick("usage", "（待补充：使用方法与示例）"),
        "requirements": pick("requirements", "（待补充：操作系统 / 依赖 / 权限）"),
    })

    ctx_en = dict(base)
    ctx_en.update({
        "description": pick("description", "（TBD: one-line description）", en=True),
        "tagline": pick("tagline", pick("description", "", True), en=True),
        "audience": pick("audience", "（TBD: who is it for）", en=True),
        "features": bullet(meta.get("features_en") or meta.get("features"), "（TBD: 3-5 key features）"),
        "highlights": bullet(meta.get("highlights_en") or meta.get("highlights"), "（TBD: why this one）"),
        "quickstart": pick("quickstart", "（TBD: quick start in 3-4 steps）", en=True),
        "usage": pick("usage", "（TBD: usage and examples）", en=True),
        "requirements": pick("requirements", "（TBD: OS / dependencies / permissions）", en=True),
    })

    print(f"=== 发版补齐: {root} ===")
    print(f"目标: {base['name']} v{base['version']}（{base['label']}）\n")

    created, skipped = [], []

    # 1. 英文 README（开源门面主文档）
    try:
        make(root, "README.md", render(EN_TEMPLATE, ctx_en), args.check_only, created, skipped,
             force=args.force_readme)
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        return 1

    # 2. 中文 README（GitHub 语言自动切换）
    make(root, "README.zh-CN.md", render(ZH_TEMPLATE, ctx_zh), args.check_only, created, skipped,
         force=args.force_readme)

    # 3. LICENSE（MIT）
    make(root, "LICENSE", render(MIT_TEMPLATE, ctx_zh), args.check_only, created, skipped)

    # 4. 版本行对齐（仅当 README 头部未标 vX.Y.Z 且用户显式给了 --version）
    readme_p = root / "README.md"
    if args.version and readme_p.exists():
        head = "\n".join(readme_p.read_text(encoding="utf-8", errors="replace").splitlines()[:15])
        if f"v{args.version}" not in head:
            if args.check_only:
                print(f"  [WOULD-FIX] README.md 头部补版本行 v{args.version}")
                created.append("README.md(版本行)")
            else:
                text = readme_p.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                for i, ln in enumerate(lines[:8]):
                    if ln.startswith("# "):
                        lines.insert(i + 1, f"\n> Version: v{args.version}")
                        break
                readme_p.write_text("\n".join(lines), encoding="utf-8")
                print(f"  [FIXED] README.md 头部补版本行 v{args.version}")

    print(f"\n--- 结果: 创建/修复 {len(created)} 个，已存在跳过 {len(skipped)} 个 ---")
    for rel in skipped:
        print(f"  [SKIP] {rel} 已存在（不覆盖）")

    if created and not args.check_only and not args.no_recheck:
        print("\n--- 自动复检 ---")
        import subprocess
        r = subprocess.run([sys.executable, str(Path(__file__).parent / "audit.py"), str(root)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r.stdout)
        return r.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
