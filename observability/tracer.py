"""
observability/tracer.py — OpenTelemetry 链路追踪封装

提供全局 Tracer 初始化、获取和 @traced 装饰器。
当 OpenTelemetry SDK 未安装时，自动降级为 NoOp 模式，不影响业务逻辑。
"""
from __future__ import annotations

import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)

# ─── 尝试导入 OpenTelemetry ─────────────────────────────────────────────────
_OTEL_AVAILABLE = False
_tracer_provider = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource

    _OTEL_AVAILABLE = True
except ImportError:
    trace = None  # type: ignore


# ─── NoOp 降级实现 ──────────────────────────────────────────────────────────
class _NoOpSpan:
    """当 OpenTelemetry 不可用时使用的空 Span。"""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """当 OpenTelemetry 不可用时使用的空 Tracer。"""

    def start_as_current_span(self, name: str, **kwargs):
        return _NoOpSpan()

    @contextmanager
    def start_span(self, name: str, **kwargs) -> Generator:
        yield _NoOpSpan()


_noop_tracer = _NoOpTracer()


# ─── 公共接口 ───────────────────────────────────────────────────────────────
def init_tracer(
    service_name: str = "giraffe",
    endpoint: str = "",
    console_export: bool = False,
) -> None:
    """
    初始化 OpenTelemetry TracerProvider。

    Args:
        service_name: 服务名称，显示在 Jaeger/Grafana 中。
        endpoint: OTLP Exporter 的 gRPC 地址（如 "localhost:4317"）。
                  为空时仅使用 ConsoleSpanExporter。
        console_export: 是否同时将 Span 输出到控制台日志。
    """
    global _tracer_provider

    if not _OTEL_AVAILABLE:
        logger.info("[Tracer] OpenTelemetry SDK 未安装，链路追踪以 NoOp 模式运行")
        return

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    # OTLP Exporter（可选）
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"[Tracer] OTLP Exporter 已连接: {endpoint}")
        except ImportError:
            logger.warning(
                "[Tracer] opentelemetry-exporter-otlp 未安装，跳过 OTLP 导出"
            )

    # Console Exporter（调试用）
    if console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("[Tracer] Console Exporter 已启用")

    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    logger.info(f"[Tracer] 链路追踪初始化完成 (service={service_name})")


def get_tracer(name: str = "giraffe") -> Any:
    """
    获取命名的 Tracer 实例。
    未初始化或未安装 OpenTelemetry 时返回 NoOp Tracer。
    """
    if _OTEL_AVAILABLE and _tracer_provider is not None:
        return trace.get_tracer(name)
    return _noop_tracer


def traced(
    span_name: str | None = None,
    attributes: dict[str, str] | None = None,
) -> Callable:
    """
    装饰器：自动为被装饰的函数创建 Span。

    Args:
        span_name: 自定义 Span 名称。默认为 "module.function_name"。
        attributes: 要附加到 Span 的静态属性。

    用法::

        @traced("giraffe.router.route")
        def route(self, message: str) -> RouteDecision:
            ...
    """

    def decorator(func: Callable) -> Callable:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()

            # NoOp 模式直接执行
            if isinstance(tracer, _NoOpTracer):
                return func(*args, **kwargs)

            with tracer.start_as_current_span(name) as span:
                if attributes:
                    for k, v in attributes.items():
                        span.set_attribute(k, v)
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator
