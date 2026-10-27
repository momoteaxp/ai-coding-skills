#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布副本转换（只作用于 publish-ready 副本，不改原始项目）

用法（由 publish.py 按 config 调用）:
    transforms.apply("remove_kb", staging)
"""
import json
import re
from pathlib import Path


def _strip_kb_text(text: str) -> str:
    # 移除 dirs_meta 里的空知识库目录键
    text = re.sub(r'\s*"知识库[^"]*"\s*:\s*\[\s*\],?', '', text)
    # 移除列表里的知识库目录项
    text = re.sub(r'\s*"知识库[^"]*",', '', text)
    # 文案中的知识库说明
    text = text.replace("（知识库/ 客户数据永不进包）", "（敏感数据永不进包）")
    return text


def remove_kb(staging: Path) -> list:
    """从发布副本移除 kb（知识库）类型与相关目录/文档，保持语法与 JSON 有效。"""
    changed = []

    init = staging / "scripts" / "init.py"
    if init.is_file():
        t = init.read_text(encoding="utf-8")
        # 移除 "kb": { ... }, 整块（4 空格缩进）
        t2 = re.sub(r'\n    "kb": \{.*?\n    \},\n', '\n', t, flags=re.S)
        t2 = t2.replace('TYPE_CATEGORY.update({"ops": "ops", "kb": "kb"})',
                        'TYPE_CATEGORY.update({"ops": "ops"})')
        # 移除 TYPE_LABELS 的 kb 行
        t2 = re.sub(r'\n\s*"kb": "[^"]*",', '', t2)
        t2 = _strip_kb_text(t2)
        if t2 != t:
            init.write_text(t2, encoding="utf-8")
            changed.append("scripts/init.py")

    rules = staging / "rules" / "global-rules.template.json"
    if rules.is_file():
        try:
            d = json.loads(rules.read_text(encoding="utf-8"))
        except Exception:
            d = None
        if d is not None:
            def scrub(obj):
                if isinstance(obj, dict):
                    obj.pop("kb", None)
                    for k in list(obj.keys()):
                        if isinstance(k, str) and k.startswith("知识库"):
                            obj.pop(k, None)
                    for v in obj.values():
                        scrub(v)
                elif isinstance(obj, list):
                    obj[:] = [x for x in obj if not (isinstance(x, str) and x.startswith("知识库"))]
                    for v in obj:
                        scrub(v)
            scrub(d)
            rules.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            changed.append("rules/global-rules.template.json")

    sk = staging / "skills" / "new-project" / "SKILL.md"
    if sk.is_file():
        t = sk.read_text(encoding="utf-8")
        t2 = "\n".join(ln for ln in t.splitlines()
                       if "知识库" not in ln and "`kb`" not in ln and "notes型（kb）" not in ln)
        if t2 != t:
            sk.write_text(t2, encoding="utf-8")
            changed.append("skills/new-project/SKILL.md")

    # 帮助文本/注释里的 kb 类型字样
    for rel in ["scripts/init.py", "scripts/new-project.py",
                "skills/takeover-project/SKILL.md"]:
        p = staging / rel
        if not p.is_file():
            continue
        t = p.read_text(encoding="utf-8")
        t2 = t.replace("software/skill/suite/web/docgen/ops/kb",
                       "software/skill/suite/web/docgen/ops")
        t2 = t2.replace("software|skill|suite|web|docgen|ops|kb",
                        "software|skill|suite|web|docgen|ops")
        t2 = t2.replace("（kb 型用 `_checkpoint` 即可、无 docs）", "（按类型取舍）")
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            if rel not in changed:
                changed.append(rel)

    vc = staging / "scripts" / "version_check.py"
    if vc.is_file():
        t = vc.read_text(encoding="utf-8")
        t2 = t.replace("KB 项目实测格式", "实测格式")
        if t2 != t:
            vc.write_text(t2, encoding="utf-8")
            changed.append("scripts/version_check.py")

    print(f"[OK] remove_kb: {changed or '无变更'}")
    return changed


TRANSFORMS = {"remove_kb": remove_kb}


def apply(name: str, staging: Path):
    fn = TRANSFORMS.get(name)
    if not fn:
        print(f"[WARN] 未知转换: {name}")
        return []
    return fn(staging)
