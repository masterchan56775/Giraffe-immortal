"""
AntibodyLibrary — 抗体库
8个内置抗体 + 动态生成新抗体。像免疫系统一样记住并处理已知错误。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Antibody:
    """单个抗体：错误模式 + 修复方案。"""
    id: str
    name: str
    error_pattern: str         # 匹配的错误模式（正则）
    error_codes: list[int]     # 匹配的HTTP状态码
    action: str                # 修复动作描述
    fix_steps: list[str]       # 具体修复步骤
    success_count: int = 0
    fail_count: int = 0
    priority: int = 5
    is_builtin: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return round(self.success_count / total, 3) if total > 0 else 0.0

    def record_success(self) -> None:
        self.success_count += 1

    def record_failure(self) -> None:
        self.fail_count += 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AntibodyMatch:
    """抗体匹配结果。"""
    antibody: Antibody | None
    matched: bool
    confidence: float
    reason: str


# ─── 8个内置抗体 ────────────────────────────────────────────────────────────
BUILTIN_ANTIBODIES: list[dict] = [
    {
        "id": "ab_404_ban",
        "name": "404-ban",
        "error_pattern": r"404|not found|endpoint not found",
        "error_codes": [404],
        "action": "禁用该Provider，切换到备用Provider",
        "fix_steps": [
            "将当前Provider标记为不可用",
            "从ModelRegistry获取备用模型",
            "切换到备用模型重试",
            "记录端点失效日志",
        ],
        "priority": 8,
    },
    {
        "id": "ab_timeout_retry",
        "name": "timeout-retry",
        "error_pattern": r"timeout|timed out|connection timeout|read timeout",
        "error_codes": [],
        "action": "重试+降级模型+延长超时",
        "fix_steps": [
            "等待1秒后重试",
            "若重试失败，切换到降级模型",
            "延长超时时间至60秒",
            "最多重试3次",
        ],
        "priority": 7,
    },
    {
        "id": "ab_rate_limit",
        "name": "rate-limit-wait",
        "error_pattern": r"rate.?limit|too many requests|quota exceeded",
        "error_codes": [429],
        "action": "指数退避等待后重试",
        "fix_steps": [
            "第1次：等待1秒后重试",
            "第2次：等待2秒后重试",
            "第3次：等待4秒后重试",
            "第4次：等待8秒后重试",
            "超过4次：切换到降级模型",
        ],
        "priority": 7,
    },
    {
        "id": "ab_auth_refresh",
        "name": "auth-refresh",
        "error_pattern": r"unauthorized|invalid.?api.?key|authentication failed|forbidden",
        "error_codes": [401, 403],
        "action": "刷新Token或切换Key",
        "fix_steps": [
            "检查API Key是否有效",
            "尝试刷新Token",
            "若仍失败，标记Provider为欠费",
            "触发CreditMonitor切换兜底模型",
        ],
        "priority": 9,
    },
    {
        "id": "ab_json_parse",
        "name": "json-parse-fix",
        "error_pattern": r"json|parse error|invalid response|decode error",
        "error_codes": [],
        "action": "重试请求或修复响应格式",
        "fix_steps": [
            "检查响应是否为有效JSON",
            "尝试提取JSON片段",
            "重新发起请求",
            "若持续失败，返回原始文本",
        ],
        "priority": 5,
    },
    {
        "id": "ab_context_trim",
        "name": "context-trim",
        "error_pattern": r"context.?length|token.?limit|too.?long|max.?tokens",
        "error_codes": [],
        "action": "自动压缩历史对话",
        "fix_steps": [
            "触发DeepCompact压缩历史",
            "减少max_tokens参数",
            "保留最近6条消息",
            "重新发起请求",
        ],
        "priority": 6,
    },
    {
        "id": "ab_model_switch",
        "name": "model-switch",
        "error_pattern": r"model.?not.?found|model unavailable|service unavailable",
        "error_codes": [503, 502],
        "action": "按降级链切换模型",
        "fix_steps": [
            "从ModelRegistry获取fallback模型",
            "切换到fallback模型重试",
            "若失败继续切换到emergency模型",
            "记录模型不可用事件",
        ],
        "priority": 8,
    },
    {
        "id": "ab_generic_catch",
        "name": "generic-catch",
        "error_pattern": r".*",  # 匹配所有
        "error_codes": [],
        "action": "触发10步系统化排查",
        "fix_steps": [
            "记录错误详情",
            "分类错误类型",
            "检查熔断器状态",
            "匹配抗体库",
            "尝试降级模型",
            "执行修复",
            "验证修复结果",
            "记录处理过程",
            "更新抗体库",
            "生成错误报告",
        ],
        "priority": 1,  # 最低优先级，兜底使用
    },
]


class AntibodyLibrary:
    """
    抗体库（单例）。
    维护8个内置抗体 + 动态生成的新抗体。
    """

    _instance: AntibodyLibrary | None = None

    def __init__(self, persist_path: Path | str | None = None) -> None:
        self._persist_path = Path(persist_path) if persist_path else None
        self._antibodies: dict[str, Antibody] = {}
        self._load_builtin()
        self._load_from_disk()

    @classmethod
    def get(cls) -> "AntibodyLibrary":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def _load_builtin(self) -> None:
        """加载8个内置抗体。"""
        for ab_data in BUILTIN_ANTIBODIES:
            ab = Antibody(**ab_data)
            self._antibodies[ab.id] = ab
        logger.info(f"[AntibodyLibrary] 加载 {len(BUILTIN_ANTIBODIES)} 个内置抗体")

    # ─── 匹配 ────────────────────────────────────────────────────────────────
    def match(self, error_message: str, http_code: int = 0, error_code: int = 0) -> AntibodyMatch:
        """
        匹配错误到最合适的抗体。
        按优先级从高到低遍历，返回第一个匹配的抗体。
        http_code / error_code 两者均支持（向前兼容）。
        """
        effective_code = http_code or error_code
        error_lower = error_message.lower()
        candidates: list[tuple[int, float, Antibody]] = []

        for ab in self._antibodies.values():
            # 检查状态码匹配
            code_match = bool(ab.error_codes and effective_code in ab.error_codes)
            # 检查正则匹配
            pattern_match = bool(re.search(ab.error_pattern, error_lower, re.I))

            if code_match or (pattern_match and ab.id != "ab_generic_catch"):
                confidence = 0.9 if code_match else 0.75
                candidates.append((ab.priority, confidence, ab))

        if not candidates:
            # 返回通用兜底抗体
            generic = self._antibodies.get("ab_generic_catch")
            return AntibodyMatch(
                antibody=generic,
                matched=bool(generic),
                confidence=0.3,
                reason="无精确匹配，使用通用抗体",
            )

        # 按优先级和置信度排序
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, confidence, best_ab = candidates[0]
        return AntibodyMatch(
            antibody=best_ab,
            matched=True,
            confidence=confidence,
            reason=f"匹配抗体: {best_ab.name} (priority={best_ab.priority})",
        )

    # ─── 动态生成新抗体 ────────────────────────────────────────────────────────
    def generate_new_antibody(
        self, error_pattern: str, action: str, fix_steps: list[str]
    ) -> Antibody:
        """根据新错误动态生成抗体并加入抗体库。"""
        import uuid
        ab_id = f"ab_gen_{uuid.uuid4().hex[:6]}"
        new_ab = Antibody(
            id=ab_id,
            name=f"auto_{ab_id}",
            error_pattern=re.escape(error_pattern[:50]),
            error_codes=[],
            action=action,
            fix_steps=fix_steps,
            is_builtin=False,
            priority=4,
        )
        self._antibodies[ab_id] = new_ab
        logger.info(f"[AntibodyLibrary] 生成新抗体: {ab_id}")
        self._save_to_disk()
        return new_ab

    # ─── 抗体管理 ─────────────────────────────────────────────────────────────
    def all_antibodies(self) -> list[Antibody]:
        return sorted(self._antibodies.values(), key=lambda a: a.priority, reverse=True)

    def get_antibody(self, ab_id: str) -> Antibody | None:
        return self._antibodies.get(ab_id)

    def remove_poor_antibodies(self, min_success_rate: float = 0.2) -> int:
        """淘汰成功率过低的自动生成抗体。"""
        to_remove = [
            ab_id for ab_id, ab in self._antibodies.items()
            if not ab.is_builtin
            and (ab.success_count + ab.fail_count) >= 5
            and ab.success_rate < min_success_rate
        ]
        for ab_id in to_remove:
            del self._antibodies[ab_id]
        if to_remove:
            logger.info(f"[AntibodyLibrary] 淘汰 {len(to_remove)} 个低效抗体")
        return len(to_remove)

    # ─── 持久化 ───────────────────────────────────────────────────────────────
    def _save_to_disk(self) -> None:
        if not self._persist_path:
            return
        custom = {ab_id: ab.to_dict() for ab_id, ab in self._antibodies.items()
                  if not ab.is_builtin}
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "w", encoding="utf-8") as fp:
            json.dump(custom, fp, ensure_ascii=False, indent=2)

    def _load_from_disk(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            with open(self._persist_path, encoding="utf-8") as fp:
                data = json.load(fp)
            for ab_id, ab_data in data.items():
                if ab_id not in self._antibodies:
                    self._antibodies[ab_id] = Antibody(**ab_data)
            logger.info(f"[AntibodyLibrary] 从磁盘加载 {len(data)} 个自定义抗体")
        except Exception as e:
            logger.warning(f"[AntibodyLibrary] 加载失败: {e}")

    def stats(self) -> dict:
        builtin = sum(1 for ab in self._antibodies.values() if ab.is_builtin)
        custom = len(self._antibodies) - builtin
        return {
            "total": len(self._antibodies),
            "builtin": builtin,
            "custom": custom,
            "top_used": [
                {"name": ab.name, "hits": ab.success_count + ab.fail_count}
                for ab in sorted(
                    self._antibodies.values(),
                    key=lambda a: a.success_count + a.fail_count,
                    reverse=True
                )[:3]
            ],
        }

    def __repr__(self) -> str:
        return f"AntibodyLibrary(total={len(self._antibodies)})"
