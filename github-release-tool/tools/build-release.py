#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键本地打包发布（本地升版本/打包/tag；公开发布由 github-release-tool 统一完成）

用法:
    python scripts/build-release.py --bump patch|minor|major
    python scripts/build-release.py --pack-current

发版门禁（与补全清单 P5 一致：自举合规 + 版本一致）:
    1. doctor.py D1-D12 全绿（仅当项目装配 scripts/doctor.py 时；未装配则跳过）
    2. 自举合规：git 已跟踪文件逐个过 enforcer.py check（仅当装配 scripts/enforcer.py 时；违规=0 是发版门槛）
    3. 版本一致：project_meta.json.version == plugin.json.version（plugin.json 未装配时只校验 meta）
    4. （--pack-current）当前版本 git tag 已存在则跳过打 tag

流程:
    git dirty 自动提交 → bump 版本（同时写 meta [+ plugin.json]）→ 打 tag →
    打包 release/<base>-vX.Y.Z.zip（base = meta.release_name 或 meta.name；排除 .git/_scratch/_checkpoint/release 等）→
    zip 完整性 + 核心文件校验 → 摘要
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8，任何调用方式下 print 不因 GBK 崩溃（→ 等字符安全）
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 版本一致性：版本行清单 + 校验/同步（发版门禁 + doctor D9 共用同一登记表）
from version_check import check_version_consistency, sync_version_lines  # noqa: E402

PROJ_ROOT = Path(__file__).parent.parent.resolve()
META_PATH = PROJ_ROOT / "project_meta.json"
PLUGIN_PATH = PROJ_ROOT / "plugin.json"
RELEASE_DIR = PROJ_ROOT / "release"
ENFORCER = PROJ_ROOT / "scripts" / "enforcer.py"
DOCTOR = PROJ_ROOT / "scripts" / "doctor.py"


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=PROJ_ROOT)
    if check and r.returncode != 0:
        print(f"[FAIL] {' '.join(cmd)}")
        if r.stderr.strip():
            print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)
    return r


def git_dirty() -> bool:
    return bool(run(["git", "status", "--porcelain"], check=False).stdout.strip())


def read_version() -> tuple:
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    mv = meta.get("version", "")
    if PLUGIN_PATH.is_file():
        plugin = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
        pv = plugin.get("version", "")
        if mv != pv:
            print(f"[FAIL] 版本不一致: project_meta.json={mv} vs plugin.json={pv}（先收敛版本再发版）")
            sys.exit(1)
    parts = mv.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        print(f"[FAIL] 版本号格式异常: {mv}")
        sys.exit(1)
    return tuple(int(p) for p in parts)


def bump_version(current: tuple, level: str) -> str:
    major, minor, patch = current
    if level == "major":
        return f"{major + 1}.0.0"
    elif level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def gate_doctor() -> bool:
    if not DOCTOR.is_file():
        print("[SKIP] 门禁 doctor 组件未装配（无 scripts/doctor.py），跳过")
        return True
    r = run([sys.executable, str(DOCTOR)], check=False)
    if r.returncode != 0:
        print(f"[FAIL] 发版门禁 doctor D1-D12 未全绿（exit={r.returncode}）")
        return False
    print("[OK] 门禁 doctor D1-D12 全绿")
    return True


def gate_self_compliance() -> bool:
    """自举合规：git 已跟踪文件逐个过 enforcer check（本项目受自身规则约束，违规=0 是发版门槛）。"""
    if not ENFORCER.is_file():
        print("[SKIP] 自举合规组件未装配（无 scripts/enforcer.py），跳过")
        return True
    r = run(["git", "-c", "core.quotepath=false", "ls-files", "-z"], check=False)
    files = [f for f in r.stdout.split("\x00") if f]
    env = dict(os.environ)
    env["FG_HOME"] = str(Path(os.environ.get("COMATE_FG_HOME", r"D:\comate")))
    bad = []
    for f in files:
        if "/.git/" in f or f.startswith(".git/"):
            continue
        p = str(PROJ_ROOT / f)
        chk = subprocess.run([sys.executable, str(ENFORCER), "check", p],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        if chk.returncode != 0:
            bad.append(f)
    if bad:
        print(f"[FAIL] 自举合规失败 {len(bad)} 个文件（违规=0 是发版门槛）:")
        for b in bad[:10]:
            print(f"  - {b}")
        return False
    print(f"[OK] 自举合规: {len(files)} 个跟踪文件全部合规（0 违规）")
    return True


def gate_version_consistency() -> bool:
    """发版门禁：版本行清单各文件（README/_索引/SKILL.md 等）版本号须与 project_meta.json 一致。
    不一致即拒绝发版并列出差异文件与当前值（纯代码执行，不依赖 AI 自觉）。"""
    ok_v, msgs = check_version_consistency(PROJ_ROOT)
    print("[版本一致性]")
    for m in msgs:
        print(m)
    if not ok_v:
        print("[FAIL] 版本一致性未通过：先同步版本行再发版（可运行 scripts/version_check.py --sync <版本>）")
        return False
    print("[OK] 版本一致性通过")
    return True


def create_zip(version: str) -> Path:
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    base = meta.get("release_name") or meta.get("name", "project")
    # release 目录可配置（2026-10-26 回灌：项目可用 meta.release_dir 指定，默认 release/）
    rel_dir = PROJ_ROOT / (meta.get("release_dir") or "release")
    rel_dir.mkdir(exist_ok=True)
    zip_path = rel_dir / f"{base}-v{version}.zip"
    # 排除项（2026-10-26 回灌：补运行数据目录 _state/_traces/decrypted 与 backup/output）
    exclude_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules",
                    "_trash", "_checkpoint", "data", "archive", "_scratch", "release",
                    "_state", "_traces", "decrypted", "backup", "output"}
    # 排除配置的 release 目录本身（2026-10-26 修复：只排除写死的 release/ 会把配置的
    # release_dir 里的旧 zip 甚至新 zip 自身套进包里）
    exclude_dirs.add(rel_dir.name)
    exclude_exts = {".bak", ".tmp", ".log", ".db"}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJ_ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                if any(f.endswith(e) for e in exclude_exts):
                    continue
                fp = Path(root) / f
                arcname = Path(base) / fp.relative_to(PROJ_ROOT)
                zf.write(fp, str(arcname).replace("\\", "/"))
    print(f"[OK] 打包完成: {zip_path} ({zip_path.stat().st_size:,} bytes)")
    return zip_path


def verify_zip(zip_path: Path) -> bool:
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        names = set(zf.namelist())
    if bad:
        print(f"[FAIL] zip 完整性校验失败: {bad}")
        return False
    # 核心文件校验：以项目实际装配的文件为准（无套件组件的项目只要求其拥有的核心件）
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    base = meta.get("release_name") or meta.get("name", "project")
    required = []
    for rel in ["plugin.json", "project_meta.json", "hooks/hooks.json",
                "scripts/pre-tool-use.py", "scripts/pre-compact.py",
                "scripts/doctor.py", "scripts/new-project.py",
                "scripts/ignore-gen.py", "scripts/enforcer.py"]:
        if (PROJ_ROOT / rel).is_file():
            required.append(f"{base}/{rel}")
    missing = [f for f in required if f not in names]
    if missing:
        print(f"[WARN] zip 中缺少核心文件: {missing}")
        return False
    print("[OK] zip 完整性 + 核心文件校验通过")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard (Comate) 一键打包发布")
    ap.add_argument("--bump", choices=["patch", "minor", "major"], default=None)
    ap.add_argument("--pack-current", action="store_true")
    ap.add_argument("--auto-commit-msg", default="chore: pre-release commit")
    args = ap.parse_args()
    if not args.bump and not args.pack_current:
        ap.error("必须指定 --bump <level> 或 --pack-current")
    if args.bump and args.pack_current:
        ap.error("--bump 与 --pack-current 互斥")

    mode = f"bump({args.bump})" if args.bump else "pack-current"
    print(f"=== FileGuard (Comate) Release ({mode}) ===")

    if not (PROJ_ROOT / ".git").exists():
        print("[FAIL] 当前目录不是 git 仓库")
        return 1
    if not ENFORCER.is_file():
        # 2026-10-26 回灌：无 enforcer.py 时降级（门禁 gate_self_compliance 本就"未装配则跳过"），
        # 不再硬 FAIL——通用项目发版不应因缺套件组件而阻塞
        print("[WARN] enforcer.py 未装配，自举合规将跳过（降级发版）")

    # 1. 发版门禁：doctor 全绿 + 自举合规 0 违规 + 版本一致性
    if not (gate_doctor() and gate_self_compliance() and gate_version_consistency()):
        print("[FAIL] 发版中止：门禁未通过")
        return 1

    # 2. dirty 自动提交
    if git_dirty():
        print("[WARN] 检测到未提交改动，自动提交中...")
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", args.auto_commit_msg])
    else:
        print("[OK] 工作树已 clean")

    # 3. 版本
    current = read_version()
    if args.bump:
        new_version = bump_version(current, args.bump)
        print(f"[INFO] 版本: {'.'.join(map(str, current))} → {new_version}")
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        plugin = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
        meta["version"] = new_version
        META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if PLUGIN_PATH.is_file():
            plugin["version"] = new_version
            PLUGIN_PATH.write_text(json.dumps(plugin, ensure_ascii=False, indent=2), encoding="utf-8")
        synced = sync_version_lines(PROJ_ROOT, new_version)
        if synced:
            print(f"[OK] 版本行同步: {', '.join(synced)}")
        run(["git", "add", "project_meta.json", "plugin.json"] + synced)
        run(["git", "commit", "-m", f"chore: bump version → {new_version}"])
        print(f"[OK] 版本号更新并提交: {new_version}（含版本行同步 {len(synced)} 个）")
    else:
        new_version = ".".join(map(str, current))
        print(f"[INFO] pack-current: 保持版本 v{new_version}（不递增）")

    # 4. 打 tag（已存在则跳过）
    tag = f"v{new_version}"
    if run(["git", "tag", "-l", tag], check=False).stdout.strip():
        print(f"[SKIP] tag 已存在: {tag}")
    else:
        run(["git", "tag", "-a", tag, "-m", f"{tag}: release"])
        print(f"[OK] git tag: {tag}")

    # 5. 打包 + 校验
    zip_path = create_zip(new_version)
    ok = verify_zip(zip_path)

    print("\n=== 发布摘要 ===")
    print(f"模式:   {mode}")
    print(f"版本:   v{new_version}")
    print(f"tag:    {tag}")
    print(f"zip:    {zip_path}")
    print(f"状态:   {'SUCCESS' if ok else 'ZIP VERIFICATION FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
