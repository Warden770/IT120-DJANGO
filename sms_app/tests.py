"""Automated tests. No real SMS is ever sent: the provider is always faked.

Run with:  python manage.py test
"""
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import services
from .models import Contact, SMSMessage
from .services import (
    SMSConfigurationError,
    SMSConnectionError,
    SMSProviderError,
    SMSResult,
    SimulatedBackend,
    TwilioBackend,
    map_twilio_status,
)
from .validators import normalize_phone_number, validate_message_body


# --- Helpers ------------------------------------------------------------------

class FakeBackend:
    """Stands in for the real provider."""

    is_simulated = False

    def __init__(self, result=None, error=None, status_after_refresh="delivered"):
        self.result = result or SMSResult(sid="SM123", status="queued")
        self.error = error
        self.status_after_refresh = status_after_refresh
        self.sent = []

    def send(self, to, body):
        self.sent.append((to, body))
        if self.error:
            raise self.error
        return self.result

    def fetch_status(self, sid):
        if self.error:
            raise self.error
        return self.status_after_refresh


def patch_backend(backend):
    return mock.patch("sms_app.views.get_backend", return_value=backend)


# --- Validation ---------------------------------------------------------------

class PhoneNumberValidationTests(SimpleTestCase):
    def test_international_number_is_kept(self):
        self.assertEqual(normalize_phone_number("+639171234567", "63"), "+639171234567")

    def test_formatting_characters_are_removed(self):
        self.assertEqual(normalize_phone_number("+63 (917) 123-4567", "63"), "+639171234567")

    def test_local_number_gets_country_code(self):
        self.assertEqual(normalize_phone_number("09171234567", "63"), "+639171234567")

    def test_double_zero_prefix(self):
        self.assertEqual(normalize_phone_number("00639171234567", "63"), "+639171234567")

    def test_number_starting_with_country_code(self):
        self.assertEqual(normalize_phone_number("639171234567", "63"), "+639171234567")

    def test_empty_number_is_rejected(self):
        for value in ("", "   ", None):
            with self.assertRaises(ValidationError) as ctx:
                normalize_phone_number(value, "63")
            self.assertEqual(ctx.exception.code, "required")

    def test_letters_are_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("0917abc4567", "63")

    def test_plus_in_the_middle_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("+63917+1234567", "63")

    def test_too_short_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("+6391", "63")

    def test_too_long_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("+6391712345678901234", "63")

    def test_unprefixed_number_without_matching_country_code_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_phone_number("5551234567", "63")


class MessageValidationTests(SimpleTestCase):
    def test_empty_message_is_rejected(self):
        for value in ("", "    \n ", None):
            with self.assertRaises(ValidationError):
                validate_message_body(value, 1600)

    def test_message_is_stripped(self):
        self.assertEqual(validate_message_body("  hello  ", 1600), "hello")

    def test_too_long_message_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_message_body("x" * 11, 10)

    def test_message_at_limit_is_accepted(self):
        self.assertEqual(validate_message_body("x" * 10, 10), "x" * 10)


# --- Views --------------------------------------------------------------------

class SendViewTests(TestCase):
    url = reverse("sms_app:send")

    def post(self, backend, phone="09171234567", message="Hello there"):
        with patch_backend(backend):
            return self.client.post(self.url, {"phone_number": phone, "message": message})

    def test_page_renders_the_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recipient phone number")
        self.assertContains(response, "Send SMS")
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_valid_submission_sends_and_records_the_message(self):
        backend = FakeBackend()
        response = self.post(backend)
        self.assertRedirects(response, self.url)
        self.assertEqual(backend.sent, [("+639171234567", "Hello there")])
        record = SMSMessage.objects.get()
        self.assertEqual(record.status, "queued")
        self.assertEqual(record.provider_sid, "SM123")
        self.assertEqual(record.recipient, "+639171234567")

    def test_success_flash_says_accepted_not_delivered(self):
        with patch_backend(FakeBackend()):
            response = self.client.post(
                self.url, {"phone_number": "09171234567", "message": "Hello"}, follow=True
            )
        flashes = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("accepted" in m.lower() for m in flashes))
        self.assertTrue(any("does not confirm delivery" in m.lower() for m in flashes))

    def test_empty_phone_number_is_rejected_without_sending(self):
        backend = FakeBackend()
        response = self.post(backend, phone="")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please enter a recipient phone number.")
        self.assertEqual(backend.sent, [])
        self.assertEqual(SMSMessage.objects.count(), 0)

    def test_empty_message_is_rejected_without_sending(self):
        backend = FakeBackend()
        response = self.post(backend, message="   ")
        self.assertContains(response, "Please type a message before sending.")
        self.assertEqual(backend.sent, [])

    def test_invalid_phone_number_is_rejected_without_sending(self):
        backend = FakeBackend()
        response = self.post(backend, phone="abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.sent, [])
        self.assertTrue(response.context["form"].errors["phone_number"])

    def test_form_keeps_user_input_after_a_validation_error(self):
        response = self.post(FakeBackend(), phone="+639171234567", message="")
        self.assertContains(response, "+639171234567")

    def test_missing_credentials_show_a_safe_error(self):
        error = SMSConfigurationError("SMS is not configured: credentials are missing.")
        response = self.post(FakeBackend(error=error))
        self.assertContains(response, "SMS is not configured")
        record = SMSMessage.objects.get()
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.provider_sid, "")

    def test_provider_connection_error_is_reported(self):
        error = SMSConnectionError("Could not reach the SMS provider.")
        response = self.post(FakeBackend(error=error))
        self.assertContains(response, "Could not reach the SMS provider.")
        self.assertEqual(SMSMessage.objects.get().status, "failed")

    def test_provider_rejection_is_reported(self):
        error = SMSProviderError("The provider says that phone number is not valid.")
        response = self.post(FakeBackend(error=error))
        self.assertContains(response, "not valid")
        self.assertEqual(SMSMessage.objects.get().status, "failed")

    @override_settings(SMS_BACKEND="console")
    def test_simulation_mode_is_clearly_labelled(self):
        with mock.patch("sms_app.views.get_backend", return_value=SimulatedBackend()):
            response = self.client.post(
                self.url, {"phone_number": "09171234567", "message": "Hello"}, follow=True
            )
        flashes = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("SIMULATION" in m for m in flashes))

    def test_post_without_csrf_token_is_forbidden(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(self.url, {"phone_number": "09171234567", "message": "Hello"})
        self.assertEqual(response.status_code, 403)


class HistoryViewTests(TestCase):
    def setUp(self):
        SMSMessage.objects.create(recipient="+639171234567", body="one", status="delivered", provider_sid="SM1")
        SMSMessage.objects.create(recipient="+639171234567", body="two", status="queued", provider_sid="SM2")
        SMSMessage.objects.create(recipient="+639171234567", body="three", status="failed", error_message="boom")

    def test_history_lists_messages_and_statistics(self):
        response = self.client.get(reverse("sms_app:history"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["total"], 3)
        self.assertEqual(response.context["stats"]["delivered"], 1)
        self.assertEqual(response.context["stats"]["pending"], 1)
        self.assertEqual(response.context["stats"]["failed"], 1)
        self.assertContains(response, "boom")

    def test_refresh_status_updates_a_pending_message(self):
        record = SMSMessage.objects.get(provider_sid="SM2")
        with patch_backend(FakeBackend(status_after_refresh="delivered")):
            self.client.post(reverse("sms_app:refresh_status", args=[record.pk]))
        record.refresh_from_db()
        self.assertEqual(record.status, "delivered")

    def test_refresh_status_reports_provider_errors(self):
        record = SMSMessage.objects.get(provider_sid="SM2")
        backend = FakeBackend(error=SMSConnectionError("Could not reach the SMS provider."))
        with patch_backend(backend):
            response = self.client.post(reverse("sms_app:refresh_status", args=[record.pk]), follow=True)
        self.assertContains(response, "Could not reach the SMS provider.")
        record.refresh_from_db()
        self.assertEqual(record.status, "queued")

    def test_refresh_status_requires_post(self):
        record = SMSMessage.objects.get(provider_sid="SM2")
        response = self.client.get(reverse("sms_app:refresh_status", args=[record.pk]))
        self.assertEqual(response.status_code, 405)

    def test_refresh_pending_only_touches_pending_messages(self):
        with patch_backend(FakeBackend(status_after_refresh="delivered")):
            self.client.post(reverse("sms_app:refresh_pending"))
        self.assertEqual(SMSMessage.objects.filter(status="delivered").count(), 2)
        self.assertEqual(SMSMessage.objects.filter(status="failed").count(), 1)


class ContactViewTests(TestCase):
    def test_add_contact_normalizes_the_number(self):
        response = self.client.post(reverse("sms_app:contacts"), {"name": "Ana", "phone_number": "0917 123 4567"})
        self.assertRedirects(response, reverse("sms_app:contacts"))
        self.assertEqual(Contact.objects.get().phone_number, "+639171234567")

    def test_invalid_contact_number_is_rejected(self):
        response = self.client.post(reverse("sms_app:contacts"), {"name": "Ana", "phone_number": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contact.objects.count(), 0)

    def test_duplicate_number_is_rejected(self):
        Contact.objects.create(name="Ana", phone_number="+639171234567")
        response = self.client.post(reverse("sms_app:contacts"), {"name": "Ben", "phone_number": "09171234567"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contact.objects.count(), 1)

    def test_delete_contact(self):
        contact = Contact.objects.create(name="Ana", phone_number="+639171234567")
        self.client.post(reverse("sms_app:contact_delete", args=[contact.pk]))
        self.assertEqual(Contact.objects.count(), 0)

    def test_saved_contacts_appear_on_the_send_page(self):
        Contact.objects.create(name="Ana", phone_number="+639171234567")
        response = self.client.get(reverse("sms_app:send"))
        self.assertContains(response, "Ana (+639171234567)")


# --- Provider integration (Twilio SDK mocked) ------------------------------------

TWILIO_SETTINGS = dict(
    SMS_BACKEND="twilio",
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_AUTH_TOKEN="super-secret-token",
    TWILIO_PHONE_NUMBER="+15005550006",
    TWILIO_MESSAGING_SERVICE_SID="",
)


class TwilioBackendTests(SimpleTestCase):
    @override_settings(**{**TWILIO_SETTINGS, "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": ""})
    def test_missing_credentials_raise_configuration_error(self):
        with self.assertRaises(SMSConfigurationError) as ctx:
            TwilioBackend().send("+639171234567", "hi")
        self.assertIn("TWILIO_ACCOUNT_SID", ctx.exception.user_message)

    @override_settings(**{**TWILIO_SETTINGS, "TWILIO_PHONE_NUMBER": ""})
    def test_missing_sender_raises_configuration_error(self):
        with self.assertRaises(SMSConfigurationError):
            TwilioBackend().send("+639171234567", "hi")

    @override_settings(**TWILIO_SETTINGS)
    def test_successful_send_returns_sid_and_status(self):
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = mock.Mock(sid="SMabc", status="queued")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            result = TwilioBackend().send("+639171234567", "hi")
        self.assertEqual(result, SMSResult(sid="SMabc", status="queued"))
        fake_client.messages.create.assert_called_once_with(to="+639171234567", body="hi", from_="+15005550006")

    @override_settings(**{**TWILIO_SETTINGS, "TWILIO_MESSAGING_SERVICE_SID": "MG123"})
    def test_messaging_service_is_preferred_over_phone_number(self):
        fake_client = mock.MagicMock()
        fake_client.messages.create.return_value = mock.Mock(sid="SMabc", status="queued")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            TwilioBackend().send("+639171234567", "hi")
        fake_client.messages.create.assert_called_once_with(
            to="+639171234567", body="hi", messaging_service_sid="MG123"
        )

    @override_settings(**TWILIO_SETTINGS)
    def test_wrong_credentials_do_not_leak_secrets(self):
        from twilio.base.exceptions import TwilioRestException

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = TwilioRestException(401, "/Messages", "Authenticate", 20003)
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            with self.assertRaises(SMSConfigurationError) as ctx:
                TwilioBackend().send("+639171234567", "hi")
        self.assertNotIn("super-secret-token", ctx.exception.user_message)

    @override_settings(**TWILIO_SETTINGS)
    def test_unverified_trial_number_gets_a_helpful_message(self):
        from twilio.base.exceptions import TwilioRestException

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = TwilioRestException(400, "/Messages", "unverified", 21608)
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            with self.assertRaises(SMSProviderError) as ctx:
                TwilioBackend().send("+639171234567", "hi")
        self.assertIn("verified", ctx.exception.user_message)

    @override_settings(**TWILIO_SETTINGS)
    def test_network_error_becomes_connection_error(self):
        import requests

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = requests.exceptions.ConnectionError("down")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            with self.assertRaises(SMSConnectionError):
                TwilioBackend().send("+639171234567", "hi")

    @override_settings(**TWILIO_SETTINGS)
    def test_timeout_becomes_connection_error(self):
        import requests

        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = requests.exceptions.Timeout("slow")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            with self.assertRaises(SMSConnectionError) as ctx:
                TwilioBackend().send("+639171234567", "hi")
        self.assertIn("too long", ctx.exception.user_message)

    @override_settings(**TWILIO_SETTINGS)
    def test_unexpected_error_is_wrapped(self):
        fake_client = mock.MagicMock()
        fake_client.messages.create.side_effect = RuntimeError("secret internals")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            with self.assertRaises(SMSProviderError) as ctx:
                TwilioBackend().send("+639171234567", "hi")
        self.assertNotIn("secret internals", ctx.exception.user_message)

    @override_settings(**TWILIO_SETTINGS)
    def test_fetch_status_maps_provider_status(self):
        fake_client = mock.MagicMock()
        fake_client.messages.return_value.fetch.return_value = mock.Mock(status="delivered")
        with mock.patch("twilio.rest.Client", return_value=fake_client):
            self.assertEqual(TwilioBackend().fetch_status("SMabc"), "delivered")


class StatusMappingTests(SimpleTestCase):
    def test_known_statuses(self):
        self.assertEqual(map_twilio_status("accepted"), "queued")
        self.assertEqual(map_twilio_status("delivered"), "delivered")
        self.assertEqual(map_twilio_status("undelivered"), "undelivered")

    def test_unknown_status_never_claims_delivery(self):
        self.assertEqual(map_twilio_status("something-new"), "sent")
        self.assertEqual(map_twilio_status(None), "sent")


class BackendFactoryTests(SimpleTestCase):
    @override_settings(SMS_BACKEND="twilio")
    def test_twilio_backend_selected(self):
        self.assertIsInstance(services.get_backend(), TwilioBackend)

    @override_settings(SMS_BACKEND="console")
    def test_console_backend_selected(self):
        self.assertIsInstance(services.get_backend(), SimulatedBackend)

    @override_settings(SMS_BACKEND="carrier-pigeon")
    def test_unknown_backend_is_a_configuration_error(self):
        with self.assertRaises(SMSConfigurationError):
            services.get_backend()

    def test_simulated_backend_never_reports_delivery(self):
        backend = SimulatedBackend()
        result = backend.send("+639171234567", "hi")
        self.assertEqual(result.status, "queued")
        self.assertNotEqual(backend.fetch_status(result.sid), "delivered")
