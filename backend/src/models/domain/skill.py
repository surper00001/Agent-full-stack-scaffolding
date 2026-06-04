"""
Skill 领域模型。

Skill 是 AI 可自安装的能力单元。每个 Skill 持久化到 DB，
运行时通过 HarnessTool 接口执行，可选在沙箱中隔离运行。

Skill 类型：
- python_function: 纯 Python 函数，进程内执行
- shell_script: Shell/Python 脚本，沙箱内执行
- http_api: HTTP API 调用封装
- langchain_tool: 兼容现有 LangChain Tool 的包装
"""

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import BaseModel


class Skill(BaseModel):
    """Skill 持久化模型 — AI 可自安装的能力单元。"""

    __tablename__ = "skills"

    # ── 基本标识 ──
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Skill 唯一标识名（如 weather_fetcher）"
    )
    display_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="显示名称"
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False, comment="功能描述（给 LLM 看的使用说明）"
    )

    # ── 版本 ──
    version: Mapped[str] = mapped_column(
        String(32), default="1.0.0", comment="语义版本号"
    )

    # ── 分类 ──
    category: Mapped[str] = mapped_column(
        String(64), default="custom",
        comment="分类: file/shell/network/knowledge/custom/meta"
    )
    skill_type: Mapped[str] = mapped_column(
        String(32), default="python_function",
        comment="类型: python_function/shell_script/http_api/langchain_tool"
    )

    # ── 代码 ──
    code: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Skill 源代码"
    )
    code_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="代码 SHA256 哈希（防篡改）"
    )

    # ── Schema 定义（Pydantic → JSON Schema） ──
    input_schema: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="输入参数 JSON Schema"
    )
    output_schema: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="输出格式 JSON Schema"
    )

    # ── 依赖 ──
    dependencies: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="pip 依赖列表（JSON 数组）"
    )
    system_deps: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="系统依赖（如 apt packages）（JSON 数组）"
    )

    # ── 调度属性 ──
    is_read_only: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否只读（可并行）"
    )
    is_concurrency_safe: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否并发安全（真正的并发安全）"
    )
    requires_sandbox: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否必须在沙箱中运行"
    )

    # ── 安全 ──
    security_level: Mapped[str] = mapped_column(
        String(32), default="medium",
        comment="安全等级: low/medium/high/critical"
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="执行前是否需要人工审批"
    )
    allowed_imports: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="允许导入的模块白名单（JSON 数组）"
    )

    # ── 沙箱配置 ──
    sandbox_image: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Docker 镜像"
    )
    sandbox_cpu_limit: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="CPU 限制（核心数）"
    )
    sandbox_memory_mb: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="内存限制（MB）"
    )
    sandbox_timeout_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="超时时间（秒）"
    )
    sandbox_network: Mapped[str | None] = mapped_column(
        String(32), default="none", comment="网络模式: none/internal/whitelist/full"
    )

    # ── 生命周期 ──
    status: Mapped[str] = mapped_column(
        String(32), default="draft", index=True,
        comment="draft/testing/pending_review/approved/published/active/deprecated/archived/rejected"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否已激活可用"
    )

    # ── 测试与质量 ──
    test_results: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近测试结果（JSON）"
    )
    security_scan_result: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近安全扫描结果（JSON）"
    )

    # ── 使用统计 ──
    usage_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="调用次数"
    )
    success_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="成功次数"
    )
    avg_duration_ms: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="平均执行耗时（毫秒）"
    )
    avg_rating: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="平均评分（1-5）"
    )

    # ── 共享 ──
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否公开（跨租户可见）"
    )
    author: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="作者（AI生成则为 agent_id）"
    )

    # ── 扩展 ──
    metadata_: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="扩展元数据（JSON）"
    )

    @property
    def is_installed(self) -> bool:
        """是否已安装（status 为 active 或 published）。"""
        return self.status in ("active", "published")

    @property
    def can_execute(self) -> bool:
        """当前是否可执行。"""
        return self.is_active and self.status == "active" and not self.is_deleted

    def __repr__(self) -> str:
        return (
            f"<Skill(id={self.id}, name={self.name!r}, "
            f"v{self.version}, status={self.status})>"
        )
