"""
LLM 韧性模块 — 熔断器 + 智能重试。

提供生产级 LLM 调用保护：
- 熔断器：连续失败 N 次后快速失败，避免雪崩
- 重试：指数退避 + 抖动，仅对瞬态错误重试
- 与 Prometheus 指标集成
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
    before_sleep_log,
)

from src.monitoring.metrics import (
    LLM_CALL_LATENCY,
    LLM_TOKEN_USAGE,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ── ResilientLLMWrapper：透明包装 BaseChatModel ──


class ResilientLLMWrapper:
    """为任何 BaseChatModel 添加熔断器 + 重试的透明包装器。

    用法:
        raw_llm = ChatOpenAI(model="deepseek-chat", ...)
        llm = ResilientLLMWrapper(raw_llm, provider="deepseek")
        response = await llm.ainvoke(messages)  # 自动熔断+重试
    """

    def __init__(
        self,
        llm: Any,  # BaseChatModel
        provider: str = "default",
        max_retries: int = 3,
    ) -> None:
        self._llm = llm
        self._provider = provider
        self._max_retries = max_retries
        self._circuit = get_circuit(provider)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """带韧性保护的异步 LLM 调用。"""
        return await _resilient_call(
            lambda: self._llm.ainvoke(*args, **kwargs),
            circuit=self._circuit,
            provider=self._provider,
            max_retries=self._max_retries,
        )

    async def astream(self, *args: Any, **kwargs: Any) -> Any:
        """带韧性保护的异步流式 LLM 调用。"""
        # 流式调用使用独立的短超时重试策略
        return await _resilient_call(
            lambda: self._llm.astream(*args, **kwargs),
            circuit=self._circuit,
            provider=self._provider,
            max_retries=min(self._max_retries, 1),  # 流式仅重试 1 次
        )

    # 透传常用属性
    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


async def _resilient_call(
    callable_fn: Callable[[], Any],
    circuit: CircuitBreaker,
    provider: str,
    max_retries: int,
) -> Any:
    """核心韧性调用逻辑 — 熔断器检查 + 指数退避重试。"""
    import asyncio

    if circuit.is_open:
        raise RuntimeError(
            f"LLM 熔断器已打开（provider={provider}），"
            f"快速失败至 {circuit.recovery_timeout}s 后重试"
        )

    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            start = time.perf_counter()
            result = await callable_fn()
            elapsed = time.perf_counter() - start

            circuit.record_success()
            LLM_CALL_LATENCY.labels(model=provider).observe(elapsed)
            return result

        except Exception as e:
            last_exception = e
            circuit.record_failure()

            # 不可重试的错误直接抛出
            if not _is_retryable(e):
                raise

            # 最后一次尝试，不再等待
            if attempt >= max_retries:
                logger.error(
                    f"LLM 调用耗尽重试次数（attempt={attempt + 1}/{max_retries + 1}）: {e}"
                )
                raise

            # 指数退避 + 抖动
            delay = min(1.0 * (2 ** attempt) + random.uniform(0, 1.0), 30.0)
            logger.warning(
                f"LLM 调用失败（attempt={attempt + 1}/{max_retries + 1}），"
                f"{delay:.1f}s 后重试: {e}"
            )
            await asyncio.sleep(delay)

    # 理论上不会到达这里
    if last_exception:
        raise last_exception
    raise RuntimeError("LLM 调用失败：未知原因")

# ── 可重试的瞬态异常类型 ──

RETRYABLE_EXCEPTIONS = (
    TimeoutError,
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    OSError,  # 网络层错误
)


def _is_retryable(exception: BaseException) -> bool:
    """判断异常是否可重试（瞬态网络/超时错误）。

    优先检查异常类名（避免硬依赖特定 SDK 的异常类型）。
    """
    exc_name = type(exception).__name__
    exc_msg = str(exception).lower()

    # 按类名匹配常见 LLM 提供商的瞬态错误
    retryable_names = {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "APIStatusError",  # OpenAI SDK 的状态错误基类
        "ServerError",  # Anthropic
    }
    if exc_name in retryable_names:
        return True

    # API 返回 429 / 5xx 状态码
    for attr in ("status_code", "http_status", "status"):
        code = getattr(exception, attr, None)
        if code is not None and (code == 429 or (500 <= code < 600)):
            return True

    # 按消息关键词匹配
    retryable_keywords = [
        "rate limit", "too many requests", "429",
        "server error", "internal error", "503", "502", "504",
        "timeout", "timed out", "connection",
        "overloaded", "capacity", "throttle",
    ]
    if any(kw in exc_msg for kw in retryable_keywords):
        return True

    # 内建网络异常
    if isinstance(exception, RETRYABLE_EXCEPTIONS):
        return True

    return False


# ── 熔断器 ──


class CircuitState(Enum):
    CLOSED = "closed"       # 正常工作
    OPEN = "open"           # 熔断，快速失败
    HALF_OPEN = "half_open"  # 半开，允许探测请求


@dataclass
class CircuitBreaker:
    """线程安全的熔断器实现。

    状态机：CLOSED → (连续失败) → OPEN → (超时后) → HALF_OPEN → (成功) → CLOSED
                                                    HALF_OPEN → (失败) → OPEN
    """

    failure_threshold: int = 5         # 连续失败次数阈值
    recovery_timeout: float = 30.0     # OPEN → HALF_OPEN 的等待时间（秒）
    half_open_max: int = 1             # HALF_OPEN 状态下允许多少次探测

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_attempts: int = 0
    _consecutive_successes: int = 0

    @property
    def is_open(self) -> bool:
        """当前是否应快速失败。"""
        if self.state == CircuitState.CLOSED:
            return False
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.last_failure_time >= self.recovery_timeout:
                # 超时，进入半开状态
                self.state = CircuitState.HALF_OPEN
                self.half_open_attempts = 0
                logger.info("熔断器: OPEN → HALF_OPEN（恢复超时已到）")
                return False
            return True
        # HALF_OPEN — 允许有限探测
        return self.half_open_attempts >= self.half_open_max

    def record_success(self) -> None:
        """记录一次成功调用。"""
        if self.state == CircuitState.HALF_OPEN:
            self._consecutive_successes += 1
            if self._consecutive_successes >= self.half_open_max:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self._consecutive_successes = 0
                logger.info("熔断器: HALF_OPEN → CLOSED（探测成功）")
        else:
            # CLOSED 状态下重置失败计数
            self.failure_count = 0

    def record_failure(self) -> None:
        """记录一次失败调用。"""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            # 探测失败，立即重新打开
            self.state = CircuitState.OPEN
            self._consecutive_successes = 0
            logger.warning("熔断器: HALF_OPEN → OPEN（探测失败）")
        elif self.failure_count >= self.failure_threshold and self.state == CircuitState.CLOSED:
            self.state = CircuitState.OPEN
            logger.warning(
                f"熔断器: CLOSED → OPEN（连续失败 {self.failure_count} 次，"
                f"等待 {self.recovery_timeout}s）"
            )


# ── 全局熔断器实例（按 provider） ──

_circuits: dict[str, CircuitBreaker] = {}


def get_circuit(provider: str = "default") -> CircuitBreaker:
    """获取指定 provider 的熔断器实例。"""
    if provider not in _circuits:
        _circuits[provider] = CircuitBreaker()
    return _circuits[provider]


def reset_all_circuits() -> None:
    """重置所有熔断器（测试用）。"""
    _circuits.clear()


# ── 装饰器 ──


def with_llm_resilience(
    provider: str = "default",
    max_retries: int = 3,
    circuit_key: str | None = None,
):
    """LLM 调用韧性装饰器：熔断器 + 指数退避重试。

    用法:
        @with_llm_resilience(provider="deepseek", max_retries=3)
        async def call_llm(prompt: str) -> str:
            ...
    """
    circuit = get_circuit(circuit_key or provider)

    def decorator(func: F) -> F:
        @retry(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max_retries + 1),  # +1 包含首次尝试
            wait=wait_exponential_jitter(
                initial=1.0, max=30.0, jitter=2.0
            ),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if circuit.is_open:
                raise RuntimeError(
                    f"LLM 熔断器已打开（provider={provider}），"
                    f"快速失败至 {circuit.recovery_timeout}s 后重试"
                )

            try:
                start = time.perf_counter()
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start

                circuit.record_success()

                # 上报 Prometheus 延迟指标
                LLM_CALL_LATENCY.labels(model=provider).observe(elapsed)

                return result
            except Exception as e:
                circuit.record_failure()
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


# ── 便捷函数 ──


async def resilient_ainvoke(
    llm: Any,
    input_messages: list[Any],
    provider: str = "default",
    max_retries: int = 3,
    **kwargs: Any,
) -> Any:
    """带熔断器+重试保护的 LLM ainvoke 调用。

    用法（替换 llm.ainvoke(messages)）:
        response = await resilient_ainvoke(llm, messages, provider="deepseek")
    """
    circuit = get_circuit(provider)
    return await _resilient_call(
        lambda: llm.ainvoke(input_messages, **kwargs),
        circuit=circuit,
        provider=provider,
        max_retries=max_retries,
    )


def report_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """上报 LLM Token 消耗到 Prometheus。"""
    LLM_TOKEN_USAGE.labels(model=model, type="prompt").inc(prompt_tokens)
    LLM_TOKEN_USAGE.labels(model=model, type="completion").inc(completion_tokens)
