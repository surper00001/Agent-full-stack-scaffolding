"""租户相关 Schema。"""

from pydantic import BaseModel, Field


class TenantResponse(BaseModel):
    """租户信息响应。"""

    id: str
    name: str = Field(default="默认租户")
    plan: str = Field(default="free", description="free | pro | enterprise")
    status: str = Field(default="active", description="active | suspended")
    member_count: int = Field(default=1, alias="memberCount")
    created_at: str = Field(default="")

    model_config = {"populate_by_name": True}


class DailyUsageItem(BaseModel):
    date: str
    count: int


class AgentUsageItem(BaseModel):
    agent_name: str = Field(alias="agentName")
    count: int
    percentage: float = 0.0

    model_config = {"populate_by_name": True}


class UsageRecordItem(BaseModel):
    date: str
    tokens: int
    agent_name: str = Field(alias="agentName")

    model_config = {"populate_by_name": True}


class TokenUsageResponse(BaseModel):
    """Token 用量响应。"""

    quota: int = 1_000_000
    used: int = 0
    daily_usage: list[DailyUsageItem] = Field(default_factory=list, alias="dailyUsage")
    by_agent: list[AgentUsageItem] = Field(default_factory=list, alias="byAgent")
    recent_records: list[UsageRecordItem] = Field(default_factory=list, alias="recentRecords")
    compared_to_last_month: int = Field(default=0, alias="comparedToLastMonth")

    model_config = {"populate_by_name": True}
