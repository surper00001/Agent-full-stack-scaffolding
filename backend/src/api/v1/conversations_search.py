"""对话搜索 API — 按内容、标题全文检索。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant
from src.db.session import get_db_session
from src.models.domain.conversation import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/search", summary="全文检索对话内容")
async def search_conversations(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(20, ge=1, le=100),
):
    """在对话标题和消息内容中全文搜索关键词。

    返回匹配的对话列表，每条对话包含匹配的消息预览。
    """
    # 搜索消息内容
    msg_query = (
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == tenant_id,
            Message.content.ilike(f"%{q}%"),
            Conversation.is_deleted == False,  # noqa: E712
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    msg_result = await db.execute(msg_query)
    messages = msg_result.scalars().all()

    # 搜索对话标题
    conv_query = (
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.title.ilike(f"%{q}%"),
            Conversation.is_deleted == False,  # noqa: E712
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    conv_result = await db.execute(conv_query)
    conversations = conv_result.scalars().all()

    # 组装结果
    results = []

    # 消息匹配结果
    seen_conv_ids = set()
    for msg in messages:
        if msg.conversation_id not in seen_conv_ids:
            seen_conv_ids.add(msg.conversation_id)
            conv_title = msg.conversation.title if msg.conversation else "未命名对话"
            results.append({
                "conversation_id": msg.conversation_id,
                "title": conv_title,
                "match_type": "message",
                "preview": _highlight(msg.content, q, max_len=150),
                "role": msg.role,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            })

    # 标题匹配结果
    for conv in conversations:
        if conv.id not in seen_conv_ids:
            results.append({
                "conversation_id": conv.id,
                "title": conv.title,
                "match_type": "title",
                "preview": _highlight(conv.title, q),
                "role": None,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
            })

    return {"success": True, "data": {"results": results, "query": q, "total": len(results)}}


def _highlight(text: str, query: str, max_len: int = 150) -> str:
    """截取包含关键词的文本片段。"""
    if not text:
        return ""
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:max_len]
    start = max(0, idx - 40)
    end = min(len(text), idx + len(query) + max_len - 40)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet
