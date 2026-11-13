from django.urls import path

from . import views

app_name = "sms_app"

urlpatterns = [
    path("", views.send_sms, name="send"),
    path("history/", views.history, name="history"),
    path("history/refresh/", views.refresh_pending, name="refresh_pending"),
    path("history/<int:pk>/refresh/", views.refresh_status, name="refresh_status"),
    path("contacts/", views.contacts, name="contacts"),
    path("contacts/<int:pk>/delete/", views.contact_delete, name="contact_delete"),
]
