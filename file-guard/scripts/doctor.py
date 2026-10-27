#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — 套件体检（D1-D12，2026-10-23 独立化完成）

检查项:
  D1 插件挂载   ~/.comate/plugins/file-guard 是 junction，plugin.json 可见
  D2 钩子配置   hooks.json 含 PreToolUse（引擎工具名）+ PreCompact，命令指向脚本存在
  D3 核心复用   scripts/enforcer.py 存在（独立单源）
  D4 规则层     受管根 _rules/global-rules.json 存在且可解析（独立规则文件）
  D5 项目登记   受管登记表 managed-projects.json 各项目 meta 可解析 + .comateignore 已生成（空表=WARN，新装机正常；缺表/空表回退受管根两层扫描）
  D6 L3 钩子    comate 项目 .git/hooks/pre-commit 是否安装（非 git / zip 安装=WARN，不阻断）
  D7 L4 FSW     comate 侧 3 计划任务是否注册（可选增强项；未注册=WARN，不阻断体检）
  D8 环境变量   生效受管根 = COMATE_FG_HOME→FG_HOME→D:\\comate（显示实际值）
  D9 版本一致性 版本行清单（project_meta/plugin/SKILL 等）全部一致
  D10 引擎级拦截 .comateignore 与 ignore-gen.py 生成内容一致（不依赖 hooks 的拦截通道）
  D11 漏网项目 受管根 products 下无 project_meta.json 的目录（含已登记项目的容器目录除外）/ 已建 meta 未登记的目录 / 登记表指向不存在的目录——三类都主动告警（防手工建项目绕过入口再漏网，2026-10-26 incident 事件；2026-10-27 容器目录豁免，如 github/github-release-skill）
  D12 进度体系前提 登记项目 meta 必须含 _checkpoint 白名单（否则 checkpoint-manager save 被拦、进度档案被迫自创，2026-10-27 incident CHECKPOINT.md 事件）

用法: python doctor.py
退出码: 0 = 全部通过；1 = 存在失败项（stderr 见明细）
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# 版本一致性：版本行清单 + 校验（与 build-release 门禁共用同一登记表）
from version_check import check_version_consistency  # noqa: E402

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PLUGIN_DIR = Path(__file__).resolve().parent.parent  # 套件根（scripts/..）；2026-10-27 去硬编码，与 build-release 同口径
COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or r"D:\comate")
USERPROFILE = Path(os.environ.get("USERPROFILE", ""))
PLUGIN_LINK = USERPROFILE / ".comate" / "plugins" / "file-guard"

PASSES: list[str] = []
FAILS: list[str] = []
WARNS: list[str] = []


def ok(msg: str) -> None:
    PASSES.append(msg)
    print(f"[PASS] {msg}")


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARNS.append(msg)
    print(f"[WARN] {msg}")


def _norm(p: str) -> str:
    s = os.path.normpath(os.path.abspath(p)).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].upper() + s[1:]
    return s.lower().rstrip("/")


def _find_meta(target: Path, max_depth: int = 2) -> Path | None:
    """从目标向上找 project_meta.json（与 pre-tool-use.py 同口径）。"""
    d = target.parent.resolve() if target.is_file() or not target.exists() else target.resolve()
    for _ in range(max_depth + 1):
        cand = d / "project_meta.json"
        if cand.is_file():
            return cand
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None


def session_diagnose(path: str) -> int:
    """会话项目归属诊断（--session <path>，排查 checkpoint 误拦/跨项目判定）。"""
    env_dir = os.environ.get("FILEGUARD_CURRENT_DIR") or ""
    p = Path(path)
    meta = _find_meta(p)
    root = meta.parent if meta else None
    print("=== FileGuard 会话项目归属诊断 ===")
    print(f"目标路径:            {p.resolve()}")
    print(f"FILEGUARD_CURRENT_DIR: {env_dir or '(未设置)'}")
    print(f"project_meta:        {meta or '(未找到)'}")
    print(f"解析项目根:          {root or '(未登记项目)'}")
    if env_dir:
        em = _find_meta(Path(env_dir))
        eroot = em.parent if em else None
        print(f"env 解析项目根:       {eroot or '(env 路径未解析到项目)'}")
        if root and eroot:
            print(f"env 与路径解析一致:   {_norm(str(eroot)) == _norm(str(root))}")
        else:
            print("env 与路径解析一致:   无法比较（存在未解析侧）")
    return 0



def main() -> int:
    # D1 插件挂载
    try:
        item = PLUGIN_LINK if PLUGIN_LINK.exists() else None
        if item is not None and (PLUGIN_LINK / "plugin.json").is_file():
            kind = "junction" if PLUGIN_LINK.is_junction() else "目录"
            ok(f"D1 插件挂载 {PLUGIN_LINK}（{kind}）plugin.json 可见")
        else:
            fail(f"D1 插件挂载 {PLUGIN_LINK} 不存在或 plugin.json 不可见（可跑 deploy.ps1 重挂）")
    except Exception as e:
        fail(f"D1 插件挂载 检查异常: {e}")

    # D2 钩子配置
    try:
        def _hook_entry_eq(a: dict, b: dict) -> bool:
            """钩子条目相等：type/command/timeout 三字段（合并语义逐条比对用）。"""
            return (a.get("type") == b.get("type")
                    and a.get("command") == b.get("command")
                    and a.get("timeout") == b.get("timeout"))

        hj = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        hk = hj.get("hooks", {})
        pre_tool = any(
            ("write_file" in m.get("matcher", "") or "Write|Edit|Rename" in m.get("matcher", ""))
            for m in hk.get("PreToolUse", [])
        )
        pre_compact = bool(hk.get("PreCompact"))
        scripts_ok = True
        for group in hk.values():
            for m in group:
                for h in m.get("hooks", []):
                    cmd = h.get("command", "")
                    if "pre-tool-use.py" in cmd and not (PLUGIN_DIR / "scripts" / "pre-tool-use.py").is_file():
                        scripts_ok = False
                    if "pre-compact.py" in cmd and not (PLUGIN_DIR / "scripts" / "pre-compact.py").is_file():
                        scripts_ok = False
        global_hook = USERPROFILE / ".comate" / "hooks.json"
        # 合并语义（2026-10-26）：全局 hooks.json 允许共存其他项目的钩子（如 knowledge-base 的
        # Stop hook，8.3 短路径），本项目的每个 (事件组, matcher) 及其命令在全局中逐条存在即可，
        # 不再要求逐字节相等（逐字节会在别人装钩子后误判 D2 失败、卡死发版）。
        gh_ok = global_hook.is_file()
        if gh_ok:
            try:
                ghk = json.loads(global_hook.read_text(encoding="utf-8")).get("hooks", {})
                for group, entries in hk.items():
                    g_entries = ghk.get(group, [])
                    for me in entries:
                        matcher = me.get("matcher", "")
                        mine = me.get("hooks", [])
                        found = any(
                            ge.get("matcher") == matcher
                            and all(_hook_entry_eq(h, gh) for gh in ge.get("hooks", [])) for h in mine
                            for ge in g_entries
                        )
                        if not found:
                            gh_ok = False
                            break
                    if not gh_ok:
                        break
            except Exception:
                gh_ok = False
        if pre_tool and pre_compact and scripts_ok and gh_ok:
            ok("D2 钩子配置 PreToolUse + PreCompact 齐全，命令指向脚本存在，全局 ~/.comate/hooks.json 含本项目钩子（合并语义）")
        else:
            fail(f"D2 钩子配置异常（PreToolUse={pre_tool} PreCompact={pre_compact} 脚本存在={scripts_ok} 全局钩子存在={gh_ok}）"
                 f"；首次装机请先跑 scripts/deploy.ps1（生成 hooks.json + 合并全局 hooks）再跑 doctor")
    except Exception as e:
        fail(f"D2 钩子配置 检查异常: {e}")

    # D3 核心复用（enforcer.py 本套件独立单源）
    enf = PLUGIN_DIR / "scripts" / "enforcer.py"
    if enf.is_file():
        ok(f"D3 核心复用 enforcer.py 存在: {enf}")
    else:
        fail(f"D3 核心复用 enforcer.py 缺失: {enf}")

    # D4 规则层（独立规则文件，可解析）
    r_c = COMATE_FG_HOME / "_rules" / "global-rules.json"
    try:
        if r_c.is_file():
            try:
                json.loads(r_c.read_text(encoding="utf-8"))
                ok(f"D4 规则层 {r_c} 存在且可解析（comate 独立规则）")
            except Exception as e:
                fail(f"D4 规则层 {r_c} JSON 解析失败: {e}")
        else:
            fail(f"D4 规则层 缺失: {r_c}")
    except Exception as e:
        fail(f"D4 规则层 检查异常: {e}")

    # D5 项目登记（以受管登记表为准；缺表/空表回退受管根两层扫描；空表=WARN，新装机正常）
    try:
        reg_path = COMATE_FG_HOME / "_rules" / "managed-projects.json"
        roots: list[Path] = []
        reg_err = ""
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            roots = [Path(p["root"]) for p in (reg.get("projects") or []) if p.get("root")]
        except FileNotFoundError:
            pass
        except Exception as e:
            reg_err = str(e)
        if not roots:
            roots = sorted({m.parent for pattern in ("*/project_meta.json", "*/*/project_meta.json")
                            for m in COMATE_FG_HOME.glob(pattern)}, key=str)
        if reg_err:
            warn(f"D5 项目登记 登记表解析失败（已回退扫描 {COMATE_FG_HOME}）: {reg_err}")
        bad = 0
        ign_missing = 0
        for root in roots:
            m = root / "project_meta.json"
            if not m.is_file():
                bad += 1
                fail(f"D5 项目登记 {root} 缺 project_meta.json")
                continue
            try:
                json.loads(m.read_text(encoding="utf-8"))
            except Exception as e:
                bad += 1
                fail(f"D5 项目登记 {m} 解析失败: {e}")
                continue
            if not (root / ".comate" / ".comateignore").is_file():
                ign_missing += 1
                fail(f"D5 项目登记 {root.name} .comateignore 未生成（跑 ignore-gen.py --write）")
        if roots and bad == 0 and ign_missing == 0:
            ok(f"D5 项目登记 {len(roots)} 个项目 meta 可解析 + .comateignore 已生成: {', '.join(r.name for r in roots)}")
        elif not roots:
            warn(f"D5 项目登记 登记表为空且 {COMATE_FG_HOME} 下暂无已登记项目（新装机正常；用 new-project 建首个项目）")
    except Exception as e:
        fail(f"D5 项目登记 检查异常: {e}")

    # D6 L3 钩子（仅 git 仓库适用；zip 安装无 .git → WARN 不阻断）
    pc = PLUGIN_DIR / ".git" / "hooks" / "pre-commit"
    if pc.is_file():
        ok("D6 L3 pre-commit 已安装")
    elif not (PLUGIN_DIR / ".git").is_dir():
        warn("D6 L3 pre-commit 不适用：当前不是 git 仓库（zip 安装正常；如需 L3：git init 后重跑 deploy.ps1）")
    else:
        warn("D6 L3 pre-commit 未安装（可选防护层；跑 deploy.ps1 或复制 scripts/git-hooks/pre-commit 到 .git/hooks/）")

    # D7 L4 FSW 计划任务
    try:
        def task_state(name):
            r = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "LIST"],
                               capture_output=True, text=True, errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            return r.returncode == 0, out

        comate_names = ["Comate Placement Guard", "Comate Placement Guard - ScanOnce", "Comate Placement Guard - Watchdog"]
        comate_states = [task_state("\\" + n)[0] for n in comate_names]

        if all(comate_states):
            ok("D7 L4 comate 计划任务 3 个均已注册（Comate Placement Guard 常驻/ScanOnce/Watchdog）")
        else:
            warn(f"D7 L4 comate 计划任务未注册: {[n for n, s in zip(comate_names, comate_states) if not s]}"
                 f"（可选增强项，不阻断体检；需要时跑 register-comate-guard-task.ps1）")
    except Exception as e:
        warn(f"D7 L4 计划任务 检查异常（不阻断体检）: {e}")

    # D8 环境变量（显示实际生效值；统一 COMATE_FG_HOME→FG_HOME→D:\comate）
    comate_env = os.environ.get("COMATE_FG_HOME") or ""
    fg_env = os.environ.get("FG_HOME") or ""
    effective_home = comate_env or fg_env or r"D:\comate"
    ok(
        "D8 环境变量 "
        f"生效受管根={effective_home} | "
        f"COMATE_FG_HOME={comate_env or '(未设)'} | "
        f"FG_HOME={fg_env or '(未设)'}"
    )

    # D9 版本一致性（project_meta 与各版本行文件，2026-10-22 反馈补）
    try:
        vok, vmsgs = check_version_consistency(PLUGIN_DIR)
        if vok:
            ok("D9 版本一致性 全部一致（project_meta/plugin/SKILL 等版本行）")
        else:
            fail("D9 版本一致性 存在不一致：" + " | ".join(m.strip() for m in vmsgs if "FAIL" in m))
    except Exception as e:
        fail(f"D9 版本一致性 检查异常: {e}")

    # D10 引擎级拦截通道（.comateignore，不依赖 hooks，2026-10-23 定案）
    try:
        p = subprocess.run(
            [sys.executable, str(PLUGIN_DIR / "scripts" / "ignore-gen.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if p.returncode == 0:
            ok("D10 .comateignore 引擎级拦截通道 全部登记项目与全局副本一致")
        else:
            fail("D10 .comateignore 一致性异常：" + ((p.stderr or p.stdout or "").strip() or "请跑 ignore-gen.py --write"))
    except Exception as e:
        fail(f"D10 .comateignore 检查异常: {e}")

    # D11 漏网项目扫描（2026-10-26：incident 事件后补——防"手工建项目绕过新建入口"再漏网）
    try:
        reg_path = COMATE_FG_HOME / "_rules" / "managed-projects.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else {"projects": []}
        reg_roots = {_norm(str(Path(p["root"]))) for p in reg.get("projects", []) if p.get("root")}
        missing_meta: list[str] = []   # 受管根下有目录但无 project_meta.json → 从未登记
        unregistered: list[str] = []   # 有 project_meta.json 但不在登记表 → 半登记（拦截生效但无兜底）
        stale: list[str] = []          # 登记表指向的根目录不存在 → 登记失效
        managed_root = COMATE_FG_HOME / "products"

        def _contains_registered(d: Path) -> bool:
            """容器目录判定：该目录内（任意深度）已有登记项目 → 是分类容器，不是漏网。
            2026-10-27 补：products 根下允许分类目录嵌套（如 github/github-release-skill）。"""
            dn = _norm(str(d))
            return any(r.startswith(dn + "/") and r != dn for r in reg_roots)

        if managed_root.is_dir():
            for d in managed_root.iterdir():
                if not d.is_dir() or d.name.startswith("."):
                    continue
                has_meta = (d / "project_meta.json").is_file()
                if not has_meta:
                    if _contains_registered(d):
                        continue  # 容器目录（内含已登记项目），非漏网
                    missing_meta.append(d.name)
                elif _norm(str(d)) not in reg_roots:
                    unregistered.append(d.name)
        for rp in reg_roots:
            if not Path(rp).exists():
                stale.append(rp)
        if missing_meta or unregistered or stale:
            fail("D11 漏网项目（需接手登记或清理）: "
                 + ("无meta " + "、".join(missing_meta) if missing_meta else "")
                 + ("；有meta未登记 " + "、".join(unregistered) if unregistered else "")
                 + ("；登记失效 " + "、".join(stale) if stale else ""))
        else:
            ok("D11 漏网项目扫描：受管根无漏网，登记表全部有效")
    except Exception as e:
        fail(f"D11 漏网项目扫描 检查异常: {e}")

    # D12 进度体系前提（2026-10-27：incident 事件后补——登记项目 meta 必须含 _checkpoint 白名单，
    # 否则标准 checkpoint 流程（checkpoint-manager save）会被拦截，进度档案被迫自创根级文件）
    try:
        reg_path = COMATE_FG_HOME / "_rules" / "managed-projects.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8")) if reg_path.is_file() else {"projects": []}
        bad_dirs: list[str] = []
        for p in reg.get("projects", []):
            rp = Path(p.get("root", ""))
            mp = rp / "project_meta.json"
            if not mp.is_file():
                continue  # 无 meta 由 D11 覆盖
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                bad_dirs.append(f"{rp.name}(meta 解析失败)")
                continue
            if "_checkpoint" not in (m.get("dirs") or {}):
                bad_dirs.append(rp.name)
        if bad_dirs:
            fail("D12 进度体系前提：以下登记项目 meta 缺 _checkpoint 白名单（标准 checkpoint 流程会被拦，"
                 "进度档案将被迫自创根级文件）: " + "、".join(bad_dirs))
        else:
            ok("D12 进度体系前提：全部登记项目 meta 含 _checkpoint 白名单")
    except Exception as e:
        fail(f"D12 进度体系前提 检查异常: {e}")

    print()
    if FAILS:
        print(f"结果: {len(PASSES)} 通过 / {len(FAILS)} 失败", file=sys.stderr)
        return 1
    if WARNS:
        print(f"结果: {len(PASSES)} 通过 / {len(WARNS)} 告警（不阻断）")
    else:
        print(f"结果: {len(PASSES)} 项全部通过")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="FileGuard (Comate) 套件体检（D1-D12）")
    ap.add_argument("--session", metavar="PATH", default="",
                    help="会话项目归属诊断：报告给定路径解析到的项目根与 FILEGUARD_CURRENT_DIR 一致性（排查 checkpoint 误拦）")
    args = ap.parse_args()
    if args.session:
        sys.exit(session_diagnose(args.session))
    sys.exit(main())
