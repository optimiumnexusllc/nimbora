"""Bug n°30 (lab, step 23): links the API builds for the browser (invitations,
Stripe return pages, embed links) began with http://localhost:3010 on a real
install. UI_APP_URL was only set by the enterprise compose; like
BACKEND_API_ENDPOINT it now falls back to PUBLIC_BASE_URL, the deployment's
public origin (the interface and the API share it)."""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def ui_app_url(**env: str) -> str:
    clean = {
        k: v
        for k, v in os.environ.items()
        if k not in ("UI_APP_URL", "PUBLIC_BASE_URL")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from api.constants import UI_APP_URL; print(UI_APP_URL)",
        ],
        env={**clean, **env, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_public_installs_link_to_their_public_origin():
    assert (
        ui_app_url(PUBLIC_BASE_URL="https://app.example.com")
        == "https://app.example.com"
    )


def test_an_explicit_ui_app_url_still_wins():
    assert (
        ui_app_url(
            PUBLIC_BASE_URL="https://app.example.com",
            UI_APP_URL="https://console.example.com",
        )
        == "https://console.example.com"
    )


def test_local_development_keeps_localhost():
    assert ui_app_url() == "http://localhost:3010"
