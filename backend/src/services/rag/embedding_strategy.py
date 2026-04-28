"""
Embedding 编码策略。

不同 Embedding 模型对 query / document 的输入格式要求不同：
- BGE 系列：query 需加检索指令前缀，document 保持原文
- Qwen3-Embedding：需通过 prompt_name 区分 query 与 document

若 query 与 document 使用相同编码方式，相似度分布会严重失真，
表现为「搜什么都像随机」——这是 RAG 召回差的高频根因之一。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingStrategy(ABC):
    """Embedding 输入格式化策略抽象基类。"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """策略绑定的模型名称。"""

    @abstractmethod
    def format_query(self, text: str) -> str:
        """格式化检索 query。"""

    @abstractmethod
    def format_document(self, text: str) -> str:
        """格式化待索引文档片段。"""

    def encode_kwargs_for_query(self) -> dict[str, Any]:
        """传给 SentenceTransformer.encode 的 query 侧额外参数。"""
        return {}

    def encode_kwargs_for_document(self) -> dict[str, Any]:
        """传给 SentenceTransformer.encode 的 document 侧额外参数。"""
        return {}


class BGEStrategy(EmbeddingStrategy):
    """BAAI/bge-* 系列模型的编码策略。"""

    QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def format_query(self, text: str) -> str:
        text = text.strip()
        if text.startswith(self.QUERY_PREFIX):
            return text
        return f"{self.QUERY_PREFIX}{text}"

    def format_document(self, text: str) -> str:
        return text.strip()


class Qwen3Strategy(EmbeddingStrategy):
    """Qwen/Qwen3-Embedding-* 系列模型的编码策略。"""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def format_query(self, text: str) -> str:
        return text.strip()

    def format_document(self, text: str) -> str:
        return text.strip()

    def encode_kwargs_for_query(self) -> dict[str, Any]:
        return {"prompt_name": "query"}

    def encode_kwargs_for_document(self) -> dict[str, Any]:
        return {"prompt_name": "document"}


class GenericStrategy(EmbeddingStrategy):
    """未知模型的兜底策略——不做额外格式化。"""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def format_query(self, text: str) -> str:
        return text.strip()

    def format_document(self, text: str) -> str:
        return text.strip()


def get_embedding_strategy(model_name: str) -> EmbeddingStrategy:
    """根据模型名自动选择编码策略。"""
    name_lower = model_name.lower()
    if "qwen3" in name_lower and "embedding" in name_lower:
        return Qwen3Strategy(model_name)
    if "bge" in name_lower or "bce-embedding" in name_lower:
        return BGEStrategy(model_name)
    return GenericStrategy(model_name)
