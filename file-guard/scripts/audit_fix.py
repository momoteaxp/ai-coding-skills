#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计修复闸门：把“审计建议”变成可校验、可回滚的代码化流程。

用法:
    # 1) 预检：逐条判断可修/不可修；只有可修放行
    python scripts/audit_fix.py precheck --project <项目根> --findings <审计发现.json> [--out-plan <计划.json>]

    # 2) 应用：默认 dry-run；--write 才落盘
    python scripts/audit_fix.py apply --project <项目根> --plan <计划.json> [--patch <补丁>] [--write]

    # 3) 回滚：从备份目录恢复
    python scripts/audit_fix.py rollback --project <项目根> --backup <备份目录> [--patch <补丁>]

设计:
- 审计只读；本工具只处理“项目内可修”（白名单内、非只读、非套件分发件）。
- 只读/配置、目录/骨架、套件分发件、全局规则 → 不可修，只列原因，不硬改。
- 应用前：git apply --check + 路径归属校验 + 备份到 _trash。
- 应用后：跑 verify_commands + enforcer + audit；失败自动回滚。
- 不 commit、不 push、不删除备份。
"""
import argparse
import fnmatch
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SUITE_ROOT = Path(__file__).resolve().parent.parent

# 套件分发件：项目里的这些副本由套件统一升级，本地改会被覆盖 → D 类
SUITE_OWNED = {
    "tools/_paths.py",
    "tools/checkpoint-manager.py",
    "tools/trash-cli.py",
    "tools/git-watchdog.py",
    "tools/version_check.py",
    "tools/build-release.py",
    "docs/开发审计标准.md",
    "docs/审计报告模板.md",
    "docs/版本管理规范.md",
    ".git/hooks/pre-commit",
}
READ_ONLY_HINTS = {"project_meta.json", "_索引.md", "README.md", "docs/README.md", "plugin.json"}
BLOCK_ORDER = {"B": 1, "C": 2, "D": 3, "E": 4}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def norm_rel(project: Path, raw: str) -> str | None:
    """把路径规范成项目内 POSIX 相对路径；越界/绝对路径返回 None。"""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().replace("\\", "/")
    p = Path(s)
    if p.is_absolute():
        try:
            s = str(p.resolve().relative_to(project.resolve())).replace("\\", "/")
        except Exception:
            return None
    s = posixpath.normpath(s)
    if s in (".", "") or s.startswith("../") or s == "..":
        return None
    return s


def meta_of(project: Path) -> dict | None:
    p = project / "project_meta.json"
    if not p.is_file():
        return None
    try:
        d = load_json(p)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def dir_keys(meta: dict) -> list[str]:
    dirs = meta.get("dirs")
    if isinstance(dirs, dict):
        return [str(k) for k in dirs]
    if isinstance(dirs, list):
        return [str(k) for k in dirs]
    return []


def dir_exts(meta: dict, key: str) -> list[str] | None:
    dirs = meta.get("dirs")
    if isinstance(dirs, dict):
        v = dirs.get(key)
        return [str(x) for x in v] if isinstance(v, list) else []
    return []


def find_dir(meta: dict, parent: str) -> str | None:
    keys = dir_keys(meta)
    hits = [k for k in keys if parent == k or parent.startswith(k + "/")]
    if not hits:
        return None
    return max(hits, key=len)


def match_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) or name == p for p in patterns)


def classify_target(project: Path, meta: dict, raw: str) -> tuple[str | None, str]:
    """返回 (阻断类型 or None, 说明)。None 表示可作为“项目内可修”目标。"""
    rel = norm_rel(project, raw)
    if rel is None:
        return "E", "目标为空、越界或不在项目内"
    if rel == "_checkpoint" or rel.startswith("_checkpoint/"):
        return "B", "checkpoint 禁止直接写；请用 tools/checkpoint-manager.py"
    if rel == "_trash" or rel.startswith("_trash/"):
        return "B", "_trash 禁止直接写；请用 trash-cli.py"
    if rel == "_rules" or rel.startswith("_rules/"):
        return "E", "全局规则；改 C0 影响所有项目"
    if rel in SUITE_OWNED or rel.startswith(".git/hooks/"):
        return "D", "套件分发件；本地改会被下一次分发覆盖，请回上游"
    ro = meta.get("read_only_files") or []
    if isinstance(ro, list) and match_any(rel, [str(x) for x in ro]):
        return "B", "命中 read_only_files；需用户确认"
    if rel in READ_ONLY_HINTS:
        return "B", "配置/索引/README；需用户确认并同步派生位置"
    if rel == "SKILL.md" and str(meta.get("type") or "").lower() == "skill":
        return None, "SKILL.md 是 skill 项目主文件，可作为可修目标"

    parent = posixpath.dirname(rel)
    base = posixpath.basename(rel)
    if base.startswith("."):
        return "B", "隐藏配置文件；需确认并同步派生位置"
    if parent == "":
        rule = str(meta.get("root_file_name_rule") or r"^(README|LICENSE|project_meta|_索引|_trash)")
        try:
            allowed = bool(re.search(rule, base))
        except re.error:
            allowed = False
        if allowed:
            return "B", "根级文件；改动需同步文档/索引"
        return "C", "根级散件；需先补 root_file_name_rule 或移入白名单目录"

    key = find_dir(meta, parent)
    if key is None:
        return "C", f"目录 {parent} 未在 project_meta.dirs 登记；需走骨架/登记流程"
    exts = dir_exts(meta, key)
    if exts and not match_any(base, exts):
        return "B", f"扩展名不在 {key} 白名单；需先改 project_meta.json"
    return None, "OK"


def classify_finding(project: Path, meta: dict, f: dict) -> tuple[str | None, str]:
    """按目标路径自动判定；AI 不需要手标 A-E。"""
    targets = f.get("targets")
    if not isinstance(targets, list) or not targets:
        targets = [f.get("file")] if f.get("file") else []
    if not targets:
        return "B", "缺少目标文件"
    blocks = []
    for t in targets:
        b, why = classify_target(project, meta, str(t))
        if b:
            blocks.append((b, f"{t}: {why}"))
    if not blocks:
        return None, "OK"
    # 取最严格的一类
    b, why = max(blocks, key=lambda x: BLOCK_ORDER.get(x[0], 0))
    return b, why


def cmd_precheck(args) -> int:
    project = Path(args.project).resolve()
    meta = meta_of(project)
    if meta is None:
        print(f"[FAIL] 未找到/无法解析 project_meta.json: {project}", file=sys.stderr)
        return 2
    try:
        doc = load_json(Path(args.findings))
    except Exception as e:
        print(f"[FAIL] 审计发现 JSON 读取失败: {e}", file=sys.stderr)
        return 2
    findings = doc.get("findings") if isinstance(doc, dict) else doc
    if not isinstance(findings, list):
        print("[FAIL] findings 不是数组", file=sys.stderr)
        return 2

    passed, blocked = [], []
    reasons = {}
    print(f"== 审计修复预检（{project}）==")
    for f in findings:
        fid = str(f.get("id") or "?")
        b, why = classify_finding(project, meta, f)
        if b:
            blocked.append(fid)
            reasons[fid] = why
            print(f"[BLOCKED] {fid} {f.get('title', '')[:60]} — {why}")
        else:
            passed.append(fid)
            print(f"[FIXABLE] {fid} {f.get('title', '')[:60]}")

    if args.out_plan:
        plan = {
            "project": str(project),
            "findings_json": str(Path(args.findings).resolve()),
            "findings": passed,
            "blocked": reasons,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        out = Path(args.out_plan)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[OK] 可执行计划已写出: {out}")

    print(f"\n汇总: 可修={len(passed)} 不可修={len(blocked)}")
    if blocked:
        print("不可修项只列出来，不要硬改：只读/配置需确认，套件件需上游，全局规则需改 C0。")
        return 1
    return 0


def cmd_context(args) -> int:
    project = Path(args.project).resolve()
    meta = meta_of(project)
    if meta is None:
        print(f"[FAIL] 未找到/无法解析 project_meta.json: {project}", file=sys.stderr)
        return 2
    data = {
        "project": str(project),
        "type": meta.get("type"),
        "dirs": meta.get("dirs") if isinstance(meta.get("dirs"), (dict, list)) else {},
        "read_only_files": meta.get("read_only_files") or [],
        "suite_owned": sorted(SUITE_OWNED),
        "root_file_name_rule": meta.get("root_file_name_rule") or r"^(README|LICENSE|project_meta|_索引|_trash)",
        "checkpoint": {
            "read": "本项目 latest.json 允许 read_file/grep_content/list_dir 直接读；规范读取优先 load",
            "write": "tools/checkpoint-manager.py save",
            "cross_project": "blocked",
            "scan": "blocked",
        },
        "note": "目标不在白名单 / 命中只读 / 是套件分发件 / 是 C0 → 不可修，只列原因。",
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"== 规则上下文（{project}）==")
        print(f"type: {data['type']}")
        print(f"dirs: {data['dirs']}")
        print(f"read_only_files: {data['read_only_files']}")
        print(f"root_file_name_rule: {data['root_file_name_rule']}")
        print(f"suite_owned: {data['suite_owned']}")
        print(f"checkpoint: {data['checkpoint']}")
        print(f"note: {data['note']}")
    return 0


def parse_patch_paths(text: str) -> set[str]:
    paths = set()
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line[len("diff --git "):].split()
            for p in parts:
                if p.startswith("a/") or p.startswith("b/"):
                    paths.add(p[2:])
        elif line.startswith("+++ ") or line.startswith("--- "):
            p = line[4:].strip()
            if p == "/dev/null":
                continue
            if "\t" in p:
                p = p.split("\t", 1)[0]
            p = p.strip().strip('"')
            if p.startswith("a/") or p.startswith("b/"):
                p = p[2:]
            if p:
                paths.add(p)
    return {posixpath.normpath(p.replace("\\", "/")) for p in paths if p}


def run(cmd, cwd: Path, timeout: int = 600):
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def audit_p0(project: Path) -> int | None:
    audit = SUITE_ROOT / "scripts" / "audit.py"
    if not audit.is_file():
        return None
    rc, out, err = run([sys.executable, str(audit), "--project", str(project)], project)
    m = re.search(r"P0=(\d+)", out or "")
    return int(m.group(1)) if m else None


def git_toplevel(project: Path) -> Path | None:
    rc, out, _ = run(["git", "rev-parse", "--show-toplevel"], project)
    if rc != 0 or not out.strip():
        return None
    try:
        return Path(out.strip()).resolve()
    except Exception:
        return None


def backup_files(project: Path, files: list[str], stamp: str) -> Path | None:
    trash = project / "_trash"
    if not trash.is_dir():
        try:
            trash.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    dst_root = trash / f"audit-fix-backup-{stamp}"
    for rel in files:
        src = project / rel
        if not src.is_file():
            continue
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst_root if dst_root.is_dir() else None


def write_log(project: Path, stamp: str, lines: list[str]) -> Path:
    scratch = project / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    out = scratch / f"audit-fix-log-{stamp}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def cmd_apply(args) -> int:
    project = Path(args.project).resolve()
    meta = meta_of(project)
    if meta is None:
        print(f"[FAIL] 未找到/无法解析 project_meta.json: {project}", file=sys.stderr)
        return 2
    try:
        plan = load_json(Path(args.plan))
    except Exception as e:
        print(f"[FAIL] 计划读取失败: {e}", file=sys.stderr)
        return 2

    findings_path = Path(args.findings or plan.get("findings_json") or "")
    if not findings_path.is_file():
        print(f"[FAIL] 审计发现 JSON 不存在: {findings_path}", file=sys.stderr)
        return 2
    doc = load_json(findings_path)
    findings = doc.get("findings") if isinstance(doc, dict) else doc
    by_id = {str(f.get("id")): f for f in findings if isinstance(f, dict)}
    ids = [str(x) for x in (args.ids.split(",") if args.ids else plan.get("findings") or []) if str(x).strip()]
    if not ids:
        print("[FAIL] 计划没有 findings；先用 precheck --out-plan 生成", file=sys.stderr)
        return 2

    selected = []
    for fid in ids:
        f = by_id.get(fid)
        if not f:
            print(f"[FAIL] 发现不存在: {fid}", file=sys.stderr)
            return 2
        b, why = classify_finding(project, meta, f)
        if b:
            print(f"[BLOCKED] {fid} — {why}", file=sys.stderr)
            print("请先处理不可修项；apply 只应用可修项。", file=sys.stderr)
            return 1
        selected.append(f)

    patch_path = Path(args.patch or plan.get("patch") or "")
    if not patch_path.is_file():
        print(f"[FAIL] 补丁不存在: {patch_path}", file=sys.stderr)
        return 2
    patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
    patch_files = parse_patch_paths(patch_text)
    allowed = set()
    for f in selected:
        targets = f.get("targets") or ([f.get("file")] if f.get("file") else [])
        for t in targets:
            rel = norm_rel(project, str(t))
            if rel:
                allowed.add(rel)
    extra = sorted(p for p in patch_files if p not in allowed)
    if extra:
        print(f"[FAIL] 补丁包含未在发现中声明的文件: {extra}", file=sys.stderr)
        return 1
    if not patch_files:
        print("[FAIL] 补丁没有可识别的文件路径", file=sys.stderr)
        return 2

    top = git_toplevel(project)
    if top is None or top != project:
        print(f"[FAIL] 项目不是独立 git 仓库（toplevel={top}）；补丁流程需要独立仓库", file=sys.stderr)
        return 1

    rc, out, err = run(["git", "apply", "--check", "--whitespace=nowarn", str(patch_path)], project)
    print(f"== 审计修复应用（{'WRITE' if args.write else 'DRY-RUN'}）==")
    print(f"项目: {project}")
    print(f"计划: {args.plan}")
    print(f"补丁: {patch_path}")
    print(f"发现: {', '.join(ids)}")
    print(f"目标: {', '.join(sorted(patch_files))}")
    if rc != 0:
        print("[FAIL] git apply --check 失败：", file=sys.stderr)
        print((err or out).strip(), file=sys.stderr)
        return 1
    print("[OK] 补丁可应用")

    if not args.write:
        print("\n这是 dry-run；确认后加 --write 实际应用。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    changed = [p for p in patch_files if (project / p).is_file()]
    bak = backup_files(project, changed, stamp)
    if bak is None:
        print("[FAIL] 无法创建备份（_trash 不可写）；中止", file=sys.stderr)
        return 1
    print(f"[OK] 已备份: {bak}")

    p0_before = None if args.no_audit else audit_p0(project)
    rc, out, err = run(["git", "apply", "--whitespace=nowarn", str(patch_path)], project)
    if rc != 0:
        print("[FAIL] git apply 失败：", file=sys.stderr)
        print((err or out).strip(), file=sys.stderr)
        return 1
    print("[OK] 补丁已应用")

    log = [f"# Audit Fix Log {stamp}", "", f"- project: {project}",
           f"- plan: {args.plan}", f"- patch: {patch_path}",
           f"- findings: {', '.join(ids)}", f"- backup: {bak}", ""]
    failed = False

    for cmd in (plan.get("verify_commands") or []):
        rc, out, err = run(cmd, project, timeout=1200)
        print(f"[{'PASS' if rc == 0 else 'FAIL'}] verify: {cmd}")
        log.append(f"## verify: {cmd}\n- exit={rc}\n- stdout:\n```\n{out[-4000:]}\n```\n- stderr:\n```\n{err[-2000:]}\n```")
        if rc != 0:
            failed = True
            break

    if not failed:
        for rel in sorted(patch_files):
            target = project / rel
            if not target.is_file():
                continue
            rc, out, err = run([sys.executable, str(SUITE_ROOT / "scripts" / "enforcer.py"),
                                "check", str(target), "--project", str(project)], project)
            print(f"[{'PASS' if rc == 0 else 'FAIL'}] enforcer: {rel}")
            log.append(f"## enforcer: {rel}\n- exit={rc}\n- out:\n```\n{(out or err).strip()}\n```")
            if rc != 0:
                failed = True
                break

    if not failed and not args.no_audit:
        p0_after = audit_p0(project)
        print(f"[INFO] audit P0: before={p0_before} after={p0_after}")
        log.append(f"## audit P0\n- before={p0_before} after={p0_after}")
        if p0_after is not None and (p0_before is None or p0_after > p0_before):
            failed = True

    if failed:
        print("[FAIL] 验证失败，回滚...", file=sys.stderr)
        rc, out, err = run(["git", "apply", "-R", "--whitespace=nowarn", str(patch_path)], project)
        rolled = rc == 0
        if not rolled and bak:
            for rel in changed:
                src = bak / rel
                dst = project / rel
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            rolled = True
        log.append(f"## rollback\n- git_apply_reverse_exit={rc}\n- restored_from_backup={rolled}")
        print(f"[{'OK' if rolled else 'FAIL'}] 回滚{'完成' if rolled else '失败，请人工恢复'}；备份保留在 {bak}",
              file=sys.stderr)
        log_path = write_log(project, stamp, log)
        print(f"[INFO] 日志: {log_path}")
        return 1

    log.append("## result\n- SUCCESS")
    log_path = write_log(project, stamp, log)
    print(f"[OK] 应用并通过验证；日志: {log_path}")
    print("未 commit、未 push。请人工复核 diff 后决定是否提交。")
    return 0


def cmd_rollback(args) -> int:
    project = Path(args.project).resolve()
    bak = Path(args.backup).resolve()
    if not bak.is_dir():
        print(f"[FAIL] 备份目录不存在: {bak}", file=sys.stderr)
        return 2
    restored = 0
    for src in bak.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(bak)
        dst = project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored += 1
    print(f"[OK] 已从备份恢复 {restored} 个文件: {bak}")
    print("注意：只恢复备份内文件；补丁新增的文件不会被删除，请人工检查。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="审计修复闸门（可修/不可修 + 补丁应用 + 回滚）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p0 = sub.add_parser("context", help="输出项目规则上下文（给审计/修复用）")
    p0.add_argument("--project", required=True)
    p0.add_argument("--json", action="store_true")

    p1 = sub.add_parser("precheck", help="逐条判断可修/不可修；只有可修放行")
    p1.add_argument("--project", required=True)
    p1.add_argument("--findings", required=True)
    p1.add_argument("--out-plan", default="", help="把 PASS 项写成可执行计划 JSON")

    p2 = sub.add_parser("apply", help="校验并应用可修补丁；默认 dry-run")
    p2.add_argument("--project", required=True)
    p2.add_argument("--plan", required=True)
    p2.add_argument("--findings", default="", help="覆盖计划里的 findings_json")
    p2.add_argument("--ids", default="", help="逗号分隔的 finding id；默认用计划里的")
    p2.add_argument("--patch", default="", help="覆盖计划里的 patch")
    p2.add_argument("--write", action="store_true", help="实际应用（默认 dry-run）")
    p2.add_argument("--no-audit", action="store_true", help="跳过 audit P0 前后对比")

    p3 = sub.add_parser("rollback", help="从备份目录恢复")
    p3.add_argument("--project", required=True)
    p3.add_argument("--backup", required=True)

    args = ap.parse_args()
    if args.cmd == "context":
        return cmd_context(args)
    if args.cmd == "precheck":
        return cmd_precheck(args)
    if args.cmd == "apply":
        return cmd_apply(args)
    if args.cmd == "rollback":
        return cmd_rollback(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
