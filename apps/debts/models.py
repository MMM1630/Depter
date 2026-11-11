from decimal import Decimal

import django
from django.conf import settings
from django.db import models
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import ImmutableRecordError

# CheckConstraint(check=...) переименован в condition= в Django 5.1
_CHECK = "condition" if django.VERSION >= (5, 1) else "check"


def normalize_name(value):
    """'  НурСултан  ' и 'нурсултан' — один и тот же клиент."""
    return " ".join(str(value).split()).casefold()


class CustomerQuerySet(models.QuerySet):
    def with_balance(self):
        zero = Value(Decimal("0"), output_field=DecimalField())
        return self.annotate(
            balance=Coalesce(Sum("transactions__amount", filter=Q(transactions__kind="debt")), zero)
            - Coalesce(Sum("transactions__amount", filter=Q(transactions__kind="payment")), zero)
        )


class Customer(models.Model):
    branch = models.ForeignKey("shops.Branch", on_delete=models.PROTECT, related_name="customers")
    name = models.CharField("Имя", max_length=120)
    name_key = models.CharField(max_length=255, editable=False)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    is_blocked = models.BooleanField("Не давать в долг", default=False)
    is_archived = models.BooleanField("В архиве", default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    objects = CustomerQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "name_key"], name="uniq_customer_per_branch"),
        ]
        indexes = [models.Index(fields=["branch", "is_archived"], name="customer_branch_arch_idx")]

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.split())
        self.name_key = normalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class TransactionQuerySet(models.QuerySet):
    def effective(self):
        """Операции без отменённых и без самих отмен (пара взаимно гасится)."""
        return self.filter(reversal_of__isnull=True, reversed_by__isnull=True)

    def update(self, **kwargs):
        raise ImmutableRecordError("Финансовые записи не изменяются: используйте отмену.")

    def delete(self):
        raise ImmutableRecordError("Финансовые записи не удаляются: используйте отмену.")


class Transaction(models.Model):
    """Неизменяемая запись. Исправление — только компенсирующая запись (reversal_of)."""

    class Kind(models.TextChoices):
        DEBT = "debt", "Долг"
        PAYMENT = "payment", "Оплата"

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    note = models.CharField("Комментарий", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    # когда операция произошла на самом деле (можно задним числом)
    occurred_at = models.DateTimeField("Дата операции", default=timezone.now)
    # когда запись внесена в систему (не редактируется)
    created_at = models.DateTimeField("Записано", auto_now_add=True)
    # защита от повторной отправки формы
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    # запись-отмена ссылается на отменяемую операцию
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="reversed_by", editable=False,
    )

    objects = TransactionQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["customer", "-occurred_at"], name="txn_customer_date_idx"),
            models.Index(fields=["kind", "occurred_at"], name="txn_kind_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(**{_CHECK: Q(amount__gt=0)}, name="txn_amount_positive"),
            models.CheckConstraint(**{_CHECK: Q(kind__in=["debt", "payment"])}, name="txn_kind_valid"),
        ]

    @property
    def is_reversal(self):
        return self.reversal_of_id is not None

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError("Финансовые записи не изменяются: используйте отмену.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError("Финансовые записи не удаляются: используйте отмену.")

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} · {self.customer}"
