#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileGuard (Comate) — PreToolUse 钩子（写前拦截 + checkpoint 跨项目读取拦截）

从 stdin 读取 comate hook JSON（tool_name / tool_input / cwd），按工具分流：

- 写类（write_file|edit_file|delete_file|apply_patch）：用 enforcer.py 做规则校验
  （C0 黑名单 / _trash / 只读 / 目录白名单），exit 0/2；
- 读类（read_file|grep_content|glob_path|list_dir|read_lints|run_command）：checkpoint
  跨项目读取拦截，对齐 C0 rules.checkpoint（read_scope=current_project_only 时启用，
  read_vectors 控制扫描工具；引擎工具名经 _VECTOR_ALIAS 归一为 C0 旧名 read/grep/glob/bash；
  当前会话项目根 = env FILEGUARD_CURRENT_DIR（规则文档 read_scope_note 预留的显式覆盖）
  显式声明；无声明 → 仅告警放行（不硬拦，cwd 只用于放行侧比对）；
  显式逃生通道 checkpoint-manager.py load --project）。
  2026-10-23/26 修复：曾从 cwd 猜会话项目导致误拦——引擎 read_file 与 run_command 的
  payload cwd 均不可靠（真实会话中在 comate/project file-guard/other-project 间漂移，
  见 _checkpoint/latest.json 读取与 `doctor --session <_checkpoint 路径>` 被拦事件）；
  绝不回退 os.getcwd()（那是客户端 spawn 钩子进程的目录，不等于会话目录）。
- run_command 另查"引号铁律"：内联代码（python -c / sh -c / heredoc）strict 项目拦截，
  提示先落盘 _scratch\\tmp-*.py（根治命令行→PowerShell→解释器多层吞引号，2026-10-23 定案）。

约定（与官方 hooks-guide 对齐）：
    exit 0  — 放行
    exit 2  — 拦截（stderr 内容会反馈给 comate 会话）

2026-10-23 校准：引擎工具名为 Agent 风格小写（write_file/run_command 等），
hooks.json matcher 与脚本分流均用引擎名；enforcer.py 为本套件 scripts/ 独立单源。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Windows 中文环境：强制本进程 stdin/stdout/stderr 用 UTF-8
for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- comate 侧受管根（环境变量可覆盖） ----
COMATE_FG_HOME = Path(os.environ.get("COMATE_FG_HOME") or os.environ.get("FG_HOME") or r"D:\comate")
META_NAME = "project_meta.json"
MAX_META_DEPTH = 2
# 引擎实际工具名（2026-10-23 校准：Comate 引擎为 Agent 风格小写名，
# 非 IDE 界面名 Write/Edit/Bash——hooks matcher 与脚本分流必须用它）
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "apply_patch"}
READ_TOOLS = {"read_file", "grep_content", "glob_path", "list_dir", "read_lints", "run_command"}
# ---- enforcer.py（本套件独立单源，与本脚本同目录） ----
ENFORCER = Path(__file__).resolve().parent / "enforcer.py"

# ---- 引号铁律：禁止内联代码（根治"引号炸了"，2026-10-23 定案） ----
# 命令内联代码（python -c / sh -c / heredoc）经"命令行→PowerShell→解释器"多层解析必吞引号。
# 规则：含代码的命令一律先落盘 _scratch\\tmp-*.py 再执行（命令行只传路径，永不传代码）。
INLINE_PATTERNS = [
    r"\b(?:python|python3|py)\s+-\s*c\b",              # python -c
    r"\b(?:sh|bash)\s+-\s*c\b",                        # sh -c / bash -c
    r"\b(?:powershell|pwsh)\s+-\s*c\b",                # powershell -c
    r"\bpowershell\s+-(?:command|Command)\b",          # powershell -command
    r"<<\s*['\"]?[A-Za-z0-9_]+",                       # heredoc <<EOF / <<'EOF'
]


def find_inline_code(cmd: str) -> str | None:
    """在命令串中找内联代码特征；无则 None。

    引号包裹内容掩码为 "Q"/'Q'（保留引号）再匹配：-m 消息文本/路径参数里的
    "python -c"、"<<EOF" 字样不误伤；真内联（python -c print(1)、cat <<'EOF'）仍命中。
    """
    masked = re.sub(r'"[^"]*"|\'[^\']*\'', lambda m: m.group(0)[0] + "Q" + m.group(0)[-1], cmd)
    for pat in INLINE_PATTERNS:
        m = re.search(pat, masked, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def check_command_quoting(tool_name: str, tool_input: dict, cwd: str) -> int:
    """run_command 内联代码拦截（引号铁律）。strict_mode=true 项目拦截（exit 2），其余告警放行。"""
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


def find_meta(target: Path) -> Path | None:
    """从目标所在目录向上查找 project_meta.json，最多 MAX_META_DEPTH 层。

    与 enforcer.py find_meta 对齐（从目录开始向上，非文件本身）。
    """
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


def project_root_of(path_str: str) -> Path | None:
    """路径向上找到所属项目根（含 project_meta.json），无则 None。"""
    if not path_str:
        return None
    meta = find_meta(Path(path_str))
    return meta.parent if meta else None


def write_active_session(cwd: str, session_id: str, conversation_id: str) -> None:
    """活跃会话标记：供 checkpoint-manager.py 无 --session-id 时推断当前窗口（v2 多窗口）。

    conversation_id = 会话 uuid（窗口身份，优先），session_id = 引擎内部 id（回退）。
    降噪（2026-10-25）：id 未变且 5 分钟内已写过 → 跳过写盘，纯读会话不每步写盘。
    fail-safe：任何异常静默忽略，绝不阻断工具调用。
    """
    if not cwd or not (session_id or conversation_id):
        return
    try:
        root = project_root_of(cwd)
        if root is None:
            return
        cp = root / "_checkpoint"
        marker = cp / ".active-session.json"
        if marker.exists():
            try:
                prev = json.loads(marker.read_text(encoding="utf-8"))
                if (str(prev.get("conversation_id") or "") == conversation_id
                        and str(prev.get("session_id") or "") == session_id
                        and _iso_age_seconds(str(prev.get("updated_at") or "")) < 300):
                    return  # id 未变且刚写过 → 不写盘
            except Exception:
                pass
        cp.mkdir(parents=True, exist_ok=True)
        state = {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cwd": cwd,
        }
        marker.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _iso_age_seconds(s: str) -> float:
    """ISO 时间距现在秒数；解析失败返回无穷大（触发重写）。"""
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(s)).total_seconds()
    except Exception:
        return float("inf")


def session_project_root(cwd: str, tool_name: str) -> Path | None:
    """当前会话项目根：仅 env FILEGUARD_CURRENT_DIR（规则 read_scope_note 预留的显式声明）可靠。

    payload cwd 一律不可信——2026-10-26 实测 run_command 的 cwd 同样漂移
    （同会话内 comate → other-project，`doctor --session <_checkpoint 路径>` 被误拦事件），
    与 read_file 同类。无声明 → None，调用方告警放行（cwd 只用于放行侧比对，永不用于硬拦侧）。
    绝不回退 os.getcwd()：那是客户端 spawn 钩子进程的目录，同样不等于会话目录。
    """
    env_dir = os.environ.get("FILEGUARD_CURRENT_DIR")
    if env_dir:
        # 显式声明优先；声明解析不到项目也以声明为准（宁告警不硬猜）
        return project_root_of(env_dir)
    return None


def load_checkpoint_cfg() -> dict:
    """C0 rules.checkpoint 配置（read_scope / read_vectors）；读取失败返回 {}（fail-open）。"""
    try:
        g = json.loads((COMATE_FG_HOME / "_rules" / "global-rules.json").read_text(encoding="utf-8"))
        return (g.get("rules") or {}).get("checkpoint") or {}
    except Exception:
        return {}


def bash_tokens(cmd: str) -> list[str]:
    """命令分词：引号包裹或空白分隔。"""
    return [a or b or c for a, b, c in re.findall(r'"([^"]*)"|\'([^\']*)\'|(\S+)', cmd)]


# C0 read_vectors 用旧名（read/grep/glob/bash），引擎工具名为 Agent 风格——映射归一（2026-10-23）
_VECTOR_ALIAS = {
    "read_file": "read",
    "grep_content": "grep",
    "glob_path": "glob",
    "run_command": "bash",
}


def vector_name(tool_name: str) -> str:
    return _VECTOR_ALIAS.get(tool_name.lower(), tool_name.lower())


def check_checkpoint_read(tool_name: str, tool_input: dict, cwd: str) -> int:
    """checkpoint 跨项目读取拦截。返回 0 放行 / 2 拦截。告警类消息写 stderr 后仍放行。"""
    cfg = load_checkpoint_cfg()
    scope = cfg.get("read_scope") or ""
    vectors = cfg.get("read_vectors") or []
    if scope != "current_project_only":
        return 0  # 规则层面关闭该拦截
    if vectors and vector_name(tool_name) not in {str(v).lower() for v in vectors}:
        return 0  # 该工具不在 read_vectors 内

    cur = session_project_root(cwd, tool_name)
    if cur is None:
        # 会话项目未识别：仅告警放行（对齐 C0 语义：current_project_only 但当前项目未知 → 提示不硬拦）。
        # 读类工具的 cwd 不可信（引擎动态值），不能据此硬拦——误拦"本项目的 checkpoint"就是
        # 2026-10-23 的用户事故；cwd 仅用于下方放行侧比对，若恰好解析到同项目则静默放行不告警。
        warn = True
    else:
        warn = False

    candidates: list[str] = []
    if tool_name == "run_command":
        cmd = (tool_input or {}).get("command") or ""
        # 显式逃生通道：checkpoint-manager.py load --project <目标项目根>（命令不含 _checkpoint token）
        if "checkpoint-manager.py" in cmd and "load" in cmd and "--project" in cmd:
            return 0
        candidates = [t for t in bash_tokens(cmd) if "_checkpoint" in norm(t)]
    else:
        if tool_name in ("read_file", "write_file", "edit_file", "delete_file", "apply_patch"):
            fp = (tool_input or {}).get("file_path") or ""
            if fp:
                candidates.append(fp)
        elif tool_name == "grep_content":
            p = (tool_input or {}).get("path") or ""
            if p:
                candidates.append(p)
        elif tool_name == "glob_path":
            td = (tool_input or {}).get("target_directory") or ""
            pat = (tool_input or {}).get("pattern") or ""
            if td:
                candidates.append(td)
            if "_checkpoint" in norm(pat):
                joined = os.path.join(td, pat) if td and not os.path.isabs(pat) else pat
                candidates.append(joined)

    cwd_hint = project_root_of(cwd) if cwd else None
    for c in candidates:
        if "_checkpoint" not in norm(c):
            continue
        own = project_root_of(c)
        if own is None:
            continue  # 目标不属于任何登记项目 → 放行
        if cur is not None and norm(str(own)) == norm(str(cur)):
            continue  # 当前项目自身 checkpoint → 放行
        if cur is not None:
            # 消息打印完整根路径消歧：两个项目可能同名（2026-10-23 事件：comate 与
            # project 各有一个 file-guard，目录名相同，只看名字会自相矛盾）
            print(
                f"[file-guard] 拦截: 跨项目读取 {c}（目标项目 {own.name}（{own}）≠ "
                f"会话项目 {cur.name}（{cur}））；read_scope=current_project_only，"
                "显式逃生通道: checkpoint-manager.py load --project <目标项目根>",
                file=sys.stderr,
            )
            return 2
        # cur 未识别：cwd 提示恰好同项目 → 静默放行；否则告警放行（不硬拦）
        if cwd_hint is not None and norm(str(own)) == norm(str(cwd_hint)):
            continue
        if warn:
            print(
                "[file-guard] 告警: 当前会话项目未识别，checkpoint 跨项目读取保护降级为提示"
                "（read_scope=current_project_only；可用 env FILEGUARD_CURRENT_DIR 显式声明"
                "会话项目根，读类工具才可恢复硬拦）",
                file=sys.stderr,
            )
            warn = False  # 多个候选只告警一次
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

    # 活跃会话标记（v2 多窗口：checkpoint-manager 无 --session-id 时按此推断当前窗口；fail-safe）
    write_active_session(cwd, str(payload.get("session_id") or ""), str(payload.get("conversation_id") or ""))

    # 读类工具：引号铁律（内联代码拦截）+ checkpoint 跨项目读取拦截
    if tool_name in READ_TOOLS:
        qr = check_command_quoting(tool_name, tool_input, cwd)
        if qr:
            return qr
        return check_checkpoint_read(tool_name, tool_input, cwd)

    if tool_name not in WRITE_TOOLS:
        return 0
    if not file_path:
        return 0

    root = norm(str(COMATE_FG_HOME))
    target = norm(file_path)

    # 1. 只管 comate 侧受管根内
    if not (target.startswith(root + "/") or target == root):
        return 0

    # 2. 项目未登记 → 放行 + 提示（登记后自动保护）
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

    # 3. 已登记 → 调 enforcer.py check（FG_HOME 指向 comate 受管根）
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

    code = proc.returncode
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    if code == 0:
        return 0  # 合规放行
    if code == 2:
        print(f"[file-guard] 校验器异常: {err or out}（放行）", file=sys.stderr)
        return 0
    # code == 1：违规拦截
    print(f"[file-guard] 拦截写操作 {tool_name} → {file_path}: {err or out}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
