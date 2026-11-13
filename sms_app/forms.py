from django import forms
from django.conf import settings

from .models import Contact
from .validators import normalize_phone_number, validate_message_body


class SendSMSForm(forms.Form):
    """Compose form: recipient number + message text."""

    phone_number = forms.CharField(
        label="Recipient phone number",
        max_length=30,
        required=False,  # validated in clean_phone_number for a friendlier message
        widget=forms.TextInput(
            attrs={"placeholder": "+639171234567 or 09171234567", "autocomplete": "off", "inputmode": "tel"}
        ),
    )
    message = forms.CharField(
        label="Message",
        required=False,  # validated in clean_message for a friendlier message
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Type your message here..."}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["message"].widget.attrs["maxlength"] = settings.SMS_MAX_LENGTH

    def clean_phone_number(self):
        return normalize_phone_number(self.cleaned_data.get("phone_number"))

    def clean_message(self):
        return validate_message_body(self.cleaned_data.get("message"))


class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["name", "phone_number"]
        labels = {"phone_number": "Phone number"}
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Juan Dela Cruz"}),
            "phone_number": forms.TextInput(attrs={"placeholder": "+639171234567 or 09171234567"}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Please enter a name.")
        return name

    def clean_phone_number(self):
        return normalize_phone_number(self.cleaned_data.get("phone_number"))
