"""Platform brand: the single place the product name comes from.

Every user-facing name — including the one the PBX shows on phones, in SIP
headers and in e-mails — is read from here, so a reseller rebrands the whole
platform with environment variables instead of code changes.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Brand:
    name: str
    pbx_name: str
    support_email: str
    noreply_email: str
    website: str
    sip_user_agent: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "PBX"


def _env(name: str, default: str) -> str:
    """An unset OR empty variable means the default: Compose passes `${VAR:-}`
    as an empty string when .env does not define it."""
    return os.environ.get(name, "").strip() or default


def brand() -> Brand:
    name = _env("BRAND_NAME", "NIMBORA")
    domain = _env("BRAND_DOMAIN", "nimbora.io")
    pbx_name = _env("BRAND_PBX_NAME", f"{name} Voice")
    return Brand(
        name=name,
        pbx_name=pbx_name,
        support_email=_env("BRAND_SUPPORT_EMAIL", f"support@{domain}"),
        noreply_email=_env("BRAND_NOREPLY_EMAIL", f"noreply@{domain}"),
        website=_env("BRAND_WEBSITE", f"https://{domain}"),
        # Shown in SIP User-Agent / Server headers of the PBX.
        sip_user_agent=_env("BRAND_SIP_USER_AGENT", _slug(pbx_name)),
    )
