from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ImmutableRecordError(RuntimeError):
    """Финансовые записи и журнал аудита не изменяются и не удаляются."""


class Organization(models.Model):
    name = models.CharField("Название", max_length=120)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        SELLER = "seller", "Продавец"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.SELLER)
    organization = models.ForeignKey(
        Organization, null=True, blank=True,
        on_delete=models.PROTECT, related_name="members",
    )
    branch = models.ForeignKey(
        "shops.Branch", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sellers",
    )

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    def clean(self):
        super().clean()
        if self.role == self.Role.OWNER and not self.organization_id:
            raise ValidationError("У владельца должна быть организация.")
        if self.role == self.Role.SELLER and self.branch_id and self.organization_id:
            if self.branch.organization_id != self.organization_id:
                raise ValidationError("Филиал продавца должен принадлежать его организации.")


class AuditLog(models.Model):
    """Журнал действий. Только добавление: изменять и удалять записи нельзя."""

    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    username = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=50, db_index=True)
    object_type = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=40, blank=True)
    details = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "-created_at"], name="audit_org_date_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Журнал аудита нельзя изменять.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Журнал аудита нельзя удалять.")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.username} {self.action}"
