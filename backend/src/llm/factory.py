"""
LLM 工厂模块。

根据配置动态创建 LangChain ChatModel 实例，
支持 DeepSeek、OpenAI、Anthropic 及兼容接口，统一模型创建入口。

DeepSeek 兼容 OpenAI API 规范，使用 ChatOpenAI 客户端调用。
"""

from functools import lru_cache
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.core.config import Settings, get_settings
from src.core.exceptions import LLMError


class LLMFactory:
    """
    LLM 工厂类。

    根据配置中的 llm_provider 自动创建对应的 ChatModel，
    并注入统一的 callbacks 用于监测。

    使用示例:
        factory = LLMFactory(settings)
        llm = factory.create_chat_model(temperature=0.7)
        embedding = factory.create_embeddings()
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def create_chat_model(
        self,
        model_name: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> BaseChatModel:
        """根据配置创建 ChatModel 实例。"""
        provider = self._settings.llm_provider

        if provider == "deepseek":
            return self._create_deepseek_chat(model_name, temperature, max_tokens, **kwargs)
        elif provider == "openai":
            return self._create_openai_chat(model_name, temperature, max_tokens, **kwargs)
        elif provider == "anthropic":
            return self._create_anthropic_chat(model_name, temperature, max_tokens, **kwargs)
        else:
            raise LLMError(f"不支持的 LLM 提供商: {provider}")

    def create_embeddings(self) -> Any:
        """创建嵌入模型实例。

        DeepSeek 的 Embedding 也兼容 OpenAI API。
        """
        settings = self._settings

        if settings.llm_provider in ("deepseek", "openai"):
            return OpenAIEmbeddings(
                model=settings.openai_embedding_model,
                openai_api_key=settings.openai_api_key.get_secret_value()
                or settings.deepseek_api_key.get_secret_value(),
                openai_api_base=settings.openai_api_base
                if settings.llm_provider == "openai"
                else settings.deepseek_api_base,
            )
        else:
            # Anthropic 暂不提供专用 Embedding，回退到 OpenAI
            return OpenAIEmbeddings(
                model=settings.openai_embedding_model,
                openai_api_key=settings.openai_api_key.get_secret_value(),
                openai_api_base=settings.openai_api_base,
            )

    def _create_deepseek_chat(
        self,
        model_name: str | None,
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> ChatOpenAI:
        """创建 DeepSeek Chat 模型（兼容 OpenAI API）。"""
        model = model_name or self._settings.deepseek_default_model
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens or 8192,
            openai_api_key=self._settings.deepseek_api_key.get_secret_value(),
            openai_api_base=self._settings.deepseek_api_base,
            **kwargs,
        )

    def _create_openai_chat(
        self,
        model_name: str | None,
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> ChatOpenAI:
        """创建 OpenAI Chat 模型。"""
        model = model_name or self._settings.openai_default_model
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            openai_api_key=self._settings.openai_api_key.get_secret_value(),
            openai_api_base=self._settings.openai_api_base,
            **kwargs,
        )

    def _create_anthropic_chat(
        self,
        model_name: str | None,
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> ChatAnthropic:
        """创建 Anthropic Chat 模型。"""
        model = model_name or self._settings.anthropic_default_model
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens or 4096,
            anthropic_api_key=self._settings.anthropic_api_key.get_secret_value(),
            **kwargs,
        )


    def create_plan_model(
        self,
        model_name: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> BaseChatModel:
        """创建规划专用模型（低温度，更确定性）。

        优先使用 PLAN_MODEL_NAME 配置，未配置则复用执行模型。
        """
        settings = self._settings
        plan_model = model_name or settings.plan_model_name or None
        if plan_model:
            return self.create_chat_model(
                model_name=plan_model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        # 未配置独立 Plan Model，复用执行模型但降低温度
        return self.create_chat_model(
            model_name=None,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


@lru_cache
def get_llm_factory() -> LLMFactory:
    """获取缓存的 LLM 工厂单例。"""
    return LLMFactory()
