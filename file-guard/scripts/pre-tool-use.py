#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — PreToolUse 钩子（写前拦截 + checkpoint 裸读/扫描兜底）

从 stdin 读取 comate hook JSON（tool_name / tool_input / cwd），按工具分流：

- 写类（write_file|edit_file|delete_file|apply_patch）：用 enforcer.py 做规则校验
  （C0 黑名单 / _trash / 只读 / 目录白名单），exit 0/2；
- checkpoint：唯一合法入口是项目本地 tools/checkpoint-manager.py。
  直接读写 _checkpoint/latest.json、扫描受管根、或调用套件 scripts/checkpoint-manager.py
  做 save/load → exit 2。hook 不再推断“当前会话属于哪个项目”——
  项目身份由被调用的本地脚本位置决定，不存在跨项目入口。
- run_command 另查“引号铁律”：内联代码（python -c / sh -c / heredoc）strict 项目拦截，
  提示先落盘 _scratch\\tmp-*.py（根治命令行→PowerShell→解释器多层吞引号，2026-10-23 定案）。

约定（与官方 hooks-guide 对齐）：
    exit 0  — 放行
    exit 2  — 拦截（stderr 内容会反馈给 comate 会话）
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- comate 侧受管根（环境变量可覆盖） ----
COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or str(Path.home() / "comate"))
META_NAME = "project_meta.json"
MAX_META_DEPTH = 2
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "apply_patch"}
READ_TOOLS = {"read_file", "grep_content", "glob_path", "list_dir", "read_lints", "run_command"}
ENFORCER = Path(__file__).resolve().parent / "enforcer.py"

CHECKPOINT_TOKENS = ("_checkpoint", "latest.json")
LOCAL_MANAGER_RE = re.compile(r"(?:^|[\\/])tools[\\/]checkpoint-manager\.py\b", re.IGNORECASE)
WORKFLOW_RE = re.compile(r"checkpoint-workflow\.py\b", re.IGNORECASE)
SUITE_RUNTIME_RE = re.compile(r"(?:^|[\\/])scripts[\\/]checkpoint-manager\.py\b", re.IGNORECASE)

# ---- 引号铁律：禁止内联代码 ----
INLINE_PATTERNS = [
    r"\b(?:python|python3|py)\s+-\s*c\b",
    r"\b(?:sh|bash)\s+-\s*c\b",
    r"\b(?:powershell|pwsh)\s+-\s*c\b",
    r"\bpowershell\s+-(?:command|Command)\b",
    r"<<\s*['\"]?[A-Za-z0-9_]+",
]


def find_inline_code(cmd: str) -> str | None:
    """在命令串中找内联代码特征；无则 None。引号内文本掩码，避免误伤消息/路径。"""
    masked = re.sub(r'"[^"]*"|\'[^\']*\'', lambda m: m.group(0)[0] + "Q" + m.group(0)[-1], cmd)
    for pat in INLINE_PATTERNS:
        m = re.search(pat, masked, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def check_command_quoting(tool_name: str, tool_input: dict, cwd: str) -> int:
    """run_command 内联代码拦截；strict_mode=true 项目拦截，其余告警放行。"""
    if tool_name != "run_command":
        return 0
    cmd = (tool_input or {}).get("command") or ""
    if not cmd:
        return 0
    hit = find_inline_code(cmd)
    if not hit:
        return 0
    strict = False
    if cwd:
        meta = find_meta(Path(cwd))
        if meta:
            try:
                strict = bool(json.loads(meta.read_text(encoding="utf-8")).get("strict_mode", False))
            except Exception:
                strict = False
    msg = (f"[file-guard] 拦截: 命令含内联代码（{hit}）。引号多层解析（命令行→PowerShell→解释器）必炸，"
           "违反引号铁律。替代：① 先把代码落盘 _scratch\\tmp-*.py 再执行（python <脚本路径>，零引号）；"
           "② 只读查询 JSON 用 scripts/cquery.py（无需内联）。")
    if strict:
        print(msg, file=sys.stderr)
        return 2
    print(f"[file-guard] 告警: {msg}", file=sys.stderr)
    return 0


def norm(p: str) -> str:
    s = os.path.normpath(os.path.abspath(p)).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        s = s[0].upper() + s[1:]
    return s.lower().rstrip("/")


def managed_roots() -> tuple[str, str]:
    """返回（受管根, 产品根）归一化路径，随 COMATE_FG_HOME 派生。"""
    return norm(str(COMATE_FG_HOME)), norm(str(COMATE_FG_HOME / "products"))


def find_meta(target: Path) -> Path | None:
    """从目标所在目录向上查找 project_meta.json，最多 MAX_META_DEPTH 层。"""
    d = target.parent.resolve() if target.is_file() or not target.exists() else target.resolve()
    for _ in range(MAX_META_DEPTH + 1):
        cand = d / META_NAME
        if cand.is_file():
            return cand
        parent = d.parent
        if parent == d:
            break
        d = parent
    return None


def bash_tokens(cmd: str) -> list[str]:
    """命令分词：引号包裹或空白分隔。"""
    return [a or b or c for a, b, c in re.findall(r'"([^"]*)"|\'([^\']*)\'|(\S+)', cmd)]


def _block(msg: str) -> int:
    print(f"[file-guard] 拦截: {msg}", file=sys.stderr)
    return 2


def check_checkpoint_access(tool_name: str, tool_input: dict) -> int:
    """checkpoint 兜底：只放行本地 tools/checkpoint-manager.py 与分发工作流。

    不再判断“当前项目是谁”：裸读/扫描/套件脚本 save/load 一律拦。
    """
    tool_input = tool_input or {}
    if tool_name == "run_command":
        cmd = tool_input.get("command") or ""
        if not cmd:
            return 0
        if WORKFLOW_RE.search(cmd):
            return 0  # 分发/升级工作流（套件管理面）
        if LOCAL_MANAGER_RE.search(cmd):
            return 0  # 唯一运行时入口
        low = cmd.replace("\\", "/").lower()
        if SUITE_RUNTIME_RE.search(cmd) and re.search(r"\b(?:save|load)\b", low):
            return _block("scripts/checkpoint-manager.py 是分发源，不是运行时；"
                          "请用本项目 tools/checkpoint-manager.py save/load。")
        roots = managed_roots()
        scan_terms = ("get-childitem", "foreach", "-recurse", "*.json", "*.jsonl", "select-string")
        broad = any(norm(t).rstrip("/") in roots for t in bash_tokens(cmd)) \
            and any(t in low for t in scan_terms)
        # 只拦“路径形态”的 checkpoint 目标：D:\...\_checkpoint、latest.json；
        # 不拦 `cquery.py ... dirs._checkpoint` 这种把字段名当参数的查询。
        path_like = []
        for t in bash_tokens(cmd):
            tl = t.replace("\\", "/").lower()
            if any(tok in tl for tok in CHECKPOINT_TOKENS) and ("/" in tl or tl.endswith(".json")):
                path_like.append(t)
        if broad or path_like:
            return _block("禁止直接读取/扫描 checkpoint；"
                          "请用本项目 tools/checkpoint-manager.py load。")
        return 0

    # 文件类工具（读 + 写）：直接指向 checkpoint，或读整个受管根 → 拦
    targets = []
    for key in ("file_path", "path", "target_directory", "pattern"):
        v = tool_input.get(key)
        if v:
            targets.append(str(v))
    for t in targets:
        low = t.replace("\\", "/").lower()
        if any(tok in low for tok in CHECKPOINT_TOKENS):
            return _block(f"禁止直接读写 checkpoint（{t}）；"
                          "请用本项目 tools/checkpoint-manager.py save/load。")
    roots = managed_roots()
    for t in targets:
        if norm(t).rstrip("/") in roots:
            return _block(f"禁止扫描整个受管根（{t}）；只在项目内操作。")
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        print(f"[file-guard] hook stdin 解析失败: {e}", file=sys.stderr)
        return 0  # 解析失败不拦截，避免误伤

    tool_input = payload.get("tool_input") or {}
    tool_name = payload.get("tool_name") or ""
    cwd = payload.get("cwd") or ""
    file_path = tool_input.get("file_path") or ""

    if tool_name in READ_TOOLS:
        qr = check_command_quoting(tool_name, tool_input, cwd)
        if qr:
            return qr
        return check_checkpoint_access(tool_name, tool_input)

    if tool_name not in WRITE_TOOLS:
        return 0

    # 写类：先拦裸写 checkpoint，再走 enforcer
    cr = check_checkpoint_access(tool_name, tool_input)
    if cr:
        return cr
    if not file_path:
        return 0

    root = norm(str(COMATE_FG_HOME))
    target = norm(file_path)
    if not (target.startswith(root + "/") or target == root):
        return 0

    meta = find_meta(Path(file_path))
    if meta is None:
        print(
            f"[file-guard] 提示: {file_path} 所在项目未登记规则，已放行。"
            f"如需防护请在该项目根目录建 {META_NAME}（可让 AI 按模板生成）。",
            file=sys.stderr,
        )
        return 0

    if not ENFORCER.is_file():
        print(f"[file-guard] 未找到 enforcer.py: {ENFORCER}（跳过拦截）", file=sys.stderr)
        return 0

    env = dict(os.environ)
    env["FG_HOME"] = str(COMATE_FG_HOME)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, str(ENFORCER), "check", file_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=25,
        )
    except Exception as e:
        print(f"[file-guard] enforcer 调用失败: {e}（放行）", file=sys.stderr)
        return 0

    if proc.returncode == 0:
        return 0
    if proc.returncode == 2:
        print(f"[file-guard] 校验器异常: {(proc.stderr or proc.stdout or '').strip()}（放行）", file=sys.stderr)
        return 0
    print(f"[file-guard] 拦截写操作 {tool_name} → {file_path}: "
          f"{(proc.stderr or proc.stdout or '').strip()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
