"""
Agent 配置领域模型。

持久化 Agent 的配置（提示词、工具、模型等），
支持动态创建和管理不同类型的 Agent。
"""

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import BaseModel


class AgentConfig(BaseModel):
    """Agent 配置表 - 保存每个 Agent 的运行时配置。"""

    __tablename__ = "agent_configs"

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Agent 名称"
    )
    agent_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="Agent 类型标识"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="系统提示词"
    )
    model_name: Mapped[str] = mapped_column(
        String(128), default="gpt-4o", comment="使用的模型名称"
    )
    temperature: Mapped[float] = mapped_column(
        Float, default=0.7, comment="模型温度参数"
    )
    max_tokens: Mapped[int | None] = mapped_column(
        nullable=True, comment="最大输出 Token 数"
    )
    tools: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工具列表（JSON 数组）"
    )
    knowledge_base_ids: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关联知识库 ID 列表（JSON 数组）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    metadata_: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="扩展元数据（JSON）"
    )

    def __repr__(self) -> str:
        return f"<AgentConfig(id={self.id}, name={self.name}, type={self.agent_type})>"
