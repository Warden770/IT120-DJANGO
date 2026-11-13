"""Phone-number and message validation helpers.

Kept free of model/view code so it is easy to unit-test and reuse.
"""
import re

from django.conf import settings
from django.core.exceptions import ValidationError

# E.164: "+", a non-zero first digit, 8-15 digits in total.
E164_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")

_ALLOWED_CHARS = re.compile(r"^[\d\s\-().+]+$")

INTERNATIONAL_HINT = "Use international format, for example +639171234567."


def normalize_phone_number(raw, default_country_code=None):
    """Return *raw* as an E.164 string (e.g. ``+639171234567``) or raise
    ``ValidationError`` with a user-friendly message.

    Accepted inputs:
      * ``+639171234567``          (already international)
      * ``0063 917 123 4567``      (``00`` international prefix)
      * ``0917 123 4567``          (local number; the default country code is added)
      * ``639171234567``           (starts with the default country code)
    """
    if default_country_code is None:
        default_country_code = getattr(settings, "DEFAULT_COUNTRY_CODE", "")
    country_code = str(default_country_code or "").lstrip("+")

    value = (raw or "").strip()
    if not value:
        raise ValidationError("Please enter a recipient phone number.", code="required")

    if not _ALLOWED_CHARS.match(value) or "+" in value[1:]:
        raise ValidationError(
            "A phone number may only contain digits, spaces, dashes, parentheses "
            "and a single leading '+'.",
            code="invalid_characters",
        )

    digits = re.sub(r"\D", "", value)

    if value.startswith("+"):
        candidate = "+" + digits
    elif digits.startswith("00"):
        candidate = "+" + digits[2:]
    elif digits.startswith("0") and country_code:
        candidate = "+" + country_code + digits[1:]
    elif country_code and digits.startswith(country_code):
        candidate = "+" + digits
    else:
        raise ValidationError(
            "Enter the number in international format (e.g. +639171234567) "
            "or in local format starting with 0 (e.g. 09171234567).",
            code="invalid_format",
        )

    if not E164_PATTERN.match(candidate):
        raise ValidationError(
            f"That does not look like a valid phone number. {INTERNATIONAL_HINT}",
            code="invalid_number",
        )
    return candidate


def validate_message_body(raw, max_length=None):
    """Return the stripped message text or raise ``ValidationError``."""
    if max_length is None:
        max_length = getattr(settings, "SMS_MAX_LENGTH", 1600)

    text = (raw or "").strip()
    if not text:
        raise ValidationError("Please type a message before sending.", code="required")
    if len(text) > max_length:
        raise ValidationError(
            f"The message is too long ({len(text)} characters). "
            f"The limit is {max_length} characters.",
            code="too_long",
        )
    return text
