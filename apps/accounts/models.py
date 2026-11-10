from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        SELLER = "seller", "Продавец"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.SELLER)
    branch = models.ForeignKey(
        "shops.Branch", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="sellers",
    )

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER or self.is_superuser
