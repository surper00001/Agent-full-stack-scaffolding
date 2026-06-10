"""KBSearchHarnessTool — 知识库搜索的 HarnessTool 封装。

将 RAG 检索管道接入 Harness 体系，获得：
- AbortSignal 传播（超时/取消 → 中止向量检索、重排序）
- 权限检查 + 并发调度元数据
- 统一注册表可见（tool_search 可发现）
"""

from __future__ import annotations

import json
import threading
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool, PermissionResult

# ── Input Schema ──

class KBSearchInput(BaseModel):
    """知识库搜索参数。"""
    query: str = Field(description="自然语言搜索查询")
    top_k: int = Field(default=5, ge=1, le=10, description="返回结果数量")


# ── 并发限流（保护 GPU） ──

_kb_search_semaphore = threading.BoundedSemaphore(2)


# ── HarnessTool ──

class KBSearchHarnessTool(HarnessTool[KBSearchInput, str]):
    """知识库搜索工具 — 第一类 HarnessTool 公民。

    注册为全局单一实例。每次调用时需传入 kb_ids 和 tenant_id
    （通常由 Agent 系统提示词或上下文注入）。
    """

    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = (
        "搜索知识库中的文档内容。当用户的问题涉及已有文档、需要查找内部资料、"
        "询问项目相关内容时使用此工具。支持自然语言查询，返回最相关的文档片段及其来源信息。\n\n"
        "Args:\n"
        "    query: 自然语言搜索查询\n"
        "    top_k: 返回结果数量，默认 5，最大 10\n\n"
        "Returns: JSON 格式搜索结果，包含 content、source、page、score、chunk_id 等字段"
    )
    input_schema: ClassVar[type[BaseModel]] = KBSearchInput
    category: ClassVar[str] = "L1-信息"
    version: ClassVar[str] = "1.0.0"

    def __init__(self) -> None:
        super().__init__()
        # 调用方可设置 KB 绑定（通过 set_binding）
        self._kb_ids: list[str] = []
        self._tenant_id: str = "default"

    def set_binding(self, kb_ids: list[str], tenant_id: str) -> None:
        """绑定到特定知识库（每次 Agent 执行前调用）。"""
        self._kb_ids = kb_ids
        self._tenant_id = tenant_id

    def is_read_only(self, input: KBSearchInput) -> bool:
        return True

    def is_concurrency_safe(self, input: KBSearchInput) -> bool:
        # GPU 并发受限（由 Semaphore(2) 保护），标记为非并发安全
        return False

    def check_permissions(self, input: KBSearchInput) -> PermissionResult:
        if not self._kb_ids:
            return PermissionResult(
                allowed=False,
                reason="未绑定知识库，请先在对话中选择知识库",
            )
        return PermissionResult(allowed=True)

    async def execute(self, input: KBSearchInput, signal: AbortSignal) -> str:
        """执行知识库搜索。"""
        signal.throw_if_aborted()

        if not self._kb_ids:
            return json.dumps({
                "query": input.query,
                "error": "未绑定知识库",
                "hint": "请在对话中选择要搜索的知识库",
                "results": [],
            }, ensure_ascii=False)

        # GPU 并发保护
        acquired = _kb_search_semaphore.acquire(timeout=30)
        if not acquired:
            return json.dumps({
                "query": input.query,
                "error": "搜索请求过多，请稍后重试",
                "results": [],
            }, ensure_ascii=False)

        try:
            result = await self._do_search(input, signal)
            return result
        finally:
            _kb_search_semaphore.release()

    async def _do_search(self, input: KBSearchInput, signal: AbortSignal) -> str:
        """核心搜索逻辑。"""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from src.services.knowledge_base_service import KnowledgeBaseService
        from src.services.rag.context_builder import search_multiple_kbs

        # 使用共享 DB 引擎
        engine = _get_shared_engine()
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        async with session_factory() as session:
            # 确保 pgvector 扩展可用
            signal.throw_if_aborted()
            try:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                await session.commit()
            except Exception:
                await session.rollback()

            signal.throw_if_aborted()
            kb_svc = KnowledgeBaseService(session)
            top_k = min(input.top_k, 10)

            # 执行多 KB 搜索（传递 AbortSignal）
            citations, context_text, kb_names, low_conf, suggestion = await search_multiple_kbs(
                kb_svc=kb_svc,
                kb_ids=self._kb_ids,
                tenant_id=self._tenant_id,
                query=input.query,
                top_k=top_k,
                rerank=True,
                signal=signal,
            )

        if not citations:
            hint = (
                suggestion
                if low_conf and suggestion
                else "知识库中未找到相关内容，建议使用 web_search 搜索互联网或请用户提供更多信息。"
            )
            return json.dumps({
                "query": input.query,
                "total_found": 0,
                "results": [],
                "hint": hint,
                "low_confidence": low_conf,
            }, ensure_ascii=False)

        results = [
            {
                "content": c.content,
                "source": c.source,
                "page": c.page,
                "score": c.score,
                "chunk_id": c.chunk_id,
                "chunk_type": c.chunk_type,
                "section_title": c.section_title,
                "image_url": c.image_url,
                "image_description": c.image_description,
                "image_caption": c.image_caption,
                "ocr_status": c.ocr_status,
            }
            for c in citations
        ]

        return json.dumps({
            "query": input.query,
            "total_found": len(results),
            "returned": len(results),
            "results": results,
            "context_for_llm": context_text,
        }, ensure_ascii=False, indent=2)


# ── 共享 DB 引擎（惰性创建，供所有 KB 搜索工具使用） ──

_shared_engine: Any = None
_engine_lock = threading.Lock()


def _get_shared_engine() -> Any:
    """惰性创建共享 DB 引擎（线程安全）。"""
    global _shared_engine
    if _shared_engine is None:
        with _engine_lock:
            if _shared_engine is None:
                from sqlalchemy.ext.asyncio import create_async_engine

                from src.core.config import get_settings

                _shared_engine = create_async_engine(
                    get_settings().database_url,
                    echo=False,
                    pool_size=3,
                    max_overflow=3,
                    pool_pre_ping=True,
                )
    return _shared_engine


# ── 工厂函数（向后兼容） ──

def create_kb_search_tool(
    tenant_id: str,
    kb_ids: list[str],
    kb_names: list[str] | None = None,
) -> Any:
    """创建一个绑定到指定知识库的 HarnessTool → LangChain 包装器。

    向后兼容旧的 create_kb_search_tool 接口，内部使用 KBSearchHarnessTool。
    返回 LangChain StructuredTool 供 LLM bind_tools 使用。
    """
    from src.harness.unified_registry import get_unified_registry

    registry = get_unified_registry()

    # 获取或创建全局 HarnessTool 实例
    harness_tool = registry.get_harness_tool("search_knowledge_base")
    if harness_tool is None:
        harness_tool = KBSearchHarnessTool()
        # 注册到统一注册表（如果未注册）
        existing = registry.get("search_knowledge_base")
        if existing is None:
            registry.register(harness_tool, source="builtin")

    # 绑定 KB 上下文
    if hasattr(harness_tool, "set_binding"):
        harness_tool.set_binding(kb_ids, tenant_id)

    # 构建带 KB 名称的定制描述
    display_names = kb_names or [f"kb_{kid[:8]}" for kid in kb_ids]
    kb_list = "、".join(display_names)
    custom_desc = (
        f"搜索知识库（{kb_list}）中的文档内容。"
        "当用户的问题涉及已有文档、需要查找内部资料、询问项目相关内容时使用此工具。"
        "支持自然语言查询，返回最相关的文档片段及其来源信息。\n\n"
        "Args:\n"
        "    query: 自然语言搜索查询\n"
        "    top_k: 返回结果数量，默认 5，最大 10"
    )

    # 手动创建 LangChain StructuredTool（带自定义描述）
    from langchain_core.tools import StructuredTool

    async def _execute(**kwargs: Any) -> Any:
        from src.harness.abort_signal import AbortSignal

        input_obj = KBSearchInput(**kwargs)
        signal = AbortSignal(name="tool-search_knowledge_base")
        try:
            perm = harness_tool.check_permissions(input_obj)
            if not perm.allowed:
                return f"[权限拒绝] {perm.reason}"
            result = await harness_tool.execute(input_obj, signal)
            return harness_tool.render_result(result)
        except Exception as e:
            return f"[工具执行失败] {type(e).__name__}: {e}"

    return StructuredTool(
        name="search_knowledge_base",
        description=custom_desc,
        args_schema=KBSearchInput,
        coroutine=_execute,
    )
