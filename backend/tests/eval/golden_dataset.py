"""
RAG 评估黄金数据集。

格式：每条记录包含 question（查询）和 ground_truth（正确答案）。
用于 Ragas 的 context_recall、context_precision 评估。

添加新条目时，ground_truth 应该是能在已索引文档中找到的确切信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalItem:
    """单条评估数据。"""

    question: str
    ground_truth: str
    tags: list[str] = field(default_factory=list)
    # 可选：预期出现在检索结果中的关键词
    expected_keywords: list[str] = field(default_factory=list)


# ── 黄金数据集 ─────────────────────────────────────────────

# 第一批：项目核心概念（20 条）
# 这些问题的答案应该能在项目文档中找到
GOLDEN_DATASET: list[EvalItem] = [
    # ── 认证相关 ──
    EvalItem(
        question="JWT 令牌的过期时间是多久？",
        ground_truth="JWT Access Token 过期时间为 30 分钟，Refresh Token 为 7 天。"
        "系统采用 HS256 算法签名，密码使用 bcrypt 哈希。",
        tags=["auth", "jwt"],
        expected_keywords=["30 分钟", "7 天", "HS256", "bcrypt"],
    ),
    EvalItem(
        question="系统如何刷新过期的访问令牌？",
        ground_truth="系统使用双令牌模式：Access Token 短效 30 分钟，Refresh Token 长效 7 天。"
        "刷新时旧 Refresh Token 立即作废（轮转机制），返回新的 Access Token 和 Refresh Token。",
        tags=["auth", "refresh"],
        expected_keywords=["双令牌", "Refresh Token", "轮转", "30 分钟"],
    ),
    EvalItem(
        question="用户密码是如何存储的？",
        ground_truth="密码使用 passlib 库的 bcrypt 算法进行哈希处理，不存储明文。",
        tags=["auth", "security"],
        expected_keywords=["passlib", "bcrypt", "哈希"],
    ),

    # ── RAG / 知识库相关 ──
    EvalItem(
        question="知识库的混合检索是如何工作的？",
        ground_truth="混合检索结合向量检索（cosine 相似度）和 BM25 关键词检索（jieba 中文分词），"
        "通过 RRF（Reciprocal Rank Fusion，k=60）融合两路结果，再交给 Reranker 精排。",
        tags=["rag", "retrieval"],
        expected_keywords=["向量检索", "BM25", "jieba", "RRF", "Reciprocal Rank Fusion"],
    ),
    EvalItem(
        question="文档分块时使用什么策略处理不同类型文档？",
        ground_truth="系统根据文档类型动态选择分隔符策略：学术论文优先标题层级、法律文档优先条款编号、"
        "技术文档优先代码块边界。同时支持父子分块（768/2000 字符双粒度）。",
        tags=["rag", "chunking"],
        expected_keywords=["分隔符", "学术", "法律", "技术", "父子分块", "768", "2000"],
    ),
    EvalItem(
        question="知识库支持哪些文档格式？",
        ground_truth="支持 PDF、Word (docx)、Markdown、TXT、图片等格式。"
        "PDF 解析支持 pdfplumber + PyMuPDF，可选 MinerU 深度学习版面分析。",
        tags=["rag", "documents"],
        expected_keywords=["PDF", "Word", "docx", "Markdown", "MinerU", "PyMuPDF"],
    ),
    EvalItem(
        question="RAG 系统如何处理表格和图片？",
        ground_truth="表格和图片作为特殊块保持完整不拆分。表格使用 Markdown + HTML 双格式存储，"
        "图片通过 Qwen3-VL-Flash 生成 VLM 描述，可选 PaddleOCR 中文增强。"
        "检索时按 chunk_type 区分渲染。",
        tags=["rag", "table", "image"],
        expected_keywords=["表格", "图片", "VLM", "Qwen3-VL", "PaddleOCR", "特殊块"],
    ),
    EvalItem(
        question="检索结果的重排序使用什么模型？",
        ground_truth="默认使用 Qwen3-Reranker-0.6B 模型，基于 yes/no token 概率打分。"
        "支持 BGE CrossEncoder 作为备选。小批量推理（6条/批）控制显存。"
        "新增强了两阶段剪枝：先评 top-15，高分通过跳过剩余。",
        tags=["rag", "reranker"],
        expected_keywords=["Qwen3-Reranker", "yes/no", "CrossEncoder", "剪枝", "0.6B"],
    ),

    # ── Agent 相关 ──
    EvalItem(
        question="系统中的 Agent 是什么架构？",
        ground_truth="Agent 基于 LangGraph 实现 ReAct（Reasoning + Acting）模式。"
        "BaseAgent 定义了生命周期，graph.py 定义 ReAct 图结构，tools.py 定义工具集。"
        "支持多知识库联邦搜索和 Web 搜索。",
        tags=["agent", "architecture"],
        expected_keywords=["LangGraph", "ReAct", "BaseAgent", "联邦搜索"],
    ),
    EvalItem(
        question="Agent 可以调用哪些工具？",
        ground_truth="Agent 支持知识库搜索（search_knowledge_base）、多知识库联合搜索（search_multiple_kbs）、"
        "Web 搜索（web_search，通过博查 API）。工具采用工厂模式动态创建。",
        tags=["agent", "tools"],
        expected_keywords=["search_knowledge_base", "web_search", "博查", "工厂模式"],
    ),

    # ── 向量库相关 ──
    EvalItem(
        question="系统支持哪些向量数据库？",
        ground_truth="支持 ChromaDB（默认，持久化/HTTP 模式）、Qdrant（高性能，自动重试）。"
        "通过 BaseVectorStore 抽象层统一接口，配置驱动切换。pgvector 支持待实现。",
        tags=["vectorstore"],
        expected_keywords=["ChromaDB", "Qdrant", "BaseVectorStore", "pgvector"],
    ),
    EvalItem(
        question="Embedding 模型使用的是什么？",
        ground_truth="默认使用 Qwen3-Embedding-0.6B 模型，通过 sentence-transformers 加载。"
        "支持 BGE 系列作为备选。使用策略模式区分 Query/Document 编码格式。"
        "GPU OOM 时自动回退 CPU。",
        tags=["embedding", "models"],
        expected_keywords=["Qwen3-Embedding", "0.6B", "sentence-transformers", "BGE", "GPU OOM"],
    ),

    # ── 工程相关 ──
    EvalItem(
        question="项目的租户隔离是如何实现的？",
        ground_truth="所有数据库模型继承 TenantIsolationMixin，自动注入 tenant_id。"
        "Middleware 层提取租户标识，Repository 层自动过滤。"
        "非多租户模式下所有记录使用 tenant_id='default'。",
        tags=["engineering", "tenant"],
        expected_keywords=["TenantIsolationMixin", "tenant_id", "Middleware", "Repository"],
    ),
    EvalItem(
        question="API 响应格式是什么？",
        ground_truth="所有 API 使用统一响应格式 APIResponse[T]：{success, code, message, data}。"
        "异常通过 AppException 子类统一处理，由全局异常处理器转换为 ErrorResponse。",
        tags=["engineering", "api"],
        expected_keywords=["APIResponse", "success", "code", "message", "data", "AppException"],
    ),
    EvalItem(
        question="数据库迁移使用什么工具？",
        ground_truth="使用 Alembic 进行数据库迁移。命令：alembic revision --autogenerate -m 'description'，"
        "然后 alembic upgrade head 执行迁移。",
        tags=["engineering", "database"],
        expected_keywords=["Alembic", "revision", "autogenerate", "upgrade head"],
    ),

    # ── 部署相关 ──
    EvalItem(
        question="后端服务如何启动？",
        ground_truth="使用 uv run uvicorn src.main:app --reload --port 8000 启动开发服务器。"
        "应用通过 lifespan 管理生命周期：初始化数据库、创建默认管理员、关闭连接池。"
        "非生产环境自动创建数据库表。",
        tags=["deployment"],
        expected_keywords=["uvicorn", "lifespan", "8000", "启动"],
    ),
    EvalItem(
        question="项目使用什么 LLM 服务提供商？",
        ground_truth="默认使用 DeepSeek（兼容 OpenAI API），支持 OpenAI 和 Anthropic 作为备选。"
        "通过 LLMFactory 统一管理模型创建，配置驱动切换。",
        tags=["llm", "deployment"],
        expected_keywords=["DeepSeek", "OpenAI", "Anthropic", "LLMFactory"],
    ),
    EvalItem(
        question="如何配置和运行测试？",
        ground_truth="使用 pytest 运行测试：uv run pytest tests/ -v 运行全部，"
        "-m unit 运行单元测试，-m 'not integration' 跳过集成测试，"
        "-k pattern 匹配特定测试名。",
        tags=["testing"],
        expected_keywords=["pytest", "unit", "integration", "-k", "-m"],
    ),

    # ── 前端相关 ──
    EvalItem(
        question="前端使用什么技术栈？",
        ground_truth="React 18 + TypeScript + Vite，使用 Tailwind CSS 样式框架，"
        "shadcn/ui 组件模式。状态管理使用 Zustand。",
        tags=["frontend"],
        expected_keywords=["React", "TypeScript", "Vite", "Tailwind", "shadcn", "Zustand"],
    ),
    EvalItem(
        question="前端的主题系统支持哪些模式？",
        ground_truth="支持两套配色方案（Emerald 翡翠绿 / Amber 琥珀金）× 明暗双模式 = 4 种主题。"
        "通过 data-theme 属性 + .dark CSS 类切换。",
        tags=["frontend", "theme"],
        expected_keywords=["Emerald", "Amber", "翡翠", "琥珀", "data-theme", "dark"],
    ),
]


# ── 工具函数 ────────────────────────────────────────────────

def get_dataset_by_tag(tag: str) -> list[EvalItem]:
    """按标签筛选评估项。"""
    return [item for item in GOLDEN_DATASET if tag in item.tags]


def get_all_questions() -> list[str]:
    """获取所有评估问题。"""
    return [item.question for item in GOLDEN_DATASET]


def get_all_ground_truths() -> list[str]:
    """获取所有标准答案。"""
    return [item.ground_truth for item in GOLDEN_DATASET]


def to_ragas_format(
    items: list[EvalItem] | None = None,
) -> dict[str, list[str]]:
    """转换为 Ragas 评估格式。

    Returns:
        {"question": [...], "ground_truth": [...]}
    """
    source = items if items is not None else GOLDEN_DATASET
    return {
        "question": [item.question for item in source],
        "ground_truth": [item.ground_truth for item in source],
    }


def dataset_stats() -> dict:
    """数据集统计信息。"""
    tags: dict[str, int] = {}
    for item in GOLDEN_DATASET:
        for tag in item.tags:
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "total_items": len(GOLDEN_DATASET),
        "tags": dict(sorted(tags.items())),
        "avg_question_len": sum(len(q.question) for q in GOLDEN_DATASET) / len(GOLDEN_DATASET),
        "avg_truth_len": sum(len(q.ground_truth) for q in GOLDEN_DATASET) / len(GOLDEN_DATASET),
    }
