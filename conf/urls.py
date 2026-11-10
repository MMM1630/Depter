from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("control-panel/", admin.site.urls),  # админка отдельно, в приложении не linked
    path("", include("apps.accounts.urls")),
    path("", include("apps.debts.urls")),
    path("", include("apps.shops.urls")),
]
