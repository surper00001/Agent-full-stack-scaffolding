"""
请求 Schema 定义（Pydantic）。

所有 API 入参均使用 Pydantic 模型校验，
确保数据类型正确和必填项完整性。
"""

from pydantic import BaseModel, Field


# ---- 会话请求 ----
class CreateConversationRequest(BaseModel):
    """创建会话请求。"""

    title: str = Field(default="新对话", max_length=512, description="会话标题")
    agent_type: str = Field(default="default", max_length=128, description="Agent 类型")


class ChatMessageRequest(BaseModel):
    """发送消息请求。"""

    content: str = Field(..., min_length=1, max_length=65535, description="用户消息内容")
    stream: bool = Field(default=False, description="是否流式返回")


# ---- Agent 请求 ----
class CreateAgentRequest(BaseModel):
    """创建 Agent 配置请求。"""

    name: str = Field(..., min_length=1, max_length=255, description="Agent 名称")
    agent_type: str = Field(..., min_length=1, max_length=64, description="Agent 类型")
    system_prompt: str = Field(..., min_length=1, description="系统提示词")
    model_name: str = Field(default="gpt-4o", max_length=128, description="模型名称")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int | None = Field(default=None, ge=1, description="最大 Token 数")
    tools: list[str] | None = Field(default=None, description="工具名称列表")


class UpdateAgentRequest(BaseModel):
    """更新 Agent 配置请求（所有字段可选）。"""

    name: str | None = Field(default=None, max_length=255)
    agent_type: str | None = Field(default=None, max_length=64)
    system_prompt: str | None = None
    model_name: str | None = Field(default=None, max_length=128)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    tools: list[str] | None = None
    is_active: bool | None = None


# ---- 查询参数 ----
class PaginationParams(BaseModel):
    """分页查询参数。"""

    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=200, description="每页数量")
