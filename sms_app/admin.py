from django.contrib import admin

from .models import Contact, SMSMessage


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "phone_number", "created_at")
    search_fields = ("name", "phone_number")


@admin.register(SMSMessage)
class SMSMessageAdmin(admin.ModelAdmin):
    list_display = ("recipient", "status", "created_at", "provider_sid")
    list_filter = ("status",)
    search_fields = ("recipient", "body", "provider_sid")
    readonly_fields = ("created_at", "updated_at")
