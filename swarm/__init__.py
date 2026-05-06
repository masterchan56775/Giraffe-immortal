"""
swarm/__init__.py — 多智能体集群模块
"""
from .agent import AgentProfile, Agent
from .profiles import ARCHITECT, CODER, REVIEWER, TESTER, BUILTIN_PROFILES, get_profile
from .orchestrator import SwarmOrchestrator, SwarmResult

__all__ = [
    "AgentProfile", "Agent",
    "ARCHITECT", "CODER", "REVIEWER", "TESTER",
    "BUILTIN_PROFILES", "get_profile",
    "SwarmOrchestrator", "SwarmResult",
]
