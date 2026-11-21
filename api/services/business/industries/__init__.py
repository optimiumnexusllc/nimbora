"""Industry templates, one module per sector."""

from api.services.business.industries import (
    finance,
    health,
    industry,
    security,
    services,
    telecom,
    transport,
    utilities,
)
from api.services.business.industries.model import (
    SECTORS,
    IndustryTemplate,
    Variable,
)

ALL: list[IndustryTemplate] = [
    *services.TEMPLATES,
    *finance.TEMPLATES,
    *health.TEMPLATES,
    *telecom.TEMPLATES,
    *utilities.TEMPLATES,
    *transport.TEMPLATES,
    *industry.TEMPLATES,
    *security.TEMPLATES,
]

__all__ = ["ALL", "SECTORS", "IndustryTemplate", "Variable"]
