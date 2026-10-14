from django.urls import path

from . import views

app_name = "generator"

urlpatterns = [
    path("", views.index, name="index"),
    path("api/qr", views.qr_api, name="qr-api"),
    path("api/health", views.health, name="health"),
]
