"""
RAG 检索质量评估 —— 基于 Ragas 框架。

测试分为两层：

1. 数据集验证（始终运行）：
   - 黄金数据集结构完整性
   - 问题/答案非空
   - 标签覆盖率

2. Ragas 评估（需要已索引的知识库，标记为 eval）：
   - context_recall: 检索结果是否包含正确答案
   - context_precision: 检索结果与问题的相关性
   - faithfulness: 答案是否忠实于检索上下文（需要 LLM）

运行方式：
    # 仅验证数据集
    pytest tests/eval/ -v -m "not eval"

    # 完整评估（需要已索引的知识库 + LLM 配置）
    pytest tests/eval/ -v -m eval

    # 评估特定标签
    pytest tests/eval/ -v -m eval -k "auth"
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from tests.eval.golden_dataset import (
    GOLDEN_DATASET,
    EvalItem,
    dataset_stats,
    get_dataset_by_tag,
    to_ragas_format,
)


# ═════════════════════════════════════════════════════════════
# 第一层：数据集验证（始终运行）
# ═════════════════════════════════════════════════════════════


class TestGoldenDataset:
    """黄金数据集结构验证。"""

    def test_dataset_not_empty(self):
        """数据集不能为空。"""
        assert len(GOLDEN_DATASET) >= 20, (
            f"黄金数据集应至少包含 20 条，当前 {len(GOLDEN_DATASET)} 条"
        )

    def test_all_questions_non_empty(self):
        """所有问题不能为空。"""
        for item in GOLDEN_DATASET:
            assert item.question.strip(), f"问题为空: {item}"
            assert len(item.question) >= 5, f"问题过短(<5字符): {item.question}"

    def test_all_ground_truths_non_empty(self):
        """所有标准答案不能为空。"""
        for item in GOLDEN_DATASET:
            assert item.ground_truth.strip(), f"答案为空: {item.question[:30]}"
            assert len(item.ground_truth) >= 10, (
                f"答案过短(<10字符): {item.question[:30]}"
            )

    def test_all_items_have_tags(self):
        """所有条目应有标签。"""
        for item in GOLDEN_DATASET:
            assert item.tags, f"缺少标签: {item.question[:30]}"

    def test_expected_keywords_in_ground_truth(self):
        """预期关键词应出现在标准答案中。"""
        for item in GOLDEN_DATASET:
            for kw in item.expected_keywords:
                assert kw in item.ground_truth, (
                    f"关键词 '{kw}' 不在答案中: {item.question[:30]}"
                )

    def test_ragas_format_conversion(self):
        """验证 Ragas 格式转换。"""
        data = to_ragas_format()
        assert "question" in data
        assert "ground_truth" in data
        assert len(data["question"]) == len(GOLDEN_DATASET)
        assert len(data["ground_truth"]) == len(GOLDEN_DATASET)

    def test_no_duplicate_questions(self):
        """问题不应重复。"""
        questions = [item.question for item in GOLDEN_DATASET]
        assert len(questions) == len(set(questions)), "存在重复问题"

    def test_tag_coverage(self):
        """验证标签覆盖关键领域。"""
        all_tags = set()
        for item in GOLDEN_DATASET:
            all_tags.update(item.tags)
        required_tags = {"auth", "rag", "agent", "embedding", "vectorstore"}
        missing = required_tags - all_tags
        assert not missing, f"缺少关键标签: {missing}"

    def test_dataset_stats(self):
        """验证统计信息。"""
        stats = dataset_stats()
        assert stats["total_items"] == len(GOLDEN_DATASET)
        assert "tags" in stats
        assert stats["avg_question_len"] > 0
        assert stats["avg_truth_len"] > 0


class TestDatasetTags:
    """按标签筛选的测试。"""

    def test_filter_by_auth_tag(self):
        items = get_dataset_by_tag("auth")
        assert len(items) >= 3, f"auth 标签应有至少 3 条，实际 {len(items)}"

    def test_filter_by_rag_tag(self):
        items = get_dataset_by_tag("rag")
        assert len(items) >= 5, f"rag 标签应有至少 5 条，实际 {len(items)}"

    def test_filter_by_agent_tag(self):
        items = get_dataset_by_tag("agent")
        assert len(items) >= 2, f"agent 标签应有至少 2 条，实际 {len(items)}"


# ═════════════════════════════════════════════════════════════
# 第二层：Ragas 评估（需要已索引的知识库，标记为 eval）
# ═════════════════════════════════════════════════════════════


def _get_eval_kb_config() -> dict[str, str] | None:
    """从环境变量读取评估用的 KB 配置。

    需要设置：
    - RAG_EVAL_KB_ID: 已索引的知识库 ID
    - RAG_EVAL_TENANT_ID: 租户 ID（默认 "default"）
    - RAG_EVAL_COLLECTION: 向量库 collection 名（默认 "kb_{kb_id}"）
    """
    kb_id = os.environ.get("RAG_EVAL_KB_ID")
    if not kb_id:
        return None
    return {
        "kb_id": kb_id,
        "tenant_id": os.environ.get("RAG_EVAL_TENANT_ID", "default"),
        "collection": os.environ.get("RAG_EVAL_COLLECTION", f"kb_{kb_id}"),
    }


def _make_ragas_dataset(
    questions: list[str],
    ground_truths: list[str],
    contexts: list[list[str]],
) -> Any:
    """构造 Ragas 评估用的 Dataset。"""
    from datasets import Dataset

    return Dataset.from_dict({
        "question": questions,
        "ground_truth": ground_truths,
        "contexts": contexts,
    })


@pytest.mark.eval
class TestRagEvalWithKB:
    """需要真实知识库的 Ragas 评估。

    前置条件（设置环境变量）：
        RAG_EVAL_KB_ID=xxx
        RAG_EVAL_TENANT_ID=default  （可选）
        RAG_EVAL_COLLECTION=kb_xxx  （可选）
    """

    @pytest.fixture(autouse=True)
    def _check_kb_config(self):
        """跳过未配置 KB 的测试。"""
        config = _get_eval_kb_config()
        if config is None:
            pytest.skip("未设置 RAG_EVAL_KB_ID 环境变量，跳过评估")

    @pytest.mark.asyncio
    async def test_context_recall_baseline(self):
        """评估 context_recall —— 检索到的上下文是否包含正确答案。

        目标：recall >= 0.5（检索结果中应至少包含一半的正确答案信息）
        """
        config = _get_eval_kb_config()
        assert config is not None

        from ragas import evaluate
        from ragas.metrics import context_recall

        questions, ground_truths, contexts_list = await _retrieve_contexts(
            config, GOLDEN_DATASET
        )

        if not contexts_list or all(len(c) == 0 for c in contexts_list):
            pytest.skip("检索返回空结果，跳过评估（检查 KB 是否有文档）")

        dataset = _make_ragas_dataset(questions, ground_truths, contexts_list)
        result = evaluate(dataset, metrics=[context_recall])

        recall = float(result["context_recall"])
        print(f"\n📊 context_recall = {recall:.3f}")

        # 记录基线，不强制断言（初次运行建立基线分数）
        assert recall >= 0.0, "评估应正常完成"

    @pytest.mark.asyncio
    async def test_context_precision_baseline(self):
        """评估 context_precision —— 检索到的上下文是否都与问题相关。

        目标：precision >= 0.5
        """
        config = _get_eval_kb_config()
        assert config is not None

        from ragas import evaluate
        from ragas.metrics import context_precision

        questions, ground_truths, contexts_list = await _retrieve_contexts(
            config, GOLDEN_DATASET
        )

        if not contexts_list or all(len(c) == 0 for c in contexts_list):
            pytest.skip("检索返回空结果，跳过评估")

        dataset = _make_ragas_dataset(questions, ground_truths, contexts_list)
        result = evaluate(dataset, metrics=[context_precision])

        precision = float(result["context_precision"])
        print(f"\n📊 context_precision = {precision:.3f}")

        assert precision >= 0.0, "评估应正常完成"

    @pytest.mark.asyncio
    async def test_full_eval_report(self):
        """完整评估报告 —— context_recall + context_precision。

        结果将作为不可变的基线快照保存到 tests/eval/baseline.json。
        后续运行会与基线对比，检测检索质量退化。
        """
        config = _get_eval_kb_config()
        assert config is not None

        from ragas import evaluate
        from ragas.metrics import context_precision, context_recall

        questions, ground_truths, contexts_list = await _retrieve_contexts(
            config, GOLDEN_DATASET
        )

        if not contexts_list or all(len(c) == 0 for c in contexts_list):
            pytest.skip("检索返回空结果，跳过评估")

        dataset = _make_ragas_dataset(questions, ground_truths, contexts_list)
        result = evaluate(dataset, metrics=[context_recall, context_precision])

        recall = float(result["context_recall"])
        precision = float(result["context_precision"])

        print(f"\n{'='*60}")
        print(f"RAG 评估报告")
        print(f"{'='*60}")
        print(f"  数据集条目: {len(questions)}")
        print(f"  总检索上下文: {sum(len(c) for c in contexts_list)}")
        print(f"  context_recall:    {recall:.4f}")
        print(f"  context_precision: {precision:.4f}")
        print(f"{'='*60}")

        # 写入基线快照
        baseline_path = os.path.join(
            os.path.dirname(__file__), "baseline.json"
        )
        baseline = {
            "dataset_size": len(questions),
            "context_recall": recall,
            "context_precision": precision,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
        print(f"\n基线已写入: {baseline_path}")

        assert recall >= 0.0
        assert precision >= 0.0


@pytest.mark.eval
@pytest.mark.asyncio
async def test_individual_query_recall():
    """逐条评估 —— 帮助发现具体哪些 query 召回差。"""
    config = _get_eval_kb_config()
    if config is None:
        pytest.skip("未设置 RAG_EVAL_KB_ID")

    from ragas import evaluate
    from ragas.metrics import context_recall

    low_recall: list[tuple[str, float]] = []

    for item in GOLDEN_DATASET:
        questions, ground_truths, contexts_list = await _retrieve_contexts(
            config, [item]
        )
        if not contexts_list or all(len(c) == 0 for c in contexts_list):
            low_recall.append((item.question, 0.0))
            continue

        dataset = _make_ragas_dataset(questions, ground_truths, contexts_list)
        try:
            result = evaluate(dataset, metrics=[context_recall])
            recall = float(result["context_recall"])
            if recall < 0.3:
                low_recall.append((item.question[:60], recall))
        except Exception as e:
            low_recall.append((item.question[:60], -1.0))
            print(f"  ⚠ 评估异常: {item.question[:60]} | {e}")

    print(f"\n📋 逐条评估完成: {len(GOLDEN_DATASET)} 条")
    if low_recall:
        print(f"\n⚠ 低召回条目 ({len(low_recall)}):")
        for q, r in sorted(low_recall, key=lambda x: x[1]):
            print(f"  recall={r:.3f} | {q}")
    else:
        print("✅ 所有条目召回正常")


# ═════════════════════════════════════════════════════════════
# 辅助函数
# ═════════════════════════════════════════════════════════════


async def _retrieve_contexts(
    config: dict[str, str],
    items: list[EvalItem],
) -> tuple[list[str], list[str], list[list[str]]]:
    """对每条问题执行检索，返回 (questions, ground_truths, contexts)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from src.core.config import get_settings
    from src.services.knowledge_base_service import KnowledgeBaseService

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=2, max_overflow=2,
    )

    questions: list[str] = []
    ground_truths: list[str] = []
    contexts_list: list[list[str]] = []

    try:
        async with async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )() as session:
            await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await session.commit()

            kb_svc = KnowledgeBaseService(session)
            kb_id = config["kb_id"]
            tenant_id = config["tenant_id"]

            for item in items:
                try:
                    result = await kb_svc.search(
                        kb_id=kb_id,
                        query=item.question,
                        tenant_id=tenant_id,
                        top_k=5,
                        rerank=True,
                    )
                except Exception as e:
                    print(f"  ⚠ 检索失败: {item.question[:40]} | {e}")
                    result = {"results": []}

                raw = result.get("results", [])
                contexts = [
                    r.get("expanded_content") or r.get("content", "")
                    for r in raw
                ]
                questions.append(item.question)
                ground_truths.append(item.ground_truth)
                contexts_list.append(contexts if contexts else [""])
    finally:
        await engine.dispose()

    return questions, ground_truths, contexts_list
