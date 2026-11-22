"""Subscriptions, plan limits and call authorization for SaaS operator mode.

The rules in one place:

* every organization gets a subscription on the default plan the first time it
  is seen, starting with a trial of ``SAAS_TRIAL_DAYS``;
* a call may start only while the subscription is usable (active, in trial, or
  past due within the grace period) and the period's minutes are not used up
  (unless the plan bills overage);
* the plan's concurrent-call limit is mirrored into the existing per-org
  ``CONCURRENT_CALL_LIMIT`` setting, which the call-concurrency service already
  enforces for every call source.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from api.constants import (
    SAAS_DEFAULT_PLAN,
    SAAS_GRACE_DAYS,
    SAAS_MODE,
    SAAS_TRIAL_DAYS,
)
from api.db import db_client
from api.db.models import OrganizationSubscriptionModel, SubscriptionPlanModel
from api.enums import OrganizationConfigurationKey
from api.services.saas.plans import DEFAULT_PLANS, LIMIT_FIELDS

USABLE_STATUSES = {"trialing", "active", "past_due"}


@dataclass(frozen=True)
class CallAuthorization:
    allowed: bool
    error_code: str = ""
    error_message: str = ""
    status_code: int = 402


@dataclass
class UsageSummary:
    organization_id: int
    plan_code: str
    plan_name: str
    status: str
    period_start: datetime
    period_end: datetime
    trial_ends_at: datetime | None
    used_minutes: float
    included_minutes: int | None
    remaining_minutes: float | None
    overage_minutes: float
    estimated_overage_cents: int
    # Human calls on the enterprise PBX (services/pbx/billing).
    human_used_minutes: float = 0.0
    human_included_minutes: int | None = None
    human_remaining_minutes: float | None = None
    human_overage_minutes: float = 0.0
    estimated_human_overage_cents: int = 0
    limits: dict[str, Any] = field(default_factory=dict)
    features: dict[str, bool] = field(default_factory=dict)
    usable: bool = True
    blocked_reason: str | None = None


def utcnow() -> datetime:
    return datetime.now(UTC)


def add_months(moment: datetime, months: int) -> datetime:
    """Same day-of-month ``months`` later, clamped to the month's last day."""
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def roll_period_forward(
    start: datetime, end: datetime, now: datetime
) -> tuple[datetime, datetime]:
    """Advance a monthly billing period until it contains ``now``."""
    # Guard against corrupted rows that would loop forever.
    for _ in range(1200):
        if now < end:
            return start, end
        start, end = end, add_months(end, 1)
    return start, end


def effective_limits(
    plan: SubscriptionPlanModel, overrides: dict | None = None
) -> dict[str, Any]:
    limits = {name: getattr(plan, name) for name in LIMIT_FIELDS}
    for name, value in (overrides or {}).items():
        if name in LIMIT_FIELDS:
            limits[name] = value
    return limits


def effective_features(
    plan: SubscriptionPlanModel, overrides: dict | None = None
) -> dict[str, bool]:
    features = dict(plan.features or {})
    features.update((overrides or {}).get("features") or {})
    return {name: bool(value) for name, value in features.items()}


async def ensure_default_plans() -> None:
    for code, fields in DEFAULT_PLANS.items():
        await db_client.insert_subscription_plan_if_missing(code, fields)


async def _default_plan() -> SubscriptionPlanModel:
    plan = await db_client.get_subscription_plan_by_code(SAAS_DEFAULT_PLAN)
    if plan is None:
        await ensure_default_plans()
        plan = await db_client.get_subscription_plan_by_code(SAAS_DEFAULT_PLAN)
    if plan is None:
        raise RuntimeError(
            f"SAAS_DEFAULT_PLAN={SAAS_DEFAULT_PLAN!r} does not name an existing plan"
        )
    return plan


async def ensure_organization_subscription(
    organization_id: int,
    *,
    billing_email: str | None = None,
    now: datetime | None = None,
) -> OrganizationSubscriptionModel:
    subscription = await db_client.get_organization_subscription(organization_id)
    if subscription is not None:
        return subscription
    now = now or utcnow()
    plan = await _default_plan()
    trial_ends_at = now + timedelta(days=SAAS_TRIAL_DAYS) if SAAS_TRIAL_DAYS else None
    subscription = await db_client.create_organization_subscription_if_missing(
        organization_id=organization_id,
        plan_id=plan.id,
        status="trialing" if trial_ends_at else "active",
        current_period_start=now,
        current_period_end=add_months(now, 1),
        trial_ends_at=trial_ends_at,
        billing_email=billing_email,
    )
    await sync_concurrency_limit(organization_id, subscription)
    logger.info(
        "Created {} subscription on plan {} for organization {}",
        subscription.status,
        plan.code,
        organization_id,
    )
    return subscription


async def sync_concurrency_limit(
    organization_id: int, subscription: OrganizationSubscriptionModel
) -> None:
    """Mirror the plan's concurrent-call limit into the org setting."""
    limit = effective_limits(subscription.plan, subscription.limit_overrides).get(
        "max_concurrent_calls"
    )
    key = OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
    if limit is None:
        # Unlimited plan: leave the deployment default (or an explicit setting).
        return
    await db_client.upsert_configuration(organization_id, key, {"value": int(limit)})


async def _current_period(
    subscription: OrganizationSubscriptionModel, now: datetime
) -> tuple[datetime, datetime]:
    """The billing period containing ``now``; persists a roll-forward.

    Stripe-managed subscriptions get their period from webhooks, so only
    locally billed ones are rolled here.
    """
    start, end = subscription.current_period_start, subscription.current_period_end
    if subscription.stripe_subscription_id or now < end:
        return start, end
    start, end = roll_period_forward(start, end, now)
    await db_client.update_organization_subscription(
        subscription.organization_id,
        {"current_period_start": start, "current_period_end": end},
    )
    return start, end


def _blocked_reason(
    subscription: OrganizationSubscriptionModel, now: datetime
) -> tuple[str, str] | None:
    status = subscription.status
    if status not in USABLE_STATUSES:
        return (
            f"subscription_{status}",
            "Your subscription is not active. Please contact your administrator "
            "or renew your plan to place calls.",
        )
    if (
        status == "trialing"
        and subscription.trial_ends_at is not None
        and now >= subscription.trial_ends_at
        and not subscription.stripe_subscription_id
    ):
        return (
            "trial_expired",
            "Your free trial has ended. Choose a plan to keep placing calls.",
        )
    if status == "past_due":
        since = subscription.past_due_since or subscription.updated_at or now
        if now >= since + timedelta(days=SAAS_GRACE_DAYS):
            return (
                "payment_overdue",
                "Your last payment failed and the grace period is over. "
                "Please update your payment method.",
            )
    return None


async def get_usage_summary(
    organization_id: int, *, now: datetime | None = None
) -> UsageSummary:
    now = now or utcnow()
    subscription = await ensure_organization_subscription(organization_id, now=now)
    plan = subscription.plan
    start, end = await _current_period(subscription, now)
    used_seconds = await db_client.get_organization_billable_seconds(
        organization_id, start, end
    )
    used_minutes = round(used_seconds / 60.0, 2)
    limits = effective_limits(plan, subscription.limit_overrides)
    included = limits.get("included_minutes")
    remaining = None if included is None else max(0.0, included - used_minutes)
    overage = 0.0 if included is None else max(0.0, used_minutes - included)
    overage_cents = int(round(overage * (plan.overage_price_cents_per_minute or 0)))
    human_seconds = await db_client.get_organization_human_seconds(
        organization_id, start, end
    )
    human_used = round(human_seconds / 60.0, 2)
    human_included = limits.get("included_human_minutes")
    human_remaining = (
        None if human_included is None else max(0.0, human_included - human_used)
    )
    human_overage = (
        0.0 if human_included is None else max(0.0, human_used - human_included)
    )
    blocked = _blocked_reason(subscription, now)
    return UsageSummary(
        organization_id=organization_id,
        plan_code=plan.code,
        plan_name=plan.name,
        status=subscription.status,
        period_start=start,
        period_end=end,
        trial_ends_at=subscription.trial_ends_at,
        used_minutes=used_minutes,
        included_minutes=included,
        remaining_minutes=remaining,
        overage_minutes=round(overage, 2),
        estimated_overage_cents=overage_cents,
        human_used_minutes=human_used,
        human_included_minutes=human_included,
        human_remaining_minutes=human_remaining,
        human_overage_minutes=round(human_overage, 2),
        estimated_human_overage_cents=int(
            round(human_overage * (plan.human_overage_price_cents_per_minute or 0))
        ),
        limits=limits,
        features=effective_features(plan, subscription.limit_overrides),
        usable=blocked is None,
        blocked_reason=blocked[0] if blocked else None,
    )


async def authorize_call(
    organization_id: int, *, now: datetime | None = None
) -> CallAuthorization:
    """Whether the organization's subscription allows starting a call now."""
    now = now or utcnow()
    summary = await get_usage_summary(organization_id, now=now)
    subscription = await db_client.get_organization_subscription(organization_id)
    if subscription is not None:
        blocked = _blocked_reason(subscription, now)
        if blocked:
            return CallAuthorization(False, blocked[0], blocked[1])
    included = summary.included_minutes
    allows_overage = bool(
        subscription is not None
        and subscription.plan.overage_price_cents_per_minute
        and summary.status == "active"
    )
    if included is not None and summary.used_minutes >= included and not allows_overage:
        return CallAuthorization(
            False,
            "minutes_exhausted",
            "All minutes included in your plan for this period are used. "
            "Upgrade your plan or wait for the next period.",
        )
    return CallAuthorization(True)


async def check_feature(organization_id: int, feature: str) -> bool:
    if not SAAS_MODE:
        return True
    subscription = await ensure_organization_subscription(organization_id)
    return effective_features(subscription.plan, subscription.limit_overrides).get(
        feature, False
    )


async def check_limit(
    organization_id: int, limit_name: str, current_count: int
) -> str | None:
    """Error message when creating one more resource would exceed the plan."""
    if not SAAS_MODE:
        return None
    subscription = await ensure_organization_subscription(organization_id)
    limit = effective_limits(subscription.plan, subscription.limit_overrides).get(
        limit_name
    )
    if limit is not None and current_count >= limit:
        return (
            f"Your plan ({subscription.plan.name}) allows {limit} for "
            f"'{limit_name}'. Upgrade your plan to add more."
        )
    return None


async def change_plan(
    organization_id: int,
    plan: SubscriptionPlanModel,
    *,
    status: str | None = None,
    now: datetime | None = None,
) -> OrganizationSubscriptionModel:
    """Move an organization to ``plan`` (admin action or Stripe webhook)."""
    now = now or utcnow()
    subscription = await ensure_organization_subscription(organization_id, now=now)
    fields: dict[str, Any] = {"plan_id": plan.id}
    if status:
        fields["status"] = status
        if status != "past_due":
            fields["past_due_since"] = None
    updated = await db_client.update_organization_subscription(organization_id, fields)
    assert updated is not None
    await sync_concurrency_limit(organization_id, updated)
    logger.info(
        "Organization {} moved from plan {} to {}",
        organization_id,
        subscription.plan.code,
        plan.code,
    )
    return updated
