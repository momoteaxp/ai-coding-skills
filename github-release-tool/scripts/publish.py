#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 一键发布（源文件只读 → 构建区净化 → 发布区）

铁律:
    - 源项目目录【只读】：本脚本绝不写入源（不 bump、不 commit、不 tag）
    - 净化在构建区副本做：_build/<name>/，每次从源重新生成
    - 发布物（仓库源码 + zip 资产）都来自同一份构建区副本

流水线:
    1. 读源 project_meta.json（只读）
    2. 构建区：复制源 → 排除产物/机器配置/内部文档（默认 docs/** 不公开）→ 在副本补齐 README/LICENSE
    3. 净化审核（对构建区）：FAIL 阻塞
    4. 版本纪律：指纹比对（内容未变拒绝重复发；变了必须源版本递增）
    5. 从构建区打 zip
    6. 复制进目标仓库（单仓库模式）→ 提交 → 打 tag → push
    7. gh release create（资产=构建区 zip）
    8. 登记 manifest（源版本/指纹/发布版本/tag）

用法:
    python scripts/publish.py <源项目根> [--repo owner/repo] [--draft] [--dry-run] [--skip-sanitize]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fnmatch import fnmatch

from _paths import PROJ_ROOT, config_path, manifest_path  # noqa: E402
import transforms  # noqa: E402

SANITIZE = PROJ_ROOT / "scripts" / "sanitize.py"
FIX = PROJ_ROOT / "scripts" / "fix.py"
BUILD_DIR = PROJ_ROOT / "_build"
PUBLISH_READY = PROJ_ROOT / "publish-ready"
OVERRIDES_PATH = PROJ_ROOT / "config" / "publish-projects.json"

DEFAULT_EXCLUDE = {".git", "_scratch", "_trash", "_checkpoint", "release",
                   "output", "data", "backup", "archive", "__pycache__",
                   ".pytest_cache", "node_modules", ".comate", "_build",
                   "publish-ready", ".fileguard-sync.json", "_索引.md"}


def run(cmd, cwd, check=True, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(cwd), env=env)
    if check and r.returncode != 0:
        print(f"[FAIL] {' '.join(cmd)}")
        if r.stderr.strip():
            print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)
    return r


def run_net(cmd, cwd, env=None, attempts=3, hint=""):
    last = None
    for i in range(attempts):
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(cwd), env=env)
        if r.returncode == 0:
            return r
        last = r
        if i < attempts - 1:
            wait = 2 * (i + 1)
            print(f"[RETRY] 网络操作失败，{wait}s 后重试（{i + 1}/{attempts - 1}）...")
            time.sleep(wait)
    print(f"[FAIL] {' '.join(cmd)}")
    if last and last.stderr.strip():
        print(f"  stderr: {last.stderr.strip()}")
    if hint:
        print(f"  {hint}")
    sys.exit(1)


GH_FALLBACKS = [r"E:\Program Files\GitHub CLI\gh.exe",
                r"D:\comate\tools\gh\bin\gh.exe",
                r"C:\Program Files\GitHub CLI\gh.exe"]


def find_gh() -> str:
    try:
        r = subprocess.run(["gh", "--version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return "gh"
    except FileNotFoundError:
        pass
    for p in GH_FALLBACKS:
        if Path(p).is_file():
            return p
    return ""


PROXY_PORTS = [10808, 10809, 7890, 7897, 2080, 1080, 8889]


def resolve_proxy(cfg: dict) -> str:
    for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(k):
            return os.environ[k]
    configured = (cfg.get("china_network", {}) or {}).get("proxy", "")
    if configured:
        return configured
    for port in PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.8):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return ""


def publish_env(proxy: str) -> dict:
    env = dict(os.environ)
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["HTTP_PROXY"] = proxy
        env["ALL_PROXY"] = proxy
    return env


def load_config() -> dict:
    p = config_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_overrides(name: str) -> dict:
    try:
        d = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        return d.get(name, {})
    except Exception:
        return {}


def load_manifest() -> dict:
    p = manifest_path()
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"version": 1, "updated": str(date.today()), "registered": [], "releases": []}


def save_manifest(m: dict):
    m["updated"] = str(date.today())
    manifest_path().write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def _ver_tuple(v: str):
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))


def last_release(root: Path):
    m = load_manifest()
    rels = [r for r in m.get("releases", []) if r.get("root") == str(root) and not r.get("draft")]
    if not rels:
        return None
    return max(rels, key=lambda r: _ver_tuple(r.get("version", "0.0.0")))


def make_tag(meta: dict, ver: str, cfg: dict) -> str:
    """tag 基名优先用 release_name（含客户端），如 <product>-<client>-v1.0.0。"""
    base = meta.get("release_name") or meta.get("name", "product")
    pattern = (cfg.get("publish", {}) or {}).get("tag_pattern", "v{version}")
    return pattern.format(name=base, version=ver)


def fingerprint(staging: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(staging.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(staging).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(p.read_bytes())
    return h.hexdigest()


BINARY_SKIP = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".exe",
               ".msi", ".pdf", ".docx", ".pptx", ".xlsx", ".db", ".pyc", ".so",
               ".dll", ".woff", ".woff2", ".ttf", ".7z", ".gz", ".tar"}


def apply_replacements(staging: Path, reps: list):
    """在发布副本内做文本替换（跨项目痕迹泛化）；不改原始项目。英文按单词边界。"""
    if not reps:
        return
    compiled = []
    for r in reps:
        src, dst = r.get("from", ""), r.get("to", "")
        if not src:
            continue
        if re.fullmatch(r"[A-Za-z0-9 _.\-]+", src):
            pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(src) + r"(?![A-Za-z0-9])")
        else:
            pat = re.compile(re.escape(src))
        compiled.append((pat, dst, r.get("glob")))
    changed = 0
    for p in staging.rglob("*"):
        if not p.is_file() or p.suffix.lower() in BINARY_SKIP:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = p.relative_to(staging).as_posix()
        new = text
        for pat, dst, glob in compiled:
            if glob and not fnmatch(rel, glob):
                continue
            new = pat.sub(dst, new)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
    print(f"[OK] 已应用发布替换 {len(compiled)} 条（命中文件 {changed} 个）")


def stage_product(root: Path, meta: dict, cfg: dict, ver: str) -> Path:
    """从源复制到发布副本（publish-ready），应用排除与发布元数据覆盖；源不动。"""
    name = meta.get("name") or root.name
    staging = PUBLISH_READY / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, staging, ignore=shutil.ignore_patterns(*DEFAULT_EXCLUDE))
    print(f"[OK] 已生成发布副本: {staging}")

    ov = load_overrides(name)
    docs_policy = (cfg.get("publish", {}) or {}).get("docs_policy", "internal")
    includes = list(ov.get("include", []) or []) + list(meta.get("publish_include", []) or [])

    # 默认：docs/** 属内部文档，不公开（include 可白名单）
    if docs_policy == "internal":
        docs = staging / "docs"
        if docs.is_dir():
            kept = 0
            for p in sorted(docs.rglob("*"), reverse=True):
                if p.is_file():
                    rel = p.relative_to(staging).as_posix()
                    if any(fnmatch(rel, inc) for inc in includes):
                        kept += 1
                        continue
                    p.unlink()
                elif p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
            if not any(docs.iterdir()):
                docs.rmdir()
            print(f"[OK] 内部文档已排除（保留白名单 {kept} 个）")

    # 显式排除（项目级配置 + 兼容源 meta 的 publish_exclude）
    excludes = list(ov.get("exclude", []) or []) + list(meta.get("publish_exclude", []) or [])
    for pat in excludes:
        for q in staging.glob(pat):
            if q.is_dir():
                shutil.rmtree(q)
            elif q.exists():
                q.unlink()
    if excludes:
        print(f"[OK] 已应用项目排除规则: {excludes}")

    # 在副本应用发布元数据覆盖（发布用的展示字段不写回源）
    if ov.get("meta_overrides"):
        mp = staging / "project_meta.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m.update(ov["meta_overrides"])
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] 已应用发布元数据覆盖: {list(ov['meta_overrides'].keys())}")

    # 在副本应用跨项目痕迹替换（只改副本，不动原始项目）
    apply_replacements(staging, ov.get("replacements", []) or [])
    # 在副本应用结构化转换（如移除 kb 功能）
    for tname in ov.get("transforms", []) or []:
        transforms.apply(tname, staging)

    # 在副本补齐 README/LICENSE（fix.py --no-recheck，源不动）
    r = run([sys.executable, str(FIX), str(staging), "--version", ver, "--no-recheck"],
            staging, check=False)
    if r.stdout.strip():
        print(r.stdout.strip())

    # 文档类替换（绝对路径/个人目录名），在 README 生成之后执行
    apply_replacements(staging, ov.get("doc_replacements", []) or [])

    # 记录发布副本状态（放在副本外，避免被发布）
    state = {
        "source_root": str(root),
        "source_version": ver,
        "generated": str(date.today()),
        "overrides": list((ov.get("meta_overrides") or {}).keys()),
        "exclude": list(ov.get("exclude", []) or []),
    }
    (PUBLISH_READY / f"{name}.state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return staging


def sanitize_stage(staging: Path):
    print("=== 门禁: 净化审核（构建区） ===")
    r = run([sys.executable, str(SANITIZE), str(staging)], staging, check=False)
    print(r.stdout)
    if r.returncode != 0:
        print("[FAIL] 发版中止：构建区净化审核存在 FAIL（调整排除/脱敏后再发；--skip-sanitize 可跳过）")
        sys.exit(1)
    print("[OK] 净化审核通过")


def fingerprint_gate(root: Path, fp: str, ver: str):
    last = last_release(root)
    if not last:
        print(f"[OK] 首次发布 v{ver}")
        return
    last_v = last.get("version", "0.0.0")
    last_fp = last.get("source_fingerprint", "")
    if last_fp and last_fp == fp:
        print("[FAIL] 构建内容与上次发布完全一致（指纹相同），无需重复发布")
        sys.exit(1)
    if _ver_tuple(ver) <= _ver_tuple(last_v):
        print(f"[FAIL] 内容有变化，但源版本 v{ver} 未大于上次发布 v{last_v}")
        print("       请先在源项目做一次有意的版本升级，再重新发布（本脚本不写源文件）")
        sys.exit(1)
    print(f"[OK] 版本纪律: v{last_v} → v{ver}（内容有变化）")


def zip_stage(staging: Path, meta: dict, ver: str) -> Path:
    base = meta.get("release_name") or meta.get("name") or staging.name
    art_dir = BUILD_DIR / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    zip_path = art_dir / f"{base}-v{ver}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                zf.write(p, f"{base}/{p.relative_to(staging).as_posix()}")
    print(f"[OK] 构建区打包: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def resolve_repo(root: Path, repo_arg: str) -> str:
    if repo_arg:
        return repo_arg
    cfg = load_config()
    gh_cfg = cfg.get("github", {}) or {}
    if gh_cfg.get("default_repo"):
        return f"{gh_cfg['owner']}/{gh_cfg['default_repo']}" if gh_cfg.get("owner") else gh_cfg["default_repo"]
    print("[FAIL] 无法确定目标仓库: 用 --repo 或配置 github.owner/default_repo")
    sys.exit(1)


def build_notes(root: Path, meta: dict, tag: str) -> Path:
    r = run(["git", "log", "--oneline", "--no-decorate", "-n", "15"], root, check=False)
    lines = [f"- {ln}" for ln in r.stdout.splitlines() if ln.strip()] or ["- （无提交记录 / no commits）"]
    notes_dir = BUILD_DIR / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    p = notes_dir / f"{tag}.md"
    p.write_text(
        f"# {meta.get('name', root.name)} {tag}\n\n"
        f"## 变更 / Changes\n{chr(10).join(lines)}\n\n"
        f"## 下载 / Download\n"
        f"- GitHub Releases: https://github.com/{{repo}}/releases/tag/{tag}\n"
        f"- Source code (zip / tar.gz) — 由 GitHub 自动附带\n",
        encoding="utf-8")
    return p


def render_repo_readme(m: dict, repo: str) -> str:
    """生成仓库根 README（产品列表 + 适用客户端），提升可发现性。"""
    latest = {}
    for r in m.get("releases", []):
        if r.get("draft"):
            continue
        key = r.get("root")
        cur = latest.get(key)
        if cur is None or _ver_tuple(r.get("version")) > _ver_tuple(cur.get("version")):
            latest[key] = r
    lines = [
        f"# {repo} — AI 编码技能 / 套件发布仓库",
        "",
        "> 自研套件、skill、插件与工具的统一发布仓库；按客户端/环境标识，源码公开（MIT）。",
        "",
        "## 产品列表",
        "",
        "| 产品 | 适用客户端 | 最新版本 | 下载 |",
        "|---|---|---|---|",
    ]
    for r in sorted(latest.values(), key=lambda x: (x.get("release") or x.get("name") or "")):
        folder = r.get("name") or Path(r.get("root", "")).name
        name = r.get("release") or folder
        clients = r.get("clients")
        client = " / ".join(clients) if clients else (r.get("client") or "Any")
        lines.append(f"| [{name}](https://github.com/{repo}/tree/main/{folder}) | {client} | "
                     f"v{r.get('version')} | [Release]({r.get('url')}) |")
    lines += [
        "",
        "## 使用说明",
        "",
        "- 每个产品独立版本与 tag；源码与发布 zip 同源。",
        "- 国内下载：在 Release 链接前加 `https://ghproxy.net/` 镜像前缀。",
        "",
    ]
    return "\n".join(lines)


def sync_stage(staging: Path, name: str, tag: str, repo: str, env: dict, repo_readme: str = ""):
    cache = BUILD_DIR / "repos" / repo.replace("/", "__")
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"=== 克隆目标仓库: {cache} ===")
        run_net(["git", "clone", f"https://github.com/{repo}.git", str(cache)], PROJ_ROOT, env=env,
                hint="网络恢复后重试：git clone https://github.com/{repo}.git".replace("{repo}", repo))
    else:
        run_net(["git", "-C", str(cache), "fetch", "origin"], PROJ_ROOT, env=env, attempts=2,
                hint="网络恢复后重试：git fetch origin")
        br = run(["git", "-C", str(cache), "symbolic-ref", "--short", "HEAD"],
                 PROJ_ROOT, check=False).stdout.strip() or "main"
        run(["git", "-C", str(cache), "reset", "--hard", f"origin/{br}"], PROJ_ROOT, env=env)

    dest = cache / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(staging, dest)

    if repo_readme:
        (cache / "README.md").write_text(repo_readme, encoding="utf-8")

    run(["git", "-C", str(cache), "add", "-A"], PROJ_ROOT, env=env)
    st = run(["git", "-C", str(cache), "status", "--porcelain"], PROJ_ROOT, check=False, env=env)
    if st.stdout.strip():
        run(["git", "-C", str(cache), "commit", "-m", f"release: {name} {tag}"], PROJ_ROOT, env=env)
        print(f"[OK] 已提交: release: {name} {tag}")
    else:
        print("[INFO] 目标仓库无变更")

    existing = run(["git", "-C", str(cache), "tag", "-l", tag], PROJ_ROOT, check=False, env=env)
    if not existing.stdout.strip():
        run(["git", "-C", str(cache), "tag", "-a", tag, "-m", f"{name} {tag}"], PROJ_ROOT, env=env)
        print(f"[OK] 已打 tag: {tag}")

    # 只推当前 tag（避免把本地缓存里已删除的旧 tag 重新推上去）
    run_net(["git", "-C", str(cache), "push", "origin", "HEAD", tag], PROJ_ROOT, env=env,
            hint=f"本地已提交并打 tag；网络恢复后可手动续推：git -C {cache} push origin HEAD {tag}")
    print(f"[OK] 已推送 {repo}")


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 一键发布（源只读 + 构建区净化）")
    ap.add_argument("root", help="源项目根目录（只读）")
    ap.add_argument("--repo", default="", help="目标仓库 owner/repo")
    ap.add_argument("--draft", action="store_true", help="发布为草稿")
    ap.add_argument("--dry-run", action="store_true", help="只构建+校验，不 push 不建 release")
    ap.add_argument("--skip-sanitize", action="store_true")
    ap.add_argument("--skip-version-gate", action="store_true", help="准备阶段跳过指纹/版本门禁（不上传时用）")
    ap.add_argument("--force", action="store_true", help="忽略发布保险锁（publish.enabled=false）")
    args = ap.parse_args()

    cfg = load_config()
    locked = not (cfg.get("publish", {}) or {}).get("enabled", False) and not args.force
    if locked and not args.dry_run:
        print("[LOCKED] 发布保险锁未开：config/release-config.json 的 publish.enabled = false")
        print("         确认准备就绪后改为 true，或显式加 --force（不推荐）")
        return 1
    if locked:
        print("[LOCKED] 保险锁关闭中：仅允许 dry-run 预演（不会上传）")

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FAIL] 目录不存在: {root}")
        return 1
    meta_p = root / "project_meta.json"
    if not meta_p.is_file():
        print("[FAIL] 源项目缺 project_meta.json")
        return 1
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    ver = meta.get("version", "")
    if not ver:
        print("[FAIL] 源项目缺版本号")
        return 1

    cfg = load_config()
    tag = make_tag(meta, ver, cfg)
    name = meta.get("name") or root.name

    # 1-2 构建区（源只读）
    staging = stage_product(root, meta, cfg, ver)

    # 3 净化
    if not args.skip_sanitize:
        sanitize_stage(staging)
    else:
        print("[WARN] 已跳过净化审核（--skip-sanitize）")

    # 4 版本纪律（指纹）
    fp = fingerprint(staging)
    if args.skip_version_gate:
        print("[WARN] 已跳过版本门禁（prepare 模式）")
    else:
        fingerprint_gate(root, fp, ver)

    # 5 打包（从构建区）
    zip_path = zip_stage(staging, meta, ver)

    repo = resolve_repo(root, args.repo)
    proxy = resolve_proxy(cfg)
    env = publish_env(proxy)
    gh = find_gh()
    if proxy:
        print(f"[INFO] 上传代理: {proxy}")
    else:
        print("[WARN] 未发现本地代理（直连 GitHub）；国内环境请先开梯子")

    if args.dry_run:
        print(f"[DRY-RUN] 仓库: {repo} | tag: {tag} | 资产: {zip_path.name} | gh: {gh or '(未找到)'}")
        print(f"[DRY-RUN] 构建区: {staging}")
        print("[DRY-RUN] 未执行 push / release create")
        return 0

    # 6 发布
    if not gh:
        print("[FAIL] 未找到 gh CLI")
        return 1
    auth_ok = False
    auth = None
    for i in range(3):
        auth = run([gh, "auth", "status"], PROJ_ROOT, check=False, env=env)
        if auth.returncode == 0:
            auth_ok = True
            break
        if i < 2:
            print(f"[RETRY] gh 认证/网络检查失败，{2 * (i + 1)}s 后重试...")
            time.sleep(2 * (i + 1))
    if not auth_ok:
        print("[FAIL] gh 未认证或网络不可达（先 gh auth login；国内检查代理）")
        if auth and auth.stderr.strip():
            print(f"  stderr: {auth.stderr.strip()[:200]}")
        return 1

    clients = meta.get("clients")
    if not clients:
        clients = [meta.get("client")] if meta.get("client") else ["Any"]
    clients = [str(c) for c in clients if c]
    record = {
        "root": str(root), "version": ver, "tag": tag, "repo": repo,
        "url": f"https://github.com/{repo}/releases/tag/{tag}",
        "published": str(date.today()), "draft": args.draft,
        "source_fingerprint": fp, "staging": str(staging),
        "name": name, "release": meta.get("release_name") or name,
        "client": " / ".join(clients), "clients": clients,
    }
    manifest = load_manifest()
    preview = {"releases": list(manifest.get("releases", [])) + [record]}
    repo_readme = render_repo_readme(preview, repo)
    sync_stage(staging, name, tag, repo, env, repo_readme)

    notes = build_notes(root, meta, tag)
    cmd = [gh, "release", "create", tag, "--repo", repo, "--title", tag,
           "--notes-file", str(notes)]
    if args.draft:
        cmd.append("--draft")
    cmd.append(str(zip_path))
    print(f"=== gh release create {tag} --repo {repo} ===")
    run_net(cmd, root, env=env,
            hint=f"源码与 tag 已推送；网络恢复后可手动创建：gh release create {tag} --repo {repo} --title {tag} --notes-file {notes} {zip_path}")

    manifest = load_manifest()
    manifest["releases"].append(record)
    save_manifest(manifest)

    print("\n=== 发布完成 ===")
    print(f"Release: https://github.com/{repo}/releases/tag/{tag}")
    print(f"构建区:  {staging}")
    print(f"资产:    {zip_path.name}（来自构建区，源文件未改动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
