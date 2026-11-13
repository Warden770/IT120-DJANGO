from django.db import models


class Contact(models.Model):
    """A saved recipient so numbers do not have to be retyped."""

    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20, unique=True, help_text="Stored in E.164 format.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone_number})"


class SMSMessage(models.Model):
    """One sending attempt, successful or not."""

    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    FAILED = "failed"

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("delivered", "Delivered"),
        ("undelivered", "Undelivered"),
        ("failed", "Failed"),
    ]

    # Statuses that may still change, so it is worth asking the provider again.
    PENDING_STATUSES = (QUEUED, SENDING, SENT)

    STATUS_HELP = {
        QUEUED: "Accepted by the provider and waiting to be sent. Not delivered yet.",
        SENDING: "The provider is handing the message to the carrier. Not delivered yet.",
        SENT: "Handed to the carrier. Delivery has not been confirmed.",
        DELIVERED: "The provider confirmed delivery to the handset.",
        UNDELIVERED: "The provider could not deliver the message.",
        FAILED: "The message was not sent (see the reason).",
    }

    recipient = models.CharField(max_length=20)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    provider_sid = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"To {self.recipient} [{self.status}]"

    @property
    def is_pending(self):
        return self.status in self.PENDING_STATUSES

    @property
    def can_refresh(self):
        return self.is_pending and bool(self.provider_sid)

    @property
    def status_help(self):
        return self.STATUS_HELP.get(self.status, "")
