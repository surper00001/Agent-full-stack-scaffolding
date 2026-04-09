"""
租户服务层。

处理多租户相关的业务逻辑。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import TenantNotFoundError
from src.db.repository import BaseRepository
from src.models.domain.tenant import Tenant


class TenantService:
    """租户业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = BaseRepository[Tenant](Tenant, session)

    async def create_tenant(
        self, name: str, slug: str, description: str | None = None
    ) -> Tenant:
        """创建新租户。"""
        tenant = Tenant(name=name, slug=slug, description=description)
        return await self._repo.create(tenant)

    async def get_tenant(self, tenant_id: str) -> Tenant:
        """按 ID 获取租户。"""
        tenant = await self._repo.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(tenant_id)
        return tenant

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """按唯一标识符获取租户。"""
        results = await self._repo.list_all(slug=slug, limit=1)
        return results[0] if results else None

    async def list_tenants(
        self, skip: int = 0, limit: int = 100
    ) -> list[Tenant]:
        """获取租户列表。"""
        return await self._repo.list_all(skip=skip, limit=limit)

    async def update_tenant(
        self, tenant_id: str, **updates: str | bool | None
    ) -> Tenant:
        """更新租户信息。"""
        tenant = await self.get_tenant(tenant_id)
        for field, value in updates.items():
            if value is not None and hasattr(tenant, field):
                setattr(tenant, field, value)
        return await self._repo.update(tenant)

    async def delete_tenant(self, tenant_id: str) -> bool:
        """软删除租户。"""
        return await self._repo.soft_delete(tenant_id)
