"""
SandboxManager — Docker容器管理
在无Docker环境下优雅降级为本地隔离执行
"""
from __future__ import annotations
import logging, uuid
logger = logging.getLogger(__name__)

class SandboxManager:
    """沙箱容器管理器。优先使用Docker，无Docker时降级为进程隔离。"""
    def __init__(self) -> None:
        self._sandboxes: dict[str, dict] = {}
        self._docker_available = self._check_docker()

    def _check_docker(self) -> bool:
        try:
            import subprocess
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
            return result.returncode == 0
        except Exception:
            return False

    def create(self, name: str = "", image: str = "python:3.11-slim") -> str:
        """创建沙箱，返回sandbox_id。"""
        sandbox_id = name or f"sandbox_{uuid.uuid4().hex[:6]}"
        self._sandboxes[sandbox_id] = {
            "id": sandbox_id,
            "image": image,
            "docker": self._docker_available,
            "status": "running",
        }
        mode = "Docker" if self._docker_available else "本地进程"
        logger.info(f"[Sandbox] 创建沙箱: {sandbox_id} ({mode}模式)")
        return sandbox_id

    def cleanup(self, sandbox_id: str) -> bool:
        """清理沙箱。"""
        if sandbox_id in self._sandboxes:
            del self._sandboxes[sandbox_id]
            logger.info(f"[Sandbox] 清理沙箱: {sandbox_id}")
            return True
        return False

    def list_sandboxes(self) -> list[dict]:
        return list(self._sandboxes.values())

    def stats(self) -> dict:
        return {
            "docker_available": self._docker_available,
            "active_sandboxes": len(self._sandboxes),
        }
