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
    vector_store_type: Literal["chroma", "pgvector"] = Field(
        default="chroma", alias="VECTOR_STORE_TYPE"
    )
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8001, alias="CHROMA_PORT")
    chroma_persist_dir: str = Field(default="./data/chroma", alias="CHROMA_PERSIST_DIR")

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
        default=2000, alias="KB_PARENT_CHUNK_SIZE",
        description="父块大小（用于扩展上下文）",
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
        default=[".pdf", ".docx", ".doc", ".txt", ".md", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
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
    kb_page_ocr_fallback: bool = Field(
        default=True, alias="KB_PAGE_OCR_FALLBACK",
        description="PDF 某页无文本时是否对该页整页渲染后 OCR",
    )
    kb_embedding_device: str = Field(
        default="auto", alias="KB_EMBEDDING_DEVICE",
        description="Embedding 模型运行设备: auto | cpu | cuda",
    )
    hf_endpoint: str = Field(
        default="", alias="HF_ENDPOINT",
        description="HuggingFace 镜像地址（留空使用官方源，国内可设 https://hf-mirror.com）",
    )
    hf_token: SecretStr = Field(
        default=SecretStr(""), alias="HF_TOKEN",
        description="HuggingFace 访问令牌（下载 gated 模型或提高限速）",
    )

    # ---- 辅助 ----
    deafult_tenant_id: str = "default"

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
