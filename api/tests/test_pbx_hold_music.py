"""The company's music on hold: generated music or its own, and an announcement
spoken with its voice, published as a music-on-hold class of its PBX tenant and
used by its queues and parking lots."""

import io
import wave

import numpy as np
import pytest

from api.services.pbx import hold_music, prompts, teamwork
from api.services.pbx.service import PbxRouteError
from api.tests.pbx_fake import FakePbx
from api.tests.test_pbx_admin import _setup


def _samples(audio: bytes) -> tuple[np.ndarray, int, int, int]:
    with wave.open(io.BytesIO(audio), "rb") as wav:
        frames = wav.readframes(wav.getnframes())
        return (
            np.frombuffer(frames, dtype="<i2"),
            wav.getframerate(),
            wav.getnchannels(),
            wav.getsampwidth(),
        )


def _wav(seconds: float = 1.0, rate: int = 44100, channels: int = 2) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2")
    data = np.repeat(tone, channels) if channels > 1 else tone
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(data.tobytes())
    return out.getvalue()


@pytest.fixture
def spoken(monkeypatch):
    said: list[tuple[int, str, int | None]] = []

    async def fake(organization_id, text, *, voice_workflow_id=None):
        said.append((organization_id, text, voice_workflow_id))
        return prompts.to_pbx_wav(_wav(2.0))

    monkeypatch.setattr(prompts, "synthesize_prompt", fake)
    return said


# ------------------------------------------------------------ generated music


def test_generated_music_is_a_soft_loop_the_pbx_plays_as_is():
    audio = hold_music.generate_music(seconds=30)
    samples, rate, channels, width = _samples(audio)
    assert (rate, channels, width) == (8000, 1, 2)  # what the engine accepts
    assert len(samples) == 30 * 8000
    peak = np.abs(samples).max()
    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
    assert 3000 < peak < 0.6 * 32767  # audible, never harsh on a phone line
    assert rms > 1000
    # Loops without a click: starts and ends near silence.
    assert np.abs(samples[:40]).max() < 400 and np.abs(samples[-40:]).max() < 400
    # Same every time (cached by nobody, but reproducible).
    assert hold_music.generate_music(seconds=30) == audio


def test_announcement_suggested_in_the_company_language():
    assert "patienter" in hold_music.suggested_announcement([])
    assert "patienter" in hold_music.suggested_announcement(["Français", "Anglais"])
    assert "hold" in hold_music.suggested_announcement(["English"])
    assert "espera" in hold_music.suggested_announcement(["espagnol"])
    assert "patienter" in hold_music.suggested_announcement(["Wolof"])


# -------------------------------------------------------------- publication


async def test_company_music_and_announcement_on_its_queues_and_lots(
    db_session, monkeypatch, test_client_factory, spoken
):
    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    lot = await teamwork.create_parking_lot(
        org.id, teamwork.NewParkingLot("Accueil", "700", "701", "720")
    )
    async with test_client_factory(user) as client:
        before = (await client.get("/api/v1/pbx/hold-music")).json()
        published = await client.post(
            "/api/v1/pbx/hold-music",
            data={
                "music": "generated",
                "announcement": "Merci de patienter, Acme vous répond.",
                "voice_workflow_id": "9",
            },
        )
        after = (await client.get("/api/v1/pbx/hold-music")).json()
    assert before["active"] is False
    assert "patienter" in before["suggested_announcement"]
    assert published.status_code == 200, published.text

    (moh,) = fake.mohs
    assert moh["label"] == hold_music.LABEL and moh["mode"] == "files"
    assert moh["sort"] == "alphabetical"
    # Music, then the announcement, in a loop.
    assert sorted(moh["file_data"]) == ["01-musique.wav", "02-annonce.wav"]
    assert spoken == [(org.id, "Merci de patienter, Acme vous répond.", 9)]
    for name in moh["file_data"]:
        _, rate, channels, _ = _samples(moh["file_data"][name])
        assert (rate, channels) == (8000, 1)
    # Every queue and parking lot of the company plays it.
    assert fake.queues and all(q["music_on_hold"] == moh["name"] for q in fake.queues)
    (stored_lot,) = [x for x in fake.parkinglots if x["id"] == lot["id"]]
    assert stored_lot["music_on_hold"] == moh["name"]
    assert stored_lot["slots_start"] == "701"  # PUT resends what it keeps
    assert after == {
        **after,
        "active": True,
        "music": True,
        "announcement": True,
        "queues": len(fake.queues),
        "parking_lots": 1,
    }


async def test_new_queues_and_lots_get_the_company_music(
    db_session, monkeypatch, spoken
):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    await hold_music.publish_hold_music(
        org.id, hold_music.HoldMusicSpec(music="generated", announcement="")
    )
    (moh,) = fake.mohs
    lot = await teamwork.create_parking_lot(
        org.id, teamwork.NewParkingLot("Accueil", "700", "701", "720")
    )
    assert (
        next(x for x in fake.parkinglots if x["id"] == lot["id"])["music_on_hold"]
        == moh["name"]
    )


async def test_own_music_is_converted_and_republishing_replaces_the_files(
    db_session, monkeypatch, spoken
):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    await hold_music.publish_hold_music(
        org.id,
        hold_music.HoldMusicSpec(music="generated", announcement="Bonjour."),
    )
    await hold_music.publish_hold_music(
        org.id,
        hold_music.HoldMusicSpec(
            music="custom", announcement="", custom_music=_wav(3.0, 44100, 2)
        ),
    )
    (moh,) = fake.mohs  # same class, updated
    assert sorted(moh["file_data"]) == ["01-musique.wav"]
    samples, rate, channels, _ = _samples(moh["file_data"]["01-musique.wav"])
    assert (rate, channels) == (8000, 1) and len(samples) == 3 * 8000


async def test_announcement_alone_gets_a_pause_between_repeats(
    db_session, monkeypatch, spoken
):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    await hold_music.publish_hold_music(
        org.id, hold_music.HoldMusicSpec(music="none", announcement="Patientez.")
    )
    (moh,) = fake.mohs
    assert sorted(moh["file_data"]) == ["01-pause.wav", "02-annonce.wav"]
    pause, *_ = _samples(moh["file_data"]["01-pause.wav"])
    assert len(pause) == hold_music.PAUSE_SECONDS * 8000 and not pause.any()


@pytest.mark.parametrize(
    "spec",
    [
        hold_music.HoldMusicSpec(music="none", announcement=""),
        hold_music.HoldMusicSpec(music="custom", announcement=""),
        hold_music.HoldMusicSpec(music="custom", custom_music=b"not a wav"),
    ],
)
async def test_nothing_to_play_or_unreadable_music_is_refused(
    db_session, monkeypatch, spoken, spec
):
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    with pytest.raises(PbxRouteError) as error:
        await hold_music.publish_hold_music(org.id, spec)
    assert error.value.status == 422
    assert fake.mohs == []


async def test_removal_gives_back_the_default_music(
    db_session, monkeypatch, test_client_factory, spoken
):
    fake = FakePbx()
    user, org, _ = await _setup(db_session, monkeypatch, fake)
    await teamwork.create_parking_lot(
        org.id, teamwork.NewParkingLot("Accueil", "700", "701", "720")
    )
    await hold_music.publish_hold_music(
        org.id, hold_music.HoldMusicSpec(music="generated", announcement="")
    )
    async with test_client_factory(user) as client:
        removed = await client.delete("/api/v1/pbx/hold-music")
        state = (await client.get("/api/v1/pbx/hold-music")).json()
    assert removed.status_code == 204
    assert fake.mohs == []
    assert all(q["music_on_hold"] == "default" for q in fake.queues)
    assert all(x["music_on_hold"] == "default" for x in fake.parkinglots)
    assert state["active"] is False


async def test_sample_of_the_generated_music(
    db_session, monkeypatch, test_client_factory
):
    fake = FakePbx()
    user, _, _ = await _setup(db_session, monkeypatch, fake)
    async with test_client_factory(user) as client:
        response = await client.get("/api/v1/pbx/hold-music/sample")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    _, rate, _, _ = _samples(response.content)
    assert rate == 8000


async def test_another_company_class_is_never_touched(db_session, monkeypatch, spoken):
    """The engine lists the tenant's classes; one with our label but another
    tenant's uuid (never expected) would not be reused."""
    fake = FakePbx()
    _, org, _ = await _setup(db_session, monkeypatch, fake)
    fake.mohs.append(
        {
            "uuid": "other",
            "name": "moh_other",
            "label": hold_music.LABEL,
            "tenant_uuid": "another-tenant",
            "mode": "files",
            "sort": "alphabetical",
            "file_data": {"01-musique.wav": b"theirs"},
        }
    )
    await hold_music.publish_hold_music(
        org.id, hold_music.HoldMusicSpec(music="generated", announcement="")
    )
    other = next(m for m in fake.mohs if m["uuid"] == "other")
    assert other["file_data"] == {"01-musique.wav": b"theirs"}
    assert len(fake.mohs) == 2


def test_service_account_may_manage_music_on_hold():
    from api.services.pbx.client import REQUIRED_ACL

    for name, acl in {
        "mohs": "confd.moh.read",
        "create_moh": "confd.moh.create",
        "delete_moh": "confd.moh.{moh_uuid}.delete",
        "upload_moh_file": "confd.moh.{moh_uuid}.files.{filename}.update",
        "delete_moh_file": "confd.moh.{moh_uuid}.files.{filename}.delete",
        "update_parkinglot": "confd.parkinglots.{parkinglot_id}.update",
    }.items():
        assert REQUIRED_ACL[name] == acl
