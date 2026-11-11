from django.db import models
from django.utils import timezone


class Branch(models.Model):
    """Филиал. Удалять нельзя (история долгов): вместо этого is_active=False (архив)."""

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.PROTECT, related_name="branches",
    )
    name = models.CharField("Название", max_length=120)
    address = models.CharField("Адрес", max_length=255, blank=True)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_branch_name_per_org"),
        ]

    def __str__(self):
        return self.name
