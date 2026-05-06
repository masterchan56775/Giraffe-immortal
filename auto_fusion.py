"""
auto_fusion.py — 自动融合引擎
Auto-Fusion Engine：扫描→对比→决策→融合→验证→报告
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


@dataclass
class FusionRecord:
    """单个特性的融合记录。"""
    name: str
    source: str
    priority: str
    status: str   # "fused" | "skipped" | "pending_confirm"
    reason: str = ""


@dataclass
class FusionReport:
    """融合报告。"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    fused: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pending_confirm: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "fused_count": len(self.fused),
            "updated_count": len(self.updated),
            "skipped_count": len(self.skipped),
            "pending_confirm": self.pending_confirm,
            "fused": self.fused,
            "errors": self.errors,
        }


class AutoFusionEngine:
    """
    自动融合引擎（核心创新之一）。

    工作流（6步）：
    ① 扫描（Scan）   — 扫描Hermes全部能力
    ② 对比（Compare）— 与本地Feature Registry对比
    ③ 决策（Decide） — 评估每个未融合特性的优先级
    ④ 融合（Fuse）   — P0自动融合，P1自动启用，P2等待确认
    ⑤ 验证（Verify） — 运行兼容性检查
    ⑥ 报告（Report） — 生成融合报告
    """

    def __init__(
        self,
        registry_path: Path | str | None = None,
        auto_fuse_priority: list[str] | None = None,
        require_confirm_for: list[str] | None = None,
    ) -> None:
        self._registry_path = Path(registry_path) if registry_path else BASE_DIR / "feature_registry.json"
        self._auto_fuse = set(auto_fuse_priority or ["P0", "P1"])
        self._require_confirm = set(require_confirm_for or ["P2"])
        self._registry: dict = {"features": [], "fusion_count": 0, "pending_count": 0}
        self._load_registry()

    # ─── 主入口 ───────────────────────────────────────────────────────────────
    def run(self, hermes_capabilities: list[dict] | None = None) -> FusionReport:
        """
        执行完整的自动融合流程（6步）。
        hermes_capabilities: Hermes提供的能力列表（每项含name/version/priority等）
        """
        report = FusionReport()

        # ① 扫描
        capabilities = self._scan(hermes_capabilities)
        logger.info(f"[AutoFusion] ① 扫描: 发现 {len(capabilities)} 个能力")

        # ② 对比
        fused_names = {f["name"] for f in self._registry.get("features", [])}
        unfused = [c for c in capabilities if c["name"] not in fused_names]
        logger.info(f"[AutoFusion] ② 对比: {len(unfused)} 个未融合特性")

        # ③ 决策 + ④ 融合
        for cap in unfused:
            priority = cap.get("priority", "P2")
            if priority in self._auto_fuse:
                success = self._fuse(cap, report)
                if success:
                    report.fused.append(cap["name"])
                else:
                    report.errors.append(cap["name"])
            elif priority in self._require_confirm:
                report.pending_confirm.append(cap["name"])
                logger.info(f"[AutoFusion] ④ 等待确认: {cap['name']} (P2)")
            else:
                report.skipped.append(cap["name"])

        # ⑤ 验证
        self._verify(report)

        # ⑥ 保存注册表
        self._save_registry()

        logger.info(
            f"[AutoFusion] ⑥ 完成: 融合{len(report.fused)}, "
            f"待确认{len(report.pending_confirm)}, "
            f"跳过{len(report.skipped)}, 错误{len(report.errors)}"
        )
        return report

    # ─── 各步骤实现 ────────────────────────────────────────────────────────────
    def _scan(self, capabilities: list[dict] | None) -> list[dict]:
        """扫描并返回能力列表。"""
        if capabilities:
            return capabilities
        # 从注册表加载已知能力（作为演示数据源）
        return self._registry.get("features", [])

    def _fuse(self, capability: dict, report: FusionReport) -> bool:
        """执行单个特性的融合。"""
        try:
            feature = {
                "name": capability["name"],
                "source": capability.get("source", "unknown"),
                "version": capability.get("version", "0.0.0"),
                "fused": True,
                "fused_at": datetime.now().strftime("%Y-%m-%d"),
                "priority": capability.get("priority", "P2"),
                "dependencies": capability.get("dependencies", []),
            }
            # 检查是否已存在（更新）
            existing = next(
                (f for f in self._registry["features"] if f["name"] == feature["name"]),
                None
            )
            if existing:
                existing.update(feature)
                report.updated.append(feature["name"])
            else:
                self._registry["features"].append(feature)

            self._registry["fusion_count"] = sum(
                1 for f in self._registry["features"] if f.get("fused")
            )
            logger.debug(f"[AutoFusion] 融合: {feature['name']}")
            return True
        except Exception as e:
            logger.error(f"[AutoFusion] 融合失败 {capability.get('name')}: {e}")
            return False

    def _verify(self, report: FusionReport) -> None:
        """兼容性验证（简单检查模块是否可导入）。"""
        modules_to_check = {
            "RouterEngine":     "router.engine",
            "ExecutorPipeline": "executor.pipeline",
            "MemorySystem":     "memory.memory_system",
            "AntibodyLibrary":  "self_heal.antibody",
        }
        for feature_name, module_path in modules_to_check.items():
            try:
                __import__(module_path)
            except ImportError as e:
                report.errors.append(f"验证失败[{feature_name}]: {e}")
                logger.warning(f"[AutoFusion] 验证失败: {feature_name} - {e}")

    # ─── 注册表管理 ───────────────────────────────────────────────────────────
    def _load_registry(self) -> None:
        if self._registry_path.exists():
            try:
                with open(self._registry_path, encoding="utf-8") as fp:
                    self._registry = json.load(fp)
            except Exception as e:
                logger.warning(f"[AutoFusion] 加载注册表失败: {e}")

    def _save_registry(self) -> None:
        self._registry["last_scan"] = datetime.now().isoformat()
        with open(self._registry_path, "w", encoding="utf-8") as fp:
            json.dump(self._registry, fp, ensure_ascii=False, indent=2)

    def get_registry_stats(self) -> dict:
        features = self._registry.get("features", [])
        fused = sum(1 for f in features if f.get("fused"))
        return {
            "total_features": len(features),
            "fused_count": fused,
            "pending_count": self._registry.get("pending_count", 0),
            "last_scan": self._registry.get("last_scan", ""),
        }

    def confirm_pending(self, feature_name: str) -> bool:
        """用户确认融合P2特性。"""
        for f in self._registry.get("features", []):
            if f["name"] == feature_name and not f.get("fused"):
                f["fused"] = True
                f["fused_at"] = datetime.now().strftime("%Y-%m-%d")
                self._save_registry()
                logger.info(f"[AutoFusion] 用户确认融合: {feature_name}")
                return True
        return False

    def __repr__(self) -> str:
        stats = self.get_registry_stats()
        return f"AutoFusionEngine(fused={stats['fused_count']}/{stats['total_features']})"
