#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 FileGuard 的路径解析结果，给用户/AI 用，避免猜路径。

用法:
    python scripts/path-info.py
    python scripts/path-info.py --json

优先级:
    1. COMATE_FG_HOME
    2. FG_HOME
    3. %APPDATA%/FileGuard/config.json 的 managed_root
    4. portable.flag -> <suite>/managed
    5. 默认 %USERPROFILE%/comate
"""
import argparse
import json
import os
from pathlib import Path


def user_config_file() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "FileGuard" / "config.json"


def resolve() -> dict:
    suite = Path(__file__).resolve().parent.parent
    source, root = "default", Path.home() / "comate"
    if os.environ.get("COMATE_FG_HOME"):
        source, root = "env:COMATE_FG_HOME", Path(os.environ["COMATE_FG_HOME"])
    elif os.environ.get("FG_HOME"):
        source, root = "env:FG_HOME", Path(os.environ["FG_HOME"])
    else:
        cfg = user_config_file()
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                if data.get("managed_root"):
                    source = "config"
                    raw = os.path.expandvars(os.path.expanduser(str(data["managed_root"])))
                    root = Path(raw)
            except Exception:
                pass
        if source == "default" and (suite / "portable.flag").is_file():
            source, root = "portable", suite / "managed"
    root = Path(root)
    writable = True
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception:
        writable = False
    return {
        "managed_root": str(root),
        "source": source,
        "exists": root.exists(),
        "writable": writable,
        "config_file": str(user_config_file()),
        "suite_dir": str(suite),
        "portable": (suite / "portable.flag").is_file(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="FileGuard 路径解析")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    info = resolve()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for k, v in info.items():
            print(f"{k}: {v}")
    return 0 if info["writable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
