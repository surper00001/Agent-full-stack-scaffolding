"""
Conversation Context Store — 对话上下文向量存储。

为 ContextManager 的 SELECTIVE 和 HYBRID 策略提供数据支持：
- 每条 user/assistant 消息独立 embed 并存入 conversation_context 集合
- 支持相似度检索（供 ContextManager 召回历史相关消息）
- 支持按 conversation_id 清理（会话删除时）
- 延迟初始化向量存储，避免启动时依赖
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.documents import Document
from loguru import logger

from src.vectorstore.base import BaseVectorStore, create_vector_store

COLLECTION_NAME = "conversation_context"


class ConversationContextStore:
    """
    对话上下文向量存储。

    负责将对话消息嵌入并持久化到向量数据库，
    供 ContextManager 在 SELECTIVE/HYBRID 模式下检索。

    使用方式:
        store = ConversationContextStore()
        await store.ensure_store()

        # 写
        await store.add_message(message_id="msg-1", role="user",
                                content="你好", conversation_id="conv-1",
                                tenant_id="t1")

        # 读
        docs = await store.search("你好", tenant_id="t1", top_k=5)

        # 清理
        await store.delete_conversation("conv-1", tenant_id="t1")
    """

    def __init__(self) -> None:
        self._store: BaseVectorStore | None = None
        self._initialized = False

    async def ensure_store(self) -> None:
        """确保向量存储已初始化（延迟加载）。"""
        if self._initialized and self._store is not None:
            return

        try:
            from src.services.embedding_service import get_embedding_service

            embedding_service = get_embedding_service()
            self._store = create_vector_store(
                embedding_function=embedding_service.to_langchain()
            )
            self._initialized = True
            logger.info("ConversationContextStore 已初始化")
        except Exception as e:
            logger.warning(f"ConversationContextStore 初始化失败（不影响核心功能）: {e}")
            self._initialized = True  # 标记为已尝试，不重复失败

    async def add_message(
        self,
        message_id: str,
        role: str,
        content: str,
        conversation_id: str,
        tenant_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        将单条消息嵌入并写入向量存储。

        Args:
            message_id: 数据库中的消息 ID
            role: 消息角色 (user / assistant)
            content: 消息文本内容
            conversation_id: 所属会话 ID
            tenant_id: 租户 ID
            metadata: 附加元数据

        Returns:
            是否成功写入
        """
        await self.ensure_store()
        if self._store is None:
            return False

        # 跳过空内容和过短消息（浪费向量空间）
        if not content or len(content.strip()) < 2:
            return False

        try:
            doc_id = _make_doc_id(message_id, conversation_id)
            merged_meta: dict[str, Any] = {
                "message_id": message_id,
                "role": role,
                "conversation_id": conversation_id,
                **(metadata or {}),
            }

            doc = Document(
                page_content=f"[{role}] {content.strip()[:4000]}",
                metadata=merged_meta,
                id=doc_id,
            )

            await self._store.add_documents(
                documents=[doc],
                collection_name=COLLECTION_NAME,
                tenant_id=tenant_id,
            )
            return True
        except Exception as e:
            logger.debug(f"写入 conversation_context 失败: {e}")
            return False

    async def add_messages_batch(
        self,
        messages: list[dict[str, Any]],
        tenant_id: str = "default",
    ) -> int:
        """
        批量写入消息到向量存储（用于回填历史会话）。

        每条消息需包含: message_id, role, content, conversation_id

        Returns:
            成功写入的条数
        """
        await self.ensure_store()
        if self._store is None:
            return 0

        docs: list[Document] = []
        for msg in messages:
            content = msg.get("content", "")
            if not content or len(content.strip()) < 2:
                continue

            doc_id = _make_doc_id(msg["message_id"], msg.get("conversation_id", ""))
            docs.append(Document(
                page_content=f"[{msg.get('role', 'unknown')}] {str(content).strip()[:4000]}",
                metadata={
                    "message_id": msg["message_id"],
                    "role": msg.get("role", "unknown"),
                    "conversation_id": msg.get("conversation_id", ""),
                },
                id=doc_id,
            ))

        if not docs:
            return 0

        try:
            await self._store.add_documents(
                documents=docs,
                collection_name=COLLECTION_NAME,
                tenant_id=tenant_id,
            )
            return len(docs)
        except Exception as e:
            logger.warning(f"批量写入 conversation_context 失败: {e}")
            return 0

    async def search(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 5,
        conversation_id: str | None = None,
    ) -> list[Document]:
        """
        搜索与查询最相关的历史消息。

        Args:
            query: 查询文本（通常是当前用户消息）
            tenant_id: 租户 ID
            top_k: 返回结果数
            conversation_id: 可选，限定搜索结果到指定会话

        Returns:
            相关 Document 列表
        """
        await self.ensure_store()
        if self._store is None:
            return []

        try:
            return await self._store.similarity_search(
                query=query,
                collection_name=COLLECTION_NAME,
                tenant_id=tenant_id,
                top_k=top_k,
            )
        except Exception as e:
            logger.debug(f"conversation_context 搜索失败: {e}")
            return []

    async def delete_conversation(self, conversation_id: str, tenant_id: str = "default") -> bool:
        """删除指定会话的所有上下文消息（会话删除时调用）。"""
        await self.ensure_store()
        if self._store is None:
            return False

        try:
            return await self._store.delete_by_filter(
                where={"conversation_id": conversation_id},
                collection_name=COLLECTION_NAME,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.debug(f"删除 conversation_context 失败: {e}")
            return False

    async def delete_message(self, message_id: str, conversation_id: str, tenant_id: str = "default") -> bool:
        """删除单条消息的向量记录。"""
        await self.ensure_store()
        if self._store is None:
            return False

        doc_id = _make_doc_id(message_id, conversation_id)
        try:
            return await self._store.delete_by_ids(
                ids=[doc_id],
                collection_name=COLLECTION_NAME,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.debug(f"删除 conversation_context 单条记录失败: {e}")
            return False

    @property
    def is_available(self) -> bool:
        """向量存储是否可用。"""
        return self._store is not None


def _make_doc_id(message_id: str, conversation_id: str) -> str:
    """生成向量存储中的文档 ID。"""
    raw = f"{conversation_id}:{message_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── 全局单例 ──

_context_store: ConversationContextStore | None = None


def get_conversation_context_store() -> ConversationContextStore:
    """获取全局 ConversationContextStore 单例。"""
    global _context_store
    if _context_store is None:
        _context_store = ConversationContextStore()
    return _context_store
