"""
Skill Pydantic Schema — 请求/响应数据模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── 请求 Schema ──

class SkillCreateRequest(BaseModel):
    """创建 Skill 请求（手动或 AI 生成）。"""
    name: str = Field(..., min_length=2, max_length=255, description="Skill 唯一标识名")
    display_name: str = Field(..., min_length=1, max_length=255, description="显示名称")
    description: str = Field(..., min_length=1, description="功能描述（给 LLM 看）")
    version: str = Field(default="1.0.0", description="语义版本号")
    category: str = Field(default="custom", description="分类")
    skill_type: str = Field(default="python_function", description="类型")
    code: str = Field(..., min_length=1, description="源代码")
    input_schema: str | None = Field(None, description="输入 JSON Schema")
    output_schema: str | None = Field(None, description="输出 JSON Schema")
    dependencies: list[str] | None = Field(None, description="pip 依赖")
    is_read_only: bool = Field(default=False)
    is_concurrency_safe: bool = Field(default=False)
    requires_sandbox: bool = Field(default=False)
    security_level: str = Field(default="medium")
    sandbox_image: str | None = None
    sandbox_cpu_limit: float | None = None
    sandbox_memory_mb: int | None = None
    sandbox_timeout_seconds: int | None = None
    sandbox_network: str | None = "none"
    is_public: bool = Field(default=False)


class SkillUpdateRequest(BaseModel):
    """更新 Skill 请求。"""
    display_name: str | None = None
    description: str | None = None
    code: str | None = None
    input_schema: str | None = None
    output_schema: str | None = None
    dependencies: list[str] | None = None
    is_read_only: bool | None = None
    is_concurrency_safe: bool | None = None
    requires_sandbox: bool | None = None
    security_level: str | None = None
    sandbox_image: str | None = None
    sandbox_cpu_limit: float | None = None
    sandbox_memory_mb: int | None = None
    sandbox_timeout_seconds: int | None = None
    sandbox_network: str | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    requires_approval: bool | None = None


class SkillGenerateRequest(BaseModel):
    """AI 生成 Skill 请求。"""
    requirement: str = Field(..., min_length=10, description="Skill 需求描述（自然语言）")
    category: str = Field(default="custom", description="预期分类")
    auto_test: bool = Field(default=True, description="是否自动在沙箱中测试")
    auto_publish: bool = Field(default=False, description="测试通过后是否自动发布")


class SkillTestRequest(BaseModel):
    """测试 Skill 请求。"""
    input_data: dict[str, Any] = Field(default_factory=dict, description="测试输入数据")
    timeout_seconds: int = Field(default=30, description="超时时间")


# ── 响应 Schema ──

class SkillItem(BaseModel):
    """Skill 列表项。"""
    id: str
    tenant_id: str
    name: str
    display_name: str
    description: str
    version: str
    category: str
    skill_type: str
    is_read_only: bool
    is_concurrency_safe: bool
    requires_sandbox: bool
    security_level: str
    status: str
    is_active: bool
    is_public: bool
    usage_count: int
    avg_rating: float | None
    author: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillDetail(BaseModel):
    """Skill 详情（含代码）。"""
    id: str
    tenant_id: str
    name: str
    display_name: str
    description: str
    version: str
    category: str
    skill_type: str
    code: str
    code_hash: str | None
    input_schema: str | None
    output_schema: str | None
    dependencies: str | None
    is_read_only: bool
    is_concurrency_safe: bool
    requires_sandbox: bool
    requires_approval: bool
    security_level: str
    sandbox_image: str | None
    sandbox_cpu_limit: float | None
    sandbox_memory_mb: int | None
    sandbox_timeout_seconds: int | None
    sandbox_network: str | None
    status: str
    is_active: bool
    is_public: bool
    test_results: str | None
    security_scan_result: str | None
    usage_count: int
    success_count: int
    avg_duration_ms: float | None
    avg_rating: float | None
    author: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SkillTestResult(BaseModel):
    """Skill 测试结果。"""
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    sandbox_logs: str | None = None


class SkillGenerateResult(BaseModel):
    """AI 生成 Skill 结果。"""
    skill: SkillDetail
    generated_code: str
    tests_passed: bool | None = None
    scan_passed: bool | None = None
    warnings: list[str] = []


# ── Skill 发现 ──

class SkillSearchResult(BaseModel):
    """Skill 搜索结果（用于 tool_search）。"""
    name: str
    description: str
    category: str
    version: str
    is_read_only: bool
    is_concurrency_safe: bool
    requires_sandbox: bool
    security_level: str
    input_schema: dict[str, Any] | None = None
