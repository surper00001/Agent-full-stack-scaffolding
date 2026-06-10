"""
会话管理 API。

提供多轮对话的创建、查询和管理接口，支持上下文感知的消息传递。
支持 Plan+ReAct 双模型模式、SSE 流式事件、文件下载。
"""

from __future__ import annotations

import asyncio
import json
import re
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from src.agents.base import BaseAgent
from src.agents.prompts import get_prompt_for_agent
from src.api.deps import CurrentUser, get_current_tenant, get_current_user
from src.core.config import get_settings
from src.core.exceptions import ForbiddenError
from src.db.session import get_db_session
from src.llm.factory import get_llm_factory
from src.models.schemas.request import (  # noqa: TC001
    ChatMessageRequest,
    CreateConversationRequest,
    PaginationParams,
)
from src.models.schemas.response import (
    APIResponse,
    ContextInfoResponse,
    ConversationItem,
    CursorPaginatedData,
    MessageItem,
    PaginatedData,
)
from src.services.conversation_context_store import get_conversation_context_store
from src.services.conversation_service import ConversationService, _orm_to_langchain_all

router = APIRouter(prefix="/conversations", tags=["会话管理"])


def _resolve_user_id(current_user: CurrentUser) -> str | None:
    return None if current_user.role == "admin" else current_user.id


def _require_non_admin(current_user: CurrentUser) -> None:
    """管理员禁止调用聊天相关接口，仅普通用户可使用。"""
    if current_user.role == "admin":
        raise ForbiddenError("管理员不可进行对话操作，请使用管理后台")


async def _to_conversation_item(
    conv: Any,
    db: AsyncSession,
    tenant_id: str,
) -> ConversationItem:
    """将会话 ORM 转为响应项，附带知识库名称和用户信息。"""
    kb_name: str | None = None
    if conv.knowledge_base_id:
        try:
            from src.services.knowledge_base_service import KnowledgeBaseService

            kb_svc = KnowledgeBaseService(db)
            kb = await kb_svc.get_kb(conv.knowledge_base_id, tenant_id)
            kb_name = kb.name
        except Exception as e:
            logger.debug(f"查询 KB 名称失败 conv={conv.id}: {e}")
            kb_name = None

    # 查询用户名
    username: str | None = None
    if conv.user_id:
        try:
            from src.db.repository import BaseRepository
            from src.models.domain.user import User

            user_repo = BaseRepository[User](User, db)
            user = await user_repo.get_by_id(conv.user_id)
            username = user.username if user else None
        except Exception as e:
            logger.debug(f"查询用户名失败 conv={conv.id}: {e}")
            username = None

    return ConversationItem(
        id=conv.id,
        title=conv.title,
        agent_type=conv.agent_type,
        message_count=conv.message_count,
        status=conv.status,
        knowledge_base_id=conv.knowledge_base_id,
        knowledge_base_name=kb_name,
        user_id=conv.user_id,
        username=username,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


# ---- 会话 CRUD ----

@router.post("", response_model=APIResponse[ConversationItem], summary="创建新会话")
async def create_conversation(
    body: CreateConversationRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[ConversationItem]:
    _require_non_admin(current_user)
    service = ConversationService(db)
    conv = await service.create_conversation(
        title=body.title,
        agent_type=body.agent_type,
        tenant_id=tenant_id,
        user_id=current_user.id,
        knowledge_base_id=body.knowledge_base_id,
    )
    return APIResponse(
        message="会话创建成功",
        data=await _to_conversation_item(conv, db, tenant_id),
    )


@router.get("", response_model=APIResponse[PaginatedData[ConversationItem]], summary="获取会话列表")
async def list_conversations(
    pagination: PaginationParams = Depends(),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[ConversationItem]]:
    service = ConversationService(db)
    skip = (pagination.page - 1) * pagination.page_size
    convs = await service.list_conversations(
        tenant_id=tenant_id,
        skip=skip,
        limit=pagination.page_size,
        user_id=_resolve_user_id(current_user),
    )
    total = await service.count_conversations(
        tenant_id=tenant_id,
        user_id=_resolve_user_id(current_user),
    )
    return APIResponse(
        data=PaginatedData(
            items=[await _to_conversation_item(c, db, tenant_id) for c in convs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=max(1, (total + pagination.page_size - 1) // pagination.page_size) if total > 0 else 0,
        )
    )


@router.get("/{conversation_id}", response_model=APIResponse[ConversationItem], summary="获取会话详情")
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[ConversationItem]:
    service = ConversationService(db)
    conv = await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )
    return APIResponse(data=await _to_conversation_item(conv, db, tenant_id))


@router.delete("/{conversation_id}", response_model=APIResponse, summary="删除会话")
async def delete_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    service = ConversationService(db)
    await service.delete_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )
    return APIResponse(message="会话已删除")


# ---- 消息 ----

@router.get(
    "/{conversation_id}/messages",
    response_model=APIResponse[PaginatedData[MessageItem]],
    summary="获取会话消息列表",
)
async def get_messages(
    conversation_id: str,
    pagination: PaginationParams = Depends(),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[MessageItem]]:
    service = ConversationService(db)
    await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )
    skip = (pagination.page - 1) * pagination.page_size
    msgs = await service.get_messages(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        skip=skip,
        limit=pagination.page_size,
    )
    total = await service.count_messages(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
    )
    return APIResponse(
        data=PaginatedData(
            items=[MessageItem.model_validate(m) for m in msgs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=max(1, (total + pagination.page_size - 1) // pagination.page_size) if total > 0 else 0,
        )
    )


@router.get(
    "/{conversation_id}/messages/cursor",
    response_model=APIResponse[CursorPaginatedData[MessageItem]],
    summary="基于游标的消息分页",
)
async def get_messages_cursor(
    conversation_id: str,
    cursor: str | None = Query(None, description="游标（ISO 时间戳）"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    direction: str = Query("backward", pattern="^(backward|forward)$"),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[CursorPaginatedData[MessageItem]]:
    service = ConversationService(db)
    await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )
    msgs, next_cursor = await service.get_messages_cursor(
        conversation_id, tenant_id,
        cursor=cursor, limit=limit, direction=direction,
    )
    return APIResponse(
        data=CursorPaginatedData(
            items=[MessageItem.model_validate(m) for m in msgs],
            next_cursor=next_cursor,
            limit=limit,
        )
    )


@router.get(
    "/{conversation_id}/context-info",
    response_model=APIResponse[ContextInfoResponse],
    summary="获取会话上下文使用统计",
)
async def get_context_info(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[ContextInfoResponse]:
    service = ConversationService(db)
    await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )
    info = await service.get_context_info(conversation_id, tenant_id)
    return APIResponse(data=ContextInfoResponse(**info))


# ---- 文件下载 ----


# ---- 核心：发送消息 ----

async def _prepare_kb_send_context(
    *,
    service: ConversationService,
    db: AsyncSession,
    conv: Any,
    body: ChatMessageRequest,
    tenant_id: str,
    user_id: str | None,
    mode: str,
) -> tuple[str, list[Any], Any | None, list[Any]]:
    """解析 KB、预检索、构建 system prompt 与工具列表。

    Returns:
        (system_prompt, mode_tools, rag_context, proactive_citations_metadata)
    """
    from src.agents.tools import create_kb_search_tool, get_default_tools
    from src.services.knowledge_base_service import KnowledgeBaseService
    from src.services.rag.context_builder import (
        RAGContext,
        build_rag_context,
        build_system_rag_prompt,
    )

    settings = get_settings()
    system_prompt = get_prompt_for_agent(conv.agent_type)
    mode_tools: list[Any] = get_default_tools() if mode in ("agent", "plan") else []
    rag_context: RAGContext | None = None

    kb_id = body.knowledge_base_id or conv.knowledge_base_id
    if body.knowledge_base_id and body.knowledge_base_id != conv.knowledge_base_id:
        await service.update_knowledge_base(
            conv.id, tenant_id, body.knowledge_base_id, user_id
        )
        conv.knowledge_base_id = body.knowledge_base_id

    if not kb_id:
        return system_prompt, mode_tools, None, []

    kb_svc = KnowledgeBaseService(db)
    kb = await kb_svc.get_kb(kb_id, tenant_id)

    if settings.kb_chat_auto_retrieve:
        rag_context = await build_rag_context(
            kb_svc=kb_svc,
            kb_id=kb_id,
            tenant_id=tenant_id,
            query=body.content,
            top_k=settings.kb_chat_retrieve_top_k,
            rerank=True,
        )
        rag_prompt = build_system_rag_prompt(kb.name, rag_context.context_text)
        if rag_prompt:
            system_prompt = f"{system_prompt}{rag_prompt}"

    if mode in ("agent", "plan"):
        # 通过统一注册表获取 KBSearchHarnessTool 的 LangChain 包装器
        kb_tool = create_kb_search_tool(
            tenant_id=tenant_id,
            kb_ids=[kb_id],
            kb_names=[kb.name],
        )
        mode_tools.append(kb_tool)

        # 同时设置 HarnessTool 的 KB 绑定（供 AbortSignal/权限/调度使用）
        from src.harness.unified_registry import get_unified_registry
        registry = get_unified_registry()
        harness_kb = registry.get_harness_tool("search_knowledge_base")
        if harness_kb is not None and hasattr(harness_kb, "set_binding"):
            harness_kb.set_binding([kb_id], tenant_id)

        system_prompt = (
            f"{system_prompt}\n\n"
            f"## 可用知识库\n"
            f"你可以使用 `search_knowledge_base` 工具对知识库「{kb.name}」进行补充检索。"
            f"当自动检索结果不足或需要更精确信息时，请主动调用该工具。"
            f"检索结果会包含来源文件、页码和内容片段，请基于这些信息回答用户，并标注来源。"
        )
    elif rag_context is None:
        # ask 模式且未预检索时仍绑定 KB 说明
        system_prompt = (
            f"{system_prompt}\n\n"
            f"## 知识库\n"
            f"当前会话已绑定知识库「{kb.name}」。"
        )

    proactive_meta = rag_context.to_metadata("proactive") if rag_context else []
    citations_meta = proactive_meta.get("citations", []) if isinstance(proactive_meta, dict) else []
    return system_prompt, mode_tools, rag_context, citations_meta


@router.post("/{conversation_id}/send", summary="发送消息并获取 Agent 回复（支持 SSE 流式，Plan+ReAct）")
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Any:
    """向指定会话发送用户消息并获取 Agent 回复。

    当 stream=true 时返回 SSE 流式响应，事件类型：
    - plan: 规划阶段产出（plan_summary, plan_steps）
    - delta: 文本增量
    - tool_calls: LLM 请求的工具调用
    - tool_results: 工具执行结果
    - file: 文件生成事件（download_url, filename）
    - rag_context: 预检索引用（citations）
    - done: 完成信号（含 token_usage 和 context_usage）
    """
    _require_non_admin(current_user)
    service = ConversationService(db)
    llm_factory = get_llm_factory()

    # 初始化对话上下文向量存储（用于 ContextManager SELECTIVE/HYBRID 策略）
    context_store = get_conversation_context_store()
    await context_store.ensure_store()
    service_with_context = ConversationService(db, context_store=context_store)

    conv = await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )

    # 0. 处理图片附件：调用 VLM 描述图片，注入到用户消息文本中
    user_content = body.content
    if body.image_ids:
        user_id = _resolve_user_id(current_user)
        img_descriptions = await _resolve_image_descriptions(
            body.image_ids, user_id, conversation_id
        )
        if img_descriptions:
            user_content = (
                f"[用户上传了 {len(body.image_ids)} 张图片，以下是图片内容描述]\n\n"
                f"{img_descriptions}\n\n"
                f"---\n\n"
                f"用户问题: {body.content}"
            )

    # 1. 保存用户消息（带 context_store 写入 conversation_context 向量集合）
    await service_with_context.add_message_with_metadata(
        conversation_id=conversation_id,
        role="user",
        content=user_content,
        tenant_id=tenant_id,
    )

    # 2. 获取历史消息
    orm_messages = await service.get_messages(conversation_id, tenant_id)
    chat_history = _orm_to_langchain_all(orm_messages)

    # 3. 根据 mode 创建不同配置的 Agent（含 KB 预检索）
    execute_llm = llm_factory.create_chat_model()
    mode = body.mode  # "ask" | "agent" | "plan"

    enable_planning = (mode == "plan")
    plan_llm = None
    if enable_planning:
        plan_llm = llm_factory.create_plan_model(model_name=body.plan_model or None)

    system_prompt, mode_tools, rag_context, proactive_citations = await _prepare_kb_send_context(
        service=service,
        db=db,
        conv=conv,
        body=body,
        tenant_id=tenant_id,
        user_id=_resolve_user_id(current_user),
        mode=mode,
    )

    # 传入 vector_store 以启用 ContextManager SELECTIVE/HYBRID 策略
    agent_vector_store = context_store._store if context_store.is_available else None
    agent = BaseAgent(
        llm=execute_llm,
        tools=mode_tools,
        system_prompt=system_prompt,
        tenant_id=tenant_id,
        plan_llm=plan_llm,
        enable_planning=enable_planning,
        vector_store=agent_vector_store,
    )

    resolved_kb_id = body.knowledge_base_id or conv.knowledge_base_id

    # ---- 流式响应 ----
    if body.stream:
        async def event_stream():
            full_response = ""
            tool_calls_in_flight: list[dict[str, Any]] = []
            plan_emitted = False
            all_citations: list[dict[str, Any]] = list(proactive_citations)
            stream_start = _time.time()
            first_token_time = None
            total_delta_chars = 0

            if rag_context and rag_context.citations:
                yield f"data: {json.dumps({'rag_context': {'citations': proactive_citations, 'kb_id': resolved_kb_id, 'kb_name': rag_context.kb_name, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}}, ensure_ascii=False)}\n\n"

            try:
                async for event in agent.stream(
                    user_input=user_content,
                    chat_history=chat_history,
                    metadata={
                        "thread_id": conversation_id,
                        "user_id": current_user.id,
                        "agent_type": conv.agent_type,
                        "tags": [conv.agent_type, mode],
                    },
                ):
                    # Planner 事件
                    if "planner" in event and not plan_emitted:
                        planner_data = event["planner"]
                        plan = planner_data.get("plan", [])
                        plan_summary = planner_data.get("plan_summary", "")
                        if plan:
                            plan_emitted = True
                            yield f"data: {json.dumps({'plan': {'steps': plan, 'summary': plan_summary}, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                    # Executor 事件（Plan+ReAct 执行节点）
                    for msg in _executor_messages_from_event(event):
                        # Tool calls
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                tc_info = {
                                    "id": tc.get("id", ""),
                                    "name": tc.get("name", ""),
                                    "arguments": tc.get("args", {}),
                                    "status": "running",
                                }
                                if not any(t["id"] == tc_info["id"] for t in tool_calls_in_flight):
                                    tool_calls_in_flight.append(tc_info)
                            yield f"data: {json.dumps({'tool_calls': tool_calls_in_flight, 'status': 'tool_call', '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                        # 每轮 executor 产出独立文本，需追加而非覆盖
                        text = _langchain_message_text(msg).strip()
                        if text:
                            # Extract thinking tags
                            thinking_match = re.search(r'&lt;thinking&gt;(.*?)&lt;/thinking&gt;', text, re.DOTALL)
                            thinking_content = None
                            if thinking_match:
                                thinking_content = thinking_match.group(1).strip()
                                text = re.sub(r'&lt;thinking&gt;.*?&lt;/thinking&gt;', '', text, flags=re.DOTALL).strip()

                            if thinking_content:
                                yield f"data: {json.dumps({'thinking': thinking_content, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                            if text:
                                sep = "\n\n" if full_response else ""
                                delta = sep + text
                                full_response += delta
                                total_delta_chars += len(delta)

                                if first_token_time is None:
                                    first_token_time = _time.time()

                                file_info = _extract_file_info(delta)
                                if file_info:
                                    yield f"data: {json.dumps({'file': file_info, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                                yield f"data: {json.dumps({'delta': delta, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000), 'ttft_ms': int((first_token_time - stream_start) * 1000) if first_token_time else None}}, ensure_ascii=False)}\n\n"

                    # Tool results
                    if "tools" in event:
                        from src.services.rag.context_builder import parse_tool_result_citations

                        tool_msgs = event["tools"].get("messages", [])
                        for tmsg in tool_msgs:
                            tc_id = getattr(tmsg, "tool_call_id", "")
                            result_content = _langchain_message_text(tmsg)
                            tool_name = getattr(tmsg, "name", "")
                            if tool_name == "search_knowledge_base":
                                tool_cites = parse_tool_result_citations(result_content)
                                if tool_cites:
                                    seen = {c["chunk_id"] for c in all_citations if c.get("chunk_id")}
                                    for c in tool_cites:
                                        if c.chunk_id and c.chunk_id not in seen:
                                            seen.add(c.chunk_id)
                                            all_citations.append({
                                                "chunk_id": c.chunk_id,
                                                "content": c.content,
                                                "source": c.source,
                                                "page": c.page,
                                                "score": c.score,
                                                "chunk_type": c.chunk_type,
                                                "section_title": c.section_title,
                                                "table_html": c.table_html,
                                                "table_caption": c.table_caption,
                                                "image_url": c.image_url,
                                                "image_description": c.image_description,
                                                "image_caption": c.image_caption,
                                                "image_width": c.image_width,
                                                "image_height": c.image_height,
                                            })
                            matched = False
                            for tc in tool_calls_in_flight:
                                if tc["id"] == tc_id:
                                    tc["result"] = result_content
                                    tc["status"] = "completed"
                                    matched = True
                                    break
                            if not matched and tc_id:
                                tool_calls_in_flight.append({
                                    "id": tc_id,
                                    "name": getattr(tmsg, "name", ""),
                                    "arguments": {},
                                    "result": result_content,
                                    "status": "completed",
                                })
                            file_info = _extract_file_info(result_content)
                            if file_info:
                                yield f"data: {json.dumps({'file': file_info, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"
                        if tool_msgs:
                            yield f"data: {json.dumps({'tool_results': tool_calls_in_flight, 'status': 'tool_result', '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                # 最终检测完整响应中的文件链接
                if full_response:
                    file_info = _extract_file_info(full_response)
                    if file_info:
                        yield f"data: {json.dumps({'file': file_info, '_timing': {'elapsed_ms': int((_time.time() - stream_start) * 1000)}}, ensure_ascii=False)}\n\n"

                # Save AI response
                if full_response:
                    msg_meta: dict[str, Any] = {}
                    if all_citations:
                        msg_meta.update({
                            "citations": all_citations,
                            "rag_mode": "hybrid" if len(all_citations) > len(proactive_citations) else "proactive",
                            "kb_id": resolved_kb_id,
                        })
                    mindmap = _extract_mindmap_meta(full_response)
                    if mindmap:
                        msg_meta["mindmap"] = mindmap
                    await service_with_context.add_message_with_metadata(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_response,
                        tenant_id=tenant_id,
                        metadata=msg_meta or None,
                    )

                # Done event
                ctx = agent.context_stats
                total_elapsed = _time.time() - stream_start
                ttft_ms_calc = int((first_token_time - stream_start) * 1000) if first_token_time else None
                total_tokens = agent.get_token_usage().get("total_tokens", 0)
                tps = total_tokens / total_elapsed if total_elapsed > 0 else 0

                done_payload = json.dumps({
                    "done": True,
                    "conversation_id": conversation_id,
                    "token_usage": agent.get_token_usage(),
                    "context_usage": {
                        "used_tokens": ctx.used_tokens if ctx else 0,
                        "max_tokens": ctx.available_tokens if ctx else 0,
                        "strategy": ctx.strategy if ctx else "",
                        "compressed_ratio": round(ctx.compressed_ratio, 3) if ctx else 0,
                        "has_summary": ctx.has_summary if ctx else False,
                    } if ctx else {},
                    "_timing": {
                        "total_elapsed_ms": int(total_elapsed * 1000),
                        "ttft_ms": ttft_ms_calc,
                        "tokens_per_second": round(tps, 1),
                    },
                }, ensure_ascii=False)
                yield f"data: {done_payload}\n\n"
                yield "data: [DONE]\n\n"

            except asyncio.CancelledError:
                if full_response:
                    try:
                        await service.add_message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=full_response + "\n\n[已中断]",
                            tenant_id=tenant_id,
                        )
                    except Exception:
                        logger.warning(f"保存中断响应失败 conv={conversation_id}")
                yield "data: [DONE]\n\n"
            except Exception:
                logger.exception(f"SSE 流式响应异常 conv={conversation_id}")
                yield f"data: {json.dumps({'error': '流式响应异常，请重试'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ---- 非流式响应 ----
    result = await agent.run(
        user_input=user_content,
        chat_history=chat_history,
        metadata={
            "thread_id": conversation_id,
            "user_id": current_user.id,
            "agent_type": conv.agent_type,
            "tags": [conv.agent_type, mode],
        },
    )

    ai_response = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "content") and getattr(msg, "type", "") != "tool":
            ai_response = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if ai_response:
        msg_meta: dict[str, Any] = {}
        if proactive_citations:
            msg_meta.update({
                "citations": proactive_citations,
                "rag_mode": "proactive",
                "kb_id": resolved_kb_id,
            })
        mindmap = _extract_mindmap_meta(ai_response)
        if mindmap:
            msg_meta["mindmap"] = mindmap
        await service_with_context.add_message_with_metadata(
            conversation_id=conversation_id,
            role="assistant",
            content=ai_response,
            tenant_id=tenant_id,
            metadata=msg_meta or None,
        )

    return APIResponse(
        message="发送成功",
        data={
            "conversation_id": conversation_id,
            "response": ai_response,
            "plan": result.get("plan", []),
            "plan_summary": result.get("plan_summary", ""),
            "token_usage": result.get("token_usage", {}),
            "context_usage": result.get("context_usage", {}),
            "citations": proactive_citations,
            "kb_id": resolved_kb_id,
        },
    )


def _langchain_message_text(msg: Any) -> str:
    """从 LangChain 消息对象提取纯文本（兼容 str / 多模态 list）。"""
    content = getattr(msg, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content) if content else ""


def _executor_messages_from_event(event: dict[str, Any]) -> list[Any]:
    """LangGraph 执行节点事件（当前图为 executor，保留 agent 兼容旧图）。"""
    for key in ("executor", "agent"):
        if key in event:
            return event[key].get("messages", []) or []
    return []


def _extract_mindmap_meta(content: str) -> dict[str, Any] | None:
    """从 AI 响应文本中提取思维导图 JSON，供存入 metadata 复用。

    匹配模式：```json ... ``` 块中包含 root.title / root.text / root.children。
    """
    import re as _re

    # 查找 json 代码块
    for match in _re.finditer(r"```json\s*\n(.*?)\n```", content, _re.DOTALL):
        try:
            obj = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "root" in obj:
            root = obj.get("root", {})
            if isinstance(root, dict) and "text" in root and "children" in root:
                return obj  # 返回完整 dict — 存入 metadata 后前端 extractMindmapFromMetadata 可复用
    return None


def _extract_file_info(text: str) -> dict[str, Any] | None:
    """从文本中提取文件下载链接信息。"""
    import re

    # 匹配 download_url 模式
    match = re.search(r'"download_url"\s*:\s*"([^"]+)"', text)
    if not match:
        return None

    url = match.group(1)
    filename_match = re.search(r'"filename"\s*:\s*"([^"]+)"', text)
    filename = filename_match.group(1) if filename_match else "download"

    return {
        "filename": filename,
        "download_url": url,
        "label": f"下载 {filename}",
    }


# ---- 聊天图片上传（已提取到 conversations_images.py） ----
from src.api.v1.conversations_images import (  # noqa: E402
    resolve_image_descriptions,
)
from src.api.v1.conversations_images import (  # noqa: E402
    router as images_router,
)


async def _resolve_image_descriptions(
    image_ids: list[str], user_id: str, conversation_id: str
) -> str:
    """根据 image_ids 读取本地图片并调用 VLM 生成描述文本。委托给独立模块。"""
    return await resolve_image_descriptions(image_ids, user_id, conversation_id)


# 注册图片上传子路由
router.include_router(images_router)

# ---- 思维导图导出 ----

@router.post("/export-mindmap", summary="导出思维导图文件", tags=["会话管理"])
async def export_mindmap_endpoint(
    body: dict[str, Any],
    current_user: CurrentUser = Depends(get_current_user),  # noqa: ARG001
) -> dict[str, Any]:
    """将思维导图 JSON 导出为指定格式文件，返回下载 URL。

    请求体: {"mindmap_json": {...}, "format": "opml|mm|markdown|json"}
    """
    from src.agents.tools.mindmap import export_mindmap as _export

    mindmap_data = body.get("mindmap_json", {})
    fmt = body.get("format", "opml")

    result_json = _export.invoke({
        "mindmap_json": json.dumps(mindmap_data, ensure_ascii=False),
        "format": fmt,
    })
    return json.loads(result_json)
