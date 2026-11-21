"""AI agents calling out through the enterprise PBX's operator lines.

Outbound AI calls (campaigns, callbacks, test calls) are originated over ARI
on the ARI configuration linked to the PBX. What reaches the operator depends
on that configuration's dial string:

* ``routes`` — ``Local/<number>@<outcall context>``: the PBX's outbound routes
  decide (pattern, presented number, failover between lines), exactly as for
  a person dialling from an extension;
* ``trunk`` — ``PJSIP/<number>@<line endpoint>``: straight out of one line.

The number can be rewritten first (``+225…`` → national or ``00`` form), and
a presented number chosen among the company's numbers.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from api.services.pbx.client import PbxError
from api.services.pbx.service import PbxRouteError, _connection, client_for
from api.services.pbx.trunks import _outcall_context
from api.services.telephony.providers.ari.dial_string import (
    build_dial_string,
    format_dialled_number,
)

Mode = Literal["routes", "trunk"]
NumberFormat = Literal["as_is", "international_00", "national"]
_ROUTES = re.compile(r"^Local/\{number\}@([A-Za-z0-9_\-]+)$")
_TRUNK = re.compile(r"^PJSIP/\{number\}@([A-Za-z0-9_.\-]+)$")
CALLER_ID = re.compile(r"^\+?[0-9]{2,20}$")


async def _ari(organization_id: int, connection):
    from api.db import db_client

    if not connection.ari_configuration_id:
        raise PbxRouteError(
            "Reliez d'abord une configuration ARI (l'accès des agents IA au PBX).", 409
        )
    ari = await db_client.get_telephony_configuration_for_org(
        connection.ari_configuration_id, organization_id
    )
    if ari is None or ari.provider != "ari":
        raise PbxRouteError("Configuration ARI introuvable", 404)
    return ari


def preview(credentials: dict, number: str) -> str:
    """The dial string an AI call to ``number`` would use."""
    return build_dial_string(
        format_dialled_number(
            number,
            credentials.get("dial_number_format"),
            credentials.get("dial_country_code"),
            credentials.get("dial_national_prefix"),
        ),
        credentials.get("dial_string_template") or "PJSIP/{number}",
    )


async def read_settings(organization_id: int, **client_kwargs) -> dict[str, Any]:
    from api.db import db_client

    connection = await _connection(organization_id)
    ari = await _ari(organization_id, connection)
    credentials = dict(ari.credentials or {})
    template = credentials.get("dial_string_template") or "PJSIP/{number}"
    mode: str = "custom"
    trunk_id = None
    if match := _ROUTES.match(template):
        mode = "routes"
    elif match := _TRUNK.match(template):
        mode = "trunk"
        endpoint_name = match.group(1)
        try:
            async with client_for(connection, **client_kwargs) as client:
                for trunk in await client.trunks():
                    if (trunk.get("endpoint_sip") or {}).get("name") == endpoint_name:
                        trunk_id = trunk.get("id")
        except PbxError:
            pass
    default = await db_client.get_default_caller_id(ari.id)
    return {
        "mode": mode,
        "trunk_id": trunk_id,
        "dial_string_template": template,
        "number_format": credentials.get("dial_number_format") or "as_is",
        "country_code": credentials.get("dial_country_code") or "",
        "national_prefix": credentials.get("dial_national_prefix") or "",
        "caller_id": default.address if default else None,
        "example": {
            "number": "+2250707112233",
            "dial_string": preview(credentials, "+2250707112233"),
        },
    }


async def configure(
    organization_id: int,
    *,
    mode: Mode,
    trunk_id: int | None = None,
    number_format: NumberFormat = "as_is",
    country_code: str = "",
    national_prefix: str = "",
    caller_id: str | None = None,
    **client_kwargs,
) -> dict[str, Any]:
    """Send AI calls out through the PBX's outbound routes or one line."""
    from api.db import db_client

    country_code = re.sub(r"[^0-9]", "", country_code or "")
    national_prefix = (national_prefix or "").strip()
    if number_format == "national" and not country_code:
        raise PbxRouteError("Indicatif du pays requis pour le format national", 422)
    if not re.fullmatch(r"[0-9]{0,3}", national_prefix):
        raise PbxRouteError("Préfixe national invalide", 422)
    caller_id = (caller_id or "").replace(" ", "") or None
    if caller_id and not CALLER_ID.match(caller_id):
        raise PbxRouteError("Numéro présenté invalide", 422)

    connection = await _connection(organization_id)
    ari = await _ari(organization_id, connection)
    async with client_for(connection, **client_kwargs) as client:
        if mode == "routes":
            if not await client.outcalls():
                raise PbxRouteError(
                    "Aucune route sortante sur le PBX : créez-en une d'abord.", 409
                )
            template = f"Local/{{number}}@{await _outcall_context(client)}"
        else:
            if trunk_id is None:
                raise PbxRouteError("Choisissez la ligne opérateur", 422)
            trunk = await client.trunk(trunk_id)
            name = (trunk.get("endpoint_sip") or {}).get("name")
            if not name:
                raise PbxRouteError("Cette ligne n'a pas de compte SIP", 409)
            template = f"PJSIP/{{number}}@{name}"

    credentials = {
        **(ari.credentials or {}),
        "dial_string_template": template,
        "dial_number_format": number_format,
        "dial_country_code": country_code,
        "dial_national_prefix": national_prefix,
    }
    await db_client.update_telephony_configuration(
        ari.id, organization_id, credentials=credentials
    )

    if caller_id:
        rows = await db_client.list_phone_numbers_for_config(ari.id)
        from api.services.customer_memory.service import normalize_phone

        normalized = normalize_phone(caller_id) or caller_id
        row = next((r for r in rows if r.address_normalized == normalized), None)
        if row is None:
            row = await db_client.create_phone_number(
                organization_id=organization_id,
                telephony_configuration_id=ari.id,
                address=caller_id,
                label=f"Numéro présenté {caller_id}",
                extra_metadata={"pbx_caller_id": True},
            )
        await db_client.set_default_caller_id(row.id, ari.id)
    return await read_settings(organization_id, **client_kwargs)
