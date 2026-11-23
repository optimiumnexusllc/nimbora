"""The company's catalog: what it sells or rents, searched by its agents.

An item is a product, a property, a room, a service, a vehicle… with a price,
a stock (or none: not tracked), an availability and free attributes
(« chambres: 3 », « surface: 120 m² », « vue: mer »). The agent searches it
during calls with « Rechercher dans le catalogue » and only ever quotes what
it found.

Prices are kept in the currency's smallest unit: cents for EUR or USD, the
franc itself for XOF or XAF (no decimals).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

KINDS = ("product", "property", "room", "service", "vehicle", "other")
KIND_LABELS = {
    "product": "Produit",
    "property": "Bien immobilier",
    "room": "Chambre",
    "service": "Prestation",
    "vehicle": "Véhicule",
    "other": "Autre",
}
# ISO 4217 currencies without minor unit (the others have two decimals).
ZERO_DECIMAL = {
    "XOF",
    "XAF",
    "JPY",
    "KRW",
    "GNF",
    "RWF",
    "UGX",
    "VND",
    "KMF",
    "BIF",
    "CLP",
    "DJF",
    "PYG",
    "VUV",
    "XPF",
}
CURRENCY_SYMBOLS = {
    "XOF": "F CFA",
    "XAF": "F CFA",
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "MAD": "DH",
}
MAX_IMPORT_ROWS = 5000
MAX_ATTRIBUTES = 30
Kind = Literal["product", "property", "room", "service", "vehicle", "other"]


class CatalogError(ValueError):
    """A problem with an item or an import line, safe to show."""


def fold(text: Any) -> str:
    """Lower case, no accents, single spaces: « Chambre Délux » → « chambre delux »."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", plain.lower()).strip()


def words_of(query: str) -> list[str]:
    return [w for w in re.split(r"[^0-9a-z]+", fold(query)) if len(w) >= 2][:8]


def decimals(currency: str) -> int:
    return 0 if currency.upper() in ZERO_DECIMAL else 2


def to_minor(amount: Any, currency: str) -> int | None:
    """« 15 000 », « 12,50 », 49.9 → smallest unit of the currency."""
    if amount is None or amount == "":
        return None
    text = re.sub(r"[\s  ]", "", str(amount)).replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text.count(".") > 1:  # « 1.234.567 » written with dots as thousands
        text = text.replace(".", "")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise CatalogError(f"Prix illisible : {amount}") from error
    if value < 0:
        raise CatalogError("Le prix ne peut pas être négatif")
    return int((value * (10 ** decimals(currency))).to_integral_value())


def format_price(
    minor: int | None, currency: str, unit: str | None = None
) -> str | None:
    """15000 XOF → « 15 000 F CFA » ; 1250 EUR → « 12,50 € »."""
    if minor is None:
        return None
    places = decimals(currency)
    value = Decimal(minor) / (10**places)
    whole, _, fraction = f"{value:,.{places}f}".partition(".")
    text = whole.replace(",", " ") + (f",{fraction}" if places else "")
    text = f"{text} {CURRENCY_SYMBOLS.get(currency.upper(), currency.upper())}"
    return f"{text} {unit}" if unit else text


class CatalogItemIn(BaseModel):
    kind: Kind = "product"
    sku: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=100)
    price: Decimal | None = Field(
        default=None, ge=0, description="In the currency, e.g. 15000 or 12.50"
    )
    currency: str = Field(default="XOF", min_length=3, max_length=3)
    unit: str | None = Field(default=None, max_length=32)
    stock: int | None = Field(default=None, ge=0, description="None: not tracked")
    available: bool = True
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)
    url: str | None = Field(default=None, max_length=500)

    @field_validator("name", "sku", "category", "unit", "description", "url")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{3}", value):
            raise ValueError("Devise : code à 3 lettres (XOF, EUR…)")
        return value.upper()

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict) -> dict:
        if len(value) > MAX_ATTRIBUTES:
            raise ValueError(f"{MAX_ATTRIBUTES} caractéristiques au plus")
        return {str(k).strip()[:60]: v for k, v in value.items() if str(k).strip()}

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value and not re.match(r"^https?://", value):
            raise ValueError("Le lien doit commencer par http:// ou https://")
        return value

    def fields(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"price"})
        data["tags"] = [t.strip()[:40] for t in self.tags if t.strip()]
        data["price_cents"] = (
            to_minor(self.price, self.currency) if self.price is not None else None
        )
        data["search_text"] = fold(
            " ".join(
                [
                    self.name,
                    self.sku or "",
                    self.category or "",
                    KIND_LABELS[self.kind],
                    self.description or "",
                    " ".join(data["tags"]),
                    " ".join(f"{k} {v}" for k, v in self.attributes.items()),
                ]
            )
        )
        return data


def item_out(item) -> dict[str, Any]:
    places = decimals(item.currency)
    return {
        "id": item.id,
        "kind": item.kind,
        "kind_label": KIND_LABELS.get(item.kind, item.kind),
        "sku": item.sku,
        "name": item.name,
        "description": item.description,
        "category": item.category,
        "price": None
        if item.price_cents is None
        else float(Decimal(item.price_cents) / (10**places)),
        "price_text": format_price(item.price_cents, item.currency, item.unit),
        "currency": item.currency,
        "unit": item.unit,
        "stock": item.stock,
        "available": bool(item.available),
        "in_stock": bool(item.available) and (item.stock is None or item.stock > 0),
        "attributes": item.attributes or {},
        "tags": item.tags or [],
        "url": item.url,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


# --------------------------------------------------------------- console


async def list_items(
    organization_id: int,
    *,
    query: str = "",
    kind: str | None = None,
    category: str | None = None,
    available_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    from api.db import db_client

    items, total = await db_client.search_catalog_items(
        organization_id,
        words=words_of(query),
        kind=kind,
        category=category,
        available_only=available_only,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return {
        "items": [item_out(i) for i in items],
        "total": total,
        "categories": await db_client.catalog_categories(organization_id),
    }


async def save_item(
    organization_id: int, spec: CatalogItemIn, item_id: int | None = None
) -> dict[str, Any]:
    from api.db import db_client

    fields = spec.fields()
    if spec.sku:
        same = await db_client.get_catalog_item_by_sku(organization_id, spec.sku)
        if same and same.id != item_id:
            raise CatalogError(f"La référence {spec.sku} existe déjà ({same.name})")
    if item_id is None:
        item = await db_client.create_catalog_item(organization_id, fields)
    else:
        item = await db_client.update_catalog_item(organization_id, item_id, fields)
        if item is None:
            raise LookupError("Article introuvable")
    return item_out(item)


# ------------------------------------------------------------- CSV in/out

COLUMNS = {
    "sku": "sku",
    "reference": "sku",
    "ref": "sku",
    "name": "name",
    "nom": "name",
    "designation": "name",
    "libelle": "name",
    "kind": "kind",
    "type": "kind",
    "category": "category",
    "categorie": "category",
    "description": "description",
    "price": "price",
    "prix": "price",
    "tarif": "price",
    "currency": "currency",
    "devise": "currency",
    "unit": "unit",
    "unite": "unit",
    "stock": "stock",
    "quantite": "stock",
    "available": "available",
    "disponible": "available",
    "url": "url",
    "lien": "url",
    "tags": "tags",
    "mots cles": "tags",
}
KIND_WORDS = {
    **{k: k for k in KINDS},
    "produit": "product",
    "bien": "property",
    "bien immobilier": "property",
    "logement": "property",
    "chambre": "room",
    "prestation": "service",
    "vehicule": "vehicle",
    "voiture": "vehicle",
    "autre": "other",
}
TRUE_WORDS = {"oui", "yes", "true", "1", "vrai", "o", "y", "disponible"}


def _row_spec(row: dict[str, str], default_currency: str) -> CatalogItemIn:
    data: dict[str, Any] = {"attributes": {}}
    for raw_key, raw_value in row.items():
        if raw_key is None:
            continue
        value = (raw_value or "").strip()
        key = COLUMNS.get(fold(raw_key))
        if key is None:
            if value:
                data["attributes"][raw_key.strip()] = value
            continue
        if not value:
            continue
        if key == "kind":
            kind = KIND_WORDS.get(fold(value))
            if kind is None:
                raise CatalogError(f"Type inconnu : {value}")
            data["kind"] = kind
        elif key == "stock":
            try:
                data["stock"] = int(re.sub(r"\s", "", value))
            except ValueError as error:
                raise CatalogError(f"Stock illisible : {value}") from error
        elif key == "available":
            data["available"] = fold(value) in TRUE_WORDS
        elif key == "tags":
            data["tags"] = [t.strip() for t in re.split(r"[|;,]", value) if t.strip()]
        elif key == "price":
            data["price_raw"] = value
        else:
            data[key] = value
    currency = (data.get("currency") or default_currency).upper()
    raw_price = data.pop("price_raw", None)
    if raw_price is not None:
        minor = to_minor(raw_price, currency)
        data["price"] = Decimal(minor) / (10 ** decimals(currency))
    data["currency"] = currency
    return CatalogItemIn(**data)


async def import_csv(
    organization_id: int, content: str, default_currency: str = "XOF"
) -> dict[str, Any]:
    """Create or update items (by reference when given). Lines with errors
    are skipped and reported; the others are saved."""
    from pydantic import ValidationError

    from api.db import db_client

    sample = content[:4096]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")), delimiter=delimiter)
    if not reader.fieldnames or not any(
        COLUMNS.get(fold(f)) == "name" for f in reader.fieldnames
    ):
        raise CatalogError("Le fichier doit avoir une colonne « nom » (ou « name »)")
    created = updated = 0
    errors: list[dict[str, Any]] = []
    for line, row in enumerate(reader, start=2):
        if line - 1 > MAX_IMPORT_ROWS:
            errors.append(
                {
                    "line": line,
                    "message": f"{MAX_IMPORT_ROWS} lignes au plus : la suite est ignorée",
                }
            )
            break
        try:
            spec = _row_spec(row, default_currency)
            existing = (
                await db_client.get_catalog_item_by_sku(organization_id, spec.sku)
                if spec.sku
                else None
            )
            if existing:
                await db_client.update_catalog_item(
                    organization_id, existing.id, spec.fields()
                )
                updated += 1
            else:
                await db_client.create_catalog_item(organization_id, spec.fields())
                created += 1
        except ValidationError as error:
            first = error.errors()[0]
            errors.append(
                {
                    "line": line,
                    "message": f"{'.'.join(map(str, first['loc']))} : {first['msg']}",
                }
            )
        except CatalogError as error:
            errors.append({"line": line, "message": str(error)})
    return {"created": created, "updated": updated, "errors": errors[:100]}


async def export_csv(organization_id: int) -> str:
    from api.db import db_client

    items, _ = await db_client.search_catalog_items(organization_id, limit=100_000)
    attribute_keys = sorted({k for i in items for k in (i.attributes or {})})
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "reference",
            "nom",
            "type",
            "categorie",
            "description",
            "prix",
            "devise",
            "unite",
            "stock",
            "disponible",
            "url",
            "tags",
            *attribute_keys,
        ]
    )
    for i in items:
        places = decimals(i.currency)
        price = (
            ""
            if i.price_cents is None
            else f"{Decimal(i.price_cents) / (10**places):.{places}f}".replace(".", ",")
        )
        writer.writerow(
            [
                i.sku or "",
                i.name,
                i.kind,
                i.category or "",
                i.description or "",
                price,
                i.currency,
                i.unit or "",
                "" if i.stock is None else i.stock,
                "oui" if i.available else "non",
                i.url or "",
                "|".join(i.tags or []),
                *[(i.attributes or {}).get(k, "") for k in attribute_keys],
            ]
        )
    return out.getvalue()


# ------------------------------------------------------------- the agent


def _for_agent(item: dict[str, Any], show_stock: bool) -> dict[str, Any]:
    if not item["available"]:
        availability = "indisponible"
    elif item["stock"] is None:
        availability = "disponible"
    elif item["stock"] == 0:
        availability = "épuisé"
    else:
        availability = f"en stock ({item['stock']})" if show_stock else "en stock"
    description = (item["description"] or "")[:240]
    return {
        "id": item["id"],
        "name": item["name"],
        "reference": item["sku"],
        "type": item["kind_label"],
        "category": item["category"],
        "price": item["price_text"] or "prix sur demande",
        "availability": availability,
        "description": description,
        "details": dict(list(item["attributes"].items())[:10]),
        "link": item["url"],
    }


async def handle_catalog(
    ctx, config: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    """The agent's catalog tool: search, or the details of one item."""
    from api.db import db_client
    from api.services.actions.common import ActionError

    show_stock = bool(config.get("show_stock", True))
    action = args.get("action") or "search"
    if action == "details":
        item = None
        if args.get("item_id"):
            item = await db_client.get_catalog_item(
                ctx.organization_id, int(args["item_id"])
            )
        elif args.get("reference"):
            item = await db_client.get_catalog_item_by_sku(
                ctx.organization_id, str(args["reference"])
            )
        if item is None or (config.get("kinds") and item.kind not in config["kinds"]):
            raise ActionError("Article introuvable : refaites une recherche.")
        detail = _for_agent(item_out(item), show_stock)
        detail["description"] = item.description or ""
        detail["details"] = item.attributes or {}
        return {"status": "ok", "item": detail}

    currency = config.get("currency") or "XOF"

    def price(name: str) -> int | None:
        value = args.get(name)
        if value in (None, ""):
            return None
        try:
            return to_minor(value, currency)
        except CatalogError:
            return None

    limit = min(max(int(config.get("max_results") or 5), 1), 10)
    query = str(args.get("query") or "")
    items, total = await db_client.search_catalog_items(
        ctx.organization_id,
        words=words_of(query),
        kinds=list(config.get("kinds") or []) or None,
        category=args.get("category") or None,
        min_price_cents=price("min_price"),
        max_price_cents=price("max_price"),
        available_only=bool(
            args.get("available_only", config.get("available_only", True))
        ),
        limit=limit,
    )
    found = [_for_agent(item_out(i), show_stock) for i in items]
    result: dict[str, Any] = {"status": "ok", "total": total, "items": found}
    if not found:
        result["hint"] = (
            "Nothing matches. Say so plainly, never invent an item; offer to widen "
            "the search (other words, no price limit, unavailable items too)."
        )
    elif total > len(found):
        result["hint"] = f"{total} items match; ask a question to narrow the choice."
    return result
