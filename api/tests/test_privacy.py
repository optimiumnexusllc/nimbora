"""GDPR / PCI: redaction, in-call masking, erasure, export, retention."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import update

from api.db.models import WorkflowRunModel
from api.services.privacy import service as privacy
from api.services.privacy.redaction import (
    iban_valid,
    luhn_valid,
    nir_valid,
    redact_text,
    redact_value,
)


def _nir() -> str:
    body = "1850578006084"
    return f"1 85 05 78 006 084 {97 - int(body) % 97:02d}"


# ------------------------------------------------------------- detectors


def test_validators():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")
    assert iban_valid("FR76 3000 6000 0112 3456 7890 189")
    assert not iban_valid("FR76 3000 6000 0112 3456 7890 188")
    assert nir_valid(_nir()) and not nir_valid("1 85 05 78 006 084 00")


@pytest.mark.parametrize(
    ("text", "expected", "counts"),
    [
        (
            "Ma carte est 4111 1111 1111 1111 et le cryptogramme 123",
            "Ma carte est [CARD] et le cryptogramme [CVV]",
            {"card": 1, "cvv": 1},
        ),
        ("IBAN FR7630006000011234567890189 merci", "IBAN [IBAN] merci", {"iban": 1}),
        ("mon mail jean.dupont@gmail.com", "mon mail [EMAIL]", {"email": 1}),
        (
            "c'est jean point dupont arobase gmail point com",
            "c'est [EMAIL]",
            {"email": 1},
        ),
        ("rappelez au +227 90 12 34 56", "rappelez au [PHONE]", {"phone": 1}),
        ("au 06 12 34 56 78 svp", "au [PHONE] svp", {"phone": 1}),
        (f"numéro de sécu {_nir()}", "numéro de sécu [SSN]", {"ssn": 1}),
        ("SSN 123-45-6789", "SSN [SSN]", {"ssn": 1}),
        ("serveur 192.168.1.20", "serveur [IP]", {"ip": 1}),
    ],
)
def test_redaction_masks_personal_data(text, expected, counts):
    result = redact_text(text)
    assert result.text == expected
    assert result.counts == counts


@pytest.mark.parametrize(
    "text",
    [
        "Commande numéro 1234567890123",  # order number, not a phone
        "Carte 4111111111111112",  # fails Luhn
        "Rendez-vous le 21/11/2026 à 10h30",
        "Je veux 3 billets à 45 euros",
        "Facture 12345678",
        "IBAN FR7630006000011234567890188",  # bad checksum
    ],
)
def test_redaction_leaves_ordinary_numbers(text):
    assert redact_text(text).text == text


def test_categories_and_nested_values():
    text = "carte 4111111111111111, mail a@b.io"
    assert redact_text(text, ["email"]).text == "carte 4111111111111111, mail [EMAIL]"
    from collections import Counter

    counts = Counter()
    value = redact_value(
        {"events": [{"text": text}], "provider": "a@b.io"},
        counts=counts,
        skip_keys=frozenset({"provider"}),
    )
    assert value["events"][0]["text"] == "carte [CARD], mail [EMAIL]"
    assert value["provider"] == "a@b.io"
    assert counts == {"card": 1, "email": 1}


def test_settings_validation():
    with pytest.raises(ValidationError):
        privacy.PrivacySettings(categories=["card", "passport"])
    with pytest.raises(ValidationError):
        privacy.PrivacySettings(recording_retention_days=0)
    settings = privacy.PrivacySettings(categories=["card", "card", "email"])
    assert settings.categories == ["card", "email"]
    assert privacy.PrivacySettings().conversation_categories == ()
    assert (
        "card"
        in privacy.PrivacySettings(mask_in_conversation=True).conversation_categories
    )


def test_run_logs_redaction_is_idempotent():
    settings = privacy.PrivacySettings(redaction_enabled=True)
    logs = {
        "realtime_feedback_events": [
            {"type": "user", "payload": {"text": "ma carte 4111 1111 1111 1111"}}
        ],
        "telephony_status_callbacks": [{"from": "+33612345678"}],
    }
    redacted, counts = privacy.redact_run_logs(logs, settings)
    assert counts == {"card": 1}
    assert (
        redacted["realtime_feedback_events"][0]["payload"]["text"] == "ma carte [CARD]"
    )
    # Technical telephony data is untouched; second pass is a no-op.
    assert redacted["telephony_status_callbacks"] == logs["telephony_status_callbacks"]
    again, counts = privacy.redact_run_logs(redacted, settings)
    assert again is redacted and counts == {}
    # Off: untouched.
    off, _ = privacy.redact_run_logs(logs, privacy.PrivacySettings())
    assert off is logs


def test_gathered_context_redaction_only_when_asked():
    gathered = {"email_client": "a@b.io", "call_disposition": "ok", "provider": "x"}
    on = privacy.PrivacySettings(redaction_enabled=True)
    assert privacy.redact_gathered_context(gathered, on) == gathered
    both = privacy.PrivacySettings(redaction_enabled=True, redact_extracted_data=True)
    assert privacy.redact_gathered_context(gathered, both)["email_client"] == "[EMAIL]"


def test_log_patcher_masks_messages():
    record = {"message": "Transcription: [ma carte 4111 1111 1111 1111]"}
    privacy.redact_log_record(record)
    assert record["message"] == "Transcription: [ma carte [CARD]]"


async def test_stt_output_is_masked_before_anyone_sees_it():
    from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame

    from api.services.pipecat.processors.pii_masking import mask_stt_output

    pushed = []

    class FakeSTT:
        async def push_frame(self, frame, direction=None):
            pushed.append(frame.text)

    stt = FakeSTT()
    mask_stt_output(
        stt, privacy.PrivacySettings(mask_in_conversation=True).conversation_categories
    )
    mask_stt_output(stt, ["card"])  # idempotent
    await stt.push_frame(
        TranscriptionFrame("c'est 4111 1111 1111 1111 code de sécurité 123", "u", "t")
    )
    await stt.push_frame(InterimTranscriptionFrame("4111 1111 1111 1111", "u", "t"))
    # E-mails are not PCI data: the agent still gets them.
    await stt.push_frame(TranscriptionFrame("mail a@b.io", "u", "t"))
    assert pushed == ["c'est [CARD] code de sécurité [CVV]", "[CARD]", "mail a@b.io"]


# --------------------------------------------------------------- database


async def _new_org(db):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    return user, org


class FakeStorage:
    def __init__(self):
        self.deleted = []

    async def adelete_file(self, key):
        self.deleted.append(key)
        return True


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    import api.services.storage as storage_module

    monkeypatch.setattr(storage_module, "get_storage_for_backend", lambda _b: fake)
    return fake


async def _run(db, user, workflow, *, phone, created_at=None, **fields):
    run = await db.create_workflow_run(
        name=f"WR-{uuid.uuid4().hex[:4]}",
        workflow_id=workflow.id,
        mode="twilio",
        user_id=user.id,
        organization_id=workflow.organization_id,
        initial_context={
            "direction": "inbound",
            "caller_number": phone,
            "provider": "twilio",
        },
        gathered_context={"customer_name": "Awa", "call_disposition": "ok"},
        logs={"realtime_feedback_events": [{"payload": {"text": "bonjour"}}]},
    )
    await db.update_workflow_run(
        run_id=run.id,
        recording_url=f"recordings/{run.id}.wav",
        transcript_url=f"transcripts/{run.id}.txt",
        storage_backend="minio",
        extra={
            "recordings": {
                "user": {"storage_key": f"recordings/{run.id}/user.wav"},
            }
        },
        is_completed=True,
        **fields,
    )
    if created_at is not None:
        async with db.async_session() as session:
            await session.execute(
                update(WorkflowRunModel)
                .where(WorkflowRunModel.id == run.id)
                .values(created_at=created_at)
            )
            await session.commit()
    return run


async def test_erasure_removes_everything_for_one_number_only(db_session, storage):
    user, org = await _new_org(db_session)
    other_user, other_org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "A", {"nodes": [], "edges": []}, user.id, org.id
    )
    other_wf = await db_session.create_workflow(
        "B", {"nodes": [], "edges": []}, other_user.id, other_org.id
    )
    target = await _run(db_session, user, workflow, phone="+33 6 12 34 56 78")
    keep = await _run(db_session, user, workflow, phone="+22790000001")
    foreign = await _run(db_session, other_user, other_wf, phone="+33612345678")
    profile = await db_session.get_or_create_customer_profile(
        org.id, "+33612345678", "612345678"
    )
    await db_session.create_call_handoff(
        organization_id=org.id,
        caller_number="0612345678",
        status="pending",
        collected_data={},
        transcript=[],
        summary_status="skipped",
    )
    await db_session.create_callback_request(
        organization_id=org.id,
        phone="+33612345678",
        source="manual",
        assign_to="human",
        status="pending",
        scheduled_at=datetime.now(UTC),
    )

    request = await privacy.erase_subject(
        org.id, "06 12 34 56 78", requested_by=user.id
    )
    assert request.status == "done"
    assert request.counts == {
        "files": 3,
        "calls": 1,
        "customer_profiles": 1,
        "handoffs": 1,
        "callbacks": 1,
    }
    # The register never holds the number in clear.
    assert "612345678" not in request.subject_hash and request.subject_hint.endswith(
        "678"
    )

    erased = await db_session.get_workflow_run_by_id(target.id)
    assert erased.recording_url is None and erased.transcript_url is None
    assert erased.initial_context == {
        "direction": "inbound",
        "provider": "twilio",
        "privacy_erased": True,
    }
    assert "customer_name" not in erased.gathered_context
    assert "realtime_feedback_events" not in erased.logs
    assert "recordings" not in erased.extra
    assert sorted(storage.deleted) == sorted(
        [
            f"recordings/{target.id}.wav",
            f"recordings/{target.id}/user.wav",
            f"transcripts/{target.id}.txt",
        ]
    )
    assert await db_session.get_customer_profile(org.id, profile.id) is None
    # Other number and other organization untouched.
    assert (await db_session.get_workflow_run_by_id(keep.id)).recording_url
    assert (await db_session.get_workflow_run_by_id(foreign.id)).recording_url


async def test_export_lists_what_is_held(db_session, storage):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "A", {"nodes": [], "edges": []}, user.id, org.id
    )
    await _run(db_session, user, workflow, phone="+22790123456")
    profile = await db_session.get_or_create_customer_profile(
        org.id, "+22790123456", "790123456"
    )
    await db_session.record_customer_interaction(
        org.id, profile.id, workflow_run_id=None, fields={"summary": "Suivi commande"}
    )
    data = await privacy.export_subject(org.id, "+227 90 12 34 56")
    assert data["summary"]["calls"] == 1 and data["summary"]["customer_profiles"] == 1
    assert data["calls"][0]["recording_kept"] is True
    assert data["calls"][0]["collected_data"]["customer_name"] == "Awa"
    assert (
        data["customer_profiles"][0]["interactions"][0]["summary"] == "Suivi commande"
    )
    register = await db_session.list_privacy_requests(org.id)
    assert [r.kind for r in register] == ["export"]
    with pytest.raises(ValueError):
        await privacy.export_subject(org.id, "12")


async def test_retention_purges_old_artifacts_once(db_session, storage):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "A", {"nodes": [], "edges": []}, user.id, org.id
    )
    now = datetime.now(UTC)
    old = await _run(
        db_session,
        user,
        workflow,
        phone="+22790000002",
        created_at=now - timedelta(days=40),
    )
    recent = await _run(
        db_session,
        user,
        workflow,
        phone="+22790000003",
        created_at=now - timedelta(days=5),
    )
    settings = privacy.PrivacySettings(
        recording_retention_days=30, transcript_retention_days=30
    )
    counts = await privacy.apply_retention(org.id, settings, now)
    assert counts == {"files": 3, "recordings": 1, "transcripts": 1}
    purged = await db_session.get_workflow_run_by_id(old.id)
    assert purged.recording_url is None and purged.transcript_url is None
    assert "realtime_feedback_events" not in purged.logs
    assert purged.extra["privacy"]["recording_purged_at"]
    # Call metadata stays (billing, statistics).
    assert purged.initial_context["caller_number"] == "+22790000002"
    assert (await db_session.get_workflow_run_by_id(recent.id)).recording_url
    assert await privacy.apply_retention(org.id, settings, now) == {}


async def test_completed_run_privacy_pass(db_session):
    user, org = await _new_org(db_session)
    workflow = await db_session.create_workflow(
        "A", {"nodes": [], "edges": []}, user.id, org.id
    )
    run = await db_session.create_workflow_run(
        name="WR-chat",
        workflow_id=workflow.id,
        mode="chat",
        user_id=user.id,
        organization_id=org.id,
        gathered_context={"email": "a@b.io"},
        logs={"realtime_feedback_events": [{"payload": {"text": "a@b.io"}}]},
    )
    assert not await privacy.apply_privacy_to_completed_run(run, org.id)
    await privacy.save_privacy_settings(
        org.id,
        privacy.PrivacySettings(redaction_enabled=True, redact_extracted_data=True),
    )
    assert await privacy.apply_privacy_to_completed_run(run, org.id)
    stored = await db_session.get_workflow_run_by_id(run.id)
    assert stored.logs["realtime_feedback_events"][0]["payload"]["text"] == "[EMAIL]"
    assert stored.gathered_context["email"] == "[EMAIL]"
    assert stored.logs["privacy"]["redacted"] is True


async def test_privacy_routes(db_session, test_client_factory, storage):
    user, org = await _new_org(db_session)
    other_user, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        settings = (await client.get("/api/v1/privacy/settings")).json()
        assert settings["redaction_enabled"] is False
        assert "card" in settings["available_categories"]
        saved = await client.put(
            "/api/v1/privacy/settings",
            json={
                "redaction_enabled": True,
                "categories": ["card", "email"],
                "mask_in_conversation": True,
                "store_recordings": False,
                "recording_retention_days": 30,
            },
        )
        assert saved.status_code == 200 and saved.json()["store_recordings"] is False
        assert (
            await client.put("/api/v1/privacy/settings", json={"categories": ["dna"]})
        ).status_code == 422
        preview = (
            await client.post(
                "/api/v1/privacy/preview",
                json={"text": "4111 1111 1111 1111 / a@b.io", "categories": ["card"]},
            )
        ).json()
        assert preview == {"text": "[CARD] / a@b.io", "counts": {"card": 1}}
        erased = await client.post(
            "/api/v1/privacy/erasure", json={"phone": "+33612345678"}
        )
        assert erased.status_code == 200 and erased.json()["kind"] == "erasure"
        assert (
            await client.post("/api/v1/privacy/erasure", json={"phone": "abcdefg"})
        ).status_code == 400
        exported = await client.post(
            "/api/v1/privacy/export", json={"phone": "+33612345678"}
        )
        assert exported.json()["summary"]["calls"] == 0
        register = (await client.get("/api/v1/privacy/requests")).json()
        assert [r["kind"] for r in register] == ["export", "erasure"]
    assert (await privacy.get_privacy_settings(org.id)).recording_retention_days == 30
    async with test_client_factory(other_user) as client:
        assert (await client.get("/api/v1/privacy/requests")).json() == []
        assert (await client.get("/api/v1/privacy/settings")).json()[
            "redaction_enabled"
        ] is False


async def test_customer_memory_retention(db_session):
    from api.db.models import CustomerInteractionModel, CustomerProfileModel

    _, org = await _new_org(db_session)
    now = datetime.now(UTC)
    stale = await db_session.get_or_create_customer_profile(
        org.id, "+22790000010", "790000010"
    )
    active = await db_session.get_or_create_customer_profile(
        org.id, "+22790000011", "790000011"
    )
    await db_session.record_customer_interaction(
        org.id, active.id, workflow_run_id=None, fields={"summary": "ancien"}
    )
    async with db_session.async_session() as session:
        await session.execute(
            update(CustomerProfileModel)
            .where(CustomerProfileModel.id == stale.id)
            .values(last_seen_at=now - timedelta(days=400))
        )
        await session.execute(
            update(CustomerInteractionModel)
            .where(CustomerInteractionModel.customer_id == active.id)
            .values(created_at=now - timedelta(days=400))
        )
        await session.commit()
    counts = await privacy.apply_retention(
        org.id, privacy.PrivacySettings(customer_memory_retention_days=365), now
    )
    assert counts == {"interactions": 1, "customer_profiles": 1}
    assert await db_session.get_customer_profile(org.id, stale.id) is None
    assert await db_session.get_customer_profile(org.id, active.id) is not None
