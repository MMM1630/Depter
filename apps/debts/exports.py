import csv

from django.utils import timezone

from .models import Transaction

HEADER = ["Дата операции", "Записано", "Филиал", "Клиент", "Телефон", "Тип",
          "Сумма (+долг / −оплата)", "Статус", "Комментарий", "Кто записал"]

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def safe(value):
    """Защита от формул в Excel/LibreOffice (CSV-injection)."""
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(_DANGEROUS) else value


class Echo:
    def write(self, value):
        return value


def _kind_label(t):
    if t.reversal_of_id is not None:
        return "Отмена долга" if t.kind == Transaction.Kind.PAYMENT else "Отмена погашения"
    return "Долг" if t.kind == Transaction.Kind.DEBT else "Погашение"


def _status(t):
    if t.reversal_of_id is not None:
        return "Отмена"
    return "Отменена" if t.is_reversed else "Действует"


def stream_csv(rows):
    writer = csv.writer(Echo())
    yield "﻿"  # BOM: Excel открывает UTF-8 корректно
    yield writer.writerow(HEADER)
    for t in rows.iterator(chunk_size=500):
        sign = "" if t.kind == Transaction.Kind.DEBT else "-"
        who = t.created_by.get_full_name() or t.created_by.username if t.created_by else ""
        yield writer.writerow([
            timezone.localtime(t.occurred_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(t.created_at).strftime("%Y-%m-%d %H:%M"),
            safe(t.customer.branch.name),
            safe(t.customer.name),
            safe(t.customer.phone),
            _kind_label(t),
            f"{sign}{t.amount}",
            _status(t),
            safe(t.note),
            safe(who),
        ])
