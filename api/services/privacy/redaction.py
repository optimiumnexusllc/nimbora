"""Find and mask personal data in call text (GDPR, PCI DSS).

Detectors are pattern-based and *validated* wherever a checksum exists, so
an order number does not get masked as a card and a card typed with spaces
still does:

* ``card``  — payment card numbers, 13-19 digits, Luhn-checked;
* ``iban``  — IBANs, ISO 7064 mod-97 checked, with or without spaces;
* ``ssn``   — French NIR (sécurité sociale, 13 digits + key, checked) and
  US SSNs (``123-45-6789``);
* ``cvv``   — 3-4 digits right after "CVV", "CVC", "cryptogramme"…;
* ``email`` — e-mail addresses (also "jean point dupont arobase gmail point com"
  as transcribed from speech);
* ``phone`` — phone numbers (8-15 digits, international or local);
* ``ip``    — IPv4 addresses.

Masks are language-neutral tokens (``[CARD]``, ``[EMAIL]``…): the LLM, QA
and the people reading transcripts understand that something was removed.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

ALL_CATEGORIES = ("card", "iban", "ssn", "cvv", "email", "phone", "ip")
# What the agent may never see during a live call when PCI masking is on.
CONVERSATION_CATEGORIES = ("card", "cvv", "iban", "ssn")

TOKENS = {
    "card": "[CARD]",
    "iban": "[IBAN]",
    "ssn": "[SSN]",
    "cvv": "[CVV]",
    "email": "[EMAIL]",
    "phone": "[PHONE]",
    "ip": "[IP]",
}

# ------------------------------------------------------------- validators


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def iban_valid(raw: str) -> bool:
    iban = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def nir_valid(raw: str) -> bool:
    nir = re.sub(r"\s+", "", raw).upper()
    if not re.fullmatch(
        r"[12]\d{2}(0[1-9]|1[0-2]|[2-9]\d)(\d{2}|2A|2B)\d{6}\d{2}", nir
    ):
        return False
    body, key = nir[:13], int(nir[13:])
    body = body.replace("2A", "19").replace("2B", "18")
    return 97 - (int(body) % 97) == key


# --------------------------------------------------------------- patterns

_SEP = r"[ \-.]?"
_CARD_RE = re.compile(r"(?<![\d])(?:\d" + _SEP + r"){12,18}\d(?![\d])")
_IBAN_RE = re.compile(
    r"\b[A-Za-z]{2}\d{2}(?:[ ]?[A-Za-z0-9]{4}){2,7}(?:[ ]?[A-Za-z0-9]{1,4})?\b"
)
_NIR_RE = re.compile(
    r"(?<![\d])[12][ ]?\d{2}[ ]?\d{2}[ ]?(?:\d{2}|2[AaBb])[ ]?\d{3}[ ]?\d{3}[ ]?\d{2}(?![\d])"
)
_US_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CVV_RE = re.compile(
    r"(?i)\b(cvv2?|cvc2?|cryptogramme|code de s[ée]curit[ée]|security code|"
    r"code au dos)\b(\W{0,12})(\d{3,4})\b"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Speech-to-text spelling: "jean point dupont arobase gmail point com".
_SPOKEN_EMAIL_RE = re.compile(
    r"(?i)\b[\w.\-]+(?:\s+(?:point|dot)\s+[\w\-]+)*\s+(?:arobase|at|chez)\s+"
    r"[\w\-]+(?:\s+(?:point|dot)\s+[\w\-]+)+\b"
)
_PHONE_RE = re.compile(r"(?<![\w+])(?:\+|00)?\d(?:[ \-.()]{0,2}\d){7,14}(?![\d])")
_IPV4_RE = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]

    @property
    def changed(self) -> bool:
        return bool(self.counts)


def _sub(
    pattern: re.Pattern,
    text: str,
    category: str,
    counts: Counter,
    validate=None,
    group: int | None = None,
) -> str:
    def replace(match: re.Match) -> str:
        value = match.group(0)
        if validate is not None and not validate(value):
            return value
        counts[category] += 1
        if group is not None:
            start, end = match.span(group)
            offset = match.start()
            return value[: start - offset] + TOKENS[category] + value[end - offset :]
        return TOKENS[category]

    return pattern.sub(replace, text)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _looks_like_phone(value: str) -> bool:
    """International numbers, or local ones that look dialed: a bare run of
    digits (order or invoice number) is not a phone number."""
    digits = _digits(value)
    stripped = value.strip()
    if stripped.startswith(("+", "00")):
        return 8 <= len(digits) <= 15
    has_separators = bool(re.search(r"[ \-.()]", stripped))
    if not 8 <= len(digits) <= 12:
        return False
    return has_separators or digits.startswith("0")


def redact_text(
    text: str | None, categories: Iterable[str] = ALL_CATEGORIES
) -> RedactionResult:
    """Mask every enabled category in ``text``. Order matters: the most
    specific (checksum-validated) detectors run before the generic ones."""
    if not text:
        return RedactionResult(text or "", {})
    enabled = set(categories)
    # Cheap pre-check: nearly all detectors need a digit or an "@"/spoken at.
    if not any(c.isdigit() for c in text) and "@" not in text:
        if "email" not in enabled or not re.search(r"(?i)\b(arobase|at|chez)\b", text):
            return RedactionResult(text, {})
    counts: Counter = Counter()
    out = text
    if "email" in enabled:
        out = _sub(_EMAIL_RE, out, "email", counts)
        out = _sub(_SPOKEN_EMAIL_RE, out, "email", counts)
    if "iban" in enabled:
        out = _sub(_IBAN_RE, out, "iban", counts, validate=iban_valid)
    if "cvv" in enabled:
        out = _sub(_CVV_RE, out, "cvv", counts, group=3)
    if "card" in enabled:
        out = _sub(
            _CARD_RE,
            out,
            "card",
            counts,
            validate=lambda v: 13 <= len(_digits(v)) <= 19 and luhn_valid(_digits(v)),
        )
    if "ssn" in enabled:
        out = _sub(_NIR_RE, out, "ssn", counts, validate=nir_valid)
        out = _sub(_US_SSN_RE, out, "ssn", counts)
    if "ip" in enabled:
        out = _sub(_IPV4_RE, out, "ip", counts)
    if "phone" in enabled:
        out = _sub(
            _PHONE_RE,
            out,
            "phone",
            counts,
            validate=_looks_like_phone,
        )
    return RedactionResult(out, dict(counts))


def redact_value(
    value: Any,
    categories: Iterable[str] = ALL_CATEGORIES,
    counts: Counter | None = None,
    *,
    skip_keys: frozenset[str] = frozenset(),
) -> Any:
    """Redact every string inside a JSON-like value (dicts, lists)."""
    categories = tuple(categories)
    counts = counts if counts is not None else Counter()
    if isinstance(value, str):
        result = redact_text(value, categories)
        counts.update(result.counts)
        return result.text
    if isinstance(value, dict):
        return {
            k: (
                v
                if k in skip_keys
                else redact_value(v, categories, counts, skip_keys=skip_keys)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(v, categories, counts, skip_keys=skip_keys) for v in value]
    return value
