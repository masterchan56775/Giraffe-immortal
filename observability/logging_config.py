"""
Giraffe 集中式日志管理
========================
所有模块统一通过 `logging.getLogger(__name__)` 获取 logger，
本模块负责在程序入口统一配置格式、级别、Handler。

使用方式：
    # 入口（giraffe.py）
    from observability.logging_config import setup_logging
    setup_logging(level="INFO", log_file="giraffe.log")

    # 各模块（只需写这一行）
    import logging
    logger = logging.getLogger(__name__)

层级结构：
    giraffe                ← 主控
    ├── giraffe.router     ← router/
    ├── giraffe.executor   ← executor/
    ├── giraffe.memory     ← memory/
    ├── giraffe.tools      ← tools/
    ├── giraffe.core       ← core/
    ├── giraffe.security   ← security/
    ├── giraffe.skills     ← skills/
    ├── giraffe.integration← integration/
    ├── giraffe.self_heal  ← self_heal/
    ├── giraffe.observability ← observability/
    └── giraffe.auto_fusion← auto_fusion/
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# ── ANSI 颜色（终端彩色输出，非 TTY 时自动关闭）────────────────────────────────
_COLORS = {
    "DEBUG":    "\033[36m",    # cyan
    "INFO":     "\033[32m",    # green
    "WARNING":  "\033[33m",    # yellow
    "ERROR":    "\033[31m",    # red
    "CRITICAL": "\033[35m",    # magenta
}
_RESET = "\033[0m"

# 短名称映射（让日志更紧凑可读）
_SHORT_NAME: dict[str, str] = {
    # 使用 __name__ 时产生的长路径 → 简短显示名
    "router.engine":           "router",
    "router.model_registry":   "registry",
    "router.model_aliases":    "aliases",
    "router.model_validator":  "validator",
    "router.intent_classifier":"intent",
    "router.gatekeeper":       "gatekeeper",
    "executor.pipeline":       "pipeline",
    "executor.agentic_loop":   "agent",
    "executor.side_query":     "sideq",
    "executor.retry":          "retry",
    "executor.circuit_breaker":"circuit",
    "executor.tool_result_store":"trs",
    "executor.coordinator":    "coord",
    "memory.memory_system":    "memory",
    "memory.compactor":        "compact",
    "memory.claude_md":        "claudemd",
    "tools.bash_tool":         "bash",
    "tools.shell_validator":   "shellval",
    "tools.worktree_tool":     "worktree",
    "skills.loader":           "skills",
    "security.approval":       "approval",
    "security.guardrail_middleware": "guardrail",
    "security.token_tracker":  "tokens",
    "integration.hooks":       "hooks",
    "integration.hooks_frontmatter": "hooks_fm",
    "integration.gateway_api": "gateway",
    "integration.startup":     "startup",
    "observability.stats":     "stats",
    "observability.tracer":    "tracer",
    "auto_fusion":             "fusion",
    "self_heal.antibody":      "antibody",
    "self_heal.evolution":     "evolution",
    "self_heal.error_processor":"errproc",
}

class _ColorFormatter(logging.Formatter):
    """
    彩色终端格式化器。
    格式：HH:MM:SS [LEVEL] short_name: message
    """
    _use_color: bool

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self._use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        # 简化 logger 名称
        name = _SHORT_NAME.get(record.name, record.name.split(".")[-1])

        level = record.levelname
        if self._use_color:
            color = _COLORS.get(level, "")
            level_str = f"{color}{level:8}{_RESET}"
            name_str = f"\033[90m{name}\033[0m"
        else:
            level_str = f"{level:8}"
            name_str = name

        # 时间
        import time
        t = time.localtime(record.created)
        ts = f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"

        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)

        return f"{ts} {level_str} {name_str}: {msg}"

class _FileFormatter(logging.Formatter):
    """纯文本文件格式（无颜色，含完整模块路径）。"""
    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

# ── 包级静音列表（第三方库过于啰嗦）──────────────────────────────────────────
_QUIET_LOGGERS = [
    "httpx", "httpcore", "urllib3", "anthropic", "google", "grpc",
    "charset_normalizer", "asyncio", "uvicorn.access",
    "opentelemetry", "botocore", "boto3",
]

def setup_logging(
    level: LogLevel = "INFO",
    log_file: str | Path | None = None,
    quiet_third_party: bool = True,
    color: bool = True,
) -> None:
    """
    统一配置全局日志系统。
    应在程序入口调用一次，且只调用一次。

    Args:
        level:              主日志级别（giraffe.* 层级）
        log_file:           写入文件路径（None=只输出终端）
        quiet_third_party:  是否静音第三方库（默认 True）
        color:              是否启用 ANSI 彩色（默认 True，非 TTY 自动关闭）
    """
    # 避免重复配置
    root = logging.getLogger()
    if getattr(root, "_giraffe_configured", False):
        return
    root._giraffe_configured = True  # type: ignore[attr-defined]

    # 根 logger 设为 WARNING（让第三方库默认静音）
    root.setLevel(logging.WARNING)
    root.handlers.clear()

    # ── 终端 Handler ──────────────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_ColorFormatter(use_color=color))
    console.setLevel(logging.DEBUG)
    root.addHandler(console)

    # ── 文件 Handler（可选）──────────────────────────────────────────────────
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(_FileFormatter())
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)

    # ── giraffe.* 层级设为用户指定级别 ────────────────────────────────────────
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # 主命名空间：所有 giraffe 模块
    for ns in (
        "giraffe",
        # 直接以模块包名注册的 logger（使用 __name__）
        "router", "executor", "memory", "tools", "core",
        "security", "skills", "integration", "observability",
        "self_heal", "auto_fusion",
        # 硬编码 string 名称（遗留代码）
        "agentic_loop", "coordinator", "compactor", "claude_md",
        "retry", "side_query", "tool_result_store", "worktree_tool",
        "hooks_frontmatter", "model_validator", "stats",
    ):
        logging.getLogger(ns).setLevel(numeric_level)

    # ── 静音第三方库 ──────────────────────────────────────────────────────────
    if quiet_third_party:
        for name in _QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    # uvicorn 特殊处理：保留 ERROR 以上（access 日志太多）
    logging.getLogger("uvicorn").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

def get_log_level() -> str:
    """获取当前 giraffe logger 的级别名称。"""
    return logging.getLevelName(logging.getLogger("giraffe").level)

def set_log_level(level: LogLevel) -> None:
    """运行时动态调整日志级别（无需重启）。"""
    numeric = getattr(logging, level.upper(), logging.INFO)
    for ns in ("giraffe", "router", "executor", "memory", "tools",
               "core", "security", "skills", "integration",
               "observability", "self_heal", "auto_fusion",
               "agentic_loop", "coordinator", "compactor"):
        logging.getLogger(ns).setLevel(numeric)
