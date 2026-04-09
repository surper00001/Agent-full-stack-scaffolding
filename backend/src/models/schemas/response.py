"""
响应 Schema 定义（Pydantic）。

统一 API 响应格式，所有接口返回结构一致的 JSON。
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应格式。"""

    success: bool = Field(default=True, description="请求是否成功")
    code: int = Field(default=20000, description="业务状态码")
    message: str = Field(default="操作成功", description="状态描述")
    data: T | None = Field(default=None, description="响应数据")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据结构。"""

    items: list[T] = Field(default_factory=list, description="数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页数量")
    pages: int = Field(default=0, description="总页数")


class ErrorResponse(BaseModel):
    """错误响应格式。"""

    success: bool = Field(default=False)
    code: int = Field(description="错误码")
    message: str = Field(description="错误信息")
    detail: Any | None = Field(default=None, description="详细信息")


# ---- 会话相关 ----
class ConversationItem(BaseModel):
    """会话列表项。"""

    id: str
    title: str
    agent_type: str
    message_count: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageItem(BaseModel):
    """消息列表项。"""

    id: str
    conversation_id: str
    role: str
    content: str
    token_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- Agent 相关 ----
class AgentConfigItem(BaseModel):
    """Agent 配置项。"""

    id: str
    name: str
    agent_type: str
    system_prompt: str
    model_name: str
    temperature: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- 健康检查 ----
class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = Field(default="healthy", description="服务状态")
    version: str = Field(description="应用版本")
    uptime: float = Field(description="运行时间（秒）")
    checks: dict[str, str] = Field(
        default_factory=dict, description="各组件检查结果"
    )
