#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 环境自检（D1-D8）

一条命令确认"发版通道"是否健康，避免每次从头排查。纯代码执行。

用法:
    python scripts/doctor.py [--json]

检查项:
    D1 gh CLI 可定位 + 版本
    D2 gh 已认证（标准登录）
    D3 token 权限含 repo/read:org
    D4 代理可用 + GitHub API 可达
    D5 发布配置完整（owner/default_repo/license.holder）
    D6 客户端 GitHub MCP 配置（mcp.json）
    D7 git 提交身份（应为 GitHub 账号）
    D8 受管项目可发现（中央登记表）
退出码: 0 = 无 FAIL；1 = 存在 FAIL。
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from _paths import PROJ_ROOT, config_path, manifest_path, managed_projects_path  # noqa: E402

GH_FALLBACKS = [r"E:\Program Files\GitHub CLI\gh.exe",
                r"D:\comate\tools\gh\bin\gh.exe",
                r"C:\Program Files\GitHub CLI\gh.exe"]
PROXY_PORTS = [10808, 10809, 7890, 7897, 2080, 1080, 8889]
MCP_CONFIG = Path(os.path.expanduser("~")) / ".comate" / "mcp.json"


def item(code, status, message):
    return {"code": code, "status": status, "message": message}


def run(cmd, env=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
    except FileNotFoundError:
        return None


def find_gh() -> str:
    r = run(["gh", "--version"])
    if r and r.returncode == 0:
        return "gh"
    for p in GH_FALLBACKS:
        if Path(p).is_file():
            return p
    return ""


def detect_proxy(cfg: dict) -> str:
    p = (cfg.get("china_network", {}) or {}).get("proxy", "")
    if p:
        return p
    for port in PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return f"http://127.0.0.1:{port}"
        except OSError:
            continue
    return ""


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description="github-release-tool 环境自检")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = load_json(config_path(), {})
    results = []

    # D1 gh
    gh = find_gh()
    if gh:
        v = run([gh, "--version"])
        ver = (v.stdout.splitlines()[0] if v and v.stdout else "?")
        results.append(item("D1", "PASS", f"gh 可用: {ver}（{gh}）"))
    else:
        results.append(item("D1", "FAIL", "未找到 gh（装正式版: 镜像下 MSI 后 msiexec 提权安装）"))

    env = dict(os.environ)
    proxy = detect_proxy(cfg)
    if proxy:
        env["HTTPS_PROXY"] = env["HTTP_PROXY"] = env["ALL_PROXY"] = proxy

    # D2 认证
    if gh:
        a = run([gh, "auth", "status"], env=env)
        if a and a.returncode == 0:
            results.append(item("D2", "PASS", "gh 已认证（标准登录）"))
        else:
            results.append(item("D2", "FAIL", "gh 未认证（gh auth login，或 gh auth login --with-token）"))
    else:
        results.append(item("D2", "WARN", "gh 缺失，跳过认证检查"))

    # D3 scopes
    if gh:
        a = run([gh, "auth", "status"], env=env)
        out = (a.stdout or "") + (a.stderr or "") if a else ""
        if "read:org" in out and "repo" in out:
            results.append(item("D3", "PASS", "token 权限含 repo + read:org"))
        elif a and a.returncode == 0:
            results.append(item("D3", "WARN", "token 权限未确认（gh auth status 输出中未见 repo/read:org）"))
        else:
            results.append(item("D3", "WARN", "未认证，无法检查 token 权限"))
    else:
        results.append(item("D3", "WARN", "gh 缺失，跳过"))

    # D4 代理 + API 可达
    api_ok = False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"https": proxy, "http": proxy} if proxy else {}))
        req = urllib.request.Request("https://api.github.com", headers={"User-Agent": "github-release-tool"})
        with opener.open(req, timeout=12) as resp:
            api_ok = resp.status == 200
    except Exception as e:
        api_ok = False
        err = str(e)[:80]
    if proxy:
        results.append(item("D4", "PASS" if api_ok else "FAIL",
                            f"代理 {proxy}；api.github.com 可达={api_ok}" if api_ok else f"代理 {proxy} 但 API 不可达: {err}"))
    else:
        results.append(item("D4", "PASS" if api_ok else "FAIL",
                            "直连 GitHub API 可达" if api_ok else f"无代理且直连不可达: {err}"))

    # D5 配置
    gh_cfg = cfg.get("github", {}) or {}
    missing = [k for k in ("owner", "default_repo") if not gh_cfg.get(k)]
    if not (cfg.get("license", {}) or {}).get("holder"):
        missing.append("license.holder")
    if missing:
        results.append(item("D5", "FAIL", f"配置未回填: {', '.join(missing)}（config/release-config.json）"))
    else:
        results.append(item("D5", "PASS", f"配置完整: {gh_cfg.get('owner')}/{gh_cfg.get('default_repo')}"))

    # D6 MCP
    mcp = load_json(MCP_CONFIG, {})
    srv = (mcp.get("mcpServers", {}) or {}).get("github", {})
    tok = (srv.get("env", {}) or {}).get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    if srv and tok.startswith("ghp_"):
        results.append(item("D6", "PASS", "客户端 GitHub MCP 已配置（个人范围，token 已注入）"))
    elif srv:
        results.append(item("D6", "WARN", "MCP 已配置但 token 缺失/格式异常"))
    else:
        results.append(item("D6", "WARN", "客户端未配置 GitHub MCP（可选，仅用于 AI 辅助操作仓库/issue/PR）"))

    # D7 git 身份
    n = run(["git", "config", "--global", "user.name"])
    e = run(["git", "config", "--global", "user.email"])
    name = (n.stdout or "").strip() if n else ""
    email = (e.stdout or "").strip() if e else ""
    if email and "@" in email:
        results.append(item("D7", "PASS", f"git 身份: {name} <{email}>"))
    else:
        results.append(item("D7", "FAIL", "git 全局身份未设置（git config --global user.name/user.email）"))

    # D8 受管项目
    mp = managed_projects_path()
    data = load_json(mp, {})
    projects = [p for p in data.get("projects", []) if p.get("status") == "active"]
    if projects:
        results.append(item("D8", "PASS", f"可发现受管项目 {len(projects)} 个"))
    else:
        results.append(item("D8", "WARN", f"受管登记表为空或缺失: {mp}"))

    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]

    if args.json:
        print(json.dumps({"results": results, "pass": len(results) - len(fails) - len(warns),
                          "warn": len(warns), "fail": len(fails)}, ensure_ascii=False, indent=2))
    else:
        print("=== github-release-tool 环境自检 ===")
        for r in results:
            mark = {"PASS": "[OK]  ", "WARN": "[WARN]", "FAIL": "[FAIL]"}[r["status"]]
            print(f"{mark} {r['code']} {r['message']}")
        print(f"--- 汇总: PASS {len(results)-len(fails)-len(warns)} / WARN {len(warns)} / FAIL {len(fails)} ---")
        print("结论: " + ("环境就绪，可直接发版" if not fails else "存在阻塞项，按 FAIL 修复后再发版"))

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
