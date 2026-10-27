#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileGuard Trash CLI — 管理 <FG_HOME>\\_trash 回收站（comate 侧缺省 %USERPROFILE%\\comate；2026-10-27 修正 project 残留默认）

用法：
  python trash-cli.py list [--days N]           # 列出 trash 内容
  python trash-cli.py restore <rel-path>|--all   # 恢复文件到 FG_HOME 原位置
  python trash-cli.py clean [--days N] [--dry-run]  # 清理超过 N 天的文件（默认 30）

设计原则：
- 目录结构保留相对路径，便于恢复时推断原位置
- auto/ = FSW/L4 自动归位移入；manual/ = 人工/AI 指令移入
- 日期子目录（YYYY-MM-DD）便于按时间批量清理
"""
import json
import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# 根目录支持 COMATE_FG_HOME/FG_HOME 环境变量覆盖（换机/换盘时无需改代码）；缺省回退 %USERPROFILE%/comate（comate 套件侧；原 project 残留已修正）
FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
TRASH_ROOT = FG_HOME / "_trash"
FG_ROOT = FG_HOME

# ---- Windows 保留设备名兜底回收（nul 清理兜底）----
# 规则源：C0 rules.reserved_device_names.names（与 enforcer.js RESERVED_DEVICE_FALLBACK
#         及 scratch-clean.py 保持一致，doctor 会校验双侧一致）。
# 说明：git-bash（MSYS）下 >nul / 2>nul 会生成真实文件且 PS/cmd 常规手段无法删除；
#       os.stat/os.path.exists 对这类名字不可靠，且新文件 mtime 是新的 —— 故无条件回收。
_C0_PATH = FG_HOME / "_rules" / "global-rules.json"
RESERVED_DEVICE_FALLBACK = ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
_RESERVED_CACHE = None


def reserved_device_names():
    """读 C0 保留设备名清单；C0 缺失/失效时回退内置（与 C0 当前值一致）。"""
    global _RESERVED_CACHE
    if _RESERVED_CACHE is not None:
        return _RESERVED_CACHE
    names = None
    try:
        with open(_C0_PATH, "r", encoding="utf-8") as f:
            names = json.load(f).get("rules", {}).get("reserved_device_names", {}).get("names")
    except Exception:
        names = None
    if not isinstance(names, list) or not names:
        names = RESERVED_DEVICE_FALLBACK
    _RESERVED_CACHE = {str(n).lower() for n in names}
    return _RESERVED_CACHE


def is_reserved_device(p: Path) -> bool:
    """按 Win32 语义判定文件名是否为保留设备名（含扩展名亦保留，如 nul.txt）。"""
    name = p.name.lower()
    if not name:
        return False
    base = name if name.startswith(".") else name.split(".", 1)[0]
    return base in reserved_device_names()


def _safe_unlink(p: Path) -> None:
    """删除文件；保留设备名等 Win32 特殊路径改走 \\\\?\\ 扩展前缀。

    实测坑点：os.path.abspath() 对保留设备名会返回错误路径
    （'D:\\...\\nul' -> '\\\\.\\nul'，随后 \\\\?\\ 前缀拼接必然 WinError 123），
    故必须由父目录（绝不可能命中保留设备名）拼出绝对路径再加前缀。
    """
    s = os.fspath(p)
    try:
        os.unlink(s)
        return
    except OSError:
        pass
    parent = os.path.dirname(s) or os.getcwd()
    if not os.path.isabs(parent):
        parent = os.path.abspath(parent)
    parent = os.path.normpath(parent)
    os.unlink(chr(92) + chr(92) + "?" + chr(92) + parent + chr(92) + p.name)


def ensure_trash():
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)

def parse_date_from_path(rel: Path):
    """从路径中提取日期（auto/YYYY-MM-DD/ 或 manual/YYYY-MM-DD/）"""
    parts = rel.parts
    if len(parts) >= 2 and parts[0] in ("auto", "manual"):
        try:
            return datetime.strptime(parts[1], "%Y-%m-%d")
        except ValueError:
            pass
    return None

def list_trash(days=None):
    """列出 trash 内容"""
    ensure_trash()
    cutoff = datetime.now() - timedelta(days=days) if days else None
    items = []
    
    for root, dirs, files in os.walk(TRASH_ROOT):
        for f in files:
            p = Path(root) / f
            rel = p.relative_to(TRASH_ROOT)
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            item_date = parse_date_from_path(rel) or mtime
            
            if cutoff and item_date < cutoff:
                continue
            
            # 推断原位置
            parts = rel.parts
            if len(parts) >= 3 and parts[0] in ("auto", "manual"):
                origin = Path(*parts[2:])
            else:
                origin = rel
            
            items.append({
                "rel": rel,
                "origin": origin,
                "mtime": mtime,
                "size": p.stat().st_size,
                "date": item_date
            })
    
    if not items:
        scope = f"（{days} 天内）" if days else ""
        print(f"[FileGuard] Trash 为空{scope}")
        return
    
    print(f"[FileGuard] Trash 内容（共 {len(items)} 项）：")
    print(f"{'相对路径':<50} {'原位置':<40} {'日期':<12} {'大小':>10}")
    print("-" * 120)
    
    for item in sorted(items, key=lambda x: x["date"], reverse=True):
        rel_str = str(item["rel"])[:48]
        origin_str = str(item["origin"])[:38]
        date_str = item["date"].strftime("%Y-%m-%d")
        size_str = f"{item['size']:,} B"
        print(f"{rel_str:<50} {origin_str:<40} {date_str:<12} {size_str:>10}")

def restore(target):
    """恢复文件到 FG_HOME 原位置"""
    ensure_trash()
    
    if target == "--all":
        restored = 0
        failed = 0
        
        for root, dirs, files in os.walk(TRASH_ROOT):
            for f in files:
                src = Path(root) / f
                rel = src.relative_to(TRASH_ROOT)
                parts = rel.parts
                
                # 推断原位置
                if len(parts) >= 3 and parts[0] in ("auto", "manual"):
                    origin_rel = Path(*parts[2:])
                else:
                    origin_rel = rel
                
                dst = FG_ROOT / origin_rel
                
                # 防覆盖：目标已存在则跳过
                if dst.exists():
                    print(f"  [跳过] 目标已存在：{dst}")
                    failed += 1
                    continue
                
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(src), str(dst))
                    print(f"  [恢复] {rel} -> {dst}")
                    restored += 1
                except Exception as e:
                    print(f"  [失败] {rel}: {e}")
                    failed += 1
        
        print(f"[FileGuard] 恢复完成：{restored} 成功，{failed} 跳过/失败")
    else:
        # 恢复单个文件
        src = TRASH_ROOT / target
        if not src.exists():
            print(f"[FileGuard] 错误：{target} 不在 trash 中")
            sys.exit(1)
        
        rel = src.relative_to(TRASH_ROOT)
        parts = rel.parts
        if len(parts) >= 3 and parts[0] in ("auto", "manual"):
            origin_rel = Path(*parts[2:])
        else:
            origin_rel = rel
        
        dst = FG_ROOT / origin_rel
        if dst.exists():
            print(f"[FileGuard] 错误：目标已存在 {dst}，请先处理冲突")
            sys.exit(1)
        
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"[FileGuard] 恢复：{target} -> {dst}")

def clean(days=30, dry_run=False):
    """清理超过 N 天的文件"""
    ensure_trash()
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    total_size = 0
    empty_dirs = []
    
    # 先收集待删除文件
    to_remove = []
    for root, dirs, files in os.walk(TRASH_ROOT):
        for f in files:
            p = Path(root) / f
            if is_reserved_device(p):
                # 保留设备名：绕过 TTL 无条件回收（stat 对这类名字不可靠）
                to_remove.append(p)
                continue
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime)
            except OSError:
                continue
            item_date = parse_date_from_path(p.relative_to(TRASH_ROOT)) or mtime
            
            if item_date < cutoff:
                to_remove.append(p)
    
    if not to_remove:
        print(f"[FileGuard] 无需要清理的文件（>{days} 天）")
        return
    
    for p in to_remove:
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        rel = p.relative_to(TRASH_ROOT)
        if dry_run:
            print(f"  [dry-run] 将删除：{rel}")
        else:
            try:
                _safe_unlink(p)
                print(f"  [删除] {rel}")
            except OSError as e:
                print(f"  [失败] {rel}: {e}")
                continue
        removed += 1
        total_size += size
    
    # 清理空目录（不删除 dry_run）
    if not dry_run:
        for root, dirs, files in os.walk(TRASH_ROOT, topdown=False):
            for d in dirs:
                dp = Path(root) / d
                try:
                    dp.rmdir()
                except OSError:
                    pass
    
    action = "将清理" if dry_run else "已清理"
    print(f"[FileGuard] {action} {removed} 项，释放 {total_size:,} bytes（>{days} 天）")

def main():
    parser = argparse.ArgumentParser(
        description="FileGuard Trash CLI — 回收站管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python trash-cli.py list                    # 列出全部
  python trash-cli.py list --days 7           # 只列最近 7 天
  python trash-cli.py restore --all          # 恢复全部
  python trash-cli.py restore auto/2026-09-17/test.txt  # 恢复单个
  python trash-cli.py clean --dry-run         # 预览清理（默认 30 天）
  python trash-cli.py clean --days 7          # 清理超过 7 天的
        """
    )
    sub = parser.add_subparsers(dest="command", help="子命令")
    
    p_list = sub.add_parser("list", help="列出 trash 内容")
    p_list.add_argument("--days", type=int, help="只列 N 天内的文件")
    
    p_restore = sub.add_parser("restore", help="恢复文件到原位置")
    p_restore.add_argument("target", help="文件相对路径（如 auto/2026-09-17/test.txt）或 --all")
    
    p_clean = sub.add_parser("clean", help="清理旧文件")
    p_clean.add_argument("--days", type=int, default=30, help="清理超过 N 天的文件（默认 30）")
    p_clean.add_argument("--dry-run", action="store_true", help="只预览不删除")
    
    args = parser.parse_args()
    
    if args.command == "list":
        list_trash(args.days)
    elif args.command == "restore":
        restore(args.target)
    elif args.command == "clean":
        clean(args.days, args.dry_run)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
