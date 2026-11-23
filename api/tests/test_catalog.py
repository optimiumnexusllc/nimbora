"""Catalog: products, properties, rooms… with price, stock and agent search."""

import uuid

import pytest

from api.services.actions.common import ActionContext
from api.services.actions.dispatch import run_action
from api.services.catalog import service as catalog
from api.services.catalog.service import CatalogItemIn, fold, format_price, to_minor


async def _new_org(db):
    user = await db.create_user_with_email(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash="x"
    )
    org, _ = await db.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user.id
    )
    await db.add_user_to_organization(user.id, org.id)
    await db.update_user_selected_organization(user.id, org.id)
    user.selected_organization_id = org.id
    return user, org


def _ctx(org_id):
    return ActionContext(
        organization_id=org_id, tool_uuid="cat-1", tool_name="Catalogue"
    )


def test_words_without_accents_and_prices_in_the_currency_unit():
    assert fold("  Chambre  DÉLUXE vue mer ") == "chambre deluxe vue mer"
    assert to_minor("15 000", "XOF") == 15000
    assert to_minor("12,50", "EUR") == 1250
    assert to_minor("1.234.567", "XOF") == 1234567
    assert to_minor(None, "EUR") is None
    assert format_price(15000, "XOF", "la nuit") == "15 000 F CFA la nuit"
    assert format_price(1250, "EUR") == "12,50 €"
    with pytest.raises(ValueError):
        to_minor("-5", "EUR")


async def _seed(org_id):
    items = [
        CatalogItemIn(
            kind="room",
            sku="CH-DLX",
            name="Chambre Délux vue mer",
            category="Chambres",
            price=85000,
            unit="la nuit",
            stock=3,
            attributes={"lits": "1 lit double", "vue": "mer"},
        ),
        CatalogItemIn(
            kind="room",
            sku="CH-STD",
            name="Chambre standard",
            category="Chambres",
            price=45000,
            unit="la nuit",
            stock=0,
        ),
        CatalogItemIn(
            kind="property",
            sku="VIL-12",
            name="Villa piscine Cocody",
            category="Ventes",
            price=250_000_000,
            attributes={"chambres": 5, "surface": "420 m²"},
            description="Villa récente avec piscine, quartier calme.",
        ),
        CatalogItemIn(
            kind="product",
            sku="TSH-01",
            name="T-shirt coton bio",
            category="Textile",
            price=7500,
            available=False,
        ),
    ]
    for item in items:
        await catalog.save_item(org_id, item)


async def test_the_agent_finds_items_by_words_budget_and_availability(db_session):
    _, org = await _new_org(db_session)
    await _seed(org.id)

    found = await run_action(
        "search_catalog",
        _ctx(org.id),
        {},
        {"action": "search", "query": "CHAMBRE delux"},
    )
    assert found["status"] == "ok"
    (room,) = found["items"]
    assert room["name"] == "Chambre Délux vue mer"
    assert room["price"] == "85 000 F CFA la nuit"
    assert room["availability"] == "en stock (3)"
    assert room["details"] == {"lits": "1 lit double", "vue": "mer"}

    # Sold out and unavailable items are left out unless asked for. (« chambre »
    # also finds the villa and its « chambres: 5 »: the tool is limited to
    # rooms here, as a hotel would set it.)
    hotel = {"kinds": ["room"]}
    rooms = await run_action(
        "search_catalog", _ctx(org.id), hotel, {"action": "search", "query": "chambre"}
    )
    assert [i["name"] for i in rooms["items"]] == ["Chambre Délux vue mer"]
    every = await run_action(
        "search_catalog",
        _ctx(org.id),
        hotel,
        {"action": "search", "query": "chambre", "available_only": False},
    )
    assert {i["availability"] for i in every["items"]} == {"en stock (3)", "épuisé"}

    # Budget, in the catalog's currency.
    cheap = await run_action(
        "search_catalog",
        _ctx(org.id),
        {},
        {"action": "search", "max_price": 50000, "available_only": False},
    )
    assert {i["name"] for i in cheap["items"]} == {
        "Chambre standard",
        "T-shirt coton bio",
    }

    # A property, by an attribute word; details of one item.
    villa = await run_action(
        "search_catalog", _ctx(org.id), {}, {"action": "search", "query": "piscine"}
    )
    item_id = villa["items"][0]["id"]
    detail = await run_action(
        "search_catalog", _ctx(org.id), {}, {"action": "details", "item_id": item_id}
    )
    assert detail["item"]["details"] == {"chambres": 5, "surface": "420 m²"}
    assert detail["item"]["price"] == "250 000 000 F CFA"

    none = await run_action(
        "search_catalog", _ctx(org.id), {}, {"action": "search", "query": "jet privé"}
    )
    assert none["items"] == [] and "never invent" in none["hint"]


async def test_tool_settings_limit_kinds_and_hide_stock(db_session):
    _, org = await _new_org(db_session)
    await _seed(org.id)
    config = {"kinds": ["room"], "show_stock": False, "max_results": 1}
    found = await run_action(
        "search_catalog",
        _ctx(org.id),
        config,
        {"action": "search", "available_only": False},
    )
    assert found["total"] == 2 and len(found["items"]) == 1
    assert "narrow" in found["hint"]
    rooms_only = await run_action(
        "search_catalog", _ctx(org.id), config, {"action": "search", "query": "villa"}
    )
    assert rooms_only["items"] == []
    stock = await run_action(
        "search_catalog", _ctx(org.id), config, {"action": "search", "query": "délux"}
    )
    assert stock["items"][0]["availability"] == "en stock"


async def test_one_company_never_sees_another_companys_catalog(db_session):
    _, mine = await _new_org(db_session)
    _, other = await _new_org(db_session)
    await _seed(other.id)
    found = await run_action(
        "search_catalog",
        _ctx(mine.id),
        {},
        {"action": "search", "query": "chambre", "available_only": False},
    )
    assert found["items"] == []
    villa = (await db_session.search_catalog_items(other.id, words=["villa"]))[0][0]
    detail = await run_action(
        "search_catalog", _ctx(mine.id), {}, {"action": "details", "item_id": villa.id}
    )
    assert detail["status"] == "error"


async def test_console_routes_and_csv_import_export(db_session, test_client_factory):
    user, org = await _new_org(db_session)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/catalog/items",
            json={
                "kind": "room",
                "sku": "CH-1",
                "name": "Suite présidentielle",
                "price": 250000,
                "unit": "la nuit",
                "stock": 1,
            },
        )
        duplicate = await client.post(
            "/api/v1/catalog/items", json={"sku": "ch-1", "name": "Autre"}
        )
        csv_content = (
            "reference;nom;type;categorie;prix;stock;disponible;chambres;quartier\n"
            "VIL-1;Villa Riviera;bien;Ventes;150 000 000;;oui;4;Riviera 3\n"
            "CH-1;Suite présidentielle;chambre;Chambres;300 000;2;oui;;\n"
            ";Sans prix;produit;;abc;;;;\n"
            "X-2;;produit;;100;;;;\n"
        )
        imported = await client.post(
            "/api/v1/catalog/import",
            files={"file": ("catalogue.csv", csv_content.encode(), "text/csv")},
        )
        listed = await client.get("/api/v1/catalog/items", params={"q": "riviera"})
        stock = await client.patch(
            f"/api/v1/catalog/items/{created.json()['id']}/stock", json={"stock": 0}
        )
        exported = await client.get("/api/v1/catalog/export.csv")
        preview = await client.post(
            "/api/v1/catalog/agent-preview",
            json={"query": "villa", "max_price": 200000000},
        )
        deleted = await client.delete(f"/api/v1/catalog/items/{created.json()['id']}")
    assert created.status_code == 201
    assert created.json()["price_text"] == "250 000 F CFA la nuit"
    assert duplicate.status_code == 409
    report = imported.json()
    assert (report["created"], report["updated"]) == (1, 1)  # CH-1 updated by reference
    assert [e["line"] for e in report["errors"]] == [4, 5]
    (villa,) = listed.json()["items"]
    assert villa["kind"] == "property"
    assert villa["attributes"] == {"chambres": "4", "quartier": "Riviera 3"}
    assert villa["price"] == 150_000_000
    assert stock.json()["in_stock"] is False
    assert (
        "Villa Riviera" in exported.text and "chambres" in exported.text.splitlines()[0]
    )
    assert preview.json()["items"][0]["name"] == "Villa Riviera"
    assert deleted.status_code == 204


async def test_the_catalog_tool_can_be_saved_and_shows_its_parameters(
    db_session, test_client_factory
):
    user, _ = await _new_org(db_session)
    async with test_client_factory(user) as client:
        response = await client.post(
            "/api/v1/tools/",
            json={
                "name": "Catalogue",
                "description": "Cherche les chambres et leurs prix.",
                "definition": {
                    "type": "search_catalog",
                    "config": {"kinds": ["room"], "currency": "XOF"},
                },
            },
        )
    assert response.status_code in (200, 201), response.text
    from api.services.actions.schemas import action_function_parameters

    properties, required = action_function_parameters(
        {"type": "search_catalog", "config": {}}
    )
    assert required == ["action"]
    assert {"query", "max_price", "item_id"} <= set(properties)
