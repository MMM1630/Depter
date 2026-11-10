from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone


class CustomerQuerySet(models.QuerySet):
    def with_balance(self):
        zero = Value(Decimal("0"), output_field=DecimalField())
        return self.annotate(
            balance=Coalesce(Sum("transactions__amount", filter=Q(transactions__kind="debt")), zero)
            - Coalesce(Sum("transactions__amount", filter=Q(transactions__kind="payment")), zero)
        )


class Customer(models.Model):
    branch = models.ForeignKey("shops.Branch", on_delete=models.CASCADE, related_name="customers")
    name = models.CharField("Имя", max_length=120)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CustomerQuerySet.as_manager()

    class Meta:
        unique_together = ("branch", "name")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    class Kind(models.TextChoices):
        DEBT = "debt", "Долг"
        PAYMENT = "payment", "Оплата"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    note = models.CharField("Комментарий", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    # раньше было auto_now_add; теперь дату долга можно указать вручную
    created_at = models.DateTimeField("Дата", default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
