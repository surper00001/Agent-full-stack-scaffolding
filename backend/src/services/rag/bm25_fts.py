"""
BM25 FTS5 检索引擎 —— SQLite FTS5 零内存方案。

替代原 rank_bm25 全量内存加载，索引持久化在磁盘，
启动内存占用从 ~2GB 降到 <50MB。

每个 (tenant_id, kb_id) 对应一张 FTS5 虚表，表名格式: fts_{tenant}_{kb}
使用 jieba 预处理中文分词，空格连接后写入 FTS5。
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from loguru import logger

if TYPE_CHECKING:
    from src.models.domain.knowledge_base import KBChunk

_TABLE_NAME_RE = re.compile(r"^fts_[a-zA-Z0-9_\-]+$")


class BM25FTSRetriever:
    """SQLite FTS5 中文 BM25 检索引擎。

    写入时用 jieba 分词并以空格连接，利用 FTS5 的 bm25() 排序函数检索。
    """

    def __init__(self, fts_db_path: str | None = None) -> None:
        self._fts_db_path = fts_db_path or os.path.join(
            os.getcwd(), "data", "fts", "bm25_fts.db"
        )
        self._lock = threading.Lock()
        self._initialized = False
        self._conn: sqlite3.Connection | None = None

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            Path(self._fts_db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._fts_db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._initialized = True

    @staticmethod
    def _table_name(tenant_id: str, kb_id: str) -> str:
        raw = f"fts_{tenant_id}_{kb_id}".replace("-", "_")
        if not _TABLE_NAME_RE.match(raw):
            raise ValueError(f"Invalid FTS table name: {raw}")
        return raw

    @staticmethod
    def _tokenize(text: str) -> str:
        import jieba

        jieba.setLogLevel(jieba.logging.INFO)
        return " ".join(jieba.cut_for_search(text))

    # ── 索引管理 ──────────────────────────────────────────

    def table_exists(self, tenant_id: str, kb_id: str) -> bool:
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)
        row = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        return row is not None

    def build_index(
        self,
        tenant_id: str,
        kb_id: str,
        chunks: list[KBChunk],
    ) -> None:
        """全量构建 FTS5 索引（首次使用或重建时调用）。"""
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        with self._lock:
            self._conn.execute(f"DROP TABLE IF EXISTS [{tbl}]")
            self._conn.execute(
                f"CREATE VIRTUAL TABLE [{tbl}] USING fts5("
                f"  chunk_id, document_id, page_start, chunk_type,"
                f"  tokenized_content,"
                f"  tokenize='unicode61',"
                f"  prefix='1 2 3'"
                f")"
            )
            rows = [
                (
                    c.id,
                    c.document_id or "",
                    c.page_start or 1,
                    c.chunk_type or "text",
                    self._tokenize(c.content or ""),
                )
                for c in chunks
            ]
            self._conn.executemany(
                f"INSERT INTO [{tbl}] (chunk_id, document_id, page_start, chunk_type, tokenized_content) "
                f"VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
            logger.info(f"FTS5 索引构建完成: {tbl}, {len(rows)} 条")

    def add_chunks(self, tenant_id: str, kb_id: str, chunks: list[KBChunk]) -> None:
        """增量写入 chunk 到 FTS5 索引。"""
        if not chunks:
            return
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        if not self.table_exists(tenant_id, kb_id):
            logger.warning(f"FTS5 表 {tbl} 不存在，跳过增量写入（将走全量构建）")
            return

        rows = [
            (
                c.id,
                c.document_id or "",
                c.page_start or 1,
                c.chunk_type or "text",
                self._tokenize(c.content or ""),
            )
            for c in chunks
        ]
        with self._lock:
            self._conn.executemany(
                f"INSERT INTO [{tbl}] (chunk_id, document_id, page_start, chunk_type, tokenized_content) "
                f"VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def delete_chunks(self, tenant_id: str, kb_id: str, chunk_ids: list[str]) -> None:
        """从 FTS5 索引中删除指定 chunk。"""
        if not chunk_ids:
            return
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        if not self.table_exists(tenant_id, kb_id):
            return

        with self._lock:
            placeholders = ",".join("?" for _ in chunk_ids)
            self._conn.execute(
                f"DELETE FROM [{tbl}] WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )
            self._conn.commit()

    def delete_by_document(self, tenant_id: str, kb_id: str, document_id: str) -> None:
        """删除某文档的所有 chunk。"""
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        if not self.table_exists(tenant_id, kb_id):
            return

        with self._lock:
            self._conn.execute(
                f"DELETE FROM [{tbl}] WHERE document_id = ?", (document_id,)
            )
            self._conn.commit()

    def drop_index(self, tenant_id: str, kb_id: str) -> None:
        """删除整个 KB 的 FTS5 表。"""
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        with self._lock:
            self._conn.execute(f"DROP TABLE IF EXISTS [{tbl}]")
            self._conn.commit()
            logger.info(f"FTS5 索引已删除: {tbl}")

    # ── 检索 ──────────────────────────────────────────────

    def search(
        self,
        tenant_id: str,
        kb_id: str,
        query: str,
        top_k: int,
    ) -> list[tuple[int, str, dict]]:
        """BM25 检索，返回 [(bm25_score, chunk_id, row_data), ...] 降序。

        如果 FTS5 表不存在，返回空列表（不会自动构建，由调用方决定是否降级）。
        """
        self._ensure_init()
        assert self._conn is not None
        tbl = self._table_name(tenant_id, kb_id)

        if not self.table_exists(tenant_id, kb_id):
            return []

        tokens = self._tokenize(query)
        if not tokens.strip():
            return []

        terms = tokens.split()
        fts_query = " AND ".join(terms)

        with self._lock:
            try:
                rows = self._conn.execute(
                    f"SELECT chunk_id, document_id, page_start, bm25([{tbl}], 1.0, 2.0) AS score "
                    f"FROM [{tbl}] WHERE [{tbl}] MATCH ? ORDER BY score LIMIT ?",
                    (fts_query, top_k),
                ).fetchall()
            except sqlite3.OperationalError:
                # FTS5 MATCH 语法错误（如纯标点查询）
                return []

        result: list[tuple[int, str, dict]] = []
        for row in rows:
            chunk_id, doc_id, page_start, score = row
            result.append((
                int(score) if score else 0,
                chunk_id,
                {
                    "document_id": doc_id,
                    "page_start": page_start,
                },
            ))
        return result

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None
                self._initialized = False


# ── 模块级单例 ──────────────────────────────────────────

_fts_retriever: BM25FTSRetriever | None = None
_fts_lock = threading.Lock()


def get_bm25_fts_retriever(fts_db_path: str | None = None) -> BM25FTSRetriever:
    global _fts_retriever
    if _fts_retriever is None:
        with _fts_lock:
            if _fts_retriever is None:
                _fts_retriever = BM25FTSRetriever(fts_db_path)
    return _fts_retriever
