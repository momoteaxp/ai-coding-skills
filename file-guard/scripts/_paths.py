#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目私有最小路径派生（SSOT 契约 L2：COMATE_FG_HOME/FG_HOME env 优先，禁止硬编码路径）。

用法: from _paths import fg_home, rules_dir; 项目内脚本一律经此派生路径。
规则见 docs/SSOT-契约.md（L0 全局层 / L2 项目层）。
"""
import os
from pathlib import Path

FALLBACK_HOME = str(Path.home() / "comate")


def fg_home() -> Path:
    """受管根目录: env COMATE_FG_HOME 优先, 兼容 FG_HOME, 缺省 %USERPROFILE%/comate。"""
    return Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or FALLBACK_HOME)


def rules_dir() -> Path:
    """C0 规则目录（全局唯一规则真源）: fg_home()/_rules。"""
    return fg_home() / "_rules"


def suite_dir() -> Path:
    """套件目录: env FILEGUARD_SUITE_SUBDIR / FG_SUITE_REL 覆盖, 缺省 产品/file-guard。"""
    rel = (os.environ.get("FILEGUARD_SUITE_SUBDIR")
           or os.environ.get("FG_SUITE_REL")
           or "产品/file-guard")
    return fg_home() / rel
