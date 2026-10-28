# -*- coding: utf-8 -*-
"""
git-watchdog.py — FileGuard 持续 git 管理 / 里程碑提交提醒

职责：在项目根检测 git 工作树状态，批量操作后自动提醒未提交变更。
模式：
  - remind  （默认）：只返回状态 + 提醒，不执行任何 git 命令
  - auto    ：在 auto_commit_scenes 匹配的 milestone 场景下自动提交

用法（命令行）：
    python tools/git-watchdog.py --project D:/project/产品/skill/demo-project [--scene migrate]

用法（导入）：
    from git_watchdog import check_status, suggest_commit_msg
    ok, result = check_status(project_root)
"""

import os
import re
import json
import sys
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional


META_NAME = "project_meta.json"


class GitStatus(NamedTuple):
    is_dirty: bool
    added: int
    modified: int
    deleted: int
    untracked: int
    files: list[str]
    branch: str


def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """静默运行 git 命令，返回 (rc, stdout, stderr)。"""
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -1, "", "git not found"


def check_status(project_root: str) -> tuple[bool, GitStatus | str]:
    """
    检测项目 git 状态。
    返回 (ok, GitStatus|error_msg)。
    """
    root = Path(project_root).resolve()
    if not (root / ".git").is_dir():
        return True, GitStatus(False, 0, 0, 0, 0, [], "")  # 无 git = 干净，不报错

    rc, out, err = _run_git(["status", "--short", "--branch"], str(root))
    if rc != 0:
        return False, err or out

    added = modified = deleted = untracked = 0
    files: list[str] = []
    branch = ""
    for line in out.strip().splitlines():
        if line.startswith("##"):
            # ## master...origin/master
            branch = line[2:].strip().split("...")[0].split()[-1]
            continue
        if len(line) < 3:
            continue
        xy = line[:2]
        fpath = line[3:]
        files.append(fpath)
        if "?" in xy:
            untracked += 1
        elif "D" in xy:
            deleted += 1
        elif "A" in xy:
            added += 1
        else:
            modified += 1

    return True, GitStatus(
        is_dirty=bool(files),
        added=added,
        modified=modified,
        deleted=deleted,
        untracked=untracked,
        files=files,
        branch=branch,
    )


def suggest_commit_msg(scene: Optional[str], status: GitStatus, project_meta: dict) -> str:
    """根据场景和变更统计生成建议的 commit message。"""
    parts: list[str] = []
    if scene:
        parts.append(scene)
    total = status.added + status.modified + status.deleted + status.untracked
    if total > 0:
        detail_parts: list[str] = []
        if status.added:
            detail_parts.append(f"+{status.added}")
        if status.modified:
            detail_parts.append(f"~{status.modified}")
        if status.deleted:
            detail_parts.append(f"-{status.deleted}")
        if status.untracked:
            detail_parts.append(f"?{status.untracked}")
        parts.append(" | ".join(detail_parts))

    # 尝试从 checkpoint 或 meta 中提取当前任务名
    current_task = ""
    cp_path = Path(project_meta.get("_project_root", "")) / "_checkpoint" / "latest.json"
    if cp_path.exists():
        try:
            with open(cp_path, "r", encoding="utf-8") as f:
                cp = json.load(f)
            current_task = cp.get("current_task", "") or ""
        except Exception:
            pass
    if current_task:
        parts.insert(0, current_task[:60])  # 截断防过长

    msg = " — ".join(parts) if parts else "chore: 自动检测到有未提交变更"
    return msg[:72]  # 截断到 git 推荐长度


def remind_text(status: GitStatus, scene: Optional[str], project_name: str) -> str:
    """生成纯文本提醒，供 AI 读入或展示给用户。"""
    lines: list[str] = []
    lines.append(f"[GitWatchdog] 项目 '{project_name}' 检测到未提交变更：")
    lines.append(f"  分支: {status.branch or '(detached)'}")
    lines.append(f"  新增 {status.added} | 修改 {status.modified} | 删除 {status.deleted} | 未跟踪 {status.untracked}")
    if status.files:
        for f in status.files[:10]:
            lines.append(f"    {f}")
        if len(status.files) > 10:
            lines.append(f"    ... 等共 {len(status.files)} 个文件")
    if scene:
        lines.append(f"  当前场景标签: {scene}")
    lines.append("  建议: 执行 `git add -A && git commit -m \"...\"` 提交本次变更")
    return "\n".join(lines)


def load_git_policy(project_root: str) -> dict:
    """读取 project_meta.json 中的 git_policy 段，返回字典（含安全默认值）。"""
    meta_path = Path(project_root) / META_NAME
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            gp = meta.get("git_policy", {})
            if isinstance(gp, dict):
                return gp
        except Exception:
            pass
    return {"mode": "remind", "threshold": 1, "auto_commit_scenes": []}


def watch(project_root: str, scene: Optional[str] = None, dry_run: bool = False) -> dict:
    """
    主入口：检测 + 决策 + 提醒（或自动提交）。
    返回结果字典，供 caller 解析。
    """
    result: dict = {"project_root": project_root, "scene": scene, "action": "none", "ok": True}

    ok, status_or_err = check_status(project_root)
    if not ok:
        result["ok"] = False
        result["error"] = str(status_or_err)
        return result

    status: GitStatus = status_or_err  # type: ignore
    if not status.is_dirty:
        result["action"] = "clean"
        result["branch"] = status.branch
        return result

    # 有变更，加载策略
    policy = load_git_policy(project_root)
    mode = policy.get("mode", "remind")
    threshold = policy.get("threshold", 1)
    total = status.added + status.modified + status.deleted + status.untracked

    result["status"] = {
        "branch": status.branch,
        "added": status.added,
        "modified": status.modified,
        "deleted": status.deleted,
        "untracked": status.untracked,
        "files": status.files,
    }

    # 低于阈值 = 静默（不提醒）
    if total < threshold:
        result["action"] = "below_threshold"
        result["threshold"] = threshold
        return result

    # 生成建议消息
    meta = {}
    try:
        meta = json.loads((Path(project_root) / META_NAME).read_text(encoding="utf-8"))
    except Exception:
        pass
    commit_msg = suggest_commit_msg(scene, status, meta)
    result["suggested_commit_msg"] = commit_msg
    result["remind_text"] = remind_text(status, scene, meta.get("name", Path(project_root).name))

    # 决策
    if mode == "auto" and scene and scene in policy.get("auto_commit_scenes", []):
        if dry_run:
            result["action"] = "would_auto_commit"
            return result
        # 执行自动提交
        rc, out, err = _run_git(["add", "-A"], project_root)
        if rc != 0:
            result["ok"] = False
            result["error"] = f"git add failed: {err or out}"
            return result
        rc, out, err = _run_git(["commit", "-m", commit_msg], project_root)
        if rc != 0:
            result["ok"] = False
            result["error"] = f"git commit failed: {err or out}"
            return result
        result["action"] = "auto_committed"
        result["commit_msg"] = commit_msg
        return result

    # remind 模式（或 scene 不匹配 auto_commit_scenes）
    result["action"] = "remind"
    return result


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="FileGuard Git Watchdog")
    ap.add_argument("--project", "-p", required=True, help="项目根目录绝对路径")
    ap.add_argument("--scene", "-s", default=None, help="场景标签（如 init / migrate / cleanup）")
    ap.add_argument("--dry-run", action="store_true", help="只检测不执行")
    args = ap.parse_args()

    result = watch(args.project, scene=args.scene, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
