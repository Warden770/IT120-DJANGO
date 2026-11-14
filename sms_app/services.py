"""SMS provider integration.

The views only talk to the small interface defined here
(``get_backend().send(...)`` / ``.fetch_status(...)``), so the provider can be
swapped or faked in tests without touching view code.

Two backends are provided:

* ``TextBeeBackend``   - real delivery through the TextBee gateway
  (https://textbee.dev). TextBee turns an Android phone you own into an SMS
  gateway: our app calls TextBee's REST API, TextBee wakes the phone, and the
  phone sends the SMS from its own SIM card.
* ``SimulatedBackend`` - sends nothing; for UI development only.

Every failure is converted into a subclass of ``SMSError`` that carries a
``user_message`` which is safe to show to the user (it never contains the API
key or raw stack traces).
"""
import logging
import uuid
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

USER_AGENT = "IT120-Django-SMS/1.0"


# --- Errors -----------------------------------------------------------------

class SMSError(Exception):
    """Base class. ``user_message`` is safe to display."""

    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


class SMSConfigurationError(SMSError):
    """Missing or incorrect configuration / credentials."""


class SMSConnectionError(SMSError):
    """The provider could not be reached (network problem or timeout)."""


class SMSProviderError(SMSError):
    """The provider answered but rejected the request."""


# --- Result type ------------------------------------------------------------

@dataclass(frozen=True)
class SMSResult:
    sid: str     # provider tracking id (TextBee: the batch id); may be empty
    status: str  # one of SMSMessage.STATUS_CHOICES values


# TextBee message statuses -> the statuses stored by this app.
# "unknown" means TextBee has no confirmed state yet, so we never treat it as
# sent or delivered.
_TEXTBEE_STATUS_MAP = {
    "pending": "queued",
    "dispatched": "sending",
    "sent": "sent",
    "delivered": "delivered",
    "failed": "failed",
    "delivery_failed": "undelivered",
    "unknown": "sending",
}


def map_textbee_status(raw_status):
    """Translate a TextBee status string. Missing or unrecognised values map to
    'queued' so we never over-claim that a message was sent or delivered."""
    return _TEXTBEE_STATUS_MAP.get((raw_status or "").lower(), "queued")


def _error_detail(response):
    """Best-effort short text from an error response body (never raises)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    raw = body.get("error") or body.get("message") or ""
    if isinstance(raw, (list, tuple)):
        raw = "; ".join(str(item) for item in raw)
    return str(raw).strip()[:150]


# --- Backends ---------------------------------------------------------------

class SimulatedBackend:
    """Does NOT send anything. Useful while building the UI offline."""

    is_simulated = True

    def send(self, to, body):
        sid = "SIM" + uuid.uuid4().hex[:21]
        logger.info("[simulated] would send SMS to %s (%d characters)", to, len(body))
        return SMSResult(sid=sid, status="queued")

    def fetch_status(self, sid):
        # A simulation can never confirm real delivery.
        return "sent"


class TextBeeBackend:
    """Sends SMS through the TextBee gateway (an Android phone you own)."""

    is_simulated = False

    # -- public interface ------------------------------------------------------

    def send(self, to, body):
        payload = {"recipients": [to], "message": body}
        if settings.TEXTBEE_DEVICE_ID:
            payload["deviceId"] = settings.TEXTBEE_DEVICE_ID

        data = self._request("POST", "/gateway/send-sms", json=payload)

        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            inner = {}
        if inner.get("success") is False:
            raise SMSProviderError(
                "TextBee did not accept the message"
                + (f": {str(inner.get('message'))[:150]}" if inner.get("message") else ".")
            )

        batch_id = str(inner.get("smsBatchId") or "")
        if not batch_id:
            logger.warning("TextBee accepted the request but returned no smsBatchId")
        # A successful response only means "queued"; it is not a delivery.
        return SMSResult(sid=batch_id, status="queued")

    def fetch_status(self, sid):
        data = self._request(
            "GET",
            "/gateway/messages",
            params={"smsBatchId": sid, "direction": "sent", "limit": 10},
        )
        messages = data.get("data") if isinstance(data, dict) else None
        if not messages or not isinstance(messages, list) or not isinstance(messages[0], dict):
            return "queued"
        return map_textbee_status(messages[0].get("status"))

    # -- helpers -----------------------------------------------------------------

    def _request(self, method, path, **kwargs):
        api_key = settings.TEXTBEE_API_KEY
        if not api_key:
            raise SMSConfigurationError(
                "SMS is not configured: TEXTBEE_API_KEY is missing. "
                "Add it to the .env file and restart the server."
            )

        url = settings.TEXTBEE_BASE_URL.rstrip("/") + path
        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            # TextBee sits behind Cloudflare, which can block default client user agents.
            "User-Agent": USER_AGENT,
        }
        try:
            response = requests.request(
                method, url, headers=headers, timeout=settings.SMS_REQUEST_TIMEOUT, **kwargs
            )
        except requests.exceptions.Timeout as exc:
            raise SMSConnectionError(
                "TextBee took too long to respond. Please try again."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise SMSConnectionError(
                "Could not reach TextBee. Check your internet connection and try again."
            ) from exc

        if response.status_code >= 400:
            raise self._http_error(response)

        try:
            return response.json()
        except ValueError as exc:
            raise SMSProviderError("TextBee returned an unexpected response. Please try again.") from exc

    @staticmethod
    def _http_error(response):
        status = response.status_code
        detail = _error_detail(response)
        logger.warning("TextBee returned HTTP %s: %s", status, detail)

        if status == 401:
            return SMSConfigurationError(
                "TextBee rejected the API key. Check TEXTBEE_API_KEY in the .env file "
                "(the key may be wrong or revoked)."
            )
        if status == 404:
            return SMSConfigurationError(
                "TextBee could not find that device. Check TEXTBEE_DEVICE_ID in the .env file, "
                "or leave it empty to use your default phone."
            )
        if status == 403:
            return SMSProviderError("TextBee blocked the request (HTTP 403). Please try again later.")
        if status == 429:
            return SMSProviderError(
                "Your TextBee plan limit has been reached"
                + (f" ({detail})" if detail else "")
                + ". Wait or check your plan in the TextBee dashboard."
            )
        if status == 400:
            lowered = detail.lower()
            if "no enabled device" in lowered or ("device" in lowered and "disabled" in lowered):
                return SMSProviderError(
                    "TextBee has no enabled phone. Open the TextBee app on your Android phone, "
                    "make sure the device is registered and enabled in the dashboard, then try again."
                )
            if "verif" in lowered and "email" in lowered:
                return SMSProviderError("Verify your email address in the TextBee dashboard first.")
            return SMSProviderError(
                "TextBee rejected the message" + (f": {detail}" if detail else ".")
            )
        if status >= 500:
            return SMSProviderError("TextBee is temporarily unavailable. Please try again later.")
        return SMSProviderError(f"TextBee returned an unexpected error (HTTP {status}).")


# --- Factory ----------------------------------------------------------------

def get_backend():
    """Return the backend selected by the SMS_BACKEND setting."""
    name = settings.SMS_BACKEND
    if name == "textbee":
        return TextBeeBackend()
    if name in ("console", "simulated"):
        return SimulatedBackend()
    raise SMSConfigurationError(
        f"Unknown SMS_BACKEND '{name}'. Use 'textbee' (real) or 'console' (simulation)."
    )
