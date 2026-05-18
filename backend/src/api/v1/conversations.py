"""
会话管理 API。

提供多轮对话的创建、查询和管理接口，支持上下文感知的消息传递。
支持 Plan+ReAct 双模型模式、SSE 流式事件、文件下载。
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.agents.prompts import get_prompt_for_agent
from src.api.deps import CurrentUser, get_current_tenant, get_current_user
from src.core.config import get_settings
from src.db.session import get_db_session
from src.llm.factory import get_llm_factory
from src.models.schemas.request import (
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
from src.services.conversation_service import ConversationService, _orm_to_langchain_all

router = APIRouter(prefix="/conversations", tags=["会话管理"])


def _resolve_user_id(current_user: CurrentUser) -> str | None:
    return None if current_user.role == "admin" else current_user.id


async def _to_conversation_item(
    conv: Any,
    db: AsyncSession,
    tenant_id: str,
) -> ConversationItem:
    """将会话 ORM 转为响应项，附带知识库名称。"""
    kb_name: str | None = None
    if conv.knowledge_base_id:
        try:
            from src.services.knowledge_base_service import KnowledgeBaseService

            kb_svc = KnowledgeBaseService(db)
            kb = await kb_svc.get_kb(conv.knowledge_base_id, tenant_id)
            kb_name = kb.name
        except Exception:
            kb_name = None
    return ConversationItem(
        id=conv.id,
        title=conv.title,
        agent_type=conv.agent_type,
        message_count=conv.message_count,
        status=conv.status,
        knowledge_base_id=conv.knowledge_base_id,
        knowledge_base_name=kb_name,
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
    total = len(convs)
    return APIResponse(
        data=PaginatedData(
            items=[await _to_conversation_item(c, db, tenant_id) for c in convs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=(total // pagination.page_size) + 1,
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
    total = len(msgs)
    return APIResponse(
        data=PaginatedData(
            items=[MessageItem.model_validate(m) for m in msgs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=(total // pagination.page_size) + 1 if pagination.page_size else 0,
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
        kb_tool = create_kb_search_tool(
            tenant_id=tenant_id,
            kb_ids=[kb_id],
            kb_names=[kb.name],
        )
        mode_tools.append(kb_tool)
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
    service = ConversationService(db)
    llm_factory = get_llm_factory()

    conv = await service.get_conversation(
        conversation_id, tenant_id, _resolve_user_id(current_user)
    )

    # 0. 处理图片附件：调用 VLM 描述图片，注入到用户消息文本中
    user_content = body.content
    image_meta: dict[str, Any] | None = None
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
        image_meta = {"image_ids": body.image_ids}

    # 1. 保存用户消息
    await service.add_message_with_metadata(
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

    agent = BaseAgent(
        llm=execute_llm,
        tools=mode_tools,
        system_prompt=system_prompt,
        tenant_id=tenant_id,
        plan_llm=plan_llm,
        enable_planning=enable_planning,
    )

    resolved_kb_id = body.knowledge_base_id or conv.knowledge_base_id

    # ---- 流式响应 ----
    if body.stream:
        async def event_stream():
            full_response = ""
            tool_calls_in_flight: list[dict[str, Any]] = []
            plan_emitted = False
            all_citations: list[dict[str, Any]] = list(proactive_citations)

            if rag_context and rag_context.citations:
                yield f"data: {json.dumps({'rag_context': {'citations': proactive_citations, 'kb_id': resolved_kb_id, 'kb_name': rag_context.kb_name}}, ensure_ascii=False)}\n\n"

            try:
                async for event in agent.stream(
                    user_input=user_content,
                    chat_history=chat_history,
                    metadata={
                        "thread_id": conversation_id,
                        "user_id": current_user.id,
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
                            yield f"data: {json.dumps({'plan': {'steps': plan, 'summary': plan_summary}}, ensure_ascii=False)}\n\n"

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
                            yield f"data: {json.dumps({'tool_calls': tool_calls_in_flight, 'status': 'tool_call'}, ensure_ascii=False)}\n\n"

                        # 每轮 executor 产出独立文本，需追加而非覆盖
                        text = _langchain_message_text(msg).strip()
                        if text:
                            sep = "\n\n" if full_response else ""
                            delta = sep + text
                            full_response += delta
                            file_info = _extract_file_info(delta)
                            if file_info:
                                yield f"data: {json.dumps({'file': file_info}, ensure_ascii=False)}\n\n"
                            yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"

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
                                yield f"data: {json.dumps({'file': file_info}, ensure_ascii=False)}\n\n"
                        if tool_msgs:
                            yield f"data: {json.dumps({'tool_results': tool_calls_in_flight, 'status': 'tool_result'}, ensure_ascii=False)}\n\n"

                # 最终检测完整响应中的文件链接
                if full_response:
                    file_info = _extract_file_info(full_response)
                    if file_info:
                        yield f"data: {json.dumps({'file': file_info}, ensure_ascii=False)}\n\n"

                # Save AI response
                if full_response:
                    msg_meta: dict[str, Any] = {}
                    if all_citations:
                        msg_meta = {
                            "citations": all_citations,
                            "rag_mode": "hybrid" if len(all_citations) > len(proactive_citations) else "proactive",
                            "kb_id": resolved_kb_id,
                        }
                    await service.add_message_with_metadata(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_response,
                        tenant_id=tenant_id,
                        metadata=msg_meta or None,
                    )

                # Done event
                ctx = agent.context_stats
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
                        pass
                yield "data: [DONE]\n\n"

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
            msg_meta = {
                "citations": proactive_citations,
                "rag_mode": "proactive",
                "kb_id": resolved_kb_id,
            }
        await service.add_message_with_metadata(
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


# ---- 聊天图片上传 ----

_CHAT_IMAGES_DIR = Path("./data/chat-images")
_CHAT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}


@router.post("/{conversation_id}/images", summary="上传聊天图片（VLM 识别后作为上下文注入）")
async def upload_chat_image(
    conversation_id: str,
    file: UploadFile = File(..., description="图片文件"),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """上传图片到对话中，返回 image_id 供 send 接口使用。"""
    if not file.filename:
        return {"success": False, "code": 40001, "message": "文件名不能为空"}

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return {
            "success": False,
            "code": 40002,
            "message": f"不支持的图片格式: {ext}，支持: {', '.join(_ALLOWED_IMAGE_EXTS)}",
        }

    if ext in (".jpg", ".jpeg"):
        mime_ext = ".jpg"
    else:
        mime_ext = ext

    image_id = uuid.uuid4().hex[:12]
    user_dir = _CHAT_IMAGES_DIR / current_user.id / conversation_id
    user_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{image_id}{mime_ext}"
    filepath = user_dir / filename

    try:
        contents = await file.read()
        filepath.write_bytes(contents)
        logger.info(f"聊天图片已保存: {filepath} ({len(contents)} bytes)")
    except Exception as e:
        logger.error(f"聊天图片保存失败: {e}")
        return {"success": False, "code": 50001, "message": f"图片保存失败: {e}"}

    # 立即用 VLM 预识别图片，以便前端可展示预览文本
    vlm_preview: str | None = None
    try:
        from src.services.vlm_service import get_vlm_service
        vlm = get_vlm_service()
        if vlm.enabled:
            vlm_preview, _ = vlm.describe_image(contents, mime_ext.lstrip("."))
            if vlm_preview:
                vlm_preview = vlm_preview.strip()
    except Exception:
        pass

    return {
        "success": True,
        "code": 200,
        "data": {
            "image_id": image_id,
            "filename": file.filename,
            "preview": vlm_preview,
        },
    }


async def _resolve_image_descriptions(
    image_ids: list[str], user_id: str, conversation_id: str
) -> str:
    """根据 image_ids 读取本地图片并调用 VLM 生成描述文本。

    Returns:
        拼接后的图片描述文本，可直接注入到用户消息中。
    """
    from src.services.vlm_service import get_vlm_service

    vlm = get_vlm_service()
    if not vlm.enabled:
        return ""

    parts: list[str] = []
    user_dir = _CHAT_IMAGES_DIR / user_id / conversation_id

    for iid in image_ids:
        # 安全检查：image_id 仅允许 hex 字符
        if not iid or len(iid) > 20 or not all(c in "0123456789abcdef" for c in iid):
            continue
        # 查找匹配的文件
        matched = None
        if user_dir.exists():
            for f in user_dir.iterdir():
                if f.stem == iid:
                    matched = f
                    break
        if not matched:
            continue
        try:
            img_bytes = matched.read_bytes()
            ext = matched.suffix.lstrip(".")
            desc, err = vlm.describe_image(img_bytes, ext)
            if desc and desc.strip():
                parts.append(f"[图片 {iid}]: {desc.strip()}")
                logger.info(f"VLM 图片描述 ({iid}): {desc[:80]}...")
            elif err:
                logger.warning(f"VLM 图片描述失败 ({iid}): {err}")
        except Exception as e:
            logger.error(f"读取图片失败 ({iid}): {e}")

    if parts:
        return "\n\n".join(parts)
    return ""
