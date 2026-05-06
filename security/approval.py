"""
ApprovalSystem — 审批系统
P0（双重确认）/ P1（单次确认）/ P2（自动通过）三级权限
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class ApprovalLevel(str, Enum):
    P0 = "P0"  # 最危险：删除文件/改配置/密钥操作 — 双重确认
    P1 = "P1"  # 中等风险：终端执行/网络请求/文件写入 — 单次确认
    P2 = "P2"  # 低风险：代码生成/文本分析/搜索 — 自动通过


# 操作 → 权限级别映射
OPERATION_LEVELS: list[tuple[re.Pattern, ApprovalLevel]] = [
    # P0 — 最危险
    (re.compile(r"删除|remove|delete|rm |drop table|truncate", re.I), ApprovalLevel.P0),
    (re.compile(r"配置|config.*(set|write|update)|密钥|api.?key|secret", re.I), ApprovalLevel.P0),
    (re.compile(r"格式化|format.*disk|系统.*重置", re.I), ApprovalLevel.P0),

    # P1 — 中等风险
    (re.compile(r"执行命令|terminal|bash|shell|subprocess|exec", re.I), ApprovalLevel.P1),
    (re.compile(r"网络请求|http.*post|http.*put|http.*delete|requests\.", re.I), ApprovalLevel.P1),
    (re.compile(r"写入文件|file.*write|open.*w\b|save.*file", re.I), ApprovalLevel.P1),
    (re.compile(r"git.*push|git.*commit|deploy|发布", re.I), ApprovalLevel.P1),
]

# 任务类型 → 默认权限级别
TASK_TYPE_LEVELS: dict[str, ApprovalLevel] = {
    "chat":            ApprovalLevel.P2,
    "code_small":      ApprovalLevel.P2,
    "code_medium":     ApprovalLevel.P2,
    "code_large":      ApprovalLevel.P1,
    "reasoning_light": ApprovalLevel.P2,
    "reasoning":       ApprovalLevel.P2,
    "vision":          ApprovalLevel.P2,
    "search":          ApprovalLevel.P2,
}


class ApprovalSystem:
    """
    三级审批系统。
    P0: 需要用户双重确认（输入"确认"两次）
    P1: 需要用户单次确认（输入"确认"一次）
    P2: 自动通过，无需确认
    """

    def __init__(
        self,
        approval_mode: str = "confirm",   # "confirm" | "auto"
        confirm_func: Callable | None = None,
    ) -> None:
        self._mode = approval_mode
        self._confirm_func = confirm_func  # 外部确认函数（用于测试/接入实际UI）
        self._approval_log: list[dict] = []

    def approve(self, task_type: str, content: str = "") -> tuple[bool, str]:
        """
        审批一个操作。
        返回 (approved, reason)。
        """
        level = self._determine_level(task_type, content)
        return self._run_approval(level, content)

    def _determine_level(self, task_type: str, content: str) -> ApprovalLevel:
        """确定操作的权限级别。"""
        # 先检查内容是否包含高危操作
        for pattern, level in OPERATION_LEVELS:
            if pattern.search(content):
                return level
        # 再按任务类型判断
        return TASK_TYPE_LEVELS.get(task_type, ApprovalLevel.P2)

    def _run_approval(self, level: ApprovalLevel, content: str) -> tuple[bool, str]:
        """执行审批流程。"""
        if self._mode == "auto" or level == ApprovalLevel.P2:
            self._log(level, content, approved=True, method="auto")
            return True, f"自动通过 ({level.value})"

        if level == ApprovalLevel.P0:
            # 双重确认
            if self._confirm_func:
                ok1 = self._confirm_func(f"[P0-高危操作] 确认执行？(首次确认)")
                ok2 = self._confirm_func(f"[P0-高危操作] 再次确认？(二次确认)") if ok1 else False
                approved = ok1 and ok2
            else:
                # 无确认函数时（如测试环境），默认阻止P0操作
                approved = False
            self._log(level, content, approved=approved, method="double_confirm")
            return approved, "P0双重确认" + ("通过" if approved else "拒绝")

        if level == ApprovalLevel.P1:
            if self._confirm_func:
                approved = self._confirm_func(f"[P1操作] 确认执行？")
            else:
                approved = True  # P1默认通过（无确认函数时）
            self._log(level, content, approved=approved, method="single_confirm")
            return approved, "P1单次确认" + ("通过" if approved else "拒绝")

        return True, "默认通过"

    def _log(self, level: ApprovalLevel, content: str, approved: bool, method: str) -> None:
        self._approval_log.append({
            "level": level.value,
            "content": content[:50],
            "approved": approved,
            "method": method,
        })

    def stats(self) -> dict:
        approved = sum(1 for r in self._approval_log if r["approved"])
        return {
            "total": len(self._approval_log),
            "approved": approved,
            "rejected": len(self._approval_log) - approved,
        }

    def __repr__(self) -> str:
        return f"ApprovalSystem(mode={self._mode})"
