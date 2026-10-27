#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — sandbox.json 权限生成器（L1 静态权限层）

生成 comate 原生 sandbox.json（L1 静态权限层）。schema 已对照客户端官方定义校准：
    E:\\Programs\\Comate\\resources\\app\\extensions\\baiducomate.comate\\schema\\sandbox-config.schema.json

官方 schema 要点（2026-10-22 校准）:
    - 合法字段仅 7 个（additionalProperties:false）: $schema / allowRead / allowWrite / denyRead / denyWrite / allowedDomains / deniedDomains
    - 全局 ~/.comate/sandbox.json + 项目级 <workspace>/.comate/sandbox.json 合并生效
    - 路径支持 glob：~/foo→$HOME/foo；裸名锚到 sourceRoot；末尾 / 覆盖子树；跨层级需显式写 **
    - 优先级: allowRead > denyRead；denyWrite > allowWrite；deniedDomains > allowedDomains
    - 仅 sandboxAuto 模式生效（客户端设置里启用沙箱自动模式）

用法:
    python scripts/sandbox-gen.py                 # 仅打印生成内容（预览）
    python scripts/sandbox-gen.py --write-project # 写入本项目 .comate/sandbox.json（工作区内）
    python scripts/sandbox-gen.py --write-global  # 写入 ~/.comate/sandbox.json（全局）
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8，任何调用方式下 print 不因 GBK 崩溃（→ 等字符安全）
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJ_ROOT = Path(__file__).parent.parent.resolve()

SCHEMA_REF = "https://json-schema.org/draft-07/schema#"

# ---- 安全基准（L1 静态层；L2 放置规则仍由 enforcer/project_meta 负责） ----
SECRET_PATTERNS = [
    "**/.env",
    "**/.env.*",
    "**/.npmrc",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/credentials.json",
    "**/credentials*.json",
    "**/secrets.*",
    "**/id_rsa",
    "**/id_ed25519",
    "**/.git/**",          # git 历史可能含旧凭据（官方 schema 示例同口径）
    "~/.ssh/**",
    "~/.aws/**",
    "~/.gnupg/**",
]
DENY_WRITE_PATTERNS = [
    "C:/Windows/**",
    "C:/Program Files/**",
    "C:/Program Files (x86)/**",
    "**/_trash/**",        # L2 已拦，L1 兜底
]
ALLOWED_DOMAINS = [
    "github.com",
    "*.github.com",
    "raw.githubusercontent.com",
    "api.github.com",
    "pypi.org",
    "*.pypi.org",
    "files.pythonhosted.org",
    "npmjs.com",
    "*.npmjs.com",
    "registry.npmjs.org",
    "mirrors.aliyun.com",
    "*.aliyun.com",
]
DENIED_DOMAINS: list[str] = []


def build_sandbox() -> dict:
    """生成 sandbox.json（仅含官方 schema 合法字段；deny 优先，fail-closed）。"""
    return {
        "$schema": SCHEMA_REF,
        "allowRead": [],
        "allowWrite": [],
        "denyRead": SECRET_PATTERNS,
        "denyWrite": DENY_WRITE_PATTERNS,
        "allowedDomains": ALLOWED_DOMAINS,
        "deniedDomains": DENIED_DOMAINS,
    }


def validate(sb: dict) -> bool:
    """对照官方 schema 校验：仅 7 个合法键、值为非空字符串数组。"""
    legal = {"$schema", "allowRead", "allowWrite", "denyRead", "denyWrite", "allowedDomains", "deniedDomains"}
    keys = set(sb.keys())
    if not keys <= legal:
        print(f"[FAIL] 含 schema 外字段: {keys - legal}（additionalProperties:false 会拒绝）", file=sys.stderr)
        return False
    for k in keys - {"$schema"}:
        v = sb[k]
        if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
            print(f"[FAIL] 字段 {k} 须为非空字符串数组", file=sys.stderr)
            return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard (Comate) sandbox.json 权限生成器")
    ap.add_argument("--write-project", action="store_true", help="写入本项目 .comate/sandbox.json（工作区内）")
    ap.add_argument("--write-global", action="store_true", help="写入 ~/.comate/sandbox.json（全局）")
    args = ap.parse_args()

    sb = build_sandbox()
    if not validate(sb):
        return 1
    text = json.dumps(sb, ensure_ascii=False, indent=2) + "\n"

    if args.write_project:
        dst = PROJ_ROOT / ".comate" / "sandbox.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        print(f"[OK] 已写入项目级: {dst}")
        return 0

    if args.write_global:
        home = Path(os.environ.get("USERPROFILE", ""))
        dst = home / ".comate" / "sandbox.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        print(f"[OK] 已写入全局: {dst}（影响所有 comate 会话，sandboxAuto 模式下生效，重启客户端后应用）")
        return 0

    print(text)
    print("\n[预览] 用 --write-project（项目级）或 --write-global（全局）落盘。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
