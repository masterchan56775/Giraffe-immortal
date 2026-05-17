"""
Git Worktree 工具 — 
支持 Coordinator 为每个 Worker 创建隔离工作区。
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from tools.base import BaseTool, PermissionResult, ToolContext, ToolResult

logger = logging.getLogger("worktree_tool")

_VALID_SLUG = re.compile(r'^[a-zA-Z0-9._/-]+$')
_MAX_SLUG_LEN = 64

def _run_git(args: list[str], cwd: str) -> tuple[int, str, str]:
    """运行 git 命令，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def _find_git_root(cwd: str) -> str | None:
    rc, out, _ = _run_git(["rev-parse", "--show-toplevel"], cwd)
    return out if rc == 0 else None

class WorktreeCreateTool(BaseTool):
    """创建 git worktree，供 Coordinator Worker 使用。"""
    name = "worktree_create"
    description = "在新的 git worktree 中创建隔离工作区（用于并行开发）。"
    input_schema = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "分支名（新建或已有）"},
            "slug": {"type": "string",
                     "description": "工作区标识符（字母数字，如 'feature-auth'）"},
            "new_branch": {"type": "boolean",
                           "description": "是否创建新分支（默认 true）", "default": True},
        },
        "required": ["branch", "slug"],
    }
    is_read_only = False

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        slug = args.get("slug", "")
        if not _VALID_SLUG.match(slug) or len(slug) > _MAX_SLUG_LEN:
            return PermissionResult(behavior="deny",
                                    message=f"无效 slug：{slug!r}（只允许字母数字和 .-/_）")
        if ".." in slug or slug.startswith("/"):
            return PermissionResult(behavior="deny", message="slug 不能含路径穿越")
        return PermissionResult(behavior="ask",
                                message=f"即将创建 worktree branch={args.get('branch')} slug={slug}")

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        branch = args["branch"]
        slug = args["slug"]
        new_branch = args.get("new_branch", True)

        git_root = _find_git_root(ctx.cwd)
        if not git_root:
            return ToolResult(content="当前目录不是 git 仓库", is_error=True)

        worktree_path = str(Path(git_root) / ".git" / "worktrees-giraffe" / slug)

        git_args = ["worktree", "add"]
        if new_branch:
            git_args.extend(["-b", branch])
        git_args.extend([worktree_path, branch if not new_branch else "HEAD"])

        rc, out, err = _run_git(git_args, git_root)
        if rc != 0:
            return ToolResult(content=f"创建 worktree 失败：{err}", is_error=True)

        logger.info(f"[Worktree] 创建: {worktree_path} (branch={branch})")
        return ToolResult(
            content=f"✅ Worktree 已创建\n路径: {worktree_path}\n分支: {branch}"
        )

class WorktreeListTool(BaseTool):
    """列出所有 git worktree。"""
    name = "worktree_list"
    description = "列出当前仓库的所有 git worktree。"
    input_schema = {"type": "object", "properties": {}}
    is_read_only = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        git_root = _find_git_root(ctx.cwd)
        if not git_root:
            return ToolResult(content="当前目录不是 git 仓库", is_error=True)
        rc, out, err = _run_git(["worktree", "list", "--porcelain"], git_root)
        if rc != 0:
            return ToolResult(content=f"列出 worktree 失败：{err}", is_error=True)
        return ToolResult(content=f"Git Worktrees:\n\n{out}" if out else "无 worktree")

    def is_concurrency_safe(self, args: dict) -> bool:
        return True

class WorktreeDeleteTool(BaseTool):
    """删除 git worktree。"""
    name = "worktree_delete"
    description = "删除指定的 git worktree（工作完成后清理）。"
    input_schema = {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "要删除的工作区 slug"},
            "force": {"type": "boolean", "description": "强制删除（即使有未提交更改）",
                      "default": False},
        },
        "required": ["slug"],
    }
    is_read_only = False

    def check_permission(self, args: dict, ctx: ToolContext) -> PermissionResult:
        return PermissionResult(
            behavior="ask",
            message=f"即将删除 worktree: {args.get('slug')}，确认？"
        )

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        slug = args["slug"]
        force = args.get("force", False)
        if not _VALID_SLUG.match(slug) or ".." in slug:
            return ToolResult(content="无效 slug", is_error=True)

        git_root = _find_git_root(ctx.cwd)
        if not git_root:
            return ToolResult(content="当前目录不是 git 仓库", is_error=True)

        worktree_path = str(Path(git_root) / ".git" / "worktrees-giraffe" / slug)
        git_args = ["worktree", "remove"]
        if force:
            git_args.append("--force")
        git_args.append(worktree_path)

        rc, out, err = _run_git(git_args, git_root)
        if rc != 0:
            return ToolResult(content=f"删除失败：{err}", is_error=True)
        return ToolResult(content=f"✅ Worktree 已删除: {slug}")
