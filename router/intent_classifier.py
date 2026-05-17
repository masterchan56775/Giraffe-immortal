"""
IntentClassifier — 意图分类器
维度1：关键词快速匹配（<1ms）
"""
from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class TaskType(str, Enum):
    CHAT            = "chat"
    CODE_SMALL      = "code_small"
    CODE_MEDIUM     = "code_medium"
    CODE_LARGE      = "code_large"
    REASONING_LIGHT = "reasoning_light"
    REASONING       = "reasoning"
    VISION          = "vision"
    SEARCH          = "search"
    ROUTING         = "routing"
    SUBTASK         = "subtask"
    AGENT_TASK      = "agent_task"    # 自动化 Agent → Grok
    REPO_ANALYSIS   = "repo_analysis" # 长仓库分析 → Grok


class ClassifyResult(NamedTuple):
    task_type: TaskType
    confidence: float          # 0.0~1.0
    method: str                # "keyword" | "llm" | "default"
    matched_keyword: str = ""  # 触发匹配的关键词


# ─────────────────────────────────────────────────────────────────────────────
# 关键词规则表：(优先级, 关键词列表, TaskType)
# 优先级数值越小越先匹配
#
# 模型路由设计：
#   Grok (grok-4.20-reasoning) ← agent_task, repo_analysis, search/trending
#   Claude (claude-sonnet-4-6) ← reasoning, code_large
#   Gemini Pro (gemini-3.1-pro-preview) ← 其他所有情况
# ─────────────────────────────────────────────────────────────────────────────
KEYWORD_RULES: list[tuple[int, list[str], TaskType]] = [

    # ── 0. Vision（最高优先级，有图必须先检测）─────────────────────────────
    (0, ["看这张图", "图片", "截图", "看图", "识别图", "分析图片", "这张", "图中"],
     TaskType.VISION),

    # ── 1. Agent Task（自动化 → Grok）──────────────────────────────────────
    # "帮我自动执行…" / "定时跑…" / "批量处理…" 等自主任务
    (1, [
        "自动化任务", "帮我自动", "自主执行", "自动执行", "自动化脚本",
        "定时任务", "批量处理", "批量操作", "执行流程", "多步操作",
        "agentic", "autonomous", "automation", "自动化",
    ], TaskType.AGENT_TASK),

    # ── 2. Repo Analysis（长仓库分析 → Grok）─────────────────────────────
    # 分析整个代码库 / repo 级别的全局探索
    (2, [
        "分析仓库", "分析代码库", "分析整个项目", "整个代码库", "全局分析",
        "仓库分析", "repo分析", "看一下这个项目", "代码库结构", "项目全貌",
        "所有文件", "整体代码", "扫描项目",
    ], TaskType.REPO_ANALYSIS),

    # ── 3. Large Code / Architecture（严肃 Coding + 架构设计 → Claude）────
    (3, [
        "重构", "架构设计", "系统设计", "微服务", "设计模式", "整体架构",
        "模块拆分", "架构", "框架设计",
    ], TaskType.CODE_LARGE),

    # ── 4. Medium Code（一般编码 → Gemini Pro）───────────────────────────
    (4, [
        "帮我写", "写代码", "编程", "写个函数", "实现", "写脚本", "编写",
        "开发", "写一个", "帮写", "代码",
    ], TaskType.CODE_MEDIUM),

    # ── 5. Small Code（小改动 → Gemini Pro）──────────────────────────────
    (5, ["改一行", "修改这行", "加个注释", "补全", "修复这个bug", "小改动"],
     TaskType.CODE_SMALL),

    # ── 6. Deep Reasoning（做研究 → Claude）──────────────────────────────
    (6, [
        "深度分析", "系统分析", "推理", "论证", "逻辑推导", "分析原因",
        "为什么会", "深入理解", "复杂问题",
        "证明", "推导", "定理", "引理", "命题", "流形", "拓扑", "代数", "微分",
        "积分", "方程", "极限", "级数", "矩阵", "向量空间", "线性代数",
        "概率", "统计", "期望", "方差", "贝叶斯", "优化", "凸优化",
        "陈类", "示性类", "黎曼", "凯勒", "同调", "同伦", "拓扑不变量",
        "求解", "解题步骤", "推导过程", "计算以下", "解以下",
    ], TaskType.REASONING),

    # ── 7. Light Reasoning（轻量分析 → Gemini Pro）───────────────────────
    (7, ["分析", "解释", "理解", "分析一下", "说明", "评估", "对比"],
     TaskType.REASONING_LIGHT),

    # ── 8. Search / Trending（热点追踪 → Grok）───────────────────────────
    (8, [
        "搜索", "查一下", "查询", "查找", "搜一搜", "帮我搜",
        "追热点", "热点", "热门", "最新消息", "实时", "当前趋势",
        "新闻", "今天发生", "最近动态", "trending",
    ], TaskType.SEARCH),

    # ── 9. Chat（闲聊 → Gemini Pro）──────────────────────────────────────
    (9, [
        "你好", "嗨", "在吗", "hi", "hello", "早上好", "晚上好", "谢谢",
        "感谢", "再见", "bye", "聊聊", "随便聊", "闲聊",
    ], TaskType.CHAT),
]

# 能力询问正则（最高优先级，覆盖所有 task_type 的关键词匹配）
# 匹配：你会X吗 / 能X吗 / 可以X吗 / 你能做X吗 等
_CAPABILITY_RE = re.compile(
    r"^(你|您|giraffe|ai|你们|咱们)?\s*"
    r"(会不会|能不能|可不可以|会|能|可以|支持|懂|了解)\s*"
    r"[^\n]{0,80}"
    r"(吗|呢|？|\?)\s*$",
    re.IGNORECASE,
)


class IntentClassifier:
    """
    意图分类器（关键词维度）。
    <1ms 快速匹配，优先于LLM分类触发。

    分类优先级：
    1. 图片检测（has_image）
    2. 能力询问预检（你会…吗 → CHAT）
    3. 关键词规则（按 priority 排序）
    4. 默认回退（CHAT）
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

        # ── 能力询问预检（高于所有关键词规则）────────────────────────────────
        # "你会解数学题吗" / "能帮我写代码吗" / "可以分析图片吗" → CHAT
        if _CAPABILITY_RE.match(msg):
            return ClassifyResult(
                task_type=TaskType.CHAT,
                confidence=0.92,
                method="keyword",
                matched_keyword="[能力询问]",
            )

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

