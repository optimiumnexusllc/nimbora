"""Quality control of human calls: grid, AI evaluation, supervisor review."""

import json
import uuid
from datetime import UTC, datetime

import pytest

from api.services.quality import service as quality
from api.services.quality.service import QualityError, QualitySettings, score_of

TRANSCRIPT = (
    "Bonjour, Agence Horizon, Awa à l'appareil. — Bonjour, je n'ai pas reçu ma "
    "facture. — Si je comprends bien, la facture de novembre ? Je vous la renvoie "
    "par e-mail aujourd'hui. — Merci. — Avec plaisir, bonne journée."
)


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


async def _recording(db, org_id, transcript=TRANSCRIPT, direction="inbound"):
    return await db.create_pbx_recording(
        org_id,
        {
            "cdr_id": 1,
            "recording_uuid": uuid.uuid4().hex,
            "started_at": datetime.now(UTC),
            "duration_seconds": 95,
            "direction": direction,
            "source": "+2250700112233",
            "source_name": "Client",
            "destination": "1002",
            "destination_name": "Awa Koné",
            "customer_phone": "+2250700112233",
            "storage_backend": "s3",
            "storage_key": "k",
            "transcript": transcript,
            "transcript_status": "done" if transcript else "none",
        },
    )


def _reply(**answers):
    return json.dumps(
        {
            "answers": {
                k: {"answer": v, "comment": f"{k} ok"} for k, v in answers.items()
            },
            "summary": "Accueil soigné ; penser à vérifier l'identité.",
        }
    )


def test_the_score_is_the_weighted_share_of_what_applied():
    criteria = [
        {"key": "a", "label": "A", "weight": 1},
        {"key": "b", "label": "B", "weight": 3},
        {"key": "c", "label": "C", "weight": 2},
    ]
    answers = {
        "a": {"answer": "yes"},
        "b": {"answer": "partial"},
        "c": {"answer": "na"},
    }
    assert score_of(criteria, answers) == 62.5  # (1 + 1.5) / 4
    assert score_of(criteria, {"c": {"answer": "na"}}) is None
    assert score_of(criteria, {}) is None


def test_criteria_get_unique_keys_from_their_labels():
    settings = QualitySettings(
        criteria=[{"label": "Écoute active"}, {"label": "Écoute active"}]
    )
    assert [c.key for c in settings.criteria] == ["ecoute_active", "ecoute_active_2"]
    with pytest.raises(ValueError):
        QualitySettings(criteria=[])


async def test_ai_evaluation_then_supervisor_review(
    db_session, monkeypatch, test_client_factory
):
    user, org = await _new_org(db_session)
    recording = await _recording(db_session, org.id)
    prompts = []

    async def infer(organization_id, system, prompt):
        prompts.append(prompt)
        return "Voici : " + _reply(
            accueil="yes",
            ecoute="yes",
            identification="no",
            solution="yes",
            ton="yes",
            conclusion="partial",
            inventé="yes",  # not in the grid: ignored
        )

    monkeypatch.setattr(quality, "_infer", infer)
    async with test_client_factory(user) as client:
        evaluated = await client.post(
            f"/api/v1/quality/recordings/{recording.id}/evaluate"
        )
        body = evaluated.json()
        assert evaluated.status_code == 200, body
        assert body["status"] == "evaluated"
        assert body["agent_extension"] == "1002" and body["agent_name"] == "Awa Koné"
        # weights 1,2,1,3,2,1 → (1+2+0+3+2+0.5)/10
        assert body["ai_score"] == body["score"] == 85.0
        assert [a["answer"] for a in body["ai_answers"]] == [
            "yes",
            "yes",
            "no",
            "yes",
            "yes",
            "partial",
        ]
        assert "Awa à l'appareil" in prompts[0] and "solution — Réponse" in prompts[0]

        reviewed = await client.put(
            f"/api/v1/quality/reviews/{body['id']}",
            json={
                "answers": {
                    "identification": {"answer": "na", "comment": "Simple question"},
                    "conclusion": {"answer": "yes"},
                    "accueil": {"answer": "yes"},
                },
                "comment": "Très bon appel",
            },
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["status"] == "reviewed"
        assert reviewed.json()["score"] == 100.0
        assert reviewed.json()["ai_score"] == 85.0  # kept for comparison

        # A new AI pass never replaces the supervisor's score.
        again = await client.post(f"/api/v1/quality/recordings/{recording.id}/evaluate")
        assert again.json()["status"] == "reviewed" and again.json()["score"] == 100.0

        unknown = await client.put(
            f"/api/v1/quality/reviews/{body['id']}",
            json={"answers": {"inconnu": {"answer": "yes"}}},
        )
        assert unknown.status_code == 422

        summary = (await client.get("/api/v1/quality/summary")).json()
        assert summary["evaluated"] == 1 and summary["average"] == 100.0
        assert summary["agents"][0]["agent_extension"] == "1002"
        assert summary["agents"][0]["reviewed"] == 1
        ident = next(c for c in summary["criteria"] if c["key"] == "identification")
        assert ident["answered"] == 0  # « sans objet » counts nowhere

        listed = (await client.get("/api/v1/quality/reviews?status=reviewed")).json()
        assert listed["total"] == 1 and "transcript" not in listed["items"][0]


async def test_failures_are_kept_and_explained(
    db_session, monkeypatch, test_client_factory
):
    user, org = await _new_org(db_session)
    silent = await _recording(db_session, org.id, transcript=None)
    talking = await _recording(db_session, org.id)

    async def gibberish(*_):
        return "je ne sais pas"

    monkeypatch.setattr(quality, "_infer", gibberish)
    async with test_client_factory(user) as client:
        no_text = await client.post(f"/api/v1/quality/recordings/{silent.id}/evaluate")
        assert (
            no_text.status_code == 409 and "transcription" in no_text.json()["detail"]
        )
        failed = await client.post(f"/api/v1/quality/recordings/{talking.id}/evaluate")
        assert failed.json()["status"] == "failed"
        assert failed.json()["ai_error"] == "Réponse du modèle illisible"

        # Without a transcript a supervisor can still evaluate by ear.
        manual = await client.post(f"/api/v1/quality/recordings/{silent.id}/review")
        assert (
            manual.json()["status"] == "pending" and len(manual.json()["criteria"]) == 6
        )


async def test_grid_and_sampling(db_session, monkeypatch, test_client_factory):
    user, org = await _new_org(db_session)
    async with test_client_factory(user) as client:
        default = (await client.get("/api/v1/quality/settings")).json()
        assert (
            default["criteria"][0]["key"] == "accueil" and not default["auto_evaluate"]
        )
        saved = await client.put(
            "/api/v1/quality/settings",
            json={
                "criteria": [{"label": "Proposer le rendez-vous", "weight": 3}],
                "auto_evaluate": True,
                "sample_percent": 100,
            },
        )
        assert saved.json()["criteria"][0]["key"] == "proposer_le_rendez_vous"

    queued = []

    async def enqueue(name, *args):
        queued.append((name, args))

    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue)
    recording = await _recording(db_session, org.id)
    assert await quality.after_recording_import(org.id, recording) is True
    assert queued == [("evaluate_call_quality", (org.id, recording.id))]
    silent = await _recording(db_session, org.id, transcript=None)
    assert await quality.after_recording_import(org.id, silent) is False


async def test_another_company_sees_nothing(
    db_session, monkeypatch, test_client_factory
):
    _, org = await _new_org(db_session)
    other, _ = await _new_org(db_session)
    recording = await _recording(db_session, org.id)
    review = await quality.start_review(org.id, recording.id)
    async with test_client_factory(other) as client:
        assert (
            await client.get(f"/api/v1/quality/reviews/{review['id']}")
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/quality/recordings/{recording.id}/evaluate")
        ).status_code == 404
        assert (await client.get("/api/v1/quality/reviews")).json()["total"] == 0
    with pytest.raises(QualityError):
        await quality.get_review(org.id + 10_000, review["id"])
