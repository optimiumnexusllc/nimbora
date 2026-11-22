"""Default subscription plans seeded on first start in SAAS_MODE.

Seeding never overwrites a plan that already exists, so prices and limits
edited from the super-admin console survive restarts. ``None`` = unlimited.
"""

# Feature flags understood by the platform.
FEATURE_LOCAL_AI = "local_ai"
FEATURE_CONTACT_CENTER = "contact_center"
FEATURE_CAMPAIGNS = "campaigns"
FEATURE_API_ACCESS = "api_access"
FEATURE_WHITE_LABEL = "white_label"
FEATURE_CUSTOM_VOICES = "custom_voices"
# Enterprise PBX: a tenant on the operator's shared PBX, created automatically,
# or the company's own dedicated PBX connected from the console.
FEATURE_PBX_SHARED = "pbx_shared"
FEATURE_PBX_DEDICATED = "pbx_dedicated"

ALL_FEATURES = (
    FEATURE_LOCAL_AI,
    FEATURE_CONTACT_CENTER,
    FEATURE_CAMPAIGNS,
    FEATURE_API_ACCESS,
    FEATURE_WHITE_LABEL,
    FEATURE_CUSTOM_VOICES,
    FEATURE_PBX_SHARED,
    FEATURE_PBX_DEDICATED,
)

# Limit columns, shared by plans and per-tenant overrides.
LIMIT_FIELDS = (
    "included_minutes",
    "included_human_minutes",
    "max_concurrent_calls",
    "max_agents",
    "max_human_seats",
    "max_campaigns",
)

DEFAULT_PLANS: dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "description": "Agents vocaux IA pour une petite équipe : 1 000 minutes/mois.",
        "currency": "eur",
        "monthly_price_cents": 9900,
        "included_minutes": 1000,
        "overage_price_cents_per_minute": 12,
        # Human calls on the enterprise PBX: telephony only, much cheaper.
        "included_human_minutes": 1000,
        "human_overage_price_cents_per_minute": 3,
        "max_concurrent_calls": 3,
        "max_agents": 3,
        "max_human_seats": 2,
        "max_campaigns": 2,
        "features": {
            FEATURE_LOCAL_AI: True,
            FEATURE_CONTACT_CENTER: True,
            FEATURE_CAMPAIGNS: True,
            FEATURE_API_ACCESS: False,
            FEATURE_WHITE_LABEL: False,
            FEATURE_CUSTOM_VOICES: False,
            FEATURE_PBX_SHARED: True,
            FEATURE_PBX_DEDICATED: False,
        },
        "sort_order": 10,
    },
    "business": {
        "name": "Business",
        "description": "Centre d'appels hybride IA + humains : 5 000 minutes/mois.",
        "currency": "eur",
        "monthly_price_cents": 39900,
        "included_minutes": 5000,
        "overage_price_cents_per_minute": 9,
        "included_human_minutes": 10000,
        "human_overage_price_cents_per_minute": 2,
        "max_concurrent_calls": 15,
        "max_agents": 15,
        "max_human_seats": 15,
        "max_campaigns": 20,
        "features": {
            FEATURE_LOCAL_AI: True,
            FEATURE_CONTACT_CENTER: True,
            FEATURE_CAMPAIGNS: True,
            FEATURE_API_ACCESS: True,
            FEATURE_WHITE_LABEL: False,
            FEATURE_CUSTOM_VOICES: True,
            FEATURE_PBX_SHARED: True,
            FEATURE_PBX_DEDICATED: False,
        },
        "sort_order": 20,
    },
    "enterprise": {
        "name": "Enterprise",
        "description": "Volumes élevés, marque blanche, limites sur mesure.",
        "currency": "eur",
        "monthly_price_cents": 149900,
        "included_minutes": 25000,
        "overage_price_cents_per_minute": 6,
        "included_human_minutes": 50000,
        "human_overage_price_cents_per_minute": 1,
        "max_concurrent_calls": 60,
        "max_agents": None,
        "max_human_seats": 100,
        "max_campaigns": None,
        "features": {feature: True for feature in ALL_FEATURES},
        "sort_order": 30,
    },
}
