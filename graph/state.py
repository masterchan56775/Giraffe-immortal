"""
graph/state.py — 图状态模型定义

GraphState 是 DAG 图中各节点间流转的共享状态对象。
使用 TypedDict 提供类型提示，同时保持 dict 的灵活性。
"""
from __future__ import annotations

from typing import TypedDict, Any


class GraphState(TypedDict, total=False):
    """
    图执行的共享状态对象。

    所有字段均为可选（total=False），节点按需读写。
    """
    # ─── 输入 ─────────────────────────────────────────────────────────────────
    message: str                   # 用户消息
    model: str                     # 目标模型
    api_key: str                   # API 密钥
    base_url: str                  # API 基础 URL
    task_type: str                 # 任务类型（chat/code/reasoning…）
    system_prompt: str             # 系统提示词
    messages: list[dict]           # 消息历史
    images: list[str]              # Base64 编码图片
    mcp_tools: list[dict]          # MCP 工具描述
    max_tokens: int                # 最大输出 token
    temperature: float             # 温度参数
    use_cache: bool                # 是否使用缓存

    # ─── 执行过程中填充 ────────────────────────────────────────────────────────
    approved: bool                 # 预审批结果
    approval_reason: str           # 审批说明
    cache_hit: bool                # 是否缓存命中
    response: str                  # 最终响应文本
    error: str | None              # 错误信息（None 表示无错误）
    retry_count: int               # 重试次数
    stage_history: list[str]       # 已执行阶段的名称记录
    stage_times: dict[str, float]  # 各阶段耗时（毫秒）
    decomposed: Any                # TaskDecomposer 的拆解结果
    tokens_used: int               # 实际消耗的 token 数
