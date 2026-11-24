"""Residual mentions of the PBX engine (deploy/pbx/scripts/check_whitelabel.py).

Run for real against a fake PBX: a web server (landing page and headers), a
SIP responder on UDP (OPTIONS → User-Agent / Server), the auth service's
configuration and e-mail templates, and a stub dpkg-query (engine web UI).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2]
CHECK = DEPLOY / "pbx" / "scripts" / "check_whitelabel.py"
INSTALL = DEPLOY / "pbx" / "install.sh"
ALERTS = DEPLOY / "observability" / "prometheus" / "alerts.yml"


class FakePbx:
    def __init__(self, tmp: Path):
        self.page = "<html><title>NIMBORA Voice</title></html>"
        self.http_headers = {"Server": "nginx"}
        self.sip_user_agent = "NIMBORA-Voice"
        self.sip_answers = True
        self.ui_installed = False
        self.auth = tmp / "wazo-auth"
        self.templates = tmp / "templates"
        self.auth.mkdir()
        self.templates.mkdir()
        for name in ("password_reset_email.jinja", "email_confirmation.jinja"):
            (self.templates / name).write_text(
                "Bonjour, votre mot de passe NIMBORA Voice."
            )
        (self.auth / "50-whitelabel.yml").write_text(
            f'password_reset_from_name: "NIMBORA Voice"\n'
            f"password_reset_email_template: {self.templates}/password_reset_email.jinja\n"
            f'email_confirmation_from_name: "NIMBORA Voice"\n'
            f"email_confirmation_template: {self.templates}/email_confirmation.jinja\n"
        )
        self.bin = tmp / "bin"
        self.bin.mkdir()
        dpkg = self.bin / "dpkg-query"
        dpkg.write_text(
            '#!/bin/sh\n[ -f "$UI_INSTALLED" ] && printf "install ok installed" && exit 0\nexit 1\n'
        )
        dpkg.chmod(0o755)
        self.ui_flag = tmp / "ui-installed"
        self.textfile = tmp / "textfile"
        self.textfile.mkdir()

    # ---------------------------------------------------------------- servers
    def start(self):
        pbx = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = pbx.page.encode()
                self.send_response(200)
                for key, value in pbx.http_headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def version_string(self):
                return pbx.http_headers.get("Server", "nginx")

            def log_message(self, *args):
                pass

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

        self.sip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sip.bind(("127.0.0.1", 0))
        self.sip.settimeout(0.2)
        self.running = True

        def serve_sip():
            while self.running:
                try:
                    data, addr = self.sip.recvfrom(4096)
                except OSError:
                    continue
                if not self.sip_answers:
                    continue
                request = data.decode()
                via = next(
                    line for line in request.split("\r\n") if line.startswith("Via:")
                )
                call_id = next(
                    line
                    for line in request.split("\r\n")
                    if line.startswith("Call-ID:")
                )
                reply = (
                    "SIP/2.0 200 OK\r\n"
                    f"{via}\r\n{call_id}\r\n"
                    f"Server: {self.sip_user_agent}\r\n"
                    f"User-Agent: {self.sip_user_agent}\r\n"
                    "Content-Length: 0\r\n\r\n"
                )
                self.sip.sendto(reply.encode(), addr)

        threading.Thread(target=serve_sip, daemon=True).start()
        return self

    def stop(self):
        self.running = False
        self.http.shutdown()
        self.sip.close()

    # ------------------------------------------------------------------- run
    def check(self, *extra: str) -> subprocess.CompletedProcess:
        if self.ui_installed:
            self.ui_flag.write_text("1")
        elif self.ui_flag.exists():
            self.ui_flag.unlink()
        return subprocess.run(
            [
                sys.executable,
                str(CHECK),
                "--url",
                f"http://127.0.0.1:{self.http.server_port}/",
                "--sip",
                f"127.0.0.1:{self.sip.getsockname()[1]}",
                "--auth-conf-dir",
                str(self.auth),
                "--textfile-dir",
                str(self.textfile),
                "--sip-timeout",
                "1",
                *extra,
            ],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "UI_INSTALLED": str(self.ui_flag),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def metrics(self) -> dict[str, float]:
        text = (self.textfile / "nimbora_pbx_whitelabel.prom").read_text()
        return {
            line.split()[0]: float(line.split()[1])
            for line in text.splitlines()
            if line and not line.startswith("#")
        }


@pytest.fixture
def pbx(tmp_path):
    fake = FakePbx(tmp_path).start()
    yield fake
    fake.stop()


def test_a_white_labelled_pbx_passes(pbx):
    result = pbx.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "aucune mention" in result.stdout.lower()
    metrics = pbx.metrics()
    assert metrics["nimbora_pbx_whitelabel_residual_mentions"] == 0
    assert metrics["nimbora_pbx_whitelabel_check_errors"] == 0
    assert metrics["nimbora_pbx_whitelabel_last_check_timestamp_seconds"] > 0
    mode = (pbx.textfile / "nimbora_pbx_whitelabel.prom").stat().st_mode & 0o777
    assert mode == 0o644  # read by the node exporter


def test_every_residual_mention_is_reported(pbx):
    """What an engine update can bring back, one finding each."""
    pbx.page = "<html>Welcome to Wazo Platform</html>"
    pbx.http_headers = {"Server": "nginx", "X-Powered-By": "wazo-ui"}
    pbx.sip_user_agent = "Wazo PBX"
    pbx.ui_installed = True
    (pbx.templates / "email_confirmation.jinja").write_text("Confirm your Wazo account")
    (pbx.auth / "60-upgrade.yml").write_text(
        'password_reset_from_name: "Wazo Platform"\n'
    )
    result = pbx.check()
    assert result.returncode == 1
    report = result.stdout
    for where in (
        "page d'accueil",
        "X-Powered-By",
        "SIP User-Agent",
        "SIP Server",
        "email_confirmation.jinja",
        "password_reset_from_name",
        "wazo-ui",
    ):
        assert where in report, where
    assert pbx.metrics()["nimbora_pbx_whitelabel_residual_mentions"] == 7


def test_the_auth_setting_that_wins_is_the_last_file(pbx):
    """conf.d files are read in order: a later file overrides the kit's."""
    (pbx.auth / "10-defaults.yml").write_text('password_reset_from_name: "Wazo"\n')
    result = pbx.check()
    assert result.returncode == 0, result.stdout
    (pbx.auth / "90-local.yml").write_text('password_reset_from_name: "Wazo"\n')
    assert pbx.check().returncode == 1


def test_missing_kit_configuration_and_template_are_findings(pbx):
    (pbx.templates / "password_reset_email.jinja").unlink()
    result = pbx.check()
    assert result.returncode == 1
    assert "introuvable" in result.stdout
    (pbx.auth / "50-whitelabel.yml").unlink()
    result = pbx.check()
    assert "50-whitelabel.yml" in result.stdout


def test_a_silent_pbx_is_an_error_not_a_pass(pbx):
    pbx.sip_answers = False
    result = pbx.check()
    assert result.returncode == 2
    assert "SIP" in result.stdout
    metrics = pbx.metrics()
    assert metrics["nimbora_pbx_whitelabel_check_errors"] == 1
    assert metrics["nimbora_pbx_whitelabel_residual_mentions"] == 0


def test_kit_runs_it_after_every_package_update_and_weekly():
    script = INSTALL.read_text()
    assert "apply_whitelabel_check" in script
    assert "/etc/apt/apt.conf.d/99nimbora-whitelabel-check" in script
    assert "DPkg::Post-Invoke" in script
    # Delayed: services restart after an upgrade.
    assert "systemd-run --quiet --collect --on-active=5min" in script
    assert "/etc/cron.d/nimbora-pbx-whitelabel-check" in script


def test_prometheus_alerts_on_mentions_and_on_a_stale_check():
    alerts = ALERTS.read_text()
    assert "nimbora_pbx_whitelabel_residual_mentions > 0" in alerts
    assert "nimbora_pbx_whitelabel_check_errors > 0" in alerts
    assert "nimbora_pbx_whitelabel_last_check_timestamp_seconds" in alerts
