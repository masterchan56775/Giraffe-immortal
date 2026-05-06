"""
SandboxExecutor — 沙箱代码执行
在受控环境中安全执行Python代码
"""
from __future__ import annotations
import builtins as _builtins_module
import io, logging, traceback
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

logger = logging.getLogger(__name__)

# 沙箱内置函数（完整builtins，可按需限制）
SAFE_BUILTINS = vars(_builtins_module).copy()
# 移除高危函数
for _dangerous in ("open", "__import__"):
    SAFE_BUILTINS.pop(_dangerous, None)


class SandboxExecutor:
    """
    在隔离环境中执行代码（进程内沙箱）。
    生产环境可替换为 Docker 隔离执行。
    """

    def __init__(self) -> None:
        self._exec_count = 0
        self._fail_count = 0

    def run_code(self, code: str, timeout: float = 10.0) -> dict:
        """
        执行Python代码，捕获 stdout/stderr 和异常。
        返回 {"success": bool, "stdout": str, "stderr": str, "return_value": Any}
        """
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        result: dict = {
            "success": False,
            "stdout": "",
            "stderr": "",
            "return_value": None,
        }
        try:
            self._exec_count += 1
            namespace: dict = {"__builtins__": SAFE_BUILTINS}
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<sandbox>", "exec"), namespace)
            result["success"] = True
            result["stdout"] = stdout_buf.getvalue()
            result["return_value"] = namespace.get("_result")
        except Exception as e:
            self._fail_count += 1
            result["stderr"] = traceback.format_exc()
            result["stdout"] = stdout_buf.getvalue()
            logger.warning(f"[SandboxExecutor] 代码执行异常: {e}")
        return result

    def run_file(self, file_path, timeout: float = 30.0) -> dict:
        """执行文件中的Python代码。"""
        try:
            code = Path(file_path).read_text(encoding="utf-8")
            return self.run_code(code, timeout=timeout)
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e), "return_value": None}

    def stats(self) -> dict:
        return {
            "total_executions": self._exec_count,
            "failures": self._fail_count,
            "success_rate": round(
                (self._exec_count - self._fail_count) / self._exec_count, 3
            ) if self._exec_count > 0 else 1.0,
        }

    def __repr__(self) -> str:
        return f"SandboxExecutor(executions={self._exec_count})"
