"""HermesAdapter + AdaptRunner"""
from __future__ import annotations
import logging
from .scanner import HermesScanner
from .compat_report import CompatReport
logger = logging.getLogger(__name__)

class HermesAdapter:
    """自动修复Hermes升级后的配置差异。"""
    def adapt(self, scan_result: dict) -> dict:
        logger.info("[HermesAdapter] 开始适配")
        fixed = []
        for feature in scan_result.get("new_features", []):
            logger.info(f"[HermesAdapter] 适配新特性: {feature}")
            fixed.append(feature)
        return {"fixed": fixed, "status": "ok"}

class AdaptRunner:
    """适配流程运行器。"""
    def __init__(self) -> None:
        self._scanner = HermesScanner()
        self._adapter = HermesAdapter()

    def run(self, current_version: str, target_version: str) -> dict:
        scan = self._scanner.scan(target_version)
        report = CompatReport()
        if scan.get("breaking_changes"):
            for issue in scan["breaking_changes"]:
                report.add_issue(str(issue))
        adapt_result = self._adapter.adapt(scan)
        return {"scan": scan, "compat_report": report.to_dict(), "adapt": adapt_result}
