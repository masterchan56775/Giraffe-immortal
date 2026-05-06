"""
observability — 全链路 Telemetry 与可观测性模块
提供 OpenTelemetry 链路追踪、Span 管理和 @traced 装饰器。
"""
from .tracer import init_tracer, get_tracer, traced

__all__ = ["init_tracer", "get_tracer", "traced"]
