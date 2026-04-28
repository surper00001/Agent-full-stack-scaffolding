"""
Reranker 服务。

按模型类型选择精排后端：
- BGE 系列：sentence_transformers CrossEncoder
- Qwen3-Reranker：transformers 因果 LM 打分（非 CrossEncoder）

模块级单例 + 按模型名缓存。
"""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from src.core.config import get_settings


class RerankerBackend(ABC):
    """Reranker 后端抽象。"""

    @abstractmethod
    def score(self, query: str, candidates: list[str]) -> list[float]:
        """对候选文本打分，返回与 candidates 等长的分数列表。"""


class CrossEncoderBackend(RerankerBackend):
    """BGE 等标准 CrossEncoder 模型后端。"""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from sentence_transformers import CrossEncoder

        logger.info(f"加载 CrossEncoder Reranker: {self._model_name}")
        self._model = CrossEncoder(self._model_name, trust_remote_code=True)

    def score(self, query: str, candidates: list[str]) -> list[float]:
        self._ensure_loaded()
        pairs = [(query, cand) for cand in candidates]
        scores = self._model.predict(pairs)
        if isinstance(scores, float):
            return [scores]
        return [float(s) for s in scores]


class Qwen3RerankerBackend(RerankerBackend):
    """Qwen3-Reranker 专用后端——使用 yes/no token 概率打分。"""

    INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info(f"加载 Qwen3 Reranker: {self._model_name}")
        self._tokenizer = AutoTokenizer.from_pretrained(
            self._model_name, trust_remote_code=True, padding_side="left"
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            self._model_name, trust_remote_code=True
        ).eval()

    def _format_pair(self, query: str, document: str) -> str:
        return (
            f"<|im_start|>system\n{self.INSTRUCTION}\n"
            f"<|im_start|>user\nQuery: {query}\nDocument: {document}\n"
            f"<|im_start|>assistant\n"
        )

    def score(self, query: str, candidates: list[str]) -> list[float]:
        import torch

        self._ensure_loaded()
        scores: list[float] = []
        yes_id = self._tokenizer.convert_tokens_to_ids("yes")
        no_id = self._tokenizer.convert_tokens_to_ids("no")

        for cand in candidates:
            prompt = self._format_pair(query, cand)
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
            with torch.no_grad():
                logits = self._model(**inputs).logits[0, -1, :]
                yes_logit = logits[yes_id].item()
                no_logit = logits[no_id].item()
                prob = float(torch.softmax(torch.tensor([no_logit, yes_logit]), dim=0)[1])
            scores.append(prob)
        return scores


def _create_backend(model_name: str) -> RerankerBackend:
    name_lower = model_name.lower()
    if "qwen3" in name_lower and "reranker" in name_lower:
        return Qwen3RerankerBackend(model_name)
    return CrossEncoderBackend(model_name)


class RerankerService:
    """重排序服务——按模型名选择后端。"""

    def __init__(self, model_name: str | None = None) -> None:
        self._settings = get_settings()
        self._model_name = model_name or self._settings.kb_reranker_model
        self._backend: RerankerBackend | None = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._init_lock = threading.Lock()

    def _get_backend(self, model_name: str | None = None) -> RerankerBackend:
        resolved = model_name or self._model_name
        if self._backend is None or resolved != self._model_name:
            with self._init_lock:
                if self._backend is None or resolved != self._model_name:
                    self._model_name = resolved
                    self._backend = _create_backend(resolved)
        return self._backend

    def _lazy_init(self) -> None:
        """同步预热模型（供 lifespan 启动时调用，与 EmbeddingService 接口一致）。"""
        self._get_backend()._ensure_loaded()  # noqa: SLF001

    def warmup(self) -> None:
        """同步预热模型（_lazy_init 别名）。"""
        self._lazy_init()

    async def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int = 3,
        model_name: str | None = None,
    ) -> list[tuple[int, float]]:
        """对候选项精排，返回 (原始索引, 分数) 降序列表。"""
        if not candidates:
            return []

        backend = self._get_backend(model_name)
        loop = asyncio.get_running_loop()

        def _run() -> list[tuple[int, float]]:
            scores = backend.score(query, candidates)
            indexed = list(enumerate(scores))
            indexed.sort(key=lambda x: x[1], reverse=True)
            return indexed[:top_k]

        return await loop.run_in_executor(self._executor, _run)

    @property
    def model_name(self) -> str:
        return self._model_name


_reranker_services: dict[str, RerankerService] = {}
_reranker_lock = threading.Lock()


def get_reranker_service(model_name: str | None = None) -> RerankerService:
    """获取 RerankerService 实例（同模型名共享）。"""
    settings = get_settings()
    resolved = model_name or settings.kb_reranker_model
    if resolved not in _reranker_services:
        with _reranker_lock:
            if resolved not in _reranker_services:
                _reranker_services[resolved] = RerankerService(resolved)
    return _reranker_services[resolved]
