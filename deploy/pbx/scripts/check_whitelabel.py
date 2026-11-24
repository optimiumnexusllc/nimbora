#!/usr/bin/env python3
"""Look for residual mentions of the PBX engine in what users and phones see.

The kit (whitelabel.yml) brands the e-mails, the SIP headers and the pages of
the PBX; an engine update can bring the original name back. Run on the PBX
host after every package update (APT hook installed by install.sh) and weekly:

  - page d'accueil : body and headers of the PBX's web page;
  - SIP : User-Agent and Server headers of the answer to an OPTIONS request;
  - e-mails : the auth service's sender names and templates, as the last
    file of /etc/wazo-auth/conf.d defines them, and the kit's file present;
  - interface du moteur : its web UI must not be installed.

Exit 0 when nothing is found, 1 when mentions are found, 2 when a check could
not run (PBX silent, page unreachable). Writes nimbora_pbx_whitelabel.prom for
the node exporter's textfile collector (Prometheus alerts in
deploy/observability). Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

WORDS = ("wazo", "asterisk")
AUTH_KEYS = (
    "password_reset_from_name",
    "password_reset_email_template",
    "password_reset_email_subject_template",
    "email_confirmation_from_name",
    "email_confirmation_template",
    "email_confirmation_subject_template",
    "email_confirmation_get_response_body_template",
)
HTTP_HEADERS = ("Server", "X-Powered-By")
KIT_AUTH_FILE = "50-whitelabel.yml"


class Report:
    def __init__(self, words: tuple[str, ...]):
        self.pattern = re.compile("|".join(map(re.escape, words)), re.IGNORECASE)
        self.mentions: list[str] = []
        self.errors: list[str] = []

    def scan(self, where: str, text: str) -> None:
        match = self.pattern.search(text or "")
        if match:
            start = max(match.start() - 30, 0)
            excerpt = " ".join(text[start : match.end() + 30].split())
            self.mentions.append(f"{where} : « {excerpt} »")

    def missing(self, where: str) -> None:
        self.mentions.append(where)

    def error(self, where: str) -> None:
        self.errors.append(where)


def check_page(report: Report, url: str) -> None:
    context = ssl.create_default_context()
    if urllib.parse.urlparse(url).hostname in ("127.0.0.1", "localhost"):
        # The PBX's own certificate may not name localhost.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=10, context=context) as response:
            body = response.read(200_000).decode("utf-8", "replace")
            headers = response.headers
    except Exception as error:  # noqa: BLE001 — any failure is reported
        report.error(f"page d'accueil injoignable ({url}) : {error}")
        return
    report.scan("page d'accueil", body)
    for name in HTTP_HEADERS:
        if headers.get(name):
            report.scan(f"en-tête HTTP {name}", headers[name])


def check_sip(report: Report, target: str, timeout: float) -> None:
    host, _, port = target.rpartition(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, int(port)))
        local_host, local_port = sock.getsockname()
        branch = "z9hG4bK" + uuid.uuid4().hex[:16]
        request = (
            f"OPTIONS sip:{host}:{port} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {local_host}:{local_port};branch={branch};rport\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:whitelabel-check@{local_host}>;tag={uuid.uuid4().hex[:8]}\r\n"
            f"To: <sip:{host}:{port}>\r\n"
            f"Call-ID: {uuid.uuid4().hex}@{local_host}\r\n"
            "CSeq: 1 OPTIONS\r\n"
            f"Contact: <sip:whitelabel-check@{local_host}:{local_port}>\r\n"
            "Accept: application/sdp\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        sock.send(request.encode())
        answer = sock.recv(65535).decode("utf-8", "replace")
    except OSError as error:
        report.error(f"SIP : pas de réponse à OPTIONS sur {target} ({error})")
        return
    finally:
        sock.close()
    for line in answer.split("\r\n"):
        name, _, value = line.partition(":")
        if name.strip().lower() in ("user-agent", "server"):
            label = "User-Agent" if name.strip().lower() == "user-agent" else "Server"
            report.scan(f"SIP {label}", value.strip())


def auth_settings(conf_dir: Path) -> dict[str, tuple[str, str]]:
    """Effective value of each setting: the last file (in name order) wins."""
    settings: dict[str, tuple[str, str]] = {}
    for path in sorted(glob.glob(str(conf_dir / "*.yml"))):
        for line in Path(path).read_text(errors="replace").splitlines():
            match = re.match(r"^([a-z_]+)\s*:\s*(.*?)\s*$", line)
            if match and match.group(1) in AUTH_KEYS:
                value = match.group(2).strip().strip("\"'")
                settings[match.group(1)] = (value, Path(path).name)
    return settings


def check_emails(report: Report, conf_dir: Path) -> None:
    if not (conf_dir / KIT_AUTH_FILE).exists():
        report.missing(
            f"e-mails : {conf_dir / KIT_AUTH_FILE} introuvable (relancer whitelabel.yml)"
        )
    for key, (value, source) in sorted(auth_settings(conf_dir).items()):
        if key.endswith("_template"):
            template = Path(value)
            if not template.is_file():
                report.missing(f"e-mails : {key} → {value} introuvable ({source})")
                continue
            report.scan(
                f"e-mails : {template.name} ({key})",
                template.read_text(errors="replace"),
            )
        else:
            report.scan(f"e-mails : {key} ({source})", value)


def check_engine_ui(report: Report) -> None:
    try:
        status = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", "wazo-ui"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except FileNotFoundError:
        return
    if "install ok installed" in status:
        report.missing("interface du moteur : le paquet wazo-ui est installé")


def write_metrics(report: Report, textfile_dir: Path) -> None:
    if not textfile_dir.is_dir():
        return
    target = textfile_dir / "nimbora_pbx_whitelabel.prom"
    lines = []
    for name, value in (
        ("nimbora_pbx_whitelabel_residual_mentions", len(report.mentions)),
        ("nimbora_pbx_whitelabel_check_errors", len(report.errors)),
        ("nimbora_pbx_whitelabel_last_check_timestamp_seconds", int(time.time())),
    ):
        lines += [f"# TYPE {name} gauge", f"{name} {value}"]
    temporary = target.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n")
    os.chmod(temporary, 0o644)  # the exporter (user prometheus) reads it
    temporary.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="https://127.0.0.1/")
    parser.add_argument("--sip", default="127.0.0.1:5060", help="host:port (UDP)")
    parser.add_argument("--sip-timeout", type=float, default=5.0)
    parser.add_argument(
        "--auth-conf-dir", type=Path, default=Path("/etc/wazo-auth/conf.d")
    )
    parser.add_argument(
        "--textfile-dir", type=Path, default=Path("/var/lib/prometheus/node-exporter")
    )
    parser.add_argument("--words", default=",".join(WORDS), help="comma-separated")
    args = parser.parse_args()

    report = Report(tuple(w.strip() for w in args.words.split(",") if w.strip()))
    check_page(report, args.url)
    check_sip(report, args.sip, args.sip_timeout)
    check_emails(report, args.auth_conf_dir)
    check_engine_ui(report)
    write_metrics(report, args.textfile_dir)

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for line in report.mentions:
        print(f"[{stamp}] MENTION  {line}")
    for line in report.errors:
        print(f"[{stamp}] ERREUR   {line}")
    if report.errors:
        return 2
    if report.mentions:
        print(
            f"[{stamp}] {len(report.mentions)} mention(s) du moteur : relancez le kit "
            "(install.sh) ou whitelabel.yml après la mise à jour."
        )
        return 1
    print(f"[{stamp}] Aucune mention du moteur (pages, SIP, e-mails, interface).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
