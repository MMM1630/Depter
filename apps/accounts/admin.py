from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Depter", {"fields": ("role", "branch")}),)
    list_display = ("username", "role", "branch", "is_active")
