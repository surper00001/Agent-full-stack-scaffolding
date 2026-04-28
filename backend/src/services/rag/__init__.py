"""
RAG 检索增强生成子模块。

注意：不在包初始化时导入 retrieval_pipeline / hybrid_search，
避免与 embedding_service 形成循环依赖。
请按需直接导入子模块，例如：
  from src.services.rag.retrieval_pipeline import RetrievalPipeline
"""

from src.services.rag.embedding_strategy import (
    EmbeddingStrategy,
    get_embedding_strategy,
)

__all__ = [
    "EmbeddingStrategy",
    "get_embedding_strategy",
]
