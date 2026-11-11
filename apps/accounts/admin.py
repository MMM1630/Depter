from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, Organization, User


class ReadOnlyAdmin(admin.ModelAdmin):
    """Только просмотр: ни добавить, ни изменить, ни удалить через админку."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class NoDeleteAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Depter", {"fields": ("role", "organization", "branch")}),)
    add_fieldsets = UserAdmin.add_fieldsets + ((None, {"fields": ("role", "organization", "branch")}),)
    list_display = ("username", "role", "organization", "branch", "is_active")
    list_filter = ("role", "is_active", "organization")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(NoDeleteAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "organization", "username", "action", "object_type", "object_id", "ip")
    list_filter = ("action", "organization")
    search_fields = ("username", "object_id")
    date_hierarchy = "created_at"
