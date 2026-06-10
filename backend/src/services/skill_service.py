"""
Skill 业务服务 — CRUD + 生命周期管理。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select

from src.core.exceptions import NotFoundError, ValidationError
from src.db.repository import BaseRepository
from src.harness.skill_lifecycle import SkillLifecycle, SkillStatus
from src.models.domain.skill import Skill

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SkillService:
    """Skill 业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = BaseRepository[Skill](Skill, session)
        self._session = session

    # ── CRUD ──

    async def create(
        self,
        name: str,
        display_name: str,
        description: str,
        code: str,
        tenant_id: str = "default",
        category: str = "custom",
        skill_type: str = "python_function",
        version: str = "1.0.0",
        is_read_only: bool = False,
        is_concurrency_safe: bool = False,
        requires_sandbox: bool = False,
        security_level: str = "medium",
        input_schema: str | None = None,
        dependencies: list[str] | None = None,
        author: str | None = None,
    ) -> Skill:
        """创建 Skill。"""
        # 检查名称唯一性
        existing = await self._repo.list_all(
            tenant_id=tenant_id,
            filters={"name": name},
        )
        if existing:
            raise ValidationError(f"Skill 名称已存在: {name}")

        code_hash = hashlib.sha256(code.encode()).hexdigest()

        skill = Skill(
            name=name,
            display_name=display_name,
            description=description,
            code=code,
            code_hash=code_hash,
            tenant_id=tenant_id,
            category=category,
            skill_type=skill_type,
            version=version,
            is_read_only=is_read_only,
            is_concurrency_safe=is_concurrency_safe,
            requires_sandbox=requires_sandbox,
            security_level=security_level,
            input_schema=input_schema,
            dependencies=json.dumps(dependencies) if dependencies else None,
            author=author,
            status=SkillStatus.DRAFT.value,
        )
        return await self._repo.create(skill)

    async def get(self, skill_id: str, tenant_id: str) -> Skill:
        skill = await self._repo.get_by_id_with_tenant(skill_id, tenant_id)
        if skill is None:
            raise NotFoundError(f"Skill 不存在: {skill_id}")
        return skill

    async def get_by_name(self, name: str, tenant_id: str) -> Skill | None:
        result = await self._repo.list_all(
            tenant_id=tenant_id,
            filters={"name": name, "is_deleted": False},
        )
        return result[0] if result else None

    async def list_all(
        self,
        tenant_id: str,
        status: str | None = None,
        category: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Skill]:
        filters: dict[str, Any] = {"is_deleted": False}
        if status:
            filters["status"] = status
        if category:
            filters["category"] = category
        return await self._repo.list_all(
            tenant_id=tenant_id,
            filters=filters,
            skip=skip,
            limit=limit,
        )

    async def list_active_skills(self, tenant_id: str = "default") -> list[Skill]:
        """获取所有激活的 Skill（运行时加载用）。"""
        return await self._repo.list_all(
            tenant_id=tenant_id,
            filters={
                "status": SkillStatus.ACTIVE.value,
                "is_deleted": False,
            },
            limit=1000,  # 不会太多
        )

    async def update(self, skill_id: str, tenant_id: str, **updates: Any) -> Skill:
        skill = await self.get(skill_id, tenant_id)

        lc = SkillLifecycle(SkillStatus(skill.status))
        if not lc.is_editable and "code" in updates:
            raise ValidationError(
                f"Skill 状态为 '{skill.status}'，不允许修改代码。"
            )

        if "code" in updates and updates["code"]:
            updates["code_hash"] = hashlib.sha256(updates["code"].encode()).hexdigest()

        for field, value in updates.items():
            if value is not None and hasattr(skill, field):
                setattr(skill, field, value)
        return await self._repo.update(skill)

    async def delete(self, skill_id: str, tenant_id: str) -> bool:
        skill = await self.get(skill_id, tenant_id)
        return await self._repo.soft_delete(skill.id)

    # ── 生命周期 ──

    async def transition_status(
        self,
        skill_id: str,
        target_status: SkillStatus,
        tenant_id: str,
        reason: str = "",
        triggered_by: str = "system",
    ) -> Skill:
        """执行状态转换。"""
        skill = await self.get(skill_id, tenant_id)
        lc = SkillLifecycle(SkillStatus(skill.status))

        try:
            lc.transition(target_status, reason=reason, triggered_by=triggered_by)
            skill.status = target_status.value
            if target_status == SkillStatus.ACTIVE:
                skill.is_active = True
            elif target_status in (SkillStatus.DEPRECATED, SkillStatus.ARCHIVED):
                skill.is_active = False
            return await self._repo.update(skill)
        except ValueError as e:
            raise ValidationError(str(e))

    async def publish(self, skill_id: str, tenant_id: str, auto_activate: bool = True) -> Skill:
        """发布 Skill（test → publish → active）。"""
        _ = await self.transition_status(skill_id, SkillStatus.PUBLISHED, tenant_id, reason="发布")
        if auto_activate:
            return await self.transition_status(skill_id, SkillStatus.ACTIVE, tenant_id, reason="自动激活")
        return _

    async def deprecate(self, skill_id: str, tenant_id: str) -> Skill:
        return await self.transition_status(skill_id, SkillStatus.DEPRECATED, tenant_id, reason="弃用")

    # ── 使用统计 ──

    async def record_usage(
        self, skill_id: str, tenant_id: str, success: bool, duration_ms: float
    ) -> None:
        """记录 Skill 使用统计。"""
        try:
            skill = await self._repo.get_by_id_with_tenant(skill_id, tenant_id)
            if skill:
                skill.usage_count = (skill.usage_count or 0) + 1
                if success:
                    skill.success_count = (skill.success_count or 0) + 1
                # 移动平均更新
                if skill.avg_duration_ms is None:
                    skill.avg_duration_ms = duration_ms
                else:
                    skill.avg_duration_ms = skill.avg_duration_ms * 0.9 + duration_ms * 0.1
                await self._repo.update(skill)
        except Exception:
            logger.debug("Skill 使用统计更新失败（不影响主流程）")

    async def count(self, tenant_id: str) -> int:
        return await self._repo.count(tenant_id=tenant_id)

    async def search(self, query: str, tenant_id: str, limit: int = 20) -> list[Skill]:
        """模糊搜索 Skill（按名称和描述）。"""
        stmt = (
            select(Skill)
            .where(
                Skill.tenant_id == tenant_id,
                not Skill.is_deleted,
                Skill.status.in_([SkillStatus.ACTIVE.value, SkillStatus.PUBLISHED.value]),
                (Skill.name.ilike(f"%{query}%")) | (Skill.description.ilike(f"%{query}%")),
            )
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
