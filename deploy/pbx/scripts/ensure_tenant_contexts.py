#!/usr/bin/env python3
"""Give the company's tenant the dialplan contexts the platform needs.

Standard library only, run on the PBX right after the install:

    python3 ensure_tenant_contexts.py --url https://localhost --insecure \
        --root-password '...' --tenant-name 'my-company'

A tenant created with ``wazo-auth-cli`` has no context: the platform then
refuses to create extensions ("Aucun contexte interne sur le PBX"), queues or
numbers. This creates, once, one context of each kind the platform reads by
type (internal, incall, outcall) with the engine's usual numbering ranges, and
lets the internal context reach the outcall one. Re-runnable: existing contexts
of a kind are kept untouched.
"""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

AUTH = "/api/auth/0.1"
CONFD = "/api/confd/1.1"


def desired_contexts(slug: str) -> list[dict]:
    """The three contexts of a tenant. ``slug`` keeps names unique across tenants."""
    return [
        {
            "name": f"{slug}-internal",
            "label": "Postes, files et groupes",
            "type": "internal",
            "user_ranges": [{"start": "1000", "end": "1999"}],
            "group_ranges": [{"start": "2000", "end": "2999"}],
            "queue_ranges": [{"start": "3000", "end": "3999"}],
            "conference_room_ranges": [{"start": "4000", "end": "4999"}],
            "enabled": True,
        },
        {
            "name": f"{slug}-incall",
            "label": "Appels entrants (numéros publics)",
            "type": "incall",
            # Start and end must have the same length: one range per number length,
            # from short national numbers to full international ones.
            "incall_ranges": [
                {"start": "0" * n, "end": "9" * n, "did_length": n}
                for n in range(4, 16)
            ],
            "enabled": True,
        },
        {
            "name": f"{slug}-outcall",
            "label": "Appels sortants (lignes opérateurs)",
            "type": "outcall",
            "enabled": True,
        },
    ]


def slugify(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in name.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:24] or "tenant"


class Api:
    def __init__(self, url: str, insecure: bool):
        self.url = url.rstrip("/")
        self.context = ssl._create_unverified_context() if insecure else None  # noqa: S323
        self.token: str | None = None
        self.tenant: str | None = None

    def call(self, method: str, path: str, body=None, *, basic=None, query=None):
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        if basic:
            raw = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
            request.add_header("Authorization", f"Basic {raw}")
        if self.token:
            request.add_header("X-Auth-Token", self.token)
        if self.tenant:
            request.add_header("Wazo-Tenant", self.tenant)
        try:
            with urllib.request.urlopen(
                request, context=self.context, timeout=30
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            sys.exit(f"Erreur {error.code} sur {method} {path} : {detail}")
        return json.loads(payload) if payload else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://localhost")
    parser.add_argument("--insecure", action="store_true", help="certificat autosigné")
    parser.add_argument("--root-user", default="root")
    parser.add_argument("--root-password", required=True)
    parser.add_argument("--tenant-name", required=True)
    args = parser.parse_args()

    api = Api(args.url, args.insecure)
    token = api.call(
        "POST",
        AUTH + "/token",
        {"expiration": 600},
        basic=(args.root_user, args.root_password),
    )
    api.token = token["data"]["token"]
    tenants = api.call("GET", AUTH + "/tenants", query={"search": args.tenant_name})[
        "items"
    ]
    tenant = next((t for t in tenants if t.get("name") == args.tenant_name), None)
    if tenant is None:
        sys.exit(f"Tenant « {args.tenant_name} » introuvable")
    api.tenant = tenant["uuid"]

    existing = api.call("GET", CONFD + "/contexts", query={"recurse": "false"})["items"]
    by_type = {c["type"]: c for c in existing}
    created = {}
    for wanted in desired_contexts(slugify(tenant.get("slug") or tenant["name"])):
        if wanted["type"] in by_type:
            context = by_type[wanted["type"]]
            created[wanted["type"]] = context
            # The engine creates default contexts without numbering ranges:
            # fill the empty ones (ranges set by hand are kept).
            missing = {
                k: v
                for k, v in wanted.items()
                if k.endswith("_ranges") and v and not context.get(k)
            }
            if missing:
                api.call(
                    "PUT",
                    CONFD + f"/contexts/{context['id']}",
                    {
                        "name": context["name"],
                        "label": context.get("label") or wanted["label"],
                        "type": context["type"],
                        "enabled": context.get("enabled", True),
                        **missing,
                    },
                )
                context.update(missing)
                print(
                    f"{wanted['type']}: « {context['name']} » complété ({', '.join(missing)})"
                )
            else:
                print(f"{wanted['type']}: « {context['name']} » déjà présent")
            continue
        context = api.call("POST", CONFD + "/contexts", wanted)
        created[wanted["type"]] = context
        print(f"{wanted['type']}: « {context['name']} » créé")

    # Extensions may dial out: the internal context includes the outcall one.
    internal, outcall = created.get("internal"), created.get("outcall")
    if internal and outcall:
        includes = [c["id"] for c in internal.get("contexts", [])]
        if outcall["id"] not in includes:
            api.call(
                "PUT",
                CONFD + f"/contexts/{internal['id']}/contexts",
                {"contexts": [{"id": i} for i in [*includes, outcall["id"]]]},
            )
            print(f"« {internal['name']} » inclut « {outcall['name']} »")

    print(json.dumps({t: c["name"] for t, c in created.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
