from django.conf import settings
from django.db import models


class Branch(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField("Название", max_length=120)
    address = models.CharField("Адрес", max_length=255, blank=True)

    def __str__(self):
        return self.name
