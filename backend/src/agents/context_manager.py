"""
上下文管理器：token 感知的对话上下文优化。

支持四种策略：
- SLIDING_WINDOW：保留最新的 N 个 token 内的消息
- SUMMARIZE：将旧消息压缩为 LLM 摘要
- SELECTIVE：基于向量相似度的选择性检索
- HYBRID：摘要 + 最近消息 + 相关消息（推荐默认）
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class ContextStrategy(StrEnum):
    SLIDING_WINDOW = "sliding_window"
    SUMMARIZE = "summarize"
    SELECTIVE = "selective"
    HYBRID = "hybrid"


@dataclass
class ContextConfig:
    strategy: ContextStrategy = ContextStrategy.HYBRID
    max_tokens: int = 128_000
    response_reserve: int = 8_192
    summary_max_tokens: int = 2_048
    recent_message_count: int = 10
    selective_top_k: int = 5


@dataclass
class ContextUsage:
    total_tokens: int = 0
    available_tokens: int = 0
    used_tokens: int = 0
    strategy: str = ""
    message_count: int = 0
    original_message_count: int = 0
    compressed_ratio: float = 0.0
    summary_tokens: int = 0
    has_summary: bool = False


class TokenCounter:
    """Token 计数器，优先使用 tiktoken，失败回退近似计数。"""

    MODEL_TOKEN_LIMITS: dict[str, int] = {
        "deepseek-chat": 65536,
        "deepseek-reasoner": 65536,
        "gpt-4o": 128000,
        "gpt-4-turbo": 128000,
        "claude-sonnet-4-6": 200000,
        "claude-opus-4-7": 200000,
        "default": 128000,
    }

    def __init__(self, model_name: str = "default") -> None:
        self._model_name = model_name
        self._encoder: Any = None
        self._init_encoder()

    def _init_encoder(self) -> None:
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        if self._encoder:
            return len(self._encoder.encode(text))
        return self._approximate_count(text)

    def count_messages(self, messages: list[BaseMessage]) -> int:
        total = 0
        for msg in messages:
            total += self._count_message_tokens(msg)
        return total

    def _count_message_tokens(self, message: BaseMessage) -> int:
        content = ""
        if isinstance(message.content, str):
            content = message.content
        elif isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, dict) and "text" in block:
                    content += block["text"]
        base = self.count_tokens(content)
        if isinstance(message, ToolMessage):
            base += self.count_tokens(message.tool_call_id or "")
        return base + 4

    @staticmethod
    def _approximate_count(text: str) -> int:
        """中英文混合近似：英文 ~4 字符/token，中文 ~1.5 字符/token。"""
        char_count = len(text)
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii = char_count - ascii_chars
        return math.ceil(ascii_chars / 4 + non_ascii / 1.5)

    def get_effective_limit(self) -> int:
        return self.MODEL_TOKEN_LIMITS.get(self._model_name, self.MODEL_TOKEN_LIMITS["default"])


class ContextSummarizer:
    """LLM 驱动的对话摘要生成器，支持增量合并。"""

    SUMMARY_PROMPT = (
        "请将以下对话内容压缩为简洁摘要，保留关键信息、用户意图、重要决策和待办事项。"
        "控制在 {max_tokens} token 以内。"
        "\n\n对话内容：\n{messages_text}"
    )

    MERGE_PROMPT = (
        "现有摘要：\n{existing_summary}\n\n"
        "以下是新的对话内容，请将其合并到现有摘要中，保留重要细节。"
        "控制在 {max_tokens} token 以内。"
        "\n\n新内容：\n{messages_text}"
    )

    def __init__(
        self,
        llm: BaseChatModel,
        token_counter: TokenCounter,
        max_summary_tokens: int = 2_048,
    ) -> None:
        self._llm = llm
        self._token_counter = token_counter
        self._max_summary_tokens = max_summary_tokens

    async def create_summary(
        self,
        messages: list[BaseMessage],
        existing_summary: str | None = None,
    ) -> str:
        if not messages:
            return existing_summary or ""

        messages_text = self._format_messages(messages)
        if existing_summary:
            prompt = self.MERGE_PROMPT.format(
                existing_summary=existing_summary,
                messages_text=messages_text,
                max_tokens=self._max_summary_tokens,
            )
        else:
            prompt = self.SUMMARY_PROMPT.format(
                messages_text=messages_text,
                max_tokens=self._max_summary_tokens,
            )

        try:
            from src.llm.resilience import resilient_ainvoke

            response = await resilient_ainvoke(
                self._llm,
                [HumanMessage(content=prompt)],
                provider="context_summarizer",
                max_retries=2,
            )
            return response.content if isinstance(response.content, str) else str(response.content)
        except Exception as e:
            logger.warning(f"上下文摘要生成失败: {e}")
            return existing_summary or ""

    @staticmethod
    def _format_messages(messages: list[BaseMessage]) -> str:
        role_map = {"human": "用户", "ai": "AI", "tool": "工具", "system": "系统"}
        parts: list[str] = []
        for msg in messages:
            msg_type = getattr(msg, "type", "unknown")
            role = role_map.get(msg_type, msg_type)
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            parts.append(f"[{role}]: {content}")
        return "\n".join(parts)


class VectorStoreProtocol(Protocol):
    """向量存储接口协议，不依赖具体实现。"""

    async def similarity_search(
        self, query: str, collection_name: str, tenant_id: str = "", top_k: int = 5, **kwargs: Any
    ) -> list[Any]: ...

    async def add_documents(
        self, documents: list[Any], collection_name: str, tenant_id: str = ""
    ) -> list[str]: ...


class ContextManager:
    """Token 感知的上下文管理器主入口。"""

    def __init__(
        self,
        config: ContextConfig | None = None,
        token_counter: TokenCounter | None = None,
        summarizer: ContextSummarizer | None = None,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self._config = config or ContextConfig()
        self._token_counter = token_counter or TokenCounter()
        self._summarizer = summarizer
        self._vector_store = vector_store
        self.stats = ContextUsage()

    async def prepare_context(
        self,
        messages: list[BaseMessage],
        system_prompt: str | None = None,
    ) -> list[BaseMessage]:
        """根据配置策略优化消息上下文并返回优化后的消息列表。"""
        strategy = self._config.strategy
        self.stats = ContextUsage()
        self.stats.original_message_count = len(messages)

        result: list[BaseMessage] = []
        if system_prompt:
            result.append(SystemMessage(content=system_prompt))

        if strategy == ContextStrategy.SLIDING_WINDOW:
            processed = self._apply_sliding_window(messages)
        elif strategy == ContextStrategy.SUMMARIZE:
            processed = await self._apply_summarize(messages)
        elif strategy == ContextStrategy.SELECTIVE:
            processed = await self._apply_selective(messages)
        elif strategy == ContextStrategy.HYBRID:
            processed = await self._apply_hybrid(messages)
        else:
            processed = messages

        result.extend(processed)

        budget = self._config.max_tokens - self._config.response_reserve
        total_tokens = self._token_counter.count_messages(result)
        if total_tokens > budget:
            result = self._trim_to_budget(result, budget)
            total_tokens = self._token_counter.count_messages(result)

        self.stats.strategy = strategy.value
        self.stats.message_count = len(result)
        self.stats.total_tokens = total_tokens
        self.stats.available_tokens = self._config.max_tokens
        self.stats.used_tokens = total_tokens
        self.stats.compressed_ratio = (
            (self.stats.original_message_count - self.stats.message_count)
            / max(self.stats.original_message_count, 1)
        )

        return result

    # ---- 各策略实现 ----

    def _apply_sliding_window(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        budget = self._config.max_tokens - self._config.response_reserve
        selected: list[BaseMessage] = []
        running = 0
        for msg in reversed(messages):
            tokens = self._token_counter._count_message_tokens(msg)
            if running + tokens > budget:
                break
            selected.append(msg)
            running += tokens
        selected.reverse()
        return selected

    async def _apply_summarize(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if not self._summarizer:
            return self._apply_sliding_window(messages)

        reserve_tokens = self._config.response_reserve + self._config.summary_max_tokens
        max_recent_tokens = max(self._config.max_tokens - reserve_tokens, 0)

        recent: list[BaseMessage] = []
        old: list[BaseMessage] = []
        running = 0
        for msg in reversed(messages):
            tokens = self._token_counter._count_message_tokens(msg)
            if running + tokens <= max_recent_tokens:
                recent.append(msg)
                running += tokens
            else:
                old.append(msg)
        recent.reverse()
        old.reverse()

        if not old:
            return messages

        summary_text = await self._summarizer.create_summary(old)
        self.stats.summary_tokens = self._token_counter.count_tokens(summary_text)
        self.stats.has_summary = bool(summary_text)

        result: list[BaseMessage] = [
            SystemMessage(content=f"[对话历史摘要]\n{summary_text}")
        ]
        result.extend(recent)
        return result

    async def _apply_selective(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        if not self._vector_store:
            return self._apply_sliding_window(messages)

        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg
                break

        result: list[BaseMessage] = []
        if last_user_msg and last_user_msg.content:
            content = last_user_msg.content if isinstance(last_user_msg.content, str) else str(last_user_msg.content)
            relevant_docs = await self._vector_store.similarity_search(
                query=content,
                collection_name="conversation_context",
                top_k=self._config.selective_top_k,
            )
            if relevant_docs:
                relevant_text = "\n".join(
                    doc.page_content if hasattr(doc, "page_content") else str(doc)
                    for doc in relevant_docs
                )
                result.append(SystemMessage(content=f"[相关历史内容]\n{relevant_text}"))

        recent = messages[-min(len(messages), 3):]
        result.extend(recent)
        return result

    async def _apply_hybrid(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        recent_count = self._config.recent_message_count
        recent = messages[-recent_count:] if len(messages) > recent_count else messages
        old = messages[:-recent_count] if len(messages) > recent_count else []

        result: list[BaseMessage] = []

        # Layer 1: Summary of old messages
        if old and self._summarizer:
            summary_text = await self._summarizer.create_summary(old)
            if summary_text:
                self.stats.has_summary = True
                self.stats.summary_tokens = self._token_counter.count_tokens(summary_text)
                result.append(SystemMessage(content=f"[对话历史摘要]\n{summary_text}"))

        # Layer 2: Selective retrieval from old messages
        if self._vector_store and old:
            last_query = None
            for msg in reversed(recent):
                if isinstance(msg, HumanMessage):
                    last_query = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break
            if last_query:
                relevant_docs = await self._vector_store.similarity_search(
                    query=last_query,
                    collection_name="conversation_context",
                    top_k=3,
                )
                if relevant_docs:
                    relevant_text = "\n".join(
                        doc.page_content if hasattr(doc, "page_content") else str(doc)
                        for doc in relevant_docs
                    )
                    result.append(SystemMessage(content=f"[相关内容]\n{relevant_text}"))

        # Layer 3: Recent messages (always included)
        result.extend(recent)
        return result

    # ---- 辅助方法 ----

    def _trim_to_budget(self, messages: list[BaseMessage], budget: int) -> list[BaseMessage]:
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        while non_system and self._token_counter.count_messages(system_msgs + non_system) > budget:
            non_system.pop(0)

        return system_msgs + non_system


def create_context_manager_from_settings(
    llm: BaseChatModel | None = None,
    vector_store: VectorStoreProtocol | None = None,
) -> ContextManager:
    """从全局 Settings 创建 ContextManager 的便捷工厂。"""
    from src.core.config import get_settings

    settings = get_settings()
    strategy_map = {
        "sliding_window": ContextStrategy.SLIDING_WINDOW,
        "summarize": ContextStrategy.SUMMARIZE,
        "selective": ContextStrategy.SELECTIVE,
        "hybrid": ContextStrategy.HYBRID,
    }
    strategy = strategy_map.get(settings.context_strategy, ContextStrategy.HYBRID)
    config = ContextConfig(
        strategy=strategy,
        max_tokens=settings.context_max_tokens,
        response_reserve=settings.context_response_reserve,
        summary_max_tokens=settings.context_summary_max_tokens,
        recent_message_count=settings.context_recent_message_count,
        selective_top_k=settings.context_selective_top_k,
    )

    token_counter = TokenCounter()
    summarizer = None
    if llm and strategy in (ContextStrategy.SUMMARIZE, ContextStrategy.HYBRID):
        summarizer = ContextSummarizer(
            llm=llm,
            token_counter=token_counter,
            max_summary_tokens=config.summary_max_tokens,
        )

    return ContextManager(
        config=config,
        token_counter=token_counter,
        summarizer=summarizer,
        vector_store=vector_store,
    )
