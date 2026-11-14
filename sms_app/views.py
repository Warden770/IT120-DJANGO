import logging

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ContactForm, SendSMSForm
from .models import Contact, SMSMessage
from .services import SMSError, get_backend

logger = logging.getLogger(__name__)

HISTORY_PAGE_SIZE = 10
REFRESH_BATCH_LIMIT = 25


def _backend_is_simulated():
    return settings.SMS_BACKEND in ("console", "simulated")


def send_sms(request):
    """Show the compose form and, on POST, validate it and send the SMS."""
    if request.method == "POST":
        form = SendSMSForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data["phone_number"]
            body = form.cleaned_data["message"]
            record = SMSMessage(recipient=recipient, body=body)
            try:
                result = get_backend().send(recipient, body)
            except SMSError as exc:
                record.status = SMSMessage.FAILED
                record.error_message = exc.user_message[:255]
                record.save()
                messages.error(request, exc.user_message)
            else:
                record.status = result.status
                record.provider_sid = result.sid
                record.save()
                if _backend_is_simulated():
                    messages.warning(
                        request,
                        f"SIMULATION: no real SMS was sent to {recipient}. "
                        "Set SMS_BACKEND=textbee to send real messages.",
                    )
                else:
                    messages.success(
                        request,
                        f"Message to {recipient} was accepted by the SMS provider "
                        f"(status: {record.get_status_display()}). "
                        "This does not confirm delivery - open History and use Refresh status.",
                    )
                return redirect("sms_app:send")
    else:
        form = SendSMSForm()

    return render(
        request,
        "sms_app/send.html",
        {
            "form": form,
            "contacts": Contact.objects.all(),
            "max_length": settings.SMS_MAX_LENGTH,
            "simulated": _backend_is_simulated(),
        },
    )


def history(request):
    """Dashboard of previous sending attempts with simple statistics."""
    stats = SMSMessage.objects.aggregate(
        total=Count("id"),
        delivered=Count("id", filter=Q(status=SMSMessage.DELIVERED)),
        failed=Count("id", filter=Q(status__in=[SMSMessage.FAILED, SMSMessage.UNDELIVERED])),
        pending=Count("id", filter=Q(status__in=SMSMessage.PENDING_STATUSES)),
    )
    page = Paginator(SMSMessage.objects.all(), HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "sms_app/history.html",
        {"page": page, "stats": stats, "simulated": _backend_is_simulated()},
    )


@require_POST
def refresh_status(request, pk):
    """Ask the provider for the latest status of one message."""
    record = get_object_or_404(SMSMessage, pk=pk)
    if not record.provider_sid:
        messages.info(request, "This attempt was never accepted by the provider, so there is no status to refresh.")
        return redirect("sms_app:history")
    try:
        new_status = get_backend().fetch_status(record.provider_sid)
    except SMSError as exc:
        messages.error(request, exc.user_message)
    else:
        record.status = new_status
        record.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Status updated: {record.get_status_display()}.")
    return redirect("sms_app:history")


@require_POST
def refresh_pending(request):
    """Refresh every message whose status can still change."""
    pending = SMSMessage.objects.filter(status__in=SMSMessage.PENDING_STATUSES).exclude(provider_sid="")
    pending = list(pending[:REFRESH_BATCH_LIMIT])
    if not pending:
        messages.info(request, "No messages are waiting for a status update.")
        return redirect("sms_app:history")

    try:
        backend = get_backend()
        updated = 0
        for record in pending:
            new_status = backend.fetch_status(record.provider_sid)
            if new_status != record.status:
                record.status = new_status
                record.save(update_fields=["status", "updated_at"])
                updated += 1
    except SMSError as exc:
        messages.error(request, exc.user_message)
    else:
        messages.success(request, f"Checked {len(pending)} message(s); {updated} changed.")
    return redirect("sms_app:history")


def contacts(request):
    """List saved contacts and add a new one."""
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save()
            messages.success(request, f"Saved {contact.name} ({contact.phone_number}).")
            return redirect("sms_app:contacts")
    else:
        form = ContactForm()
    return render(request, "sms_app/contacts.html", {"form": form, "contacts": Contact.objects.all()})


@require_POST
def contact_delete(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    name = contact.name
    contact.delete()
    messages.success(request, f"Deleted {name}.")
    return redirect("sms_app:contacts")
