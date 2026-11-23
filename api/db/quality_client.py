"""Database access for the quality control of human calls (per organization)."""

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    CallQualityReviewModel,
    CallQualitySettingsModel,
    PbxCallRecordingModel,
)


class QualityClient(BaseDBClient):
    async def get_quality_settings(
        self, organization_id: int
    ) -> CallQualitySettingsModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallQualitySettingsModel).where(
                    CallQualitySettingsModel.organization_id == organization_id
                )
            )
            return result.scalars().first()

    async def save_quality_settings(
        self, organization_id: int, values: dict[str, Any]
    ) -> CallQualitySettingsModel:
        async with self.async_session() as session:
            row = (
                (
                    await session.execute(
                        select(CallQualitySettingsModel).where(
                            CallQualitySettingsModel.organization_id == organization_id
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = CallQualitySettingsModel(organization_id=organization_id)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_quality_review(
        self, organization_id: int, review_id: int
    ) -> tuple[CallQualityReviewModel, PbxCallRecordingModel] | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallQualityReviewModel, PbxCallRecordingModel)
                .join(
                    PbxCallRecordingModel,
                    PbxCallRecordingModel.id == CallQualityReviewModel.recording_id,
                )
                .where(
                    CallQualityReviewModel.id == review_id,
                    CallQualityReviewModel.organization_id == organization_id,
                )
            )
            row = result.first()
            return (row[0], row[1]) if row else None

    async def get_quality_review_for_recording(
        self, organization_id: int, recording_id: int
    ) -> CallQualityReviewModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallQualityReviewModel).where(
                    CallQualityReviewModel.organization_id == organization_id,
                    CallQualityReviewModel.recording_id == recording_id,
                )
            )
            return result.scalars().first()

    async def upsert_quality_review(
        self, organization_id: int, recording_id: int, values: dict[str, Any]
    ) -> CallQualityReviewModel:
        async with self.async_session() as session:
            row = (
                (
                    await session.execute(
                        select(CallQualityReviewModel).where(
                            CallQualityReviewModel.organization_id == organization_id,
                            CallQualityReviewModel.recording_id == recording_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = CallQualityReviewModel(
                    organization_id=organization_id, recording_id=recording_id
                )
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_quality_reviews(
        self,
        organization_id: int,
        *,
        status: str | None = None,
        agent_extension: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[CallQualityReviewModel, PbxCallRecordingModel]], int]:
        where = [CallQualityReviewModel.organization_id == organization_id]
        if status:
            where.append(CallQualityReviewModel.status == status)
        if agent_extension:
            where.append(CallQualityReviewModel.agent_extension == agent_extension)
        if since:
            where.append(CallQualityReviewModel.created_at >= since)
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count(CallQualityReviewModel.id)).where(*where)
                )
            ).scalar_one()
            result = await session.execute(
                select(CallQualityReviewModel, PbxCallRecordingModel)
                .join(
                    PbxCallRecordingModel,
                    PbxCallRecordingModel.id == CallQualityReviewModel.recording_id,
                )
                .where(*where)
                .order_by(
                    PbxCallRecordingModel.started_at.desc().nulls_last(),
                    CallQualityReviewModel.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
            return [(r[0], r[1]) for r in result.all()], total

    async def quality_by_agent(
        self, organization_id: int, since: datetime
    ) -> list[dict[str, Any]]:
        """Average score and counts per advisor, over the scored reviews."""
        review = CallQualityReviewModel
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    review.agent_extension,
                    func.max(review.agent_name),
                    func.count(review.id),
                    func.avg(review.score),
                    func.count(review.reviewed_at),
                )
                .where(
                    review.organization_id == organization_id,
                    review.created_at >= since,
                    review.score.is_not(None),
                )
                .group_by(review.agent_extension)
            )
            return [
                {
                    "agent_extension": extension,
                    "agent_name": name,
                    "evaluated": count,
                    "average": round(float(average), 1)
                    if average is not None
                    else None,
                    "reviewed": reviewed,
                }
                for extension, name, count, average, reviewed in result.all()
            ]
