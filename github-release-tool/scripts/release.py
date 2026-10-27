#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一发布工作流（单一入口）

工序（固定）:
    check    只读诊断源项目（审计 + 净化预检），输出报告
    prepare  生成发布副本 publish-ready/<产品> → 净化 → 打包 → 验证语法/JSON（不上传）
    suggest  生成给对应项目窗口的功能/体验建议报告 + 换机自检
    publish  正式发布（受保险锁约束）
    all      check → prepare → suggest（不上传）
    status   查看保险锁/版本/发布副本状态

用法:
    python scripts/release.py <check|prepare|suggest|publish|all|status> <源项目根>
        [--repo owner/repo] [--draft] [--force] [--skip-clean-test]
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

PROJ = Path(__file__).resolve().parent.parent
PY = sys.executable
PUBLISH = PROJ / "scripts" / "publish.py"
AUDIT = PROJ / "scripts" / "audit.py"
SANITIZE = PROJ / "scripts" / "sanitize.py"
CLEAN = PROJ / "scripts" / "clean_test.py"
READY = PROJ / "publish-ready"
SUGGESTIONS = PROJ / "suggestions"


def run(cmd, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0 and check:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
    return r


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def source_meta(root: Path) -> dict:
    return read_json(root / "project_meta.json")


def project_name(root: Path) -> str:
    return source_meta(root).get("name") or root.name


def load_config() -> dict:
    return read_json(PROJ / "config" / "release-config.json")


def write_report(name: str, kind: str, body: str) -> Path:
    READY.mkdir(parents=True, exist_ok=True)
    p = READY / f"{name}.{kind}.md"
    p.write_text(f"# {name} — {kind}\n\n生成时间：{date.today()}\n\n{body}\n", encoding="utf-8")
    return p


def last_release(root: Path):
    m = read_json(PROJ / "data" / "release-manifest.json")
    rels = [r for r in m.get("releases", []) if r.get("root") == str(root) and not r.get("draft")]
    if not rels:
        return None

    def key(r):
        return tuple(int(x) if x.isdigit() else 0 for x in r.get("version", "0.0.0").split("."))

    return max(rels, key=key)


def cmd_status(args):
    cfg = load_config()
    lock = (cfg.get("publish", {}) or {}).get("enabled", False)
    print(f"保险锁: {'开（可发布）' if lock else '关（只允许 prepare/dry-run）'}")
    gh = cfg.get("github", {}) or {}
    print(f"目标仓库: {gh.get('owner')}/{gh.get('default_repo')}")
    if args.root:
        root = Path(args.root).resolve()
        name = project_name(root)
        ver = source_meta(root).get("version", "?")
        last = last_release(root)
        print(f"产品: {name} | 源版本: {ver} | 上次发布: " + (f"v{last['version']} ({last['tag']})" if last else "无"))
        state = READY / f"{name}.state.json"
        print(f"发布副本: {READY / name} | 状态文件: {'有' if state.is_file() else '无'}")
    else:
        print("发布副本:")
        for p in sorted(READY.glob("*.state.json")):
            print(f"  - {p.name}")
    return 0


def cmd_check(args):
    root = Path(args.root).resolve()
    name = project_name(root)
    a = run([PY, str(AUDIT), str(root)])
    s = run([PY, str(SANITIZE), str(root)])
    print(a.stdout)
    print(s.stdout)
    body = ("## 审计（源项目，只读）\n```\n" + a.stdout + "\n```\n\n"
            "## 净化预检（源项目，只读）\n```\n" + s.stdout + "\n```")
    report = write_report(name, "check", body)
    print(f"[REPORT] {report}")
    return 0


def cmd_prepare(args):
    root = Path(args.root).resolve()
    name = project_name(root)
    r = run([PY, str(PUBLISH), str(root), "--dry-run", "--skip-version-gate"])
    print(r.stdout)
    if r.returncode != 0:
        print("[FAIL] prepare 失败（见上方净化/打包输出）")
        return 1
    ready = READY / name
    comp = run([PY, "-m", "compileall", "-q", str(ready / "scripts")]) if (ready / "scripts").is_dir() else None
    bad_json = []
    for p in ready.rglob("*.json"):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            bad_json.append(f"{p.relative_to(ready)}: {e}")
    body = ("## 发布副本\n" + str(ready) + "\n\n"
            "## prepare 输出\n```\n" + r.stdout + "\n```\n\n"
            f"## 语法检查\ncompileall exit = {comp.returncode if comp else 'n/a'}\n\n"
            "## JSON 校验\n" + ("\n".join(bad_json) if bad_json else "全部有效") + "\n")
    report = write_report(name, "prepare", body)
    print(f"[REPORT] {report}")
    ok = (comp is None or comp.returncode == 0) and not bad_json
    print("[OK] prepare 完成" if ok else "[FAIL] 语法/JSON 校验未通过")
    return 0 if ok else 1


def cmd_suggest(args):
    root = Path(args.root).resolve()
    name = project_name(root)
    ready = READY / name
    static = read_json(PROJ / "config" / "project-suggestions.json").get(name, [])
    lines = [
        f"# {name} — 发布前建议（请转交对应项目窗口）",
        "",
        f"生成时间：{date.today()}",
        f"源项目：{root}",
        "> 以下为**功能 / 体验 / 可移植性**建议，不影响本机使用；发布相关的净化已在发布副本自动完成。",
        "",
        "## 需要项目窗口处理",
        "",
    ]
    if static:
        for i, it in enumerate(static, 1):
            lines.append(f"{i}. **[{it.get('category')}]** {it.get('location')}：{it.get('issue')}")
            lines.append(f"   → 建议：{it.get('suggestion')}")
    else:
        lines.append("（无静态建议项）")

    if not args.skip_clean_test and (ready / "scripts" / "deploy.ps1").is_file() and (ready / "scripts" / "init.py").is_file():
        ct = run([PY, str(CLEAN), str(ready)])
        print(ct.stdout)
        fails = [ln.strip() for ln in ct.stdout.splitlines() if "[FAIL]" in ln]
        lines += ["", "## 换机自检发现", ""]
        if fails:
            for f in fails:
                lines.append(f"- {f}")
        else:
            lines.append("（无）")

    SUGGESTIONS.mkdir(parents=True, exist_ok=True)
    p = SUGGESTIONS / f"{name}-{date.today()}.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[REPORT] {p}")
    return 0


def cmd_publish(args):
    root = Path(args.root).resolve()
    cmd = [PY, str(PUBLISH), str(root)]
    if args.force:
        cmd.append("--force")
    if args.draft:
        cmd.append("--draft")
    if args.repo:
        cmd += ["--repo", args.repo]
    r = run(cmd)
    print(r.stdout)
    if r.stderr.strip():
        print(r.stderr, file=sys.stderr)
    return r.returncode


def cmd_profile(args):
    """设置仓库描述与 topics（提升可发现性）。"""
    import publish

    cfg = load_config()
    prof = read_json(PROJ / "config" / "repo-profile.json")
    gh_cfg = cfg.get("github", {}) or {}
    repo = f"{gh_cfg.get('owner')}/{gh_cfg.get('default_repo')}"
    gh = publish.find_gh()
    if not gh:
        print("[FAIL] 未找到 gh CLI")
        return 1
    env = publish.publish_env(publish.resolve_proxy(cfg))
    tmp = PROJ / "_build" / "profile"
    tmp.mkdir(parents=True, exist_ok=True)

    repo_meta = {"description": prof.get("description", "")}
    if prof.get("homepage"):
        repo_meta["homepage"] = prof["homepage"]
    (tmp / "repo.json").write_text(json.dumps(repo_meta, ensure_ascii=False), encoding="utf-8")
    (tmp / "topics.json").write_text(
        json.dumps({"names": prof.get("topics", [])}, ensure_ascii=False), encoding="utf-8")

    r1 = subprocess.run([gh, "api", "-X", "PATCH", f"repos/{repo}", "--input", str(tmp / "repo.json")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    print("[repo description]", "OK" if r1.returncode == 0 else (r1.stderr.strip()[:200]))
    r2 = subprocess.run([gh, "api", "-X", "PUT", f"repos/{repo}/topics", "--input", str(tmp / "topics.json")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    print("[topics]", "OK" if r2.returncode == 0 else (r2.stderr.strip()[:200]))
    if r2.returncode == 0:
        print("[topics]", ", ".join(prof.get("topics", [])))

    # 更新仓库首页产品表（含客户端）
    cache = PROJ / "_build" / "repos" / repo.replace("/", "__")

    def _run(cmd):
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)

    try:
        if not (cache / ".git").exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", f"https://github.com/{repo}.git", str(cache)])
        else:
            _run(["git", "-C", str(cache), "fetch", "origin"])
            _run(["git", "-C", str(cache), "reset", "--hard", "origin/main"])
        import publish
        text = publish.render_repo_readme(publish.load_manifest(), repo)
        (cache / "README.md").write_text(text, encoding="utf-8")
        _run(["git", "-C", str(cache), "add", "README.md"])
        c = _run(["git", "-C", str(cache), "commit", "-m", "docs: 更新产品列表（README）"])
        out = (c.stdout or "") + (c.stderr or "")
        if "nothing to commit" not in out:
            p = _run(["git", "-C", str(cache), "push", "origin", "HEAD"])
            print("[repo README]", "OK" if p.returncode == 0 else ((p.stderr or "").strip()[:200]))
        else:
            print("[repo README] 无变更")
    except Exception as e:
        print(f"[repo README] 跳过: {e}")
    return 0 if r1.returncode == 0 and r2.returncode == 0 else 1


def cmd_all(args):
    root = Path(args.root).resolve()
    rc = cmd_check(args)
    rc = cmd_prepare(args) or rc
    cmd_suggest(args)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="统一发布工作流")
    ap.add_argument("command", choices=["status", "check", "prepare", "suggest", "publish", "all", "profile"])
    ap.add_argument("root", nargs="?", help="源项目根目录")
    ap.add_argument("--repo", default="")
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--skip-clean-test", action="store_true")
    args = ap.parse_args()

    if args.command in ("check", "prepare", "suggest", "publish", "all") and not args.root:
        ap.error(f"{args.command} 需要 <源项目根>")
    return {"status": cmd_status, "check": cmd_check, "prepare": cmd_prepare,
            "suggest": cmd_suggest, "publish": cmd_publish, "all": cmd_all,
            "profile": cmd_profile}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
