"""Database access for the catalog. Every query is filtered by organization."""

from typing import Any

from sqlalchemy import and_, delete, func, or_
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import CatalogItemModel

CATALOG_FIELDS = {
    "kind",
    "sku",
    "name",
    "description",
    "category",
    "price_cents",
    "currency",
    "unit",
    "stock",
    "available",
    "attributes",
    "tags",
    "url",
    "search_text",
}


class CatalogClient(BaseDBClient):
    async def search_catalog_items(
        self,
        organization_id: int,
        *,
        words: list[str] | None = None,
        kind: str | None = None,
        kinds: list[str] | None = None,
        category: str | None = None,
        min_price_cents: int | None = None,
        max_price_cents: int | None = None,
        available_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogItemModel], int]:
        """``words`` are already folded (lower case, no accents): every word
        must appear in the item's search text."""
        conditions = [CatalogItemModel.organization_id == organization_id]
        for word in words or []:
            conditions.append(CatalogItemModel.search_text.contains(word))
        if kind:
            conditions.append(CatalogItemModel.kind == kind)
        if kinds:
            conditions.append(CatalogItemModel.kind.in_(kinds))
        if category:
            conditions.append(func.lower(CatalogItemModel.category) == category.lower())
        if min_price_cents is not None:
            conditions.append(CatalogItemModel.price_cents >= min_price_cents)
        if max_price_cents is not None:
            conditions.append(CatalogItemModel.price_cents <= max_price_cents)
        if available_only:
            conditions.append(CatalogItemModel.available.is_(True))
            conditions.append(
                or_(CatalogItemModel.stock.is_(None), CatalogItemModel.stock > 0)
            )
        where = and_(*conditions)
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(CatalogItemModel).where(where)
                )
            ).scalar_one()
            rows = (
                await session.execute(
                    select(CatalogItemModel)
                    .where(where)
                    .order_by(
                        CatalogItemModel.category.nulls_last(),
                        CatalogItemModel.name,
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).scalars()
            return list(rows), int(total)

    async def get_catalog_item(
        self, organization_id: int, item_id: int
    ) -> CatalogItemModel | None:
        async with self.async_session() as session:
            return (
                await session.execute(
                    select(CatalogItemModel).where(
                        CatalogItemModel.organization_id == organization_id,
                        CatalogItemModel.id == item_id,
                    )
                )
            ).scalar_one_or_none()

    async def get_catalog_item_by_sku(
        self, organization_id: int, sku: str
    ) -> CatalogItemModel | None:
        async with self.async_session() as session:
            return (
                await session.execute(
                    select(CatalogItemModel).where(
                        CatalogItemModel.organization_id == organization_id,
                        func.lower(CatalogItemModel.sku) == sku.lower(),
                    )
                )
            ).scalar_one_or_none()

    async def create_catalog_item(
        self, organization_id: int, fields: dict[str, Any]
    ) -> CatalogItemModel:
        async with self.async_session() as session:
            item = CatalogItemModel(
                organization_id=organization_id,
                **{k: v for k, v in fields.items() if k in CATALOG_FIELDS},
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def update_catalog_item(
        self, organization_id: int, item_id: int, fields: dict[str, Any]
    ) -> CatalogItemModel | None:
        async with self.async_session() as session:
            item = (
                await session.execute(
                    select(CatalogItemModel).where(
                        CatalogItemModel.organization_id == organization_id,
                        CatalogItemModel.id == item_id,
                    )
                )
            ).scalar_one_or_none()
            if item is None:
                return None
            for key, value in fields.items():
                if key in CATALOG_FIELDS:
                    setattr(item, key, value)
            await session.commit()
            await session.refresh(item)
            return item

    async def delete_catalog_item(self, organization_id: int, item_id: int) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                delete(CatalogItemModel).where(
                    CatalogItemModel.organization_id == organization_id,
                    CatalogItemModel.id == item_id,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def catalog_categories(self, organization_id: int) -> list[str]:
        async with self.async_session() as session:
            rows = await session.execute(
                select(CatalogItemModel.category)
                .where(
                    CatalogItemModel.organization_id == organization_id,
                    CatalogItemModel.category.is_not(None),
                )
                .distinct()
                .order_by(CatalogItemModel.category)
            )
            return [r for r in rows.scalars() if r]
