#!/usr/bin/env python3
"""Make the PBX engine's Asterisk NAT-aware when it runs in a container.

Standard library only, run on the PBX itself after deploy/pbx/install.sh:

    python3 pbx_nat.py --url https://localhost --insecure \
        --root-password '...' --public-ip 203.0.113.10 \
        --local-net 10.250.0.0/24 --rtp-range 10000-20000

The container only knows its private address. Phones and softphones on the
Internet must be told the public one, otherwise SIP and SDP carry the private
address and the audio never arrives. This sets, through the engine's
configuration API (so the change survives upgrades and regenerations):

- on every SIP transport: ``external_media_address`` and
  ``external_signaling_address`` to the public IP, ``local_net`` to the
  container's network (traffic to those addresses is not rewritten);
- the RTP port range, which the host must redirect to the container.

Transports cannot be reloaded live by Asterisk; the script restarts it, which
cuts calls in progress, so run it right after the installation. Re-runnable.
"""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

AUTH = "/api/auth/0.1"
CONFD = "/api/confd/1.1"


class Api:
    def __init__(self, url: str, insecure: bool):
        self.url = url.rstrip("/")
        self.context = ssl._create_unverified_context() if insecure else None  # noqa: S323
        self.token: str | None = None

    def call(self, method: str, path: str, body=None, *, basic=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        if basic:
            raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
            request.add_header("Authorization", f"Basic {raw}")
        if self.token:
            request.add_header("X-Auth-Token", self.token)
        try:
            with urllib.request.urlopen(
                request, context=self.context, timeout=30
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            sys.exit(f"Erreur {error.code} sur {method} {path} : {detail}")
        return json.loads(payload) if payload else None


def with_options(
    options: list[list[str]], wanted: dict[str, list[str]]
) -> list[list[str]]:
    """Return ``options`` with the ``wanted`` keys replaced (multi-valued keys allowed)."""
    kept = [opt for opt in options if opt[0] not in wanted]
    for key, values in wanted.items():
        kept.extend([key, value] for value in values)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--insecure", action="store_true", help="certificat autosigné")
    parser.add_argument("--root-user", default="root")
    parser.add_argument("--root-password", required=True)
    parser.add_argument("--public-ip", required=True)
    parser.add_argument("--local-net", action="append", default=[], help="répétable")
    parser.add_argument("--rtp-range", default="10000-20000")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    start, end = args.rtp_range.split("-", 1)
    api = Api(args.url, args.insecure)
    token = api.call(
        "POST",
        AUTH + "/token",
        {"expiration": 600},
        basic=(args.root_user, args.root_password),
    )
    api.token = token["data"]["token"]

    wanted = {
        "external_media_address": [args.public_ip],
        "external_signaling_address": [args.public_ip],
    }
    if args.local_net:
        wanted["local_net"] = args.local_net

    changed = 0
    transports = api.call("GET", CONFD + "/sip/transports")["items"]
    for transport in transports:
        options = with_options(transport["options"], wanted)
        if options != transport["options"]:
            api.call(
                "PUT",
                CONFD + f"/sip/transports/{transport['uuid']}",
                {"name": transport["name"], "options": options},
            )
            changed += 1
        print(
            f"transport {transport['name']}: {'mis à jour' if options != transport['options'] else 'déjà à jour'}"
        )

    rtp = api.call("GET", CONFD + "/asterisk/rtp/general")
    options = dict(rtp.get("options") or {})
    if options.get("rtpstart") != start or options.get("rtpend") != end:
        options.update({"rtpstart": start, "rtpend": end})
        api.call("PUT", CONFD + "/asterisk/rtp/general", {"options": options})
        changed += 1
        print(f"rtp: {start}-{end} appliqué")
    else:
        print(f"rtp: {start}-{end} déjà en place")

    if changed and not args.no_restart:
        print("Redémarrage d'Asterisk (les transports ne se rechargent pas à chaud)…")
        subprocess.run(["systemctl", "restart", "asterisk"], check=True)
    print(f"{changed} changement(s)")


if __name__ == "__main__":
    main()
