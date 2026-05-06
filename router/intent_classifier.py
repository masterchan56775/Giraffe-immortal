"""
IntentClassifier — 意图分类器
维度1：关键词快速匹配（<1ms）
"""
from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class TaskType(str, Enum):
    CHAT = "chat"
    CODE_SMALL = "code_small"
    CODE_MEDIUM = "code_medium"
    CODE_LARGE = "code_large"
    REASONING_LIGHT = "reasoning_light"
    REASONING = "reasoning"
    VISION = "vision"
    SEARCH = "search"
    ROUTING = "routing"
    SUBTASK = "subtask"


class ClassifyResult(NamedTuple):
    task_type: TaskType
    confidence: float          # 0.0~1.0
    method: str                # "keyword" | "llm" | "default"
    matched_keyword: str = ""  # 触发匹配的关键词


# 关键词规则表：(优先级, 关键词列表, TaskType)
# 优先级越小越先匹配
KEYWORD_RULES: list[tuple[int, list[str], TaskType]] = [
    # Vision — 最优先（有图必须先检测）
    (0, ["看这张图", "图片", "截图", "看图", "识别图", "分析图片", "这张", "图中"], TaskType.VISION),

    # Large Code / Architecture
    (1, ["重构", "架构设计", "系统设计", "微服务", "设计模式", "整体架构", "模块拆分",
         "架构", "框架设计"], TaskType.CODE_LARGE),

    # Medium Code
    (2, ["帮我写", "写代码", "编程", "写个函数", "实现", "写脚本", "编写", "开发",
         "写一个", "帮写", "代码"], TaskType.CODE_MEDIUM),

    # Small Code
    (3, ["改一行", "修改这行", "加个注释", "补全", "修复这个bug", "小改动"], TaskType.CODE_SMALL),

    # Deep Reasoning
    (4, ["深度分析", "系统分析", "推理", "论证", "思考", "逻辑推导", "分析原因",
         "为什么会", "深入理解", "复杂问题"], TaskType.REASONING),

    # Light Reasoning
    (5, ["分析", "解释", "理解", "分析一下", "说明", "评估", "对比"], TaskType.REASONING_LIGHT),

    # Search
    (6, ["搜索", "查一下", "查询", "查找", "搜一搜", "帮我搜"], TaskType.SEARCH),

    # Chat
    (7, ["你好", "嗨", "在吗", "hi", "hello", "早上好", "晚上好", "谢谢", "感谢",
         "再见", "bye", "聊聊", "随便聊", "闲聊"], TaskType.CHAT),
]


class IntentClassifier:
    """
    意图分类器（关键词维度）。
    <1ms 快速匹配，优先于LLM分类触发。
    """

    def __init__(self) -> None:
        # 预编译正则
        self._compiled: list[tuple[int, re.Pattern, TaskType, str]] = []
        for priority, keywords, task_type in KEYWORD_RULES:
            pattern = re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE)
            self._compiled.append((priority, pattern, task_type, "|".join(keywords[:3])))

    def classify(self, message: str, has_image: bool = False) -> ClassifyResult:
        """
        对消息进行意图分类。
        has_image=True 时直接返回 vision 类型。
        """
        if has_image:
            return ClassifyResult(
                task_type=TaskType.VISION,
                confidence=1.0,
                method="keyword",
                matched_keyword="[image_detected]",
            )

        msg = message.strip()

        for priority, pattern, task_type, sample_kw in self._compiled:
            match = pattern.search(msg)
            if match:
                return ClassifyResult(
                    task_type=task_type,
                    confidence=0.85,
                    method="keyword",
                    matched_keyword=match.group(0),
                )

        # 默认回退 chat
        return ClassifyResult(
            task_type=TaskType.CHAT,
            confidence=0.3,
            method="default",
        )

    def is_ambiguous(self, result: ClassifyResult) -> bool:
        """判断分类结果是否模糊（需要进一步LLM分类）。"""
        return result.confidence < 0.6 or result.method == "default"

    def __repr__(self) -> str:
        return f"IntentClassifier(rules={len(self._compiled)})"
