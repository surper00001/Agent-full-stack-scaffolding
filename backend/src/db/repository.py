"""
通用 Repository 模式实现。

提供标准的 CRUD 操作封装，所有数据访问均通过 Repository，
便于单元测试 mock 和业务逻辑与持久化解耦。
"""

from typing import Any, Generic, TypeVar

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """泛型基础 Repository，提供通用 CRUD 操作。"""

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    # ---- 查询 ----

    async def get_by_id(self, id_: str) -> ModelType | None:
        """按主键 ID 查询单条记录。"""
        return await self._session.get(self._model, id_)

    async def get_by_id_with_tenant(
        self, id_: str, tenant_id: str
    ) -> ModelType | None:
        """按主键 ID 和租户 ID 查询（多租户安全查询）。"""
        stmt = select(self._model).where(
            and_(
                self._model.id == id_,  # type: ignore[attr-defined]
                self._model.tenant_id == tenant_id,  # type: ignore[attr-defined]
                self._model.is_deleted == False,  # noqa: E712  # type: ignore[attr-defined]
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        tenant_id: str | None = None,
        skip: int = 0,
        limit: int = 100,
        **filters: Any,
    ) -> list[ModelType]:
        """分页查询列表，支持按租户过滤和自定义条件。"""
        conditions = [self._model.is_deleted == False]  # noqa: E712  # type: ignore[attr-defined]
        if tenant_id is not None:
            conditions.append(self._model.tenant_id == tenant_id)
        for field, value in filters.items():
            if hasattr(self._model, field) and value is not None:
                conditions.append(getattr(self._model, field) == value)

        stmt = (
            select(self._model)
            .where(and_(*conditions))
            .offset(skip)
            .limit(limit)
            .order_by(self._model.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, tenant_id: str | None = None, **filters: Any) -> int:
        """统计符合条件的记录数。"""
        conditions = [self._model.is_deleted == False]  # noqa: E712  # type: ignore[attr-defined]
        if tenant_id is not None:
            conditions.append(self._model.tenant_id == tenant_id)
        for field, value in filters.items():
            if hasattr(self._model, field) and value is not None:
                conditions.append(getattr(self._model, field) == value)

        stmt = select(func.count()).select_from(self._model).where(and_(*conditions))
        result = await self._session.execute(stmt)
        return result.scalar_one()

    # ---- 写入 ----

    async def create(self, instance: ModelType) -> ModelType:
        """新增记录。"""
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def update(self, instance: ModelType) -> ModelType:
        """更新记录。"""
        await self._session.flush()
        return instance

    async def soft_delete(self, id_: str) -> bool:
        """软删除（标记 is_deleted=True）。"""
        instance = await self.get_by_id(id_)
        if instance is None:
            return False
        instance.is_deleted = True  # type: ignore[attr-defined]
        await self._session.flush()
        return True

    async def hard_delete(self, id_: str) -> bool:
        """物理删除（谨慎使用）。"""
        instance = await self.get_by_id(id_)
        if instance is None:
            return False
        await self._session.delete(instance)
        await self._session.flush()
        return True

    async def hard_delete_by_filter(
        self, tenant_id: str | None = None, **filters: Any
    ) -> int:
        """按条件物理删除（不区分 is_deleted）。"""
        conditions: list[Any] = []
        if tenant_id is not None:
            conditions.append(self._model.tenant_id == tenant_id)
        for field, value in filters.items():
            if hasattr(self._model, field) and value is not None:
                conditions.append(getattr(self._model, field) == value)
        if not conditions:
            return 0
        stmt = delete(self._model).where(and_(*conditions))
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def soft_delete_by_filter(
        self, tenant_id: str | None = None, **filters: Any
    ) -> int:
        """按条件软删除。"""
        conditions: list[Any] = [self._model.is_deleted == False]  # noqa: E712
        if tenant_id is not None:
            conditions.append(self._model.tenant_id == tenant_id)
        for field, value in filters.items():
            if hasattr(self._model, field) and value is not None:
                conditions.append(getattr(self._model, field) == value)
        if len(conditions) <= 1 and tenant_id is None and not filters:
            return 0
        stmt = (
            update(self._model)
            .where(and_(*conditions))
            .values(is_deleted=True)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)
