"""Вся денежная логика. Views только вызывают эти функции.

Правила:
* каждая операция идёт внутри transaction.atomic();
* строка клиента блокируется (SELECT ... FOR UPDATE), баланс считается ПОСЛЕ блокировки;
* ключ идемпотентности проверяется ПОСЛЕ блокировки: повторный POST не создаёт вторую запись;
* баланс клиента никогда не уходит в минус;
* записи не меняются и не удаляются: ошибка исправляется компенсирующей записью (отмена).
"""
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.utils import timezone

from apps.accounts import audit
from apps.accounts.i18n import fmt_money, tr
from apps.accounts.mixins import visible_branches

from .models import Customer, Transaction, normalize_name

ZERO = Decimal("0")
CENT = Decimal("0.01")


class DomainError(Exception):
    """Ожидаемая бизнес-ошибка: показывается пользователю на его языке."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key, self.params = key, params

    def message(self):
        return tr(self.key, **self.params)


@dataclass
class Outcome:
    customer: Customer
    txn: Transaction
    duplicate: bool = False


def occurred_datetime(day):
    """Сегодня — текущее время, прошлая дата — полдень этого дня."""
    if day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(datetime.combine(day, time(12, 0)))


def balance_of(customer_id):
    agg = Transaction.objects.filter(customer_id=customer_id).aggregate(
        d=Sum("amount", filter=Q(kind=Transaction.Kind.DEBT)),
        p=Sum("amount", filter=Q(kind=Transaction.Kind.PAYMENT)),
    )
    return (agg["d"] or ZERO) - (agg["p"] or ZERO)


def _money(value):
    try:
        amount = Decimal(value).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise DomainError("err_amount")
    if amount <= 0:
        raise DomainError("err_amount")
    return amount


def _lock_customer(user, customer_id):
    """Строка клиента блокируется до конца транзакции; чужие клиенты = 404."""
    customer = (
        Customer.objects.select_for_update(of=("self",))
        .select_related("branch")
        .filter(pk=customer_id, branch__in=visible_branches(user))
        .first()
    )
    if customer is None:
        raise Http404("customer")
    return customer


def _duplicate(user, key):
    if not key:
        return None
    existing = Transaction.objects.filter(idempotency_key=key).first()
    if existing is None:
        return None
    if existing.created_by_id != user.pk:
        raise DomainError("err_token")
    return existing


def _ensure_can_lend(customer):
    if customer.is_archived:
        raise DomainError("err_archived")
    if customer.is_blocked:
        raise DomainError("err_blocked")
    if not customer.branch.is_active:
        raise DomainError("err_branch_inactive")


def _create(*, customer, kind, amount, occurred_at, note, user, key, reversal_of=None):
    txn = Transaction(
        customer=customer, kind=kind, amount=amount, occurred_at=occurred_at,
        note=(note or "")[:255], created_by=user, idempotency_key=key, reversal_of=reversal_of,
    )
    txn.save()
    return txn


def _check_day(day):
    if day > timezone.localdate():
        raise DomainError("err_future")


@transaction.atomic
def add_debt(*, user, customer_id, amount, on_date, note="", key=None):
    """Новый долг существующему клиенту."""
    customer = _lock_customer(user, customer_id)
    dup = _duplicate(user, key)
    if dup:
        return Outcome(customer, dup, True)
    amount = _money(amount)
    _check_day(on_date)
    _ensure_can_lend(customer)
    txn = _create(customer=customer, kind=Transaction.Kind.DEBT, amount=amount,
                  occurred_at=occurred_datetime(on_date), note=note, user=user, key=key)
    audit.log(user, "debt.add", txn, customer=customer.name, amount=amount, date=on_date)
    return Outcome(customer, txn)


@transaction.atomic
def add_debt_by_name(*, user, branch_id, name, phone="", amount, on_date, note="", key=None):
    """Новый долг по имени: клиент находится без учёта регистра/пробелов или создаётся."""
    branch = visible_branches(user).filter(pk=branch_id).first()
    if branch is None:
        raise Http404("branch")
    clean_name = " ".join(str(name).split())
    if not clean_name:
        raise DomainError("err_enter_name")
    phone = (phone or "").strip()
    customer, created = Customer.objects.get_or_create(
        branch=branch, name_key=normalize_name(clean_name),
        defaults={"name": clean_name, "phone": phone},
    )
    customer = _lock_customer(user, customer.pk)
    dup = _duplicate(user, key)
    if dup:
        return Outcome(customer, dup, True)
    amount = _money(amount)
    _check_day(on_date)
    _ensure_can_lend(customer)
    if phone and customer.phone != phone:
        customer.phone = phone
        customer.save(update_fields=["phone"])
    txn = _create(customer=customer, kind=Transaction.Kind.DEBT, amount=amount,
                  occurred_at=occurred_datetime(on_date), note=note, user=user, key=key)
    audit.log(user, "debt.add", txn, customer=customer.name, amount=amount, date=on_date,
              new_customer=created)
    return Outcome(customer, txn)


@transaction.atomic
def repay(*, user, customer_id, mode, amount=None, key=None):
    """Погашение: 'full' закрывает весь долг, 'partial' — указанную сумму (не больше долга)."""
    customer = _lock_customer(user, customer_id)
    dup = _duplicate(user, key)
    if dup:
        return Outcome(customer, dup, True)
    balance = balance_of(customer.pk)  # считаем только после блокировки
    if balance <= 0:
        raise DomainError("err_no_debt")
    if mode == "full":
        pay, note = balance, "@full"
    elif mode == "partial":
        if amount is None:
            raise DomainError("err_enter_amount")
        pay, note = _money(amount), "@partial"
        if pay > balance:
            raise DomainError("err_too_much", n=fmt_money(balance))
    else:
        raise DomainError("err_amount")
    txn = _create(customer=customer, kind=Transaction.Kind.PAYMENT, amount=pay,
                  occurred_at=timezone.now(), note=note, user=user, key=key)
    audit.log(user, "payment.add", txn, customer=customer.name, amount=pay, mode=mode,
              closed=pay == balance)
    return Outcome(customer, txn)


@transaction.atomic
def reverse_transaction(*, user, txn_id, reason, key=None):
    """Отмена операции компенсирующей записью. Только владелец. Исходная запись остаётся."""
    if not user.is_owner:
        raise PermissionDenied
    original = (
        Transaction.objects.filter(pk=txn_id, customer__branch__in=visible_branches(user)).first()
    )
    if original is None:
        raise Http404("transaction")
    customer = _lock_customer(user, original.customer_id)
    dup = _duplicate(user, key)
    if dup:
        return Outcome(customer, dup, True)
    if original.reversal_of_id is not None or Transaction.objects.filter(reversal_of=original).exists():
        raise DomainError("err_reverse_done")
    if customer.is_archived:
        raise DomainError("err_archived")
    balance = balance_of(customer.pk)
    after = balance - original.amount if original.kind == Transaction.Kind.DEBT else balance + original.amount
    if after < 0:
        raise DomainError("err_reverse_negative")
    opposite = (Transaction.Kind.PAYMENT if original.kind == Transaction.Kind.DEBT
                else Transaction.Kind.DEBT)
    reversal = _create(customer=customer, kind=opposite, amount=original.amount,
                       occurred_at=timezone.now(), note=reason, user=user, key=key,
                       reversal_of=original)
    audit.log(user, "txn.reverse", reversal, original=original.pk, customer=customer.name,
              amount=original.amount, reason=reason)
    return Outcome(customer, reversal)


@transaction.atomic
def set_customer_flag(*, user, customer_id, flag, value):
    """Блокировка (не давать в долг) и архив клиента. Только владелец."""
    if not user.is_owner:
        raise PermissionDenied
    if flag not in ("is_blocked", "is_archived"):
        raise ValueError(flag)
    customer = _lock_customer(user, customer_id)
    if flag == "is_archived" and value and balance_of(customer.pk) != 0:
        raise DomainError("err_archive_balance")
    if getattr(customer, flag) == value:
        return customer
    setattr(customer, flag, value)
    customer.save(update_fields=[flag])
    action = {
        ("is_blocked", True): "customer.block", ("is_blocked", False): "customer.unblock",
        ("is_archived", True): "customer.archive", ("is_archived", False): "customer.restore",
    }[(flag, value)]
    audit.log(user, action, customer, name=customer.name)
    return customer
