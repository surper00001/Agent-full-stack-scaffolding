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
