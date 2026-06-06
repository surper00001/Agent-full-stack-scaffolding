"""管理员视角的用户 Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


class UserListItem(BaseModel):
    """用户列表项。"""

    id: str
    username: str
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    is_verified: bool
    conversation_count: int = 0
    total_tokens: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class UserConversationItem(BaseModel):
    """用户对话项。"""

    id: str
    title: str
    agent_type: str
    message_count: int
    status: str
    total_tokens: int = 0
    knowledge_base_name: str | None = None
    created_at: datetime
    updated_at: datetime


class UserTokenUsageItem(BaseModel):
    """用户单次对话 Token 消耗项。"""

    conversation_id: str
    conversation_title: str
    tokens: int
    message_count: int
    created_at: datetime


class DailyTokenItem(BaseModel):
    """按日聚合的 Token 消耗。"""

    date: str
    tokens: int


class UserTokenTrendResponse(BaseModel):
    """用户 Token 趋势响应。"""

    user_id: str
    username: str
    total_tokens: int
    daily: list[DailyTokenItem]
    by_conversation: list[UserTokenUsageItem]


class UserDetailResponse(BaseModel):
    """用户详情（管理员视角）。"""

    id: str
    username: str
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    is_verified: bool
    conversation_count: int
    total_tokens: int
    token_quota: int | None = None
    created_at: datetime
    updated_at: datetime
    recent_conversations: list[UserConversationItem] = Field(default_factory=list)


class SetTokenQuotaRequest(BaseModel):
    """设置用户 Token 配额请求。"""

    token_quota: int = Field(ge=0, description="Token 配额上限，0 表示无限制")


class UpdateUserRoleRequest(BaseModel):
    """更新用户角色请求。"""

    role: str = Field(pattern="^(admin|user)$", description="角色: admin | user")
