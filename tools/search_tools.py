"""
搜索工具集
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from tools.base import BaseTool, ToolContext, ToolResult

_MAX_RESULTS = 200
_MAX_OUTPUT_CHARS = 60_000

def _resolve_path(path: str, cwd: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()

# ─── GrepTool ─────────────────────────────────────────────────────────────────

class GrepTool(BaseTool):
    """
    正则搜索文件内容，。
    优先使用 ripgrep（rg），回退 Python re。
    """

    name = "grep"
    description = (
        "在文件或目录中正则搜索。"
        "返回匹配行（含文件名和行号）。"
        "支持 glob 过滤，默认搜索当前工作目录。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "正则表达式模式（ECMAScript/PCRE 风格）",
            },
            "path": {
                "type": "string",
                "description": "搜索目录或文件（默认 cwd）",
            },
            "glob": {
                "type": "string",
                "description": "文件名过滤 glob（如 '*.py'、'*.{ts,js}'）",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "是否大小写敏感（默认 false）",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": f"最大结果数（默认 {_MAX_RESULTS}）",
                "default": _MAX_RESULTS,
            },
        },
        "required": ["pattern"],
    }
    is_read_only = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        pattern = args["pattern"]
        search_path = _resolve_path(args.get("path", "."), ctx.cwd)
        glob_pat = args.get("glob")
        case_sensitive = args.get("case_sensitive", False)
        max_results = min(int(args.get("max_results", _MAX_RESULTS)), 500)

        if not search_path.exists():
            return ToolResult(content=f"路径不存在：{search_path}", is_error=True)

        # 尝试 ripgrep
        rg_result = self._try_ripgrep(
            pattern, search_path, glob_pat, case_sensitive, max_results
        )
        if rg_result is not None:
            return rg_result

        # 回退 Python re
        return self._python_grep(
            pattern, search_path, glob_pat, case_sensitive, max_results
        )

    def _try_ripgrep(
        self,
        pattern: str,
        path: Path,
        glob: str | None,
        case_sensitive: bool,
        max_results: int,
    ) -> ToolResult | None:
        """尝试调用系统 rg 命令。失败则返回 None。"""
        cmd = ["rg", "--line-number", "--no-heading",
               f"--max-count={max_results}", pattern, str(path)]
        if glob:
            cmd.extend(["--glob", glob])
        if not case_sensitive:
            cmd.append("--ignore-case")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15
            )
            output = result.stdout
            if len(output) > _MAX_OUTPUT_CHARS:
                output = output[:_MAX_OUTPUT_CHARS] + "\n...[结果截断]"
            lines = output.strip().splitlines()
            count = len(lines)
            header = f"找到 {count} 处匹配（pattern={pattern!r}）\n\n"
            return ToolResult(content=header + output if output else header + "(无匹配)")
        except FileNotFoundError:
            return None  # rg 不存在
        except Exception:
            return None

    def _python_grep(
        self,
        pattern: str,
        path: Path,
        glob: str | None,
        case_sensitive: bool,
        max_results: int,
    ) -> ToolResult:
        """Python re 回退实现。"""
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(content=f"无效正则：{e}", is_error=True)

        matches: list[str] = []
        files_to_search: list[Path] = []

        if path.is_file():
            files_to_search = [path]
        else:
            for root, _, files in os.walk(path):
                for f in files:
                    fp = Path(root) / f
                    if glob and not fnmatch.fnmatch(f, glob):
                        continue
                    files_to_search.append(fp)

        for fp in files_to_search:
            if len(matches) >= max_results:
                break
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.splitlines(), 1):
                    if compiled.search(line):
                        matches.append(f"{fp}:{i}: {line}")
                        if len(matches) >= max_results:
                            break
            except Exception:
                continue

        output = "\n".join(matches)
        header = f"找到 {len(matches)} 处匹配（pattern={pattern!r}）\n\n"
        return ToolResult(content=header + (output or "(无匹配)"))

    def is_concurrency_safe(self, args: dict) -> bool:
        return True

# ─── GlobTool ─────────────────────────────────────────────────────────────────

class GlobTool(BaseTool):
    """
    按 glob 模式列出文件。
    """

    name = "glob"
    description = (
        "按 glob 模式列出文件（如 '**/*.py'、'src/**/*.ts'）。"
        "结果按修改时间倒序，显示相对路径。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob 模式（如 '**/*.py'）",
            },
            "path": {
                "type": "string",
                "description": "搜索根目录（默认 cwd）",
            },
            "max_results": {
                "type": "integer",
                "description": "最大文件数（默认 200）",
                "default": 200,
            },
        },
        "required": ["pattern"],
    }
    is_read_only = True

    def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        pattern = args["pattern"]
        base = _resolve_path(args.get("path", "."), ctx.cwd)
        max_results = min(int(args.get("max_results", 200)), 1000)

        if not base.exists():
            return ToolResult(content=f"目录不存在：{base}", is_error=True)

        try:
            matches = sorted(
                base.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:max_results]
        except Exception as e:
            return ToolResult(content=f"glob 错误：{e}", is_error=True)

        if not matches:
            return ToolResult(content=f"未找到匹配文件：{pattern}")

        lines = []
        for p in matches:
            try:
                rel = p.relative_to(base)
            except ValueError:
                rel = p
            size = p.stat().st_size if p.is_file() else 0
            lines.append(f"{rel}  ({size} B)" if p.is_file() else str(rel))

        output = "\n".join(lines)
        header = f"找到 {len(matches)} 个文件（pattern={pattern!r}）\n\n"
        return ToolResult(content=header + output)

    def is_concurrency_safe(self, args: dict) -> bool:
        return True
