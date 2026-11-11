from django.contrib import admin

from apps.accounts.admin import NoDeleteAdmin, ReadOnlyAdmin

from .models import Customer, Transaction


@admin.register(Transaction)
class TransactionAdmin(ReadOnlyAdmin):
    list_display = ("occurred_at", "customer", "kind", "amount", "created_by", "created_at", "reversal_of")
    list_filter = ("kind",)
    search_fields = ("customer__name",)
    date_hierarchy = "occurred_at"
    list_select_related = ("customer", "created_by")


@admin.register(Customer)
class CustomerAdmin(NoDeleteAdmin):
    list_display = ("name", "branch", "phone", "is_blocked", "is_archived")
    list_filter = ("is_blocked", "is_archived", "branch")
    search_fields = ("name", "phone")

    def has_add_permission(self, request):
        return False
