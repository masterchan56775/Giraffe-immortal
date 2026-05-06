"""
SkillLoader — 技能加载器
负责技能模块的发现、注册和加载
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillLoader:
    """技能加载器。动态加载 skills/ 目录下的技能模块。"""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        self._skills_dir = Path(skills_dir) if skills_dir else Path(__file__).parent.parent / "skills"
        self._loaded: dict[str, Any] = {}

    def load_all(self) -> int:
        """加载所有技能模块，返回加载数量。

        注意: 若 skills 目录不存在，记录 WARNING 并返回 0（不会抛异常）。
        """
        if not self._skills_dir.exists():
            logger.warning(
                f"[SkillLoader] skills 目录不存在: {self._skills_dir.resolve()} —— 跳过技能加载。"
                f"如需加载技能，请确保该目录存在并包含 skill_*.py 文件。"
            )
            return 0
        count = 0
        for py_file in self._skills_dir.glob("skill_*.py"):
            name = py_file.stem
            if self._load_module(name, py_file):
                count += 1
        logger.info(f"[SkillLoader] 加载了 {count} 个技能")
        return count

    def _load_module(self, name: str, path: Path) -> bool:
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._loaded[name] = module
                return True
        except Exception as e:
            logger.warning(f"[SkillLoader] 加载失败 {name}: {e}")
        return False

    def get_skill(self, name: str) -> Any | None:
        return self._loaded.get(name)

    def list_skills(self) -> list[str]:
        return list(self._loaded.keys())

    def __repr__(self) -> str:
        return f"SkillLoader(loaded={len(self._loaded)})"
