from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# Админка: только суперпользователи, адрес из .env (DJANGO_ADMIN_URL), вход защищён axes.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser
admin.site.site_header = "Depter · control panel"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.debts.urls")),
    path("", include("apps.shops.urls")),
]
