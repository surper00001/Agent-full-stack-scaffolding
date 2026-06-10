"""
LLM 回调模块。

提供统一的 LangChain 回调处理器：
- TokenUsageCallback — Token 用量统计与成本估算
- build_trace_callbacks() — 构建完整回调列表 + Langfuse 追踪元数据
"""

import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger


class TokenUsageCallback(BaseCallbackHandler):
    """
    Token 用量统计回调。

    记录每次 LLM 调用的 token 消耗和耗时，
    可用于成本监控和性能分析。
    """

    def __init__(self) -> None:
        self.total_tokens: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_cost: float = 0.0
        self.call_count: int = 0
        self._start_time: float = 0.0

    def on_llm_start(
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any  # noqa: ARG002
    ) -> None:
        self._start_time = time.monotonic()
        self.call_count += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:  # noqa: ARG002
        """LLM 调用结束时统计 token 和耗时。"""
        elapsed = time.monotonic() - self._start_time

        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.total_tokens += prompt_tokens + completion_tokens

            logger.debug(
                f"LLM 调用完成 | 耗时: {elapsed:.2f}s | "
                f"输入: {prompt_tokens} tokens | 输出: {completion_tokens} tokens"
            )

            # 记录 LLM 调用到可观测性追踪器
            try:
                from src.services.observability_service import get_llm_tracker

                model_name = "unknown"
                if response.llm_output and "model_name" in response.llm_output:
                    model_name = response.llm_output["model_name"]
                elif hasattr(response, "model"):
                    model_name = str(response.model)  # type: ignore[union-attr]

                get_llm_tracker().record_sync(
                    model=model_name,
                    node="executor",
                    latency_ms=elapsed * 1000,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    success=True,
                )
            except Exception:
                pass  # tracker recording failure is non-critical

        else:
            logger.debug(f"LLM 调用完成 | 耗时: {elapsed:.2f}s (token 信息不可用)")

    def get_summary(self) -> dict[str, Any]:
        """获取用量摘要。"""
        return {
            "call_count": self.call_count,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_cost": self.total_cost,
        }


def build_trace_callbacks(
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """构建 LangChain 回调列表和 Langfuse 追踪元数据。

    返回 (callbacks, metadata) 元组：
    - callbacks: [TokenUsageCallback, (Langfuse CallbackHandler)]
    - metadata: 包含 langfuse_session_id, langfuse_user_id, langfuse_tags
      将其传入 LangGraph config["metadata"] 即可自动归因

    遵循 Langfuse 最佳实践：
    - framework integration (CallbackHandler) 自动捕获 model/token/cost
    - session_id 将对话分组到 Langfuse Sessions 视图
    - user_id 支持按用户过滤和成本归因
    - tags 支持按特性/环境等维度筛选
    """
    callbacks: list[Any] = [TokenUsageCallback()]
    metadata: dict[str, Any] = {}

    try:
        from src.monitoring.tracer import get_monitor

        monitor = get_monitor()
        if monitor.langfuse_handler is not None:
            callbacks.append(monitor.langfuse_handler)

        if session_id:
            metadata["langfuse_session_id"] = session_id
        if user_id:
            metadata["langfuse_user_id"] = user_id
        if tags:
            metadata["langfuse_tags"] = tags
    except Exception:
        logger.debug("构建 LangChain callbacks 时出错，使用空 callback 列表", exc_info=True)

    return callbacks, metadata
