#!/usr/bin/env python3
"""Create the platform's service account on the PBX (least privilege).

Standard library only, so it runs on the PBX host right after the install:

    python3 create_service_account.py --url https://localhost --insecure \
        --root-password '...' --password '...' --tenant-name 'my-company'

Creates (or reuses) the policy from ../integration-policy.json and an
``external_api`` user holding it, in the company's tenant, then prints the
values to enter in the platform (PBX connection page).
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
from pathlib import Path

AUTH = "/api/auth/0.1"


class Api:
    def __init__(self, url: str, insecure: bool):
        self.url = url.rstrip("/")
        self.context = ssl._create_unverified_context() if insecure else None  # noqa: S323
        self.token: str | None = None
        self.tenant: str | None = None

    def call(self, method: str, path: str, body=None, *, basic=None, query=None):
        url = f"{self.url}{AUTH}{path}"
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
            with urllib.request.urlopen(request, context=self.context, timeout=20) as response:
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
    parser.add_argument("--username", default="nimbora-integration")
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--policy-file",
        default=str(Path(__file__).resolve().parent.parent / "integration-policy.json"),
    )
    args = parser.parse_args()

    api = Api(args.url, args.insecure)
    token = api.call("POST", "/token", {"expiration": 600}, basic=(args.root_user, args.root_password))
    api.token = token["data"]["token"]

    tenants = api.call("GET", "/tenants", query={"search": args.tenant_name})["items"]
    tenant = next((t for t in tenants if t.get("name") == args.tenant_name), None)
    if tenant is None:
        sys.exit(f"Tenant « {args.tenant_name} » introuvable")
    api.tenant = tenant["uuid"]

    policy_spec = json.loads(Path(args.policy_file).read_text())
    policies = api.call("GET", "/policies", query={"search": policy_spec["name"]})["items"]
    policy = next((p for p in policies if p.get("name") == policy_spec["name"]), None)
    if policy is None:
        policy = api.call("POST", "/policies", policy_spec)
    else:
        policy = api.call("PUT", f"/policies/{policy['uuid']}", policy_spec)

    users = api.call("GET", "/users", query={"search": args.username})["items"]
    user = next((u for u in users if u.get("username") == args.username), None)
    if user is None:
        user = api.call(
            "POST",
            "/users",
            {"username": args.username, "password": args.password, "purpose": "external_api", "enabled": True},
        )
    # An existing account keeps its password (install.sh reuses the same one).
    api.call("PUT", f"/users/{user['uuid']}/policies/{policy['uuid']}")

    print(json.dumps({
        "base_url": args.url,
        "username": args.username,
        "tenant_uuid": tenant["uuid"],
        "tenant_name": tenant["name"],
        "policy": policy_spec["name"],
        "acl_count": len(policy_spec["acl"]),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
