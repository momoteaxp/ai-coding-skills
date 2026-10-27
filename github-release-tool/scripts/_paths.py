#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""github-release-tool — 项目私有路径派生（FG_HOME env 优先，禁止硬编码路径）。

用法: from _paths import ...; 脚本一律经此派生路径（对齐受管项目体系 SSOT 契约 L2）。
"""
import os
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent


def fg_home() -> Path:
    """受管根目录: env FG_HOME 优先, 缺省 D:/comate。"""
    return Path(os.environ.get("FG_HOME", "D:/comate"))


def rules_dir() -> Path:
    """C0 规则/登记目录（全局唯一真源）: fg_home()/_rules。"""
    return fg_home() / "_rules"


def managed_projects_path() -> Path:
    """受管项目中央登记表。"""
    return rules_dir() / "managed-projects.json"


def config_path() -> Path:
    return PROJ_ROOT / "config" / "release-config.json"


def manifest_path() -> Path:
    return PROJ_ROOT / "data" / "release-manifest.json"


def templates_dir() -> Path:
    return PROJ_ROOT / "skills" / "github-publish" / "templates"
