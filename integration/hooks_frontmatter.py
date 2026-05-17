"""
YAML Frontmatter Hooks
技能文件可声明 pre/post_tool_use hooks，工具生命周期自动触发。
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger("hooks_frontmatter")

@dataclass
class HookSpec:
    """单个 hook 定义。"""
    type: str = "command"    # command | python
    command: str = ""        # shell 命令
    tool: str = ""           # 匹配的工具名（空=所有）
    on_error: str = "ignore" # ignore | fail | warn

@dataclass
class FrontmatterHooks:
    """从技能文件 frontmatter 解析出的 hooks。"""
    pre_tool_use: list[HookSpec] = field(default_factory=list)
    post_tool_use: list[HookSpec] = field(default_factory=list)
    on_session_start: list[HookSpec] = field(default_factory=list)
    on_session_end: list[HookSpec] = field(default_factory=list)

def parse_hooks_from_frontmatter(meta: dict) -> FrontmatterHooks:
    """
    从技能文件 frontmatter dict 解析 hooks。
    对应 registerFrontmatterHooks。

    示例 frontmatter：
    ```yaml
    hooks:
      pre_tool_use:
        - tool: bash
          command: "echo '即将执行 bash'"
      post_tool_use:
        - command: "git status"
    ```
    """
    hooks_meta = meta.get("hooks", {})
    if not isinstance(hooks_meta, dict):
        return FrontmatterHooks()

    def _parse_hook_list(raw) -> list[HookSpec]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(HookSpec(
                    type=item.get("type", "command"),
                    command=item.get("command", ""),
                    tool=item.get("tool", ""),
                    on_error=item.get("on_error", "ignore"),
                ))
            elif isinstance(item, str):
                result.append(HookSpec(command=item))
        return result

    return FrontmatterHooks(
        pre_tool_use=_parse_hook_list(hooks_meta.get("pre_tool_use", [])),
        post_tool_use=_parse_hook_list(hooks_meta.get("post_tool_use", [])),
        on_session_start=_parse_hook_list(hooks_meta.get("on_session_start", [])),
        on_session_end=_parse_hook_list(hooks_meta.get("on_session_end", [])),
    )

class HooksRunner:
    """执行 frontmatter hooks。"""

    def __init__(self, cwd: str = "."):
        self.cwd = cwd
        self._hooks: FrontmatterHooks = FrontmatterHooks()

    def load_from_skill(self, skill_meta: dict) -> None:
        """从技能文件元数据加载 hooks。"""
        self._hooks = parse_hooks_from_frontmatter(skill_meta)

    def run_pre_tool_use(self, tool_name: str, args: dict) -> bool:
        """执行 pre_tool_use hooks，返回 False 表示应阻止工具执行。"""
        return self._run_hooks(self._hooks.pre_tool_use, tool_name, {"args": args})

    def run_post_tool_use(self, tool_name: str, result) -> bool:
        """执行 post_tool_use hooks。"""
        return self._run_hooks(self._hooks.post_tool_use, tool_name,
                               {"result": str(result)[:200] if result else ""})

    def run_session_start(self) -> None:
        self._run_hooks(self._hooks.on_session_start, "", {})

    def run_session_end(self) -> None:
        self._run_hooks(self._hooks.on_session_end, "", {})

    def _run_hooks(self, hooks: list[HookSpec], tool_name: str,
                   context: dict) -> bool:
        """运行 hook 列表，返回是否继续执行。"""
        for hook in hooks:
            # 检查是否匹配工具名
            if hook.tool and hook.tool != tool_name:
                continue
            try:
                if hook.type == "command" and hook.command:
                    self._run_command_hook(hook, context)
            except Exception as e:
                if hook.on_error == "fail":
                    logger.error(f"[Hooks] hook 失败，阻止执行: {e}")
                    return False
                elif hook.on_error == "warn":
                    logger.warning(f"[Hooks] hook 失败（继续）: {e}")
                else:
                    logger.debug(f"[Hooks] hook 失败（忽略）: {e}")
        return True

    def _run_command_hook(self, hook: HookSpec, context: dict) -> None:
        """执行 shell 命令 hook。"""
        cmd = hook.command
        # 简单的上下文变量替换
        for k, v in context.items():
            cmd = cmd.replace(f"{{{k}}}", str(v)[:100])

        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=self.cwd, timeout=10
        )
        if result.returncode != 0 and hook.on_error != "ignore":
            raise RuntimeError(
                f"Hook 命令失败 (rc={result.returncode}): {result.stderr[:200]}"
            )
        if result.stdout:
            logger.debug(f"[Hooks] hook 输出: {result.stdout[:200]}")

# ── 全局 hooks 注册表 ─────────────────────────────────────────────────────────

_session_hooks: list[Callable] = []

def register_session_hook(fn: Callable, event: str = "post_tool_use") -> None:
    """注册全局会话 hook（Python 函数）。"""
    _session_hooks.append((event, fn))

def fire_global_hooks(event: str, **kwargs) -> None:
    """触发全局 hooks。"""
    for ev, fn in _session_hooks:
        if ev == event:
            try:
                fn(**kwargs)
            except Exception as e:
                logger.debug(f"[Hooks] 全局 hook 异常: {e}")
