"""Database access for GDPR features: erasure, export, retention, register.

Every query is filtered by ``organization_id``. Phone matching uses the last
9 digits (the same rule as customer memory), so ``+33 6 12 34 56 78`` and
``0612345678`` are the same person.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    CallbackRequestModel,
    CallHandoffModel,
    CustomerInteractionModel,
    CustomerProfileModel,
    OrganizationConfigurationModel,
    PrivacyRequestModel,
    WorkflowModel,
    WorkflowRunModel,
)

# Where a phone number can appear on a run.
RUN_PHONE_KEYS = (
    "caller_number",
    "called_number",
    "phone_number",
    "from_number",
    "to_number",
)


def _suffix_expr(expression):
    digits = func.regexp_replace(expression, r"\D", "", "g")
    return func.right(digits, 9)


class PrivacyClient(BaseDBClient):
    # ------------------------------------------------------------ register
    async def create_privacy_request(self, **fields: Any) -> PrivacyRequestModel:
        async with self.async_session() as session:
            row = PrivacyRequestModel(**fields)
            session.add(row)
            await session.flush()
            row_id = row.id
            await session.commit()
        return await self.get_privacy_request(fields["organization_id"], row_id)

    async def get_privacy_request(
        self, organization_id: int, request_id: int
    ) -> PrivacyRequestModel | None:
        async with self.async_session() as session:
            result = await session.execute(
                select(PrivacyRequestModel)
                .where(
                    PrivacyRequestModel.organization_id == organization_id,
                    PrivacyRequestModel.id == request_id,
                )
                .execution_options(populate_existing=True)
            )
            return result.scalars().first()

    async def update_privacy_request(
        self, organization_id: int, request_id: int, fields: dict[str, Any]
    ) -> PrivacyRequestModel | None:
        allowed = {"status", "counts", "error", "completed_at"}
        values = {k: v for k, v in fields.items() if k in allowed}
        async with self.async_session() as session:
            await session.execute(
                update(PrivacyRequestModel)
                .where(
                    PrivacyRequestModel.organization_id == organization_id,
                    PrivacyRequestModel.id == request_id,
                )
                .values(**values)
            )
            await session.commit()
        return await self.get_privacy_request(organization_id, request_id)

    async def list_privacy_requests(
        self, organization_id: int, limit: int = 50
    ) -> list[PrivacyRequestModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(PrivacyRequestModel)
                .where(PrivacyRequestModel.organization_id == organization_id)
                .order_by(PrivacyRequestModel.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    # ------------------------------------------------------ subject lookup
    async def list_runs_for_phone_suffix(
        self, organization_id: int, suffix: str, limit: int = 500
    ) -> list[WorkflowRunModel]:
        conditions = [
            _suffix_expr(WorkflowRunModel.initial_context[key].as_string()) == suffix
            for key in RUN_PHONE_KEYS
        ]
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    or_(*conditions),
                )
                .order_by(WorkflowRunModel.created_at.desc())
                .limit(limit)
                .execution_options(populate_existing=True)
            )
            return list(result.scalars().all())

    async def list_customer_profiles_for_suffix(
        self, organization_id: int, suffix: str
    ) -> list[CustomerProfileModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CustomerProfileModel).where(
                    CustomerProfileModel.organization_id == organization_id,
                    CustomerProfileModel.phone_suffix == suffix,
                )
            )
            return list(result.scalars().all())

    async def list_handoffs_for_suffix(
        self, organization_id: int, suffix: str
    ) -> list[CallHandoffModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallHandoffModel).where(
                    CallHandoffModel.organization_id == organization_id,
                    _suffix_expr(CallHandoffModel.caller_number) == suffix,
                )
            )
            return list(result.scalars().all())

    async def list_callbacks_for_suffix(
        self, organization_id: int, suffix: str
    ) -> list[CallbackRequestModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(CallbackRequestModel).where(
                    CallbackRequestModel.organization_id == organization_id,
                    _suffix_expr(CallbackRequestModel.phone) == suffix,
                )
            )
            return list(result.scalars().all())

    async def delete_handoffs_for_suffix(
        self, organization_id: int, suffix: str
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                delete(CallHandoffModel).where(
                    CallHandoffModel.organization_id == organization_id,
                    _suffix_expr(CallHandoffModel.caller_number) == suffix,
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def delete_callbacks_for_suffix(
        self, organization_id: int, suffix: str
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                delete(CallbackRequestModel).where(
                    CallbackRequestModel.organization_id == organization_id,
                    _suffix_expr(CallbackRequestModel.phone) == suffix,
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def scrub_workflow_run(
        self, organization_id: int, run_id: int, fields: dict[str, Any]
    ) -> bool:
        """Overwrite personal fields of a run that belongs to the organization."""
        allowed = {
            "initial_context",
            "gathered_context",
            "logs",
            "annotations",
            "recording_url",
            "transcript_url",
            "extra",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return False
        owned = (
            select(WorkflowModel.id)
            .where(WorkflowModel.organization_id == organization_id)
            .scalar_subquery()
        )
        async with self.async_session() as session:
            result = await session.execute(
                update(WorkflowRunModel)
                .where(
                    WorkflowRunModel.id == run_id,
                    WorkflowRunModel.workflow_id.in_(owned),
                )
                .values(**values)
            )
            await session.commit()
            return bool(result.rowcount)

    # ------------------------------------------------------------ retention
    async def list_runs_with_artifacts_before(
        self,
        organization_id: int,
        before: datetime,
        kind: str,
        limit: int = 200,
    ) -> list[WorkflowRunModel]:
        """Completed runs older than ``before`` still holding ``kind``
        (``recording`` or ``transcript``) and not purged yet."""
        purged_flag = WorkflowRunModel.extra[
            ("privacy", f"{kind}_purged_at")
        ].as_string()
        if kind == "recording":
            holds = or_(
                WorkflowRunModel.recording_url.isnot(None),
                WorkflowRunModel.extra["recordings"].as_string().isnot(None),
            )
        else:
            holds = or_(
                WorkflowRunModel.transcript_url.isnot(None),
                WorkflowRunModel.logs["realtime_feedback_events"]
                .as_string()
                .isnot(None),
            )
        async with self.async_session() as session:
            result = await session.execute(
                select(WorkflowRunModel)
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .where(
                    WorkflowModel.organization_id == organization_id,
                    WorkflowRunModel.created_at < before,
                    WorkflowRunModel.is_completed.is_(True),
                    holds,
                    purged_flag.is_(None),
                )
                .order_by(WorkflowRunModel.created_at.asc())
                .limit(limit)
                .execution_options(populate_existing=True)
            )
            return list(result.scalars().all())

    async def delete_customer_interactions_before(
        self, organization_id: int, before: datetime
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                delete(CustomerInteractionModel).where(
                    CustomerInteractionModel.organization_id == organization_id,
                    CustomerInteractionModel.created_at < before,
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def delete_customer_profiles_inactive_since(
        self, organization_id: int, before: datetime
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                delete(CustomerProfileModel).where(
                    CustomerProfileModel.organization_id == organization_id,
                    and_(
                        CustomerProfileModel.last_seen_at.isnot(None),
                        CustomerProfileModel.last_seen_at < before,
                    ),
                )
            )
            await session.commit()
            return result.rowcount or 0

    async def list_organizations_with_configuration(
        self, key: str
    ) -> list[tuple[int, Any]]:
        """(organization_id, value) for every organization that set ``key``.

        Used only by the background retention sweep.
        """
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    OrganizationConfigurationModel.organization_id,
                    OrganizationConfigurationModel.value,
                ).where(OrganizationConfigurationModel.key == key)
            )
            return [(row[0], row[1]) for row in result.all()]
