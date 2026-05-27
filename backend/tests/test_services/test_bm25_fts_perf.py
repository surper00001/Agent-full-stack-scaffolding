"""
BM25 Memory vs FTS5 性能对比测试。

注意：此测试验证 FTS5 在数据量增长时的内存优势和延迟特性。
运行需要 rank_bm25 可用。
"""

import time
import tracemalloc
from typing import Any

import pytest

from src.services.rag.bm25_fts import BM25FTSRetriever


def _make_chunks(n: int) -> list[Any]:
    """生成 n 个模拟 chunk（中文+混合内容）。"""
    from types import SimpleNamespace

    templates = [
        "数字孪生系统架构由{idx}个核心模块组成，包括数据采集、模型构建、仿真分析和可视化展示",
        "第{idx}章介绍了JWT认证机制，包含Token生成、签名验证和过期刷新三个步骤",
        "在{idx}号实验中，我们观察到了基于Transformer的注意力机制在长文本上的性能衰减",
        "微服务{idx}的部署方案采用Kubernetes进行容器编排，并配置了HPA自动伸缩策略",
        "数据库{idx}的连接池配置建议：最小连接数10，最大连接数100，超时时间30秒",
        "API接口{idx}的限流策略为每分钟1000次请求，超过限制返回429状态码",
        "测试用例{idx}覆盖了正常流程、边界条件和异常处理的完整测试矩阵",
        "系统{idx}的日志级别在生产环境建议设置为WARNING，开发环境使用DEBUG",
        "模型{idx}的训练数据包含50万条中文语料，使用AdamW优化器和余弦退火学习率",
        "前端组件{idx}使用React Hooks实现状态管理，通过Zustand进行全局状态共享",
    ]
    chunks = []
    for i in range(n):
        tmpl = templates[i % len(templates)]
        chunks.append(SimpleNamespace(
            id=f"chunk_{i:06d}",
            document_id=f"doc_{(i // 100) + 1:04d}",
            page_start=(i % 20) + 1,
            chunk_type="text",
            content=tmpl.format(idx=i + 1),
        ))
    return chunks


def _run_test(chunks, fts, label: str, warmup: bool = False):
    """运行一次检索并报告指标。"""
    queries = ["JWT认证机制", "微服务部署", "数据库连接池", "系统架构"]

    # 构建 / 加载索引
    t0 = time.perf_counter()
    fts.build_index("perf", "test_kb", chunks)
    build_time = time.perf_counter() - t0

    # 检索
    total_latency = 0.0
    total_results = 0
    for q in queries:
        t1 = time.perf_counter()
        results = fts.search("perf", "test_kb", q, top_k=10)
        total_latency += time.perf_counter() - t1
        total_results += len(results)

    avg_latency = total_latency / len(queries) * 1000  # ms
    avg_results = total_results / len(queries)

    if not warmup:
        print(f"\n[{label}] chunks={len(chunks)}")
        print(f"  构建耗时: {build_time:.2f}s")
        print(f"  平均检索延迟: {avg_latency:.2f}ms")
        print(f"  平均结果数: {avg_results:.1f}")

    return build_time, avg_latency, avg_results


class TestBM25Performance:
    """FTS5 性能行为测试 — 确保在小规模下的合理表现。"""

    @pytest.mark.unit
    def test_fts5_memory_grows_reasonably(self):
        """验证 FTS5 不会失控膨胀内存（10000 chunks 场景）。"""
        chunks = _make_chunks(10000)

        from src.services.rag.bm25_fts import BM25FTSRetriever
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "perf_fts.db")
            fts = BM25FTSRetriever(fts_db_path=db_path)

            tracemalloc.start()
            _run_test(chunks, fts, "FTS5_10K")
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            peak_mb = peak / 1024 / 1024
            # 关闭连接释放文件句柄（Windows 不允许删除打开的文件）
            fts.close()
            print(f"\n  FTS5 峰值内存(含tracemalloc/jieba): {peak_mb:.1f}MB")
            # FTS5 峰值应在 100MB 以下（含 tracemalloc + jieba 分词库内存）
            assert peak_mb < 100, f"内存 {peak_mb:.1f}MB 超出预期"

    @pytest.mark.unit
    def test_fts5_latency_acceptable(self):
        """验证 FTS5 检索延迟在可接受范围内 (<50ms)。"""
        chunks = _make_chunks(10000)

        from src.services.rag.bm25_fts import BM25FTSRetriever
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "perf_fts2.db")
            fts = BM25FTSRetriever(fts_db_path=db_path)

            _, avg_latency, avg_results = _run_test(chunks, fts, "FTS5_LAT")
            assert avg_latency < 50, f"延迟 {avg_latency:.2f}ms 超出预期"
            assert avg_results >= 1, "应至少返回 1 条结果"

            fts.close()

    @pytest.mark.unit
    def test_fts5_chinese_recall(self):
        """验证中文多词组合查询的召回率。"""
        chunks = []
        from types import SimpleNamespace

        chunks.append(SimpleNamespace(
            id="target", document_id="doc1", page_start=1,
            chunk_type="text",
            content="数字孪生系统由数据层、模型层和应用层构成，支持实时仿真",
        ))
        for i in range(100):
            chunks.append(SimpleNamespace(
                id=f"noise_{i:04d}", document_id="doc2", page_start=1,
                chunk_type="text",
                content=f"噪音文档内容编号{i}，与目标内容无关的随机文本填充",
            ))

        from src.services.rag.bm25_fts import BM25FTSRetriever
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "perf_recall.db")
            fts = BM25FTSRetriever(fts_db_path=db_path)
            fts.build_index("recall", "kb", chunks)

            # 精确查询应召回 target
            results = fts.search("recall", "kb", "数字孪生数据层", top_k=3)
            chunk_ids = [cid for _, cid, _ in results]
            assert "target" in chunk_ids, f"未召回目标chunk, 结果: {chunk_ids}"

            fts.close()
