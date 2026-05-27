"""
应用核心配置模块。

使用 pydantic-settings 从 .env 文件和环境变量中加载配置，
所有配置项集中管理，便于不同环境切换。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置，自动从 .env 和环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用 ----
    app_name: str = Field(default="agent-platform", alias="APP_NAME")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_secret_key: SecretStr = Field(
        default=SecretStr("change-me"), alias="APP_SECRET_KEY"
    )

    # ---- 数据库 ----
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_user: str = Field(default="agent_user", alias="DB_USER")
    db_password: SecretStr = Field(default=SecretStr(""), alias="DB_PASSWORD")
    db_name: str = Field(default="agent_platform", alias="DB_NAME")
    db_pool_size: int = Field(default=20, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # ---- Redis ----
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")

    # ---- 向量数据库 ----
    vector_store_type: Literal["chroma", "qdrant", "pgvector"] = Field(
        default="chroma", alias="VECTOR_STORE_TYPE"
    )
    # Chroma
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8001, alias="CHROMA_PORT")
    chroma_persist_dir: str = Field(default="./data/chroma", alias="CHROMA_PERSIST_DIR")
    # Qdrant
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_api_key: SecretStr = Field(default=SecretStr(""), alias="QDRANT_API_KEY")
    qdrant_prefer_grpc: bool = Field(default=False, alias="QDRANT_PREFER_GRPC")

    # ---- LLM ----
    # DeepSeek（默认，兼容 OpenAI API）
    deepseek_api_key: SecretStr = Field(
        default=SecretStr(""), alias="DEEPSEEK_API_KEY"
    )
    deepseek_api_base: str = Field(
        default="https://api.deepseek.com/v1", alias="DEEPSEEK_API_BASE"
    )
    deepseek_default_model: str = Field(
        default="deepseek-chat", alias="DEEPSEEK_DEFAULT_MODEL"
    )

    # OpenAI（备选）
    openai_api_key: SecretStr = Field(default=SecretStr(""), alias="OPENAI_API_KEY")
    openai_api_base: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_API_BASE"
    )
    openai_default_model: str = Field(default="gpt-4o", alias="OPENAI_DEFAULT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    # Anthropic（备选）
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), alias="ANTHROPIC_API_KEY"
    )
    anthropic_default_model: str = Field(
        default="claude-sonnet-4-6", alias="ANTHROPIC_DEFAULT_MODEL"
    )

    # 默认 LLM 提供商: deepseek | openai | anthropic
    llm_provider: Literal["deepseek", "openai", "anthropic"] = Field(
        default="deepseek", alias="LLM_PROVIDER"
    )

    # ---- 监测（开源方案：LangFuse + OpenTelemetry） ----
    monitoring_enabled: bool = Field(default=True, alias="MONITORING_ENABLED")
    monitoring_provider: Literal["langfuse", "otel"] = Field(
        default="langfuse", alias="MONITORING_PROVIDER"
    )

    # LangFuse（开源 LLM 监测平台）
    langfuse_public_key: str | None = Field(
        default=None, alias="LANGFUSE_PUBLIC_KEY"
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None, alias="LANGFUSE_SECRET_KEY"
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com", alias="LANGFUSE_HOST"
    )

    # OpenTelemetry（备选/增强）
    otel_exporter_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(
        default="agent-platform", alias="OTEL_SERVICE_NAME"
    )

    # ---- 多租户 ----
    multi_tenant_enabled: bool = Field(default=False, alias="MULTI_TENANT_ENABLED")
    tenant_header_name: str = Field(default="x-tenant-id", alias="TENANT_HEADER_NAME")

    # ---- Agent ----
    agent_max_iterations: int = Field(default=15, alias="AGENT_MAX_ITERATIONS")
    agent_max_execution_time: int = Field(
        default=300, alias="AGENT_MAX_EXECUTION_TIME"
    )

    # Plan 模型（可独立选择推理能力更强的模型做规划）
    plan_model_name: str = Field(
        default="", alias="PLAN_MODEL_NAME",
        description="规划专用模型，留空则复用执行模型",
    )

    # ---- 博查 Web Search ----
    bocha_api_key: SecretStr = Field(
        default=SecretStr(""), alias="BOCHA_API_KEY"
    )
    bocha_api_base: str = Field(
        default="https://api.bochaai.com/v1/web-search",
        alias="BOCHA_API_BASE",
    )

    # ---- 视觉语言模型 VLM（OCR 增强 / 图像描述） ----
    dashscope_api_key: SecretStr = Field(
        default=SecretStr(""), alias="DASHSCOPE_API_KEY",
        description="阿里云 DashScope API Key（Qwen3-VL 多模态模型）",
    )
    dashscope_api_base: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="DASHSCOPE_API_BASE",
    )
    vlm_enabled: bool = Field(
        default=True, alias="VLM_ENABLED",
        description="是否启用 VLM 增强 OCR 与图像描述（Qwen3-VL-Flash）",
    )
    vlm_model: str = Field(
        default="qwen3-vl-flash", alias="VLM_MODEL",
        description="多模态图像理解模型名称",
    )

    # ---- 文件输出 ----
    file_output_dir: str = Field(
        default="./data/outputs", alias="FILE_OUTPUT_DIR",
        description="Agent 生成文件的存储目录",
    )
    file_download_url_prefix: str = Field(
        default="/api/v1/files", alias="FILE_DOWNLOAD_URL_PREFIX",
        description="文件下载 URL 前缀",
    )

    # ---- 上下文管理 ----
    context_strategy: str = Field(
        default="hybrid", alias="CONTEXT_STRATEGY",
        description="上下文策略: sliding_window | summarize | selective | hybrid",
    )
    context_max_tokens: int = Field(
        default=128_000, alias="CONTEXT_MAX_TOKENS",
        description="上下文窗口最大 token 数",
    )
    context_response_reserve: int = Field(
        default=8_192, alias="CONTEXT_RESPONSE_RESERVE",
        description="为模型输出预留的 token 数",
    )
    context_summary_max_tokens: int = Field(
        default=2_048, alias="CONTEXT_SUMMARY_MAX_TOKENS",
        description="摘要的最大 token 数",
    )
    context_recent_message_count: int = Field(
        default=10, alias="CONTEXT_RECENT_MESSAGE_COUNT",
        description="混合策略保留的最近消息数",
    )
    context_selective_top_k: int = Field(
        default=5, alias="CONTEXT_SELECTIVE_TOP_K",
        description="选择性检索返回的消息数",
    )

    # ---- 检查点持久化 ----
    checkpoint_db_url: str = Field(
        default="sqlite:///./data/checkpoints.db", alias="CHECKPOINT_DB_URL",
        description="LangGraph 检查点数据库 URL",
    )

    # ---- JWT / Auth ----
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("change-me-jwt-secret-at-least-32-chars"),
        alias="JWT_SECRET_KEY",
    )
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, alias="JWT_REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # ---- 验证码 ----
    verification_code_ttl: int = Field(
        default=300, alias="VERIFICATION_CODE_TTL"
    )

    # ---- 知识库 ----
    kb_storage_dir: str = Field(
        default="./data/knowledge_bases", alias="KB_STORAGE_DIR",
        description="知识库源文件存档目录",
    )
    kb_embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B", alias="KB_EMBEDDING_MODEL",
        description="Embedding 模型名称（sentence-transformers 格式）",
    )
    kb_reranker_model: str = Field(
        default="Qwen/Qwen3-Reranker-0.6B", alias="KB_RERANKER_MODEL",
        description="Reranker 模型名称（Qwen3 使用 transformers 打分）",
    )
    kb_default_chunk_size: int = Field(
        default=768, alias="KB_DEFAULT_CHUNK_SIZE",
        description="默认分块大小（字符数）",
    )
    kb_default_chunk_overlap: int = Field(
        default=128, alias="KB_DEFAULT_CHUNK_OVERLAP",
        description="默认分块重叠（字符数）",
    )
    kb_parent_chunk_size: int = Field(
        default=1500, alias="KB_PARENT_CHUNK_SIZE",
        description="父块大小（用于扩展上下文，需为 embed 元数据头预留空间）",
    )
    kb_parent_chunk_overlap: int = Field(
        default=100, alias="KB_PARENT_CHUNK_OVERLAP",
        description="父块重叠（字符数）",
    )
    kb_search_top_k: int = Field(
        default=5, alias="KB_SEARCH_TOP_K",
        description="向量检索返回数量",
    )
    kb_reranker_top_k: int = Field(
        default=3, alias="KB_RERANKER_TOP_K",
        description="重排序后返回数量",
    )
    kb_bm25_backend: Literal["memory", "sqlite_fts5"] = Field(
        default="sqlite_fts5", alias="KB_BM25_BACKEND",
        description="BM25 后端: memory (rank_bm25 全量内存) | sqlite_fts5 (SQLite FTS5 磁盘索引)",
    )
    kb_hybrid_search_enabled: bool = Field(
        default=True, alias="KB_HYBRID_SEARCH_ENABLED",
        description="是否启用 BM25+向量混合检索",
    )
    kb_chat_auto_retrieve: bool = Field(
        default=True, alias="KB_CHAT_AUTO_RETRIEVE",
        description="聊天时是否自动预检索知识库并注入上下文",
    )
    kb_chat_retrieve_top_k: int = Field(
        default=5, alias="KB_CHAT_RETRIEVE_TOP_K",
        description="聊天预检索返回条数",
    )
    kb_rerank_min_score: float = Field(
        default=0.25, alias="KB_RERANK_MIN_SCORE",
        description="重排序最低分数阈值（0-1）",
    )
    kb_search_mmr_enabled: bool = Field(
        default=True, alias="KB_SEARCH_MMR_ENABLED",
        description="是否启用 MMR 多样化去重",
    )
    kb_search_mmr_lambda: float = Field(
        default=0.7, alias="KB_SEARCH_MMR_LAMBDA",
        description="MMR 平衡系数（越大越偏向相关性）",
    )
    kb_supported_extensions: list[str] = Field(
        default=[".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
        alias="KB_SUPPORTED_EXTENSIONS",
        description="支持上传的文件扩展名",
    )
    kb_max_file_size_mb: int = Field(
        default=50, alias="KB_MAX_FILE_SIZE_MB",
        description="单文件最大上传大小（MB）",
    )
    kb_ocr_enabled: bool = Field(
        default=True, alias="KB_OCR_ENABLED",
        description="是否启用 OCR 识别图片文字",
    )
    kb_ocr_lang: str = Field(
        default="ch", alias="KB_OCR_LANG",
        description="PaddleOCR 语言模型（ch=中英文混合）",
    )
    kb_vlm_table_extraction: bool = Field(
        default=True, alias="KB_VLM_TABLE_EXTRACTION",
        description="是否使用 VLM（Qwen3-VL-Flash）从 PDF 页面发现并提取表格",
    )
    kb_vlm_table_extraction_max_pages: int = Field(
        default=5, alias="KB_VLM_TABLE_EXTRACTION_MAX_PAGES",
        description="每个文档最多使用 VLM 提取表格的页数（控制成本）",
    )
    kb_pdf_parser: Literal["default", "mineru", "auto"] = Field(
        default="auto", alias="KB_PDF_PARSER",
        description="PDF 解析器: default (pdfplumber+PyMuPDF) | mineru (magic-pdf 深度学习版面分析) | auto (自动检测，MinerU 可用则优先使用)",
    )
    mineru_device: str = Field(
        default="cpu", alias="MINERU_DEVICE",
        description="MinerU 推理设备: cpu | cuda | cuda:0 等",
    )
    mineru_models_dir: str = Field(
        default="", alias="MINERU_MODELS_DIR",
        description="MinerU 模型下载/缓存目录（留空使用默认路径）",
    )
    mineru_model_source: str = Field(
        default="modelscope", alias="MINERU_MODEL_SOURCE",
        description="MinerU 模型来源: huggingface | modelscope | local",
    )
    mineru_backend: str = Field(
        default="pipeline", alias="MINERU_BACKEND",
        description="MinerU 解析后端: pipeline（通用）| hybrid-auto-engine（图文混合，精度更高但资源消耗大）",
    )
    mineru_enable_table_recognition: bool = Field(
        default=True, alias="MINERU_ENABLE_TABLE_RECOGNITION",
        description="MinerU 是否启用表格识别",
    )
    kb_page_ocr_fallback: bool = Field(
        default=True, alias="KB_PAGE_OCR_FALLBACK",
        description="PDF 某页无文本时是否对该页整页渲染后 OCR",
    )
    kb_retrieval_metrics_enabled: bool = Field(
        default=True, alias="KB_RETRIEVAL_METRICS_ENABLED",
        description="是否在检索日志中输出每步耗时（用于性能监控）",
    )
    kb_embedding_cache_enabled: bool = Field(
        default=True, alias="KB_EMBEDDING_CACHE_ENABLED",
        description="是否启用 Redis 缓存 Embedding 向量",
    )
    kb_search_cache_enabled: bool = Field(
        default=True, alias="KB_SEARCH_CACHE_ENABLED",
        description="是否启用 Redis 缓存搜索结果",
    )
    kb_search_cache_ttl: int = Field(
        default=300, alias="KB_SEARCH_CACHE_TTL",
        description="搜索结果缓存过期时间（秒），默认 5 分钟",
    )
    kb_embedding_cache_ttl: int = Field(
        default=86400, alias="KB_EMBEDDING_CACHE_TTL",
        description="Embedding 缓存过期时间（秒），默认 24 小时",
    )
    kb_embedding_concurrency: int = Field(
        default=2, alias="KB_EMBEDDING_CONCURRENCY",
        description="Embedding 并发线程数（CPU 预处理可并行，GPU 推理内部串行化）",
    )
    kb_embedding_device: str = Field(
        default="auto", alias="KB_EMBEDDING_DEVICE",
        description="Embedding 模型运行设备: auto | cpu | cuda",
    )
    kb_query_rewrite_enabled: bool = Field(
        default=True, alias="KB_QUERY_REWRITE_ENABLED",
        description="启用 Query 改写（HyDE），短 query 自动生成假设文档提升召回",
    )
    kb_query_rewrite_min_chars: int = Field(
        default=20, alias="KB_QUERY_REWRITE_MIN_CHARS",
        description="Query 长度低于此值（字符数）时启用改写",
    )
    kb_query_rewrite_model: str = Field(
        default="", alias="KB_QUERY_REWRITE_MODEL",
        description="Query 改写专用 LLM 模型（留空复用执行模型，推荐轻量模型如 deepseek-chat）",
    )
    kb_reranker_pruning_enabled: bool = Field(
        default=True, alias="KB_RERANKER_PRUNING_ENABLED",
        description="启用 Reranker 两阶段剪枝，第一阶段 top15 高分即止",
    )
    kb_reranker_first_pass_count: int = Field(
        default=15, alias="KB_RERANKER_FIRST_PASS_COUNT",
        description="Reranker 第一阶段候选数（高分通过则跳过第二阶段）",
    )
    kb_reranker_pruning_threshold: float = Field(
        default=0.5, alias="KB_RERANKER_PRUNING_THRESHOLD",
        description="第一阶段最高分 >= 此值则跳过第二阶段",
    )
    kb_embedding_batch_wait_ms: int = Field(
        default=50, alias="KB_EMBEDDING_BATCH_WAIT_MS",
        description="Embedding 攒批等待窗口（毫秒），0 禁用",
    )
    kb_embedding_batch_max: int = Field(
        default=64, alias="KB_EMBEDDING_BATCH_MAX",
        description="Embedding 攒批最大合并条数",
    )
    kb_gpu_memory_fraction: float = Field(
        default=0.70, alias="KB_GPU_MEMORY_FRACTION",
        description="GPU 显存占用比例上限（0-1），避免占满影响桌面渲染",
    )
    hf_endpoint: str = Field(
        default="", alias="HF_ENDPOINT",
        description="HuggingFace 镜像地址（留空使用官方源，国内可设 https://hf-mirror.com）",
    )
    hf_token: SecretStr = Field(
        default=SecretStr(""), alias="HF_TOKEN",
        description="HuggingFace 访问令牌（下载 gated 模型或提高限速）",
    )

    # ---- 管理员 ----
    admin_username: str = Field(
        default="admin_tt", alias="ADMIN_USERNAME",
        description="默认管理员用户名",
    )
    admin_password: SecretStr = Field(
        default=SecretStr("Tt149212!!!"), alias="ADMIN_PASSWORD",
        description="默认管理员密码（仅首次启动创建时使用）",
    )
    admin_email: str = Field(
        default="admin@agent-platform.local", alias="ADMIN_EMAIL",
        description="默认管理员邮箱",
    )

    # ---- 辅助 ----
    default_tenant_id: str = "default"

    @property
    def database_url(self) -> str:
        """构建异步数据库连接 URL。"""
        password = self.db_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """构建同步数据库连接 URL（用于 Alembic 迁移）。"""
        password = self.db_password.get_secret_value()
        return (
            f"postgresql://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        """构建 Redis 连接 URL。"""
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """获取缓存的全局配置实例（单例模式）。"""
    return Settings()
