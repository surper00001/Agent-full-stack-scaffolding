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
        import torch

        torch.set_num_threads(4)
        from sentence_transformers import CrossEncoder

        _device = None  # None = auto-detect (SentenceTransformer handles this)
        if torch.cuda.is_available():
            _device = "cuda"
            logger.info(f"加载 CrossEncoder Reranker: {self._model_name} (GPU)")
        else:
            logger.info(f"加载 CrossEncoder Reranker: {self._model_name} (CPU)")
        self._model = CrossEncoder(
            self._model_name, trust_remote_code=True, device=_device,
        )

    def score(self, query: str, candidates: list[str]) -> list[float]:
        self._ensure_loaded()
        pairs = [(query, cand) for cand in candidates]
        scores = self._model.predict(pairs)
        if isinstance(scores, float):
            return [scores]
        return [float(s) for s in scores]


class Qwen3RerankerBackend(RerankerBackend):
    """Qwen3-Reranker 专用后端——使用 yes/no token 概率打分，小批量推理以控制显存。"""

    INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"

    # 小批量推理：logits 张量为 [batch, seq, vocab] 约 151k 词表，
    # 25 candidates × 2048 tokens → ~15.5 GB logits 显存，导致 OOM。
    # 分批处理将最大 logits 控制在 ~4 GB 以内。
    _MAX_BATCH_SIZE = 6

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        import torch

        torch.set_num_threads(4)
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info(f"加载 Qwen3 Reranker: {self._model_name}")
        self._tokenizer = AutoTokenizer.from_pretrained(
            self._model_name, trust_remote_code=True, padding_side="left"
        )
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        _device_kwargs: dict = {}
        if torch.cuda.is_available():
            _device_kwargs = {"device_map": "auto", "torch_dtype": torch.bfloat16}
            logger.info("   Reranker 使用 GPU (bfloat16)")
        else:
            logger.info("   Reranker 使用 CPU")
        self._model = AutoModelForCausalLM.from_pretrained(
            self._model_name, trust_remote_code=True, **_device_kwargs
        ).eval()
        self._loaded = True

    def _format_pair(self, query: str, document: str) -> str:
        return (
            f"<|im_start|>system\n{self.INSTRUCTION}\n"
            f"<|im_start|>user\nQuery: {query}\nDocument: {document}\n"
            f"<|im_start|>assistant\n"
        )

    def score(self, query: str, candidates: list[str]) -> list[float]:
        import torch

        self._ensure_loaded()
        yes_id = self._tokenizer.convert_tokens_to_ids("yes")
        no_id = self._tokenizer.convert_tokens_to_ids("no")

        device = self._model.model.embed_tokens.weight.device
        all_probs: list[float] = []

        # 小批量推理：每批最多 _MAX_BATCH_SIZE 个候选，避免 logits 张量 OOM
        for batch_start in range(0, len(candidates), self._MAX_BATCH_SIZE):
            batch = candidates[batch_start:batch_start + self._MAX_BATCH_SIZE]
            prompts = [self._format_pair(query, cand) for cand in batch]
            inputs = self._tokenizer(
                prompts, return_tensors="pt", truncation=True,
                max_length=2048, padding=True,
            )
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                logits = self._model(**inputs).logits[:, -1, :]
                yes_logits = logits[:, yes_id]
                no_logits = logits[:, no_id]
                stacked = torch.stack([no_logits, yes_logits], dim=1)
                probs = torch.softmax(stacked, dim=1)[:, 1]
            all_probs.extend(probs.tolist())

        return all_probs


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
        """对候选项精排，返回 (原始索引, 分数) 降序列表。

        支持两阶段剪枝：先精排少量候选，高分通过则跳过剩余，
        减少 30-40% 推理延迟。
        """
        if not candidates:
            return []

        backend = self._get_backend(model_name)
        loop = asyncio.get_running_loop()
        settings = get_settings()

        # 两阶段剪枝
        if (
            settings.kb_reranker_pruning_enabled
            and len(candidates) > settings.kb_reranker_first_pass_count
        ):
            return await self._rerank_with_pruning(
                query, candidates, top_k, backend, settings, loop
            )

        # 标准路径（候选数少或剪枝关闭）
        def _run() -> list[tuple[int, float]]:
            scores = backend.score(query, candidates)
            indexed = list(enumerate(scores))
            indexed.sort(key=lambda x: x[1], reverse=True)
            return indexed[:top_k]

        return await loop.run_in_executor(self._executor, _run)

    async def _rerank_with_pruning(
        self,
        query: str,
        candidates: list[str],
        top_k: int,
        backend: RerankerBackend,
        settings: Any,
        loop: Any,
    ) -> list[tuple[int, float]]:
        """两阶段剪枝：先评 top-N，高分即止；否则扩展评剩余。"""
        n1 = settings.kb_reranker_first_pass_count
        threshold = settings.kb_reranker_pruning_threshold

        # 第一阶段
        first_pass = candidates[:n1]
        logger.debug(
            f"Reranker 两阶段: 第一阶段 {len(first_pass)}/{len(candidates)} 候选"
        )

        def _score_pass(items: list[str]) -> list[tuple[int, float]]:
            scores = backend.score(query, items)
            indexed = list(enumerate(scores))
            indexed.sort(key=lambda x: x[1], reverse=True)
            return indexed

        stage1 = await loop.run_in_executor(self._executor, _score_pass, first_pass)

        best_score = stage1[0][1] if stage1 else 0.0

        if best_score >= threshold:
            logger.debug(
                f"Reranker 剪枝生效: 最高分={best_score:.3f} >= {threshold}，跳过第二阶段"
            )
            # 恢复原始索引
            return [(i, s) for i, s in stage1[:top_k]]

        # 第二阶段：扩展剩余候选
        remaining = candidates[n1:]
        logger.debug(
            f"Reranker 第一阶段最高分={best_score:.3f} < {threshold}，"
            f"扩展第二阶段 {len(remaining)} 候选"
        )
        stage2 = await loop.run_in_executor(self._executor, _score_pass, remaining)

        # 合并：stage1 索引不变，stage2 偏移 n1
        merged = stage1 + [(i + n1, s) for i, s in stage2]
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged[:top_k]

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
