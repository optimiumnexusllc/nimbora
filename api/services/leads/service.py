"""Leads: qualify prospects during calls, follow them through the pipeline.

The agent's « Qualifier le prospect » tool records what the caller says: the
need, the budget, the timeline, whether they decide, what interests them. Each
answer adds to a **score** out of 100; past the tool's threshold the lead moves
to « Qualifié » by itself. The tool answers with what is still unknown, so the
agent asks the next useful question instead of a form.

Stages: Nouveau → Qualifié → Proposition → Négociation → Gagné / Perdu.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from api.services.catalog.service import decimals, format_price, to_minor

STAGES = ("new", "qualified", "proposal", "negotiation", "won", "lost")
STAGE_LABELS = {
    "new": "Nouveau",
    "qualified": "Qualifié",
    "proposal": "Proposition",
    "negotiation": "Négociation",
    "won": "Gagné",
    "lost": "Perdu",
}
CLOSED = {"won", "lost"}
SOURCES = ("call", "whatsapp", "web", "manual", "import")
Stage = Literal["new", "qualified", "proposal", "negotiation", "won", "lost"]

# What each answer is worth (out of 100).
WEIGHTS = {
    "need": 25,
    "budget": 25,
    "timeline": 20,
    "decision_maker": 15,
    "contact": 10,
    "interests": 5,
}
QUESTIONS = {
    "need": "what they need exactly",
    "budget": "their budget",
    "timeline": "when they want it",
    "decision_maker": "whether they decide alone or with someone",
    "contact": "their name or e-mail",
}


def known(lead: dict[str, Any]) -> dict[str, bool]:
    return {
        "need": bool((lead.get("need") or "").strip()),
        "budget": lead.get("budget_max") is not None
        or lead.get("budget_min") is not None,
        "timeline": bool((lead.get("timeline") or "").strip()),
        "decision_maker": lead.get("decision_maker") is not None,
        "contact": bool(lead.get("name") or lead.get("email")),
        "interests": bool(lead.get("interests")),
    }


def score_of(lead: dict[str, Any]) -> int:
    """Out of 100; someone who decides counts fully, someone who does not half."""
    facts = known(lead)
    score = sum(WEIGHTS[k] for k, v in facts.items() if v and k != "decision_maker")
    if lead.get("decision_maker") is True:
        score += WEIGHTS["decision_maker"]
    elif lead.get("decision_maker") is False:
        score += WEIGHTS["decision_maker"] // 2
    return min(score, 100)


def lead_out(lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "company": lead.company,
        "need": lead.need,
        "budget_min": _major(lead.budget_min, lead.currency),
        "budget_max": _major(lead.budget_max, lead.currency),
        "budget_text": budget_text(lead.budget_min, lead.budget_max, lead.currency),
        "currency": lead.currency,
        "timeline": lead.timeline,
        "decision_maker": lead.decision_maker,
        "interests": lead.interests or [],
        "stage": lead.stage,
        "stage_label": STAGE_LABELS.get(lead.stage, lead.stage),
        "score": lead.score,
        "source": lead.source,
        "owner": lead.owner,
        "notes": lead.notes,
        "lost_reason": lead.lost_reason,
        "next_action": lead.next_action,
        "next_action_at": lead.next_action_at.isoformat()
        if lead.next_action_at
        else None,
        "customer_id": lead.customer_id,
        "workflow_run_id": lead.workflow_run_id,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "closed_at": lead.closed_at.isoformat() if lead.closed_at else None,
    }


def _major(minor: int | None, currency: str) -> float | None:
    if minor is None:
        return None
    return float(Decimal(minor) / (10 ** decimals(currency)))


def budget_text(low: int | None, high: int | None, currency: str) -> str | None:
    if low is None and high is None:
        return None
    if low is not None and high is not None and low != high:
        return f"{format_price(low, currency)} à {format_price(high, currency)}"
    if high is not None:
        return (
            f"jusqu'à {format_price(high, currency)}"
            if low is None
            else format_price(high, currency)
        )
    return f"à partir de {format_price(low, currency)}"


class LeadIn(BaseModel):
    """A lead as the team edits it in the console."""

    name: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=128)
    need: str | None = Field(default=None, max_length=4000)
    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="XOF", pattern=r"^[A-Z]{3}$")
    timeline: str | None = Field(default=None, max_length=128)
    decision_maker: bool | None = None
    interests: list[str] = Field(default_factory=list, max_length=20)
    stage: Stage = "new"
    owner: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=8000)
    lost_reason: str | None = Field(default=None, max_length=255)
    next_action: str | None = Field(default=None, max_length=255)
    next_action_at: datetime | None = None

    @field_validator(
        "name",
        "phone",
        "email",
        "company",
        "need",
        "timeline",
        "owner",
        "notes",
        "lost_reason",
        "next_action",
    )
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    def fields(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"budget_min", "budget_max"})
        data["budget_min"] = (
            to_minor(self.budget_min, self.currency)
            if self.budget_min is not None
            else None
        )
        data["budget_max"] = (
            to_minor(self.budget_max, self.currency)
            if self.budget_max is not None
            else None
        )
        data["interests"] = [i.strip()[:120] for i in self.interests if i.strip()]
        if (
            data["budget_min"] is not None
            and data["budget_max"] is not None
            and data["budget_min"] > data["budget_max"]
        ):
            data["budget_min"], data["budget_max"] = (
                data["budget_max"],
                data["budget_min"],
            )
        data["score"] = score_of(data)
        return data


def _closing(stage: str, previous: str | None) -> dict[str, Any]:
    if stage in CLOSED and previous not in CLOSED:
        return {"closed_at": datetime.now(UTC)}
    if stage not in CLOSED and previous in CLOSED:
        return {"closed_at": None}
    return {}


async def create_lead(
    organization_id: int, spec: LeadIn, source: str = "manual"
) -> dict[str, Any]:
    from api.db import db_client

    fields = {**spec.fields(), "source": source, **_closing(spec.stage, None)}
    return lead_out(await db_client.create_lead(organization_id, fields))


async def update_lead(
    organization_id: int, lead_id: int, spec: LeadIn
) -> dict[str, Any]:
    from api.db import db_client

    current = await db_client.get_lead(organization_id, lead_id)
    if current is None:
        raise LookupError("Prospect introuvable")
    fields = {**spec.fields(), **_closing(spec.stage, current.stage)}
    return lead_out(await db_client.update_lead(organization_id, lead_id, fields))


async def move_lead(
    organization_id: int, lead_id: int, stage: str, lost_reason: str | None = None
) -> dict[str, Any]:
    from api.db import db_client

    if stage not in STAGES:
        raise ValueError("Étape inconnue")
    current = await db_client.get_lead(organization_id, lead_id)
    if current is None:
        raise LookupError("Prospect introuvable")
    fields: dict[str, Any] = {"stage": stage, **_closing(stage, current.stage)}
    if stage == "lost":
        fields["lost_reason"] = (lost_reason or "").strip()[:255] or current.lost_reason
    return lead_out(await db_client.update_lead(organization_id, lead_id, fields))


async def pipeline(organization_id: int) -> list[dict[str, Any]]:
    """Every stage, in order, with its count and budgets (per currency)."""
    from api.db import db_client

    rows = await db_client.lead_pipeline(organization_id)
    result = []
    for stage in STAGES:
        mine = [r for r in rows if r["stage"] == stage]
        result.append(
            {
                "stage": stage,
                "label": STAGE_LABELS[stage],
                "count": sum(r["count"] for r in mine),
                "budgets": [
                    {
                        "currency": r["currency"],
                        "total": _major(r["budget"], r["currency"]),
                        "text": format_price(r["budget"], r["currency"]),
                    }
                    for r in mine
                    if r["budget"]
                ],
            }
        )
    return result


async def export_csv(organization_id: int) -> str:
    from api.db import db_client

    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "id",
            "nom",
            "telephone",
            "email",
            "societe",
            "besoin",
            "budget",
            "echeance",
            "decideur",
            "interets",
            "etape",
            "score",
            "source",
            "responsable",
            "prochaine action",
            "cree le",
        ]
    )
    for lead in await db_client.list_leads(organization_id, limit=100_000):
        row = lead_out(lead)
        writer.writerow(
            [
                row["id"],
                row["name"] or "",
                row["phone"] or "",
                row["email"] or "",
                row["company"] or "",
                row["need"] or "",
                row["budget_text"] or "",
                row["timeline"] or "",
                {True: "oui", False: "non"}.get(row["decision_maker"], ""),
                "|".join(row["interests"]),
                row["stage_label"],
                row["score"],
                row["source"],
                row["owner"] or "",
                row["next_action"] or "",
                (row["created_at"] or "")[:10],
            ]
        )
    return out.getvalue()


# ------------------------------------------------------------- the agent


def _source(ctx) -> str:
    channel = str((ctx.initial_context or {}).get("channel") or "").lower()
    if channel in {"whatsapp", "web"}:
        return channel
    return "call"


async def handle_lead(
    ctx, config: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    """Save what the caller said about their project; merge with their open lead."""
    from api.db import db_client

    currency = config.get("currency") or "XOF"
    threshold = int(config.get("qualified_score") or 60)

    def money(name: str) -> int | None:
        value = args.get(name)
        if value in (None, ""):
            return None
        try:
            return to_minor(value, currency)
        except ValueError:
            return None

    update: dict[str, Any] = {}
    for key in ("need", "timeline", "name", "email", "company"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            update[key] = value.strip()[: 4000 if key == "need" else 255]
    if args.get("decision_maker") is not None:
        update["decision_maker"] = bool(args["decision_maker"])
    low, high = money("budget_min"), money("budget_max")
    if low is not None:
        update["budget_min"] = low
    if high is not None:
        update["budget_max"] = high
    interests = args.get("interests")
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",")]
    note = (args.get("notes") or "").strip()

    phone = ctx.caller_phone
    lead = (
        await db_client.find_open_lead_by_phone(ctx.organization_id, phone)
        if phone
        else None
    )
    if lead is None and ctx.workflow_run_id:
        same_call = [
            x
            for x in await db_client.list_leads(ctx.organization_id, limit=50)
            if x.workflow_run_id == ctx.workflow_run_id
        ]
        lead = same_call[0] if same_call else None

    merged: dict[str, Any] = {}
    if lead is not None:
        merged = {
            k: getattr(lead, k)
            for k in (
                "name",
                "email",
                "company",
                "need",
                "budget_min",
                "budget_max",
                "timeline",
                "decision_maker",
                "interests",
                "stage",
                "notes",
            )
        }
    merged.update(update)
    if interests:
        merged["interests"] = list(
            dict.fromkeys(
                [*(merged.get("interests") or []), *[i[:120] for i in interests if i]]
            )
        )[:20]
    if note:
        stamp = ctx.now.strftime("%d/%m %H:%M")
        merged["notes"] = (
            f"{merged.get('notes')}\n" if merged.get("notes") else ""
        ) + f"[{stamp}] {note[:1000]}"
    merged["score"] = score_of(merged)
    stage = merged.get("stage") or "new"
    if stage == "new" and merged["score"] >= threshold:
        stage = "qualified"
    merged["stage"] = stage
    merged["currency"] = getattr(lead, "currency", None) or currency
    merged["workflow_run_id"] = ctx.workflow_run_id or getattr(
        lead, "workflow_run_id", None
    )

    if lead is None:
        customer = None
        if phone:
            from api.services.customer_memory.service import phone_suffix

            customer = await db_client.find_customer_profile(
                ctx.organization_id, phone, phone_suffix(phone)
            )
        merged.update(
            {
                "phone": phone,
                "source": _source(ctx),
                "customer_id": customer.id if customer else None,
                "name": merged.get("name") or ctx.customer_name,
            }
        )
        merged["score"] = score_of(merged)
        saved = await db_client.create_lead(ctx.organization_id, merged)
    else:
        saved = await db_client.update_lead(ctx.organization_id, lead.id, merged)

    facts = known(
        lead_out(saved)
        | {"budget_max": saved.budget_max, "budget_min": saved.budget_min}
    )
    missing = [QUESTIONS[k] for k in QUESTIONS if not facts[k]]
    return {
        "status": "ok",
        "lead_id": saved.id,
        "score": saved.score,
        "stage": STAGE_LABELS[saved.stage],
        "still_unknown": missing,
        "hint": (
            "Ask naturally, one at a time: " + "; ".join(missing)
            if missing
            else "The lead is complete: offer the next step (visit, quote, appointment)."
        ),
    }
