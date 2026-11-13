"""SMS provider integration.

The views only talk to the small interface defined here
(``get_backend().send(...)`` / ``.fetch_status(...)``), so the provider can be
swapped or faked in tests without touching view code.

Two backends are provided:

* ``TwilioBackend``  - real delivery through the Twilio REST API.
* ``SimulatedBackend`` - sends nothing; for UI development only.

Every failure is converted into a subclass of ``SMSError`` that carries a
``user_message`` which is safe to show to the user (it never contains
credentials or raw stack traces).
"""
import logging
import uuid
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


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
    sid: str
    status: str  # one of SMSMessage.STATUS_CHOICES values


# Twilio message statuses -> the statuses stored by this app.
_TWILIO_STATUS_MAP = {
    "accepted": "queued",
    "scheduled": "queued",
    "queued": "queued",
    "sending": "sending",
    "sent": "sent",
    "delivered": "delivered",
    "undelivered": "undelivered",
    "failed": "failed",
    "canceled": "failed",
}


def map_twilio_status(raw_status):
    """Translate a Twilio status string; unknown values are treated as 'sent'
    (handed over, delivery unconfirmed) so we never over-claim delivery."""
    return _TWILIO_STATUS_MAP.get((raw_status or "").lower(), "sent")


# Friendly texts for the most common Twilio error codes.
_TWILIO_ERROR_TEXT = {
    21211: "The provider says that phone number is not valid. Check the number and try again.",
    21214: "The provider says that phone number cannot receive SMS.",
    21408: "Your provider account is not permitted to send SMS to that country.",
    21606: "The configured sender number cannot send SMS. Check TWILIO_PHONE_NUMBER.",
    21608: "This number is not verified for your Twilio trial account. "
           "Verify it in the Twilio Console first (trial accounts can only text verified numbers).",
    21610: "That recipient has opted out of receiving messages from this sender.",
    21614: "That number is not a mobile number that can receive SMS.",
    21612: "The sender number cannot send to that destination.",
    21617: "The message is too long for the provider.",
    20429: "Too many requests were sent to the provider. Wait a moment and try again.",
}


# --- Backends ---------------------------------------------------------------

class SimulatedBackend:
    """Does NOT send anything. Useful while building the UI offline."""

    is_simulated = True

    def send(self, to, body):
        sid = "SIM" + uuid.uuid4().hex[:30]
        logger.info("[simulated] would send SMS to %s (%d characters)", to, len(body))
        return SMSResult(sid=sid, status="queued")

    def fetch_status(self, sid):
        # A simulation can never confirm real delivery.
        return "sent"


class TwilioBackend:
    """Sends SMS through Twilio's REST API."""

    is_simulated = False

    def _client(self):
        account_sid = settings.TWILIO_ACCOUNT_SID
        auth_token = settings.TWILIO_AUTH_TOKEN
        if not account_sid or not auth_token:
            raise SMSConfigurationError(
                "SMS is not configured: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are missing. "
                "Add them to the .env file and restart the server."
            )
        if not (settings.TWILIO_PHONE_NUMBER or settings.TWILIO_MESSAGING_SERVICE_SID):
            raise SMSConfigurationError(
                "SMS is not configured: set TWILIO_PHONE_NUMBER (or TWILIO_MESSAGING_SERVICE_SID) "
                "in the .env file and restart the server."
            )
        try:
            from twilio.http.http_client import TwilioHttpClient
            from twilio.rest import Client
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise SMSConfigurationError(
                "The 'twilio' package is not installed. Run: pip install -r requirements.txt"
            ) from exc

        http_client = TwilioHttpClient(timeout=settings.SMS_REQUEST_TIMEOUT)
        return Client(account_sid, auth_token, http_client=http_client)

    def send(self, to, body):
        client = self._client()
        params = {"to": to, "body": body}
        if settings.TWILIO_MESSAGING_SERVICE_SID:
            params["messaging_service_sid"] = settings.TWILIO_MESSAGING_SERVICE_SID
        else:
            params["from_"] = settings.TWILIO_PHONE_NUMBER

        try:
            message = client.messages.create(**params)
        except Exception as exc:  # converted to a safe, user-facing SMSError
            raise self._translate(exc) from exc

        return SMSResult(sid=message.sid, status=map_twilio_status(message.status))

    def fetch_status(self, sid):
        client = self._client()
        try:
            message = client.messages(sid).fetch()
        except Exception as exc:
            raise self._translate(exc) from exc
        return map_twilio_status(message.status)

    @staticmethod
    def _translate(exc):
        """Map any exception raised while talking to Twilio to an SMSError."""
        try:
            import requests
            from twilio.base.exceptions import TwilioRestException
        except ImportError:  # pragma: no cover
            return SMSProviderError("Unexpected error while contacting the SMS provider.")

        if isinstance(exc, TwilioRestException):
            logger.warning("Twilio rejected the request: status=%s code=%s msg=%s", exc.status, exc.code, exc.msg)
            if exc.status == 401 or exc.code == 20003:
                return SMSConfigurationError(
                    "The SMS provider rejected the account credentials. "
                    "Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in the .env file."
                )
            if exc.code in _TWILIO_ERROR_TEXT:
                return SMSProviderError(_TWILIO_ERROR_TEXT[exc.code])
            detail = (exc.msg or "").strip()[:150]
            return SMSProviderError(
                "The SMS provider rejected the message" + (f": {detail}" if detail else ".")
            )

        if isinstance(exc, requests.exceptions.Timeout):
            return SMSConnectionError("The SMS provider took too long to respond. Please try again.")
        if isinstance(exc, requests.exceptions.RequestException):
            return SMSConnectionError(
                "Could not reach the SMS provider. Check your internet connection and try again."
            )

        logger.exception("Unexpected error while contacting the SMS provider")
        return SMSProviderError("Unexpected error while contacting the SMS provider. Please try again.")


# --- Factory ----------------------------------------------------------------

def get_backend():
    """Return the backend selected by the SMS_BACKEND setting."""
    name = settings.SMS_BACKEND
    if name == "twilio":
        return TwilioBackend()
    if name in ("console", "simulated"):
        return SimulatedBackend()
    raise SMSConfigurationError(
        f"Unknown SMS_BACKEND '{name}'. Use 'twilio' (real) or 'console' (simulation)."
    )
