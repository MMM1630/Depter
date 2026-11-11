from django.contrib import admin

from apps.accounts.admin import NoDeleteAdmin

from .models import Branch


@admin.register(Branch)
class BranchAdmin(NoDeleteAdmin):
    list_display = ("name", "organization", "is_active")
    list_filter = ("is_active", "organization")
    search_fields = ("name",)
