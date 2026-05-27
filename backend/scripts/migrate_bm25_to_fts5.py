"""
BM25 Memory → SQLite FTS5 迁移脚本。

从 PostgreSQL 读取所有 KB 的 chunk，为每个 KB 构建 FTS5 索引。
运行方式（从 backend/ 目录）：
    uv run python scripts/migrate_bm25_to_fts5.py
    uv run python scripts/migrate_bm25_to_fts5.py --kb-id <kb_id>   # 仅迁移指定 KB
"""

from __future__ import annotations

import argparse
import asyncio
import time

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.core.config import get_settings
from src.models.domain.knowledge_base import KBChunk
from src.services.rag.bm25_fts import BM25FTSRetriever


async def migrate_all(fts: BM25FTSRetriever, session: AsyncSession) -> dict:
    """迁移所有 KB 到 FTS5。"""
    # 获取所有不同的 (kb_id, tenant_id)
    result = await session.execute(
        select(KBChunk.knowledge_base_id, KBChunk.tenant_id).distinct()
    )
    kb_pairs = result.all()
    logger.info(f"发现 {len(kb_pairs)} 个知识库需要迁移")

    stats: dict[str, dict] = {}
    for kb_id, tenant_id in kb_pairs:
        stats[f"{tenant_id}:{kb_id}"] = await migrate_one(fts, session, kb_id, tenant_id)
    return stats


async def migrate_one(
    fts: BM25FTSRetriever, session: AsyncSession, kb_id: str, tenant_id: str
) -> dict:
    """迁移单个 KB 到 FTS5。"""
    result = await session.execute(
        select(KBChunk)
        .where(KBChunk.knowledge_base_id == kb_id)
        .where(KBChunk.tenant_id == tenant_id)
        .order_by(KBChunk.chunk_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        return {"kb_id": kb_id, "chunks": 0, "time": 0}

    start = time.perf_counter()
    fts.build_index(tenant_id, kb_id, chunks)
    elapsed = time.perf_counter() - start

    logger.info(f"  {kb_id}: {len(chunks)} 条 chunk, {elapsed:.2f}s")
    return {"kb_id": kb_id, "chunks": len(chunks), "time": round(elapsed, 2)}


async def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 BM25 索引到 SQLite FTS5")
    parser.add_argument("--kb-id", type=str, default=None, help="仅迁移指定知识库")
    parser.add_argument("--tenant-id", type=str, default="default", help="租户 ID")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)

    fts = BM25FTSRetriever()

    async with AsyncSession(engine) as session:
        if args.kb_id:
            stat = await migrate_one(fts, session, args.kb_id, args.tenant_id)
            logger.info(f"迁移完成: {stat}")
        else:
            stats = await migrate_all(fts, session)
            total_chunks = sum(s["chunks"] for s in stats.values())
            total_time = sum(s["time"] for s in stats.values())
            logger.info(
                f"全部迁移完成: {len(stats)} 个 KB, {total_chunks} 条 chunk, "
                f"总耗时 {total_time:.2f}s"
            )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
