"""
LLM 回调模块。

提供统一的 LangChain 回调处理器，用于：
- Token 用量统计
- LLM 调用耗时记录
- 成本估算
- 日志输出
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
        self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any
    ) -> None:
        self._start_time = time.monotonic()
        self.call_count += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
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
