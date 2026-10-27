#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目私有最小路径派生（SSOT 契约 L2：FG_HOME env 优先，禁止硬编码路径）。

用法: from _paths import fg_home, rules_dir; 项目内脚本一律经此派生路径。
规则见 docs/SSOT-契约.md（L0 全局层 / L2 项目层）。
"""
import os
from pathlib import Path

FALLBACK_HOME = "D:/comate"


def fg_home() -> Path:
    """受管根目录: env FG_HOME 优先, 缺省 D:/comate。"""
    return Path(os.environ.get("FG_HOME", FALLBACK_HOME))


def rules_dir() -> Path:
    """C0 规则目录（全局唯一规则真源）: fg_home()/_rules。"""
    return fg_home() / "_rules"
