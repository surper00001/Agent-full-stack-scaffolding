"""
处理进度追踪器。

提供文档处理全生命周期的阶段、百分比、预估时间追踪。
内存存储 + thread-safe，供 API 轮询查询。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class ProcessStage(str, Enum):  # noqa: UP042
    UPLOADED = "uploaded"        # 已上传，等待处理
    ANALYZING = "analyzing"      # 文档结构分析
    PARSING = "parsing"          # 文档解析（提取文本/表格/图片）
    CHUNKING = "chunking"        # 智能分块
    EMBEDDING = "embedding"      # 向量化
    INDEXING = "indexing"        # 入库向量数据库
    READY = "ready"              # 处理完成
    ERROR = "error"              # 处理失败
    CANCELLED = "cancelled"      # 用户取消


STAGE_WEIGHTS: dict[ProcessStage, float] = {
    ProcessStage.UPLOADED: 0.0,
    ProcessStage.ANALYZING: 0.05,
    ProcessStage.PARSING: 0.30,
    ProcessStage.CHUNKING: 0.15,
    ProcessStage.EMBEDDING: 0.35,
    ProcessStage.INDEXING: 0.10,
    ProcessStage.READY: 1.0,
    ProcessStage.ERROR: 1.0,
}

STAGE_LABELS: dict[ProcessStage, str] = {
    ProcessStage.UPLOADED: "已上传，等待处理",
    ProcessStage.ANALYZING: "正在分析文档结构...",
    ProcessStage.PARSING: "正在解析文档内容...",
    ProcessStage.CHUNKING: "正在智能分块...",
    ProcessStage.EMBEDDING: "正在生成向量...",
    ProcessStage.INDEXING: "正在写入向量数据库...",
    ProcessStage.READY: "处理完成",
    ProcessStage.ERROR: "处理失败",
    ProcessStage.CANCELLED: "已取消",
}


@dataclass
class ProgressSnapshot:
    stage: ProcessStage
    label: str
    percentage: float       # 0.0 ~ 1.0
    started_at: float
    estimated_seconds: float | None = None   # 预估剩余秒数
    file_size_bytes: int = 0
    error_message: str | None = None

    # 富详情 —— 每个阶段的具体数字
    total_pages: int = 0
    parsed_pages: int = 0
    text_blocks: int = 0
    table_blocks: int = 0
    image_blocks: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0


@dataclass
class _TrackerEntry:
    doc_id: str
    stage: ProcessStage = ProcessStage.UPLOADED
    started_at: float = field(default_factory=time.time)
    stage_started_at: float = field(default_factory=time.time)
    file_size_bytes: int = 0
    total_pages: int = 0
    parsed_pages: int = 0
    text_blocks: int = 0
    table_blocks: int = 0
    image_blocks: int = 0
    total_chunks: int = 0
    embedded_chunks: int = 0
    chunked_count: int = 0  # 正在分块阶段的已分块数
    error_message: str | None = None
    _bytes_per_second: float | None = None


class ProcessingProgressTracker:
    """线程安全的处理进度追踪器（单例）。"""

    _instance: ProcessingProgressTracker | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._entries: dict[str, _TrackerEntry] = {}
        self._cancelled: set[str] = set()  # 已取消的 doc_id 集合
        self._historical_rate: float | None = None

    @classmethod
    def get_instance(cls) -> ProcessingProgressTracker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---- public API ----

    def start(self, doc_id: str, file_size_bytes: int = 0) -> None:
        with self._lock:
            self._entries[doc_id] = _TrackerEntry(
                doc_id=doc_id,
                file_size_bytes=file_size_bytes,
                stage=ProcessStage.UPLOADED,
            )

    def set_stage(self, doc_id: str, stage: ProcessStage) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.stage = stage
                entry.stage_started_at = time.time()

    def set_parse_detail(
        self,
        doc_id: str,
        total_pages: int,
        text_blocks: int,
        table_blocks: int,
        image_blocks: int,
    ) -> None:
        """解析完成后一次性设置解析详情。"""
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.total_pages = total_pages
                entry.parsed_pages = total_pages
                entry.text_blocks = text_blocks
                entry.table_blocks = table_blocks
                entry.image_blocks = image_blocks

    def update_parse(self, doc_id: str, pages_done: int) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.parsed_pages = pages_done

    def set_total_chunks(self, doc_id: str, total: int) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.total_chunks = total

    def update_chunk(self, doc_id: str, done: int) -> None:
        """分块进度更新。"""
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.chunked_count = done

    def update_embed(self, doc_id: str, chunks_done: int) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.embedded_chunks = chunks_done

    def set_error(self, doc_id: str, message: str) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                entry.stage = ProcessStage.ERROR
                entry.error_message = message

    def set_cancelled(self, doc_id: str) -> None:
        """标记文档处理为已取消。"""
        with self._lock:
            self._cancelled.add(doc_id)
            entry = self._entries.get(doc_id)
            if entry:
                entry.stage = ProcessStage.CANCELLED

    def cancel(self, doc_id: str) -> bool:
        """发出取消信号，返回是否成功标记（False 表示任务已完成无法取消）。"""
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry and entry.stage in (
                ProcessStage.READY, ProcessStage.ERROR, ProcessStage.CANCELLED,
            ):
                return False  # 已完成/已失败/已取消，不可再取消
            self._cancelled.add(doc_id)
            if entry:
                entry.stage = ProcessStage.CANCELLED
            return True

    def is_cancelled(self, doc_id: str) -> bool:
        """检查文档处理是否已被取消。"""
        with self._lock:
            return doc_id in self._cancelled

    def set_ready(self, doc_id: str) -> None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry:
                elapsed = time.time() - entry.started_at
                if elapsed > 0 and entry.file_size_bytes > 0:
                    rate = entry.file_size_bytes / elapsed
                    if self._historical_rate is None:
                        self._historical_rate = rate
                    else:
                        self._historical_rate = 0.3 * rate + 0.7 * self._historical_rate
                entry.stage = ProcessStage.READY

    def get_progress(self, doc_id: str) -> ProgressSnapshot | None:
        with self._lock:
            entry = self._entries.get(doc_id)
            if entry is None:
                return None

            percentage = self._calc_percentage(entry)
            estimated = self._estimate_remaining(entry)

            return ProgressSnapshot(
                stage=entry.stage,
                label=self._build_detailed_label(entry),
                percentage=percentage,
                started_at=entry.started_at,
                estimated_seconds=estimated,
                file_size_bytes=entry.file_size_bytes,
                error_message=entry.error_message,
                total_pages=entry.total_pages,
                parsed_pages=entry.parsed_pages,
                text_blocks=entry.text_blocks,
                table_blocks=entry.table_blocks,
                image_blocks=entry.image_blocks,
                total_chunks=entry.total_chunks,
                embedded_chunks=entry.embedded_chunks,
            )

    def cleanup(self, doc_id: str) -> None:
        with self._lock:
            self._entries.pop(doc_id, None)
            self._cancelled.discard(doc_id)

    # ---- internal ----

    @staticmethod
    def _build_detailed_label(entry: _TrackerEntry) -> str:
        """构建带具体数字的阶段描述。"""
        stage = entry.stage

        if stage == ProcessStage.UPLOADED:
            size_mb = entry.file_size_bytes / (1024 * 1024)
            return f"已上传，等待处理（{size_mb:.1f}MB）"

        if stage == ProcessStage.ANALYZING:
            return "正在分析文档结构..."

        if stage == ProcessStage.PARSING:
            if entry.total_pages > 0:
                return (
                    f"正在解析文档（第 {entry.parsed_pages}/{entry.total_pages} 页）"
                    f"—— 已识别 {entry.text_blocks} 段文本、{entry.table_blocks} 个表格、{entry.image_blocks} 张图片"
                )
            return "正在解析文档内容（文本/表格/图片）..."

        if stage == ProcessStage.CHUNKING:
            if entry.total_chunks > 0:
                return f"正在智能分块（{entry.chunked_count} / {entry.total_chunks} 块）"
            return "正在智能分块..."

        if stage == ProcessStage.EMBEDDING:
            if entry.total_chunks > 0:
                return f"正在生成向量（{entry.embedded_chunks} / {entry.total_chunks}）"
            return "正在生成向量..."

        if stage == ProcessStage.INDEXING:
            return f"正在写入向量数据库（{entry.total_chunks} 条）..."

        if stage == ProcessStage.READY:
            parts = ["处理完成"]
            if entry.total_pages > 0:
                parts.append(f"{entry.total_pages} 页")
            if entry.text_blocks > 0:
                parts.append(f"{entry.text_blocks} 段文本")
            if entry.table_blocks > 0:
                parts.append(f"{entry.table_blocks} 个表格")
            if entry.image_blocks > 0:
                parts.append(f"{entry.image_blocks} 张图片")
            if entry.total_chunks > 0:
                parts.append(f"{entry.total_chunks} 个向量块")
            return "，".join(parts)

        if stage == ProcessStage.ERROR:
            return f"处理失败: {entry.error_message or '未知错误'}"

        if stage == ProcessStage.CANCELLED:
            return "已取消"

        return STAGE_LABELS.get(stage, stage.value)

    def _calc_percentage(self, entry: _TrackerEntry) -> float:
        """计算当前总体百分比。"""
        stage = entry.stage

        if stage == ProcessStage.PARSING and entry.total_pages > 0:
            sub = min(entry.parsed_pages / entry.total_pages, 1.0)
            return 0.05 + sub * 0.25

        if stage == ProcessStage.CHUNKING and entry.total_chunks > 0:
            sub = min(entry.chunked_count / entry.total_chunks, 1.0)
            return 0.30 + sub * 0.15

        if stage == ProcessStage.EMBEDDING and entry.total_chunks > 0:
            sub = min(entry.embedded_chunks / entry.total_chunks, 1.0)
            return 0.45 + sub * 0.40

        if stage == ProcessStage.INDEXING:
            return 0.92

        if stage in (ProcessStage.READY, ProcessStage.ERROR, ProcessStage.CANCELLED):
            return 1.0

        return STAGE_WEIGHTS.get(stage, 0.0)

    def _estimate_remaining(self, entry: _TrackerEntry) -> float | None:
        """预估剩余秒数。"""
        if entry.stage in (ProcessStage.READY, ProcessStage.ERROR, ProcessStage.CANCELLED, ProcessStage.UPLOADED):
            return None

        if self._historical_rate:
            remaining_weight = 1.0 - self._calc_percentage(entry)
            if remaining_weight <= 0:
                return None
            total_work = entry.file_size_bytes / self._historical_rate
            remaining = total_work * remaining_weight
            return max(remaining, 1.0)

        if entry.stage == ProcessStage.EMBEDDING and entry.total_chunks > 0:
            done = entry.embedded_chunks
            total = entry.total_chunks
            if done > 0:
                elapsed = time.time() - entry.stage_started_at
                rate = done / elapsed if elapsed > 0 else 1
                return max((total - done) / rate, 0.5) if rate > 0 else None

        return None
