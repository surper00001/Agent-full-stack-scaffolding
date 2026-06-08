"""
Skill API — Harness Engineering Skill 管理接口。

提供 Skill 的 CRUD、测试、发布、安装等接口。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_tenant, get_current_user, require_admin
from src.db.session import get_db_session
from src.harness.skill_lifecycle import SkillStatus
from src.models.schemas.response import APIResponse, PaginatedData
from src.models.schemas.skill import (
    SkillCreateRequest,
    SkillDetail,
    SkillGenerateRequest,
    SkillGenerateResult,
    SkillItem,
    SkillTestRequest,
    SkillTestResult,
    SkillUpdateRequest,
)
from src.services.skill_service import SkillService

router = APIRouter(prefix="/skills", tags=["Skill 管理"])


def _validate_skill_id(skill_id: str) -> str:
    """验证 skill_id 为合法 UUID，防止前端路由（如 /skills/new）误入。"""
    try:
        uuid.UUID(skill_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Skill 不存在: {skill_id}")
    return skill_id


# ── CRUD ──

@router.get("", response_model=APIResponse[PaginatedData[SkillItem]], summary="获取 Skill 列表")
async def list_skills(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="按状态过滤"),
    category: str | None = Query(default=None, description="按分类过滤"),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[SkillItem]]:
    service = SkillService(db)
    skip = (page - 1) * page_size
    skills = await service.list_all(
        tenant_id=tenant_id,
        status=status,
        category=category,
        skip=skip,
        limit=page_size,
    )
    total = await service.count(tenant_id=tenant_id)
    return APIResponse(
        data=PaginatedData(
            items=[SkillItem.model_validate(s) for s in skills],
            total=total,
            page=page,
            page_size=page_size,
            pages=max(1, (total + page_size - 1) // page_size),
        )
    )


@router.post("", response_model=APIResponse[SkillDetail], summary="创建 Skill")
async def create_skill(
    body: SkillCreateRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    service = SkillService(db)
    skill = await service.create(
        name=body.name,
        display_name=body.display_name,
        description=body.description,
        code=body.code,
        tenant_id=tenant_id,
        category=body.category,
        skill_type=body.skill_type,
        version=body.version,
        is_read_only=body.is_read_only,
        is_concurrency_safe=body.is_concurrency_safe,
        requires_sandbox=body.requires_sandbox,
        security_level=body.security_level,
        input_schema=body.input_schema,
        dependencies=body.dependencies,
    )
    return APIResponse(message="Skill 创建成功", data=SkillDetail.model_validate(skill))


@router.get("/{skill_id}", response_model=APIResponse[SkillDetail], summary="获取 Skill 详情")
async def get_skill(
    skill_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    skill = await service.get(skill_id, tenant_id)
    return APIResponse(data=SkillDetail.model_validate(skill))


@router.put("/{skill_id}", response_model=APIResponse[SkillDetail], summary="更新 Skill")
async def update_skill(
    skill_id: str,
    body: SkillUpdateRequest,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    updates = body.model_dump(exclude_none=True)
    skill = await service.update(skill_id, tenant_id, **updates)
    return APIResponse(message="Skill 已更新", data=SkillDetail.model_validate(skill))


@router.delete("/{skill_id}", response_model=APIResponse, summary="删除 Skill")
async def delete_skill(
    skill_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    await service.delete(skill_id, tenant_id)
    return APIResponse(message="Skill 已删除")


# ── 生命周期 ──

@router.post("/{skill_id}/test", response_model=APIResponse[SkillTestResult], summary="测试 Skill")
async def test_skill(
    skill_id: str,
    body: SkillTestRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillTestResult]:
    _validate_skill_id(skill_id)
    from src.harness.sandbox.manager import get_sandbox_manager

    service = SkillService(db)
    skill = await service.get(skill_id, tenant_id)

    test_code = (
        f"{skill.code}\n\n"
        f"import json\n"
        f"test_input = {__import__('json').dumps(body.input_data)}\n"
        f"result = execute(test_input)\n"
        f"print(json.dumps(result, ensure_ascii=False))\n"
    )

    manager = get_sandbox_manager()
    result = await manager.execute_code(test_code, timeout=body.timeout_seconds)
    return APIResponse(
        message="测试完成",
        data=SkillTestResult(
            success=result.success,
            output=result.stdout.strip() if result.success else None,
            error=(result.stderr or result.stdout) if not result.success else None,
            duration_ms=result.duration_ms,
            sandbox_logs=None,
        ),
    )


@router.post("/{skill_id}/publish", response_model=APIResponse[SkillDetail], summary="发布 Skill")
async def publish_skill(
    skill_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    # 先执行安全扫描
    skill = await service.get(skill_id, tenant_id)
    from src.harness.security.policies import get_policy
    from src.harness.security.scanner import CodeScanner

    scanner = CodeScanner(get_policy(skill.security_level))
    scan = scanner.scan(skill.code)
    if not scan.passed:
        raise HTTPException(
            status_code=400,
            detail=f"安全扫描未通过 ({scan.score}/100)，请修复后重试",
        )

    skill = await service.publish(skill_id, tenant_id)
    return APIResponse(message="Skill 已发布并激活", data=SkillDetail.model_validate(skill))


@router.post("/{skill_id}/deprecate", response_model=APIResponse[SkillDetail], summary="弃用 Skill")
async def deprecate_skill(
    skill_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    skill = await service.deprecate(skill_id, tenant_id)
    return APIResponse(message="Skill 已弃用", data=SkillDetail.model_validate(skill))


@router.post("/{skill_id}/status/{target_status}", response_model=APIResponse[SkillDetail], summary="转换状态")
async def transition_skill(
    skill_id: str,
    target_status: str,
    reason: str = Query(default=""),
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillDetail]:
    _validate_skill_id(skill_id)
    service = SkillService(db)
    try:
        target = SkillStatus(target_status)
    except ValueError:
        valid = [s.value for s in SkillStatus]
        raise HTTPException(status_code=400, detail=f"无效状态: {target_status}，有效值: {valid}")

    skill = await service.transition_status(skill_id, target, tenant_id, reason=reason, triggered_by="user")
    return APIResponse(message=f"Skill 状态已转为: {target.value}", data=SkillDetail.model_validate(skill))


# ── AI 生成 ──

@router.post("/{skill_id}/generate", response_model=APIResponse[SkillGenerateResult], summary="AI 生成 Skill")
async def generate_skill(
    skill_id: str,
    body: SkillGenerateRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[SkillGenerateResult]:
    _validate_skill_id(skill_id)
    # 此接口触发 AI 生成 Skill 的流程
    # 实际生成由 Harness Agent 完成
    from src.agents.harness_agent import run_harness_agent
    from src.llm.factory import LLMFactory

    service = SkillService(db)
    skill = await service.get(skill_id, tenant_id)

    llm = LLMFactory().create_chat_model()
    result = await run_harness_agent(llm, body.requirement)

    last_msg = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "content") and getattr(msg, "type", "") != "tool":
            last_msg = msg.content
            break

    return APIResponse(
        message="AI 生成完成",
        data=SkillGenerateResult(
            skill=SkillDetail.model_validate(skill),
            generated_code=last_msg,
            tests_passed=None,
            scan_passed=None,
            warnings=[],
        ),
    )
