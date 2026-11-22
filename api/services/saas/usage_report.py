"""Monthly usage of every company, AI and human minutes, for invoicing.

The subscription page of a company shows its own billing period; the
operator's report uses calendar months so every company is invoiced on the
same dates. Included minutes of the plan (with the company's overrides) apply
to each month.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from api.db import db_client
from api.services.saas.subscription_service import effective_limits


@dataclass
class UsageLine:
    organization_id: int
    company_name: str
    billing_email: str
    plan_code: str
    currency: str
    ai_minutes: float
    ai_included_minutes: int | None
    ai_overage_minutes: float
    ai_overage_cents: int
    human_minutes: float
    human_included_minutes: int | None
    human_overage_minutes: float
    human_overage_cents: int
    total_overage_cents: int


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """'2026-11' → [2026-11-01, 2026-12-01) in UTC."""
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("Mois attendu au format AAAA-MM") from error
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return start, end


def _overage(used: float, included: int | None, price: int | None) -> tuple[float, int]:
    if included is None:
        return 0.0, 0
    minutes = max(0.0, used - included)
    return round(minutes, 2), round(minutes * (price or 0))


async def monthly_usage(month: str) -> list[UsageLine]:
    start, end = month_bounds(month)
    usage = await db_client.get_usage_by_organization(start, end)
    subscriptions, _ = await db_client.list_organization_subscriptions(limit=100000)
    lines: list[UsageLine] = []
    for subscription in subscriptions:
        seconds = usage.get(subscription.organization_id, {"ai": 0.0, "human": 0.0})
        plan = subscription.plan
        limits = effective_limits(plan, subscription.limit_overrides)
        ai = round(seconds["ai"] / 60.0, 2)
        human = round(seconds["human"] / 60.0, 2)
        ai_over, ai_cents = _overage(
            ai, limits.get("included_minutes"), plan.overage_price_cents_per_minute
        )
        human_over, human_cents = _overage(
            human,
            limits.get("included_human_minutes"),
            plan.human_overage_price_cents_per_minute,
        )
        lines.append(
            UsageLine(
                organization_id=subscription.organization_id,
                company_name=subscription.company_name or "",
                billing_email=subscription.billing_email or "",
                plan_code=plan.code,
                currency=plan.currency,
                ai_minutes=ai,
                ai_included_minutes=limits.get("included_minutes"),
                ai_overage_minutes=ai_over,
                ai_overage_cents=ai_cents,
                human_minutes=human,
                human_included_minutes=limits.get("included_human_minutes"),
                human_overage_minutes=human_over,
                human_overage_cents=human_cents,
                total_overage_cents=ai_cents + human_cents,
            )
        )
    # Overages first, then the biggest users: the invoices to prepare first.
    lines.sort(
        key=lambda line: (
            -line.total_overage_cents,
            -(line.ai_minutes + line.human_minutes),
            line.organization_id,
        )
    )
    return lines


def to_csv(lines: list[UsageLine]) -> str:
    out = io.StringIO()
    fields = list(UsageLine.__dataclass_fields__)
    writer = csv.DictWriter(out, fieldnames=fields, delimiter=";")
    writer.writeheader()
    for line in lines:
        writer.writerow({k: ("" if v is None else v) for k, v in asdict(line).items()})
    return out.getvalue()
