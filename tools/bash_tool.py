"""
BashTool
支持 Windows PowerShell 和 Unix bash。
危险命令需用户确认。
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from typing import ClassVar

from tools.base import BaseTool, PermissionResult, ToolContext, ToolResult
from tools.shell_validator import classify_command, is_read_only as _cmd_is_read_only

# ─── 危险命令检测 ───────────────────────────────────────────────────────────

# 正则：匹配真正危险的命令（数据销毁、格式化、权限提升）
_DANGER_PATTERNS: list[tuple[str, str]] = [
    # 磁盘/分区操作
    (r"\bdd\s+.*of=(/dev/sd|/dev/hd|/dev/nvme|/dev/disk)", "dd 写入磁盘设备"),
    (r"\bmkfs\b", "格式化文件系统"),
    (r"\bfdisk\b|\bparted\b|\bgdisk\b", "分区操作"),
    (r"\bshred\b", "安全擦除文件"),
    # 递归删除（危险路径）
    (r"rm\s+(-\w*f\w*|-\w*r\w*){1,}.*\s+[/~](?!\w)", "递归删除根/家目录"),
    (r"rm\s+(-rf|-fr)\s+[/~]$", "递归删除根目录"),
    (r"rm\s+(-rf|-fr)\s+\*", "递归删除通配符"),
    # Windows 危险
    (r"format\s+[a-zA-Z]:", "格式化磁盘"),
    (r"Remove-Item\s+.*-Recurse.*-Force.*[/\\][^a-zA-Z]", "强制递归删除"),
    # 权限/所有权
    (r"chmod\s+-R\s+777\s+/", "递归 chmod 777 根目录"),
    (r"chown\s+-R.*\s+/", "递归 chown 根目录"),
    # 危险重定向
    (r">\s*/etc/(passwd|shadow|sudoers|crontab)", "覆写系统文件"),
    (r">\s*/dev/(sd|hd|nvme|disk)", "直接写入设备"),
    # fork bomb
    (r":\(\)\s*\{.*:\|:.*\}", "fork bomb"),
]

# 需要确认（可疑但非绝对危险）
_CONFIRM_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+(-\w*r\w*|-\w*f\w*)", "删除文件/目录（含 -r 或 -f）"),
    (r"\bkill\s+(-9|-SIGKILL)\b", "强制终止进程"),
    (r"\bsudo\b", "sudo 提权命令"),
    (r"\bsu\s+-", "切换到 root"),
    (r">\s+/etc/", "写入 /etc/ 目录"),
    (r"\bcurl\b.*\|\s*(ba)?sh\b", "管道执行远程脚本"),
    (r"\bwget\b.*-O\s*-.*\|\s*(ba)?sh\b", "wget 管道执行脚本"),
    # Windows
    (r"\bRemove-Item\b.*-Recurse\b", "PowerShell 递归删除"),
    (r"\bFormat-Volume\b", "格式化卷"),
]

# 超时（秒）
_DEFAULT_TIMEOUT = 30
_MAX_OUTPUT_CHARS = 50_000

def _detect_danger(command: str) -> tuple[bool, str]:
    """
    返回 (is_hard_danger, reason)。
    hard_danger=True → 直接拒绝；False → 需要用户确认。
    """
    for pattern, reason in _DANGER_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, reason
    return False, ""

def _detect_suspicious(command: str) -> tuple[bool, str]:
    """返回 (is_suspicious, reason)，需要用户确认。"""
    for pattern, reason in _CONFIRM_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, reason
    return False, ""

# ─── BashTool ────────────────────────────────────────────────────────────────

class BashTool(BaseTool):
    """
    执行 Shell 命令。
    Windows 用 PowerShell，Unix 用 bash/sh。

    
    """

    name = "bash"
    description = (
        "在当前工作目录执行 Shell 命令（Windows: PowerShell；Unix: bash）。"
        "超时默认 30 秒。危险命令会被拦截或要求确认。"
        "返回 stdout + stderr，非零退出码时 is_error=True。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 30，最大 300）",
                "default": 30,
            },
            "cwd": {
                "type": "string",
                "description": "执行目录（默认为当前工作目录）",
            },
        },
        "required": ["command"],
    }
    is_read_only = False
    is_destructive = False   # 由 check_permission 动态判断

    # 是否 Windows
    IS_WINDOWS: ClassVar[bool] = platform.system() == "Windows"

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        command = args.get("command", "")

        # 先走精确分类器
        level, reason = classify_command(command)
        if level == "deny":
            return PermissionResult(behavior="deny",
                                    message=f"🚫 命令被拒绝（{reason}）：{command!r}")
        if level == "ask":
            # 进一步检查硬拒绝（旧正则保留双保险）
            is_danger, dreason = _detect_danger(command)
            if is_danger:
                return PermissionResult(behavior="deny",
                                        message=f"🚫 命令被拒绝（{dreason}）：{command!r}")
            return PermissionResult(behavior="ask",
                                    message=f"⚠️  命令需要确认（{reason}）：\n  {command}")
        # level == 'safe' → 仍检查硬拒绝（防止白名单绕过）
        is_danger, dreason = _detect_danger(command)
        if is_danger:
            return PermissionResult(behavior="deny",
                                    message=f"🚫 命令被拒绝（{dreason}）：{command!r}")
        return PermissionResult(behavior="allow")

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        command: str = args["command"]
        timeout: int = min(int(args.get("timeout", _DEFAULT_TIMEOUT)), 300)
        cwd: str = args.get("cwd") or ctx.cwd or "."

        try:
            if self.IS_WINDOWS:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive",
                     "-ExecutionPolicy", "Bypass", "-Command", command],
                    capture_output=True, text=True, timeout=timeout, cwd=cwd,
                )
            else:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=cwd,
                    executable="/bin/bash" if os.path.exists("/bin/bash") else None,
                )
        except subprocess.TimeoutExpired:
            return ToolResult(content=f"命令超时（{timeout}s）：{command}", is_error=True)
        except FileNotFoundError as e:
            return ToolResult(content=f"命令未找到：{e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"执行错误：{e}", is_error=True)

        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        output = "\n".join(parts) or "(无输出)"

        # 大输出持久化（比截断更优雅）
        try:
            from executor.tool_result_store import maybe_persist
            output = maybe_persist("bash", output)
        except Exception:
            if len(output) > _MAX_OUTPUT_CHARS:
                output = output[:_MAX_OUTPUT_CHARS] + f"\n...[截断至 {_MAX_OUTPUT_CHARS} 字符]"

        is_error = result.returncode != 0
        if is_error:
            output = f"退出码 {result.returncode}\n{output}"

        return ToolResult(content=output, is_error=is_error)

    def is_concurrency_safe(self, args: dict) -> bool:
        """只读命令可并发执行。"""
        command = args.get("command", "")
        return _cmd_is_read_only(command)
