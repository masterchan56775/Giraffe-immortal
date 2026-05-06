"""
FaultPlaybook — 故障处理卡
4类常见故障的标准处理流程
"""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class FaultType(str, Enum):
    NETWORK    = "network"    # 网络故障 → 重试+降级
    API_ERROR  = "api_error"  # API错误 → 模型切换
    RESOURCE   = "resource"   # 资源耗尽 → 压缩+清理
    LOGIC      = "logic"      # 逻辑错误 → 回滚+报告


class FaultHandler:
    """故障处理器基类。"""

    def __init__(self, fault_type: FaultType, description: str) -> None:
        self.fault_type = fault_type
        self.description = description

    def handle(self, context: dict) -> dict:
        raise NotImplementedError


class NetworkFaultHandler(FaultHandler):
    """网络故障 → 重试 + 降级"""

    def __init__(self) -> None:
        super().__init__(FaultType.NETWORK, "网络故障处理：重试+降级")

    def handle(self, context: dict) -> dict:
        retry_func: Callable | None = context.get("retry_func")
        model_chain: list[str] = context.get("model_chain", [])
        max_retries = context.get("max_retries", 3)

        result = {"fault_type": self.fault_type.value, "success": False, "steps": []}

        for attempt in range(max_retries):
            wait = 2 ** attempt  # 指数退避
            result["steps"].append(f"第{attempt+1}次重试，等待{wait}s")
            time.sleep(min(wait, 8))

            if retry_func:
                try:
                    resp = retry_func()
                    result["success"] = True
                    result["response"] = resp
                    break
                except Exception as e:
                    result["steps"].append(f"重试失败: {e}")

            # 降级模型
            if model_chain and attempt < len(model_chain) - 1:
                context["current_model"] = model_chain[attempt + 1]
                result["steps"].append(f"降级到: {context['current_model']}")

        return result


class ApiErrorHandler(FaultHandler):
    """API错误 → 模型切换"""

    def __init__(self) -> None:
        super().__init__(FaultType.API_ERROR, "API错误处理：模型切换")

    def handle(self, context: dict) -> dict:
        model_chain: list[str] = context.get("model_chain", [])
        current_model: str = context.get("current_model", "")
        retry_func: Callable | None = context.get("retry_func")

        result = {"fault_type": self.fault_type.value, "success": False, "steps": []}

        for model in model_chain:
            if model == current_model:
                continue
            result["steps"].append(f"切换模型: {model}")
            context["current_model"] = model

            if retry_func:
                try:
                    resp = retry_func()
                    result["success"] = True
                    result["model_used"] = model
                    break
                except Exception as e:
                    result["steps"].append(f"模型{model}失败: {e}")

        return result


class ResourceFaultHandler(FaultHandler):
    """资源耗尽 → 压缩+清理"""

    def __init__(self) -> None:
        super().__init__(FaultType.RESOURCE, "资源耗尽处理：压缩+清理")

    def handle(self, context: dict) -> dict:
        compact_func: Callable | None = context.get("compact_func")
        cleanup_func: Callable | None = context.get("cleanup_func")
        retry_func: Callable | None = context.get("retry_func")

        result = {"fault_type": self.fault_type.value, "success": False, "steps": []}

        if compact_func:
            try:
                compact_func()
                result["steps"].append("已压缩对话历史")
            except Exception as e:
                result["steps"].append(f"压缩失败: {e}")

        if cleanup_func:
            try:
                cleanup_func()
                result["steps"].append("已清理缓存")
            except Exception as e:
                result["steps"].append(f"清理失败: {e}")

        if retry_func:
            try:
                resp = retry_func()
                result["success"] = True
                result["steps"].append("压缩后重试成功")
            except Exception as e:
                result["steps"].append(f"重试失败: {e}")

        return result


class LogicErrorHandler(FaultHandler):
    """逻辑错误 → 回滚+报告"""

    def __init__(self) -> None:
        super().__init__(FaultType.LOGIC, "逻辑错误处理：回滚+报告")

    def handle(self, context: dict) -> dict:
        rollback_func: Callable | None = context.get("rollback_func")
        error_detail: str = context.get("error_detail", "未知逻辑错误")

        result = {
            "fault_type": self.fault_type.value,
            "success": False,
            "steps": ["识别逻辑错误"],
        }

        if rollback_func:
            try:
                rollback_func()
                result["steps"].append("回滚操作完成")
            except Exception as e:
                result["steps"].append(f"回滚失败: {e}")

        result["report"] = {
            "error_detail": error_detail,
            "recommendation": "请检查输入数据和业务逻辑",
            "needs_human_review": True,
        }
        result["steps"].append("已生成故障报告")
        return result


class FaultPlaybook:
    """
    故障处理卡。
    维护4类故障的标准处理流程，根据故障类型自动选择处理器。
    """

    def __init__(self) -> None:
        self._handlers: dict[FaultType, FaultHandler] = {
            FaultType.NETWORK:   NetworkFaultHandler(),
            FaultType.API_ERROR: ApiErrorHandler(),
            FaultType.RESOURCE:  ResourceFaultHandler(),
            FaultType.LOGIC:     LogicErrorHandler(),
        }
        self._playbook_runs = 0

    def run(self, fault_type: FaultType, context: dict) -> dict:
        """运行指定故障类型的处理流程。"""
        handler = self._handlers.get(fault_type)
        if not handler:
            logger.error(f"[FaultPlaybook] 未知故障类型: {fault_type}")
            return {"error": "unknown fault type"}

        self._playbook_runs += 1
        logger.info(f"[FaultPlaybook] 运行故障处理: {fault_type.value}")
        return handler.handle(context)

    def detect_fault_type(self, error_msg: str, http_code: int = 0) -> FaultType:
        """根据错误信息自动检测故障类型。"""
        msg_lower = error_msg.lower()
        if http_code in (429, 503, 502) or "timeout" in msg_lower or "connection" in msg_lower:
            return FaultType.NETWORK
        if http_code in (401, 403, 404, 400) or "model" in msg_lower:
            return FaultType.API_ERROR
        if "token" in msg_lower or "context" in msg_lower or "memory" in msg_lower:
            return FaultType.RESOURCE
        return FaultType.LOGIC

    def auto_handle(self, error_msg: str, http_code: int = 0, **context_kwargs) -> dict:
        """自动检测故障类型并处理。"""
        fault_type = self.detect_fault_type(error_msg, http_code)
        return self.run(fault_type, context_kwargs)

    def stats(self) -> dict:
        return {"playbook_runs": self._playbook_runs}

    def __repr__(self) -> str:
        return f"FaultPlaybook(handlers={len(self._handlers)}, runs={self._playbook_runs})"
