"""Automated tests. No real SMS is ever sent: the provider is always faked.

Run with:  python manage.py test
"""
from unittest import mock

import requests
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
    TextBeeBackend,
    map_textbee_status,
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


# --- Provider integration (HTTP calls mocked) --------------------------------------

TEXTBEE_SETTINGS = dict(
    SMS_BACKEND="textbee",
    TEXTBEE_API_KEY="super-secret-key",
    TEXTBEE_DEVICE_ID="",
    TEXTBEE_BASE_URL="https://api.textbee.dev/api/v1",
)


def fake_response(status_code=200, body=None, json_error=False):
    response = mock.Mock()
    response.status_code = status_code
    if json_error:
        response.json.side_effect = ValueError("not json")
    else:
        response.json.return_value = body if body is not None else {}
    return response


def patch_http(**kwargs):
    return mock.patch("sms_app.services.requests.request", **kwargs)


class TextBeeBackendTests(SimpleTestCase):
    @override_settings(**{**TEXTBEE_SETTINGS, "TEXTBEE_API_KEY": ""})
    def test_missing_api_key_raises_configuration_error(self):
        with patch_http() as request:
            with self.assertRaises(SMSConfigurationError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("TEXTBEE_API_KEY", ctx.exception.user_message)
        request.assert_not_called()

    @override_settings(**TEXTBEE_SETTINGS)
    def test_successful_send_returns_batch_id_and_queued_status(self):
        body = {"data": {"success": True, "message": "SMS added to queue", "smsBatchId": "batch123", "recipientCount": 1}}
        with patch_http(return_value=fake_response(200, body)) as request:
            result = TextBeeBackend().send("+639171234567", "hi")
        self.assertEqual(result, SMSResult(sid="batch123", status="queued"))
        args, kwargs = request.call_args
        self.assertEqual(args, ("POST", "https://api.textbee.dev/api/v1/gateway/send-sms"))
        self.assertEqual(kwargs["json"], {"recipients": ["+639171234567"], "message": "hi"})
        self.assertEqual(kwargs["headers"]["x-api-key"], "super-secret-key")

    @override_settings(**{**TEXTBEE_SETTINGS, "TEXTBEE_DEVICE_ID": "dev42"})
    def test_device_id_is_sent_when_configured(self):
        body = {"data": {"success": True, "smsBatchId": "b1"}}
        with patch_http(return_value=fake_response(200, body)) as request:
            TextBeeBackend().send("+639171234567", "hi")
        self.assertEqual(request.call_args.kwargs["json"]["deviceId"], "dev42")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_send_never_reports_more_than_queued(self):
        body = {"data": {"success": True, "smsBatchId": "b1"}}
        with patch_http(return_value=fake_response(200, body)):
            self.assertEqual(TextBeeBackend().send("+639171234567", "hi").status, "queued")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_unsuccessful_payload_raises_provider_error(self):
        body = {"data": {"success": False, "message": "quota"}}
        with patch_http(return_value=fake_response(200, body)):
            with self.assertRaises(SMSProviderError):
                TextBeeBackend().send("+639171234567", "hi")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_wrong_api_key_does_not_leak_secrets(self):
        with patch_http(return_value=fake_response(401, {"error": "Unauthorized", "code": "AUTH_INVALID"})):
            with self.assertRaises(SMSConfigurationError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertNotIn("super-secret-key", ctx.exception.user_message)
        self.assertIn("TEXTBEE_API_KEY", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_no_enabled_device_gets_a_helpful_message(self):
        body = {"error": "No enabled device found. Enable a device or pass a deviceId."}
        with patch_http(return_value=fake_response(400, body)):
            with self.assertRaises(SMSProviderError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("TextBee app", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_other_bad_request_includes_the_provider_reason(self):
        with patch_http(return_value=fake_response(400, {"message": ["recipient is invalid"]})):
            with self.assertRaises(SMSProviderError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("recipient is invalid", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_unknown_device_is_a_configuration_error(self):
        with patch_http(return_value=fake_response(404, {"message": "Device not found"})):
            with self.assertRaises(SMSConfigurationError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("TEXTBEE_DEVICE_ID", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_plan_limit_is_reported(self):
        with patch_http(return_value=fake_response(429, {"message": "Daily limit reached"})):
            with self.assertRaises(SMSProviderError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("limit", ctx.exception.user_message.lower())

    @override_settings(**TEXTBEE_SETTINGS)
    def test_server_error_is_reported_without_internals(self):
        with patch_http(return_value=fake_response(500, json_error=True)):
            with self.assertRaises(SMSProviderError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("temporarily unavailable", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_network_error_becomes_connection_error(self):
        with patch_http(side_effect=requests.exceptions.ConnectionError("down")):
            with self.assertRaises(SMSConnectionError):
                TextBeeBackend().send("+639171234567", "hi")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_timeout_becomes_connection_error(self):
        with patch_http(side_effect=requests.exceptions.Timeout("slow")):
            with self.assertRaises(SMSConnectionError) as ctx:
                TextBeeBackend().send("+639171234567", "hi")
        self.assertIn("too long", ctx.exception.user_message)

    @override_settings(**TEXTBEE_SETTINGS)
    def test_non_json_success_response_is_a_provider_error(self):
        with patch_http(return_value=fake_response(200, json_error=True)):
            with self.assertRaises(SMSProviderError):
                TextBeeBackend().send("+639171234567", "hi")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_fetch_status_maps_the_first_message_status(self):
        body = {"data": [{"_id": "m1", "status": "delivered"}], "meta": {"hasMore": False}}
        with patch_http(return_value=fake_response(200, body)) as request:
            self.assertEqual(TextBeeBackend().fetch_status("batch123"), "delivered")
        args, kwargs = request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(kwargs["params"]["smsBatchId"], "batch123")

    @override_settings(**TEXTBEE_SETTINGS)
    def test_fetch_status_with_no_messages_stays_queued(self):
        with patch_http(return_value=fake_response(200, {"data": [], "meta": {}})):
            self.assertEqual(TextBeeBackend().fetch_status("batch123"), "queued")


class StatusMappingTests(SimpleTestCase):
    def test_known_statuses(self):
        self.assertEqual(map_textbee_status("pending"), "queued")
        self.assertEqual(map_textbee_status("dispatched"), "sending")
        self.assertEqual(map_textbee_status("sent"), "sent")
        self.assertEqual(map_textbee_status("delivered"), "delivered")
        self.assertEqual(map_textbee_status("failed"), "failed")

    def test_unknown_or_missing_status_never_claims_sent_or_delivered(self):
        self.assertEqual(map_textbee_status("unknown"), "sending")
        self.assertEqual(map_textbee_status("something-new"), "queued")
        self.assertEqual(map_textbee_status(None), "queued")


class BackendFactoryTests(SimpleTestCase):
    @override_settings(SMS_BACKEND="textbee")
    def test_textbee_backend_selected(self):
        self.assertIsInstance(services.get_backend(), TextBeeBackend)

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
