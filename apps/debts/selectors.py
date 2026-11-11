"""Аналитические запросы (только чтение). Все суммы считаются в Decimal; float только для JSON графика."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Exists, OuterRef, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.i18n import get_lang, tr, whole
from apps.accounts.mixins import visible_branches

from .models import Customer, Transaction, normalize_name

ZERO = Decimal("0")


def visible_customers(user):
    return Customer.objects.filter(branch__in=visible_branches(user))


def visible_transactions(user):
    return Transaction.objects.filter(customer__branch__in=visible_branches(user))


def customers_base(user, q="", archived=False):
    qs = visible_customers(user).filter(is_archived=archived)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name_key__contains=normalize_name(q)) | Q(phone__icontains=q))
    return qs


def total_owed(customers_qs):
    """Суммарный долг выбранных клиентов (customers_qs — без аннотаций)."""
    agg = Transaction.objects.filter(customer__in=customers_qs.values("pk")).aggregate(
        d=Sum("amount", filter=Q(kind="debt")), p=Sum("amount", filter=Q(kind="payment")),
    )
    return (agg["d"] or ZERO) - (agg["p"] or ZERO)


def with_reversal_flag(qs):
    return qs.annotate(is_reversed=Exists(Transaction.objects.filter(reversal_of=OuterRef("pk"))))


def export_rows(user, d_from, d_to):
    qs = (
        visible_transactions(user)
        .filter(occurred_at__date__gte=d_from, occurred_at__date__lte=d_to)
        .select_related("customer", "customer__branch", "created_by")
    )
    return with_reversal_flag(qs).order_by("occurred_at", "id")


def dashboard_data(user, days_n):
    qs = visible_transactions(user).effective()
    tot = qs.aggregate(debt=Sum("amount", filter=Q(kind="debt")), paid=Sum("amount", filter=Q(kind="payment")))
    given, paid = tot["debt"] or ZERO, tot["paid"] or ZERO

    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(days_n - 1, -1, -1)]
    rows = (
        qs.filter(occurred_at__date__gte=days[0])
        .annotate(d=TruncDate("occurred_at"))
        .values("d", "kind")
        .annotate(s=Sum("amount"))
    )
    data = {(r["d"], r["kind"]): r["s"] for r in rows}
    debts = [data.get((d, "debt"), ZERO) for d in days]
    pays = [data.get((d, "payment"), ZERO) for d in days]

    debtors = visible_customers(user).filter(is_archived=False).with_balance().filter(balance__gt=0)
    top = list(debtors.order_by("-balance", "name")[:5])
    peak = top[0].balance if top else Decimal(1)
    for c in top:
        c.pct = max(6, int(c.balance / peak * 100))

    ring = int(min(100, max(0, round(paid / given * 100)))) if given else 0
    return {
        "owed": whole(given - paid), "given": whole(given), "paid": whole(paid),
        "debtors_count": debtors.count(),
        "ring": ring,
        "days_n": days_n,
        "period_tabs": [(p, tr(f"d{p}")) for p in (7, 14, 30)],
        "period_given": sum(debts, ZERO), "period_paid": sum(pays, ZERO),
        "has_data": any(debts) or any(pays),
        "top_debtors": top,
        "recent": qs.select_related("customer", "created_by").order_by("-created_at", "-id")[:8],
        "chart": {
            "days": [d.isoformat() for d in days],
            "debts": [float(x) for x in debts],
            "payments": [float(x) for x in pays],
            "lang": get_lang(),
            "L": {"debt": tr("legend_debt"), "paid": tr("legend_paid"),
                  "som": tr("som"), "thousand": tr("thousand")},
        },
    }
