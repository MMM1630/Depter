from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import DetailView, FormView, ListView, TemplateView

from apps.accounts.i18n import fmt_money, get_lang, tr, whole
from apps.accounts.mixins import user_branches
from .forms import AmountForm, DebtForm, RepayForm, debt_datetime
from .models import Customer, Transaction

ZERO = Decimal("0")


class Dashboard(LoginRequiredMixin, TemplateView):
    template_name = "debts/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        branches = user_branches(user)
        qs = Transaction.objects.filter(customer__branch__in=branches)

        try:
            n = int(self.request.GET.get("days", 7))
        except ValueError:
            n = 7
        if n not in (7, 14, 30):
            n = 7

        tot = qs.aggregate(
            debt=Sum("amount", filter=Q(kind="debt")),
            paid=Sum("amount", filter=Q(kind="payment")),
        )
        given, paid = tot["debt"] or ZERO, tot["paid"] or ZERO

        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(n - 1, -1, -1)]
        rows = (
            qs.filter(created_at__date__gte=days[0])
            .annotate(d=TruncDate("created_at"))
            .values("d", "kind")
            .annotate(s=Sum("amount"))
        )
        data = {(r["d"], r["kind"]): r["s"] for r in rows}
        debts = [data.get((d, "debt"), ZERO) for d in days]
        pays = [data.get((d, "payment"), ZERO) for d in days]

        debtors = Customer.objects.filter(branch__in=branches).with_balance().filter(balance__gt=0)
        top = list(debtors.order_by("-balance", "name")[:5])
        peak = top[0].balance if top else Decimal(1)
        for c in top:
            c.pct = max(6, int(c.balance / peak * 100))

        ring = int(min(100, max(0, round(paid / given * 100)))) if given else 0

        ctx.update(
            who=user.first_name or user.username,
            owed=whole(given - paid), given=whole(given), paid=whole(paid),
            debtors_count=debtors.count(),
            ring=ring,
            days_n=n,
            period_tabs=[(p, tr(f"d{p}")) for p in (7, 14, 30)],
            period_given=sum(debts, ZERO), period_paid=sum(pays, ZERO),
            has_data=any(debts) or any(pays),
            top_debtors=top,
            recent=qs.select_related("customer", "created_by")[:8],
            chart={
                "days": [d.isoformat() for d in days],
                "debts": [float(x) for x in debts],
                "payments": [float(x) for x in pays],
                "lang": get_lang(),
                "L": {
                    "debt": tr("legend_debt"), "paid": tr("legend_paid"),
                    "som": tr("som"), "thousand": tr("thousand"),
                },
            },
        )
        return ctx


class AddDebt(LoginRequiredMixin, FormView):
    form_class = DebtForm
    template_name = "debts/debt_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["names"] = (Customer.objects.filter(branch__in=user_branches(self.request.user))
                        .values_list("name", flat=True).distinct())
        return ctx

    def form_valid(self, form):
        d = form.cleaned_data
        phone = d["phone"].strip()
        customer, created = Customer.objects.get_or_create(
            branch=d["branch"], name=d["customer_name"].strip(), defaults={"phone": phone},
        )
        if not created and phone and customer.phone != phone:
            customer.phone = phone
            customer.save(update_fields=["phone"])
        Transaction.objects.create(
            customer=customer, kind="debt", amount=d["amount"], note=d["note"],
            created_by=self.request.user, created_at=debt_datetime(d["date"]),
        )
        messages.success(self.request, tr("msg_debt", name=customer.name, n=fmt_money(d["amount"])))
        return redirect("customer_detail", pk=customer.pk)


class CustomerList(LoginRequiredMixin, ListView):
    template_name = "debts/customer_list.html"

    def get_queryset(self):
        qs = (Customer.objects.filter(branch__in=user_branches(self.request.user))
              .with_balance().select_related("branch"))
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(phone__icontains=q))
        if not self.request.GET.get("all"):
            qs = qs.filter(balance__gt=0)
        return qs.order_by("-balance", "name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["show_all"] = bool(self.request.GET.get("all"))
        ctx["total"] = sum((c.balance for c in ctx["object_list"]), ZERO)
        return ctx


class CustomerDetail(LoginRequiredMixin, DetailView):
    template_name = "debts/customer_detail.html"

    def get_queryset(self):
        return Customer.objects.filter(branch__in=user_branches(self.request.user)).with_balance()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        days, by_day = [], {}
        for t in self.object.transactions.select_related("created_by"):
            d = timezone.localtime(t.created_at).date()
            g = by_day.get(d)
            if g is None:
                g = by_day[d] = {"date": d, "debt": ZERO, "paid": ZERO, "items": []}
                days.append(g)
            g["debt" if t.kind == "debt" else "paid"] += t.amount
            g["items"].append(t)
        ctx["days"] = days
        return ctx


class CustomerActionView(LoginRequiredMixin, FormView):
    def get_customer(self):
        if not hasattr(self, "_customer"):
            self._customer = get_object_or_404(
                Customer.objects.filter(branch__in=user_branches(self.request.user)).with_balance(),
                pk=self.kwargs["pk"],
            )
        return self._customer

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["customer"] = self.get_customer()
        return ctx

    def get_success_url(self):
        nxt = self.request.GET.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, {self.request.get_host()}, self.request.is_secure()):
            return nxt
        return reverse("customer_detail", args=[self.kwargs["pk"]])


class CustomerAddDebt(CustomerActionView):
    form_class = AmountForm
    template_name = "debts/action.html"

    def form_valid(self, form):
        c, d = self.get_customer(), form.cleaned_data
        Transaction.objects.create(
            customer=c, kind="debt", amount=d["amount"], note=d["note"],
            created_by=self.request.user, created_at=debt_datetime(d["date"]),
        )
        messages.success(self.request, tr("msg_debt", name=c.name, n=fmt_money(d["amount"])))
        return super().form_valid(form)


class CustomerRepay(CustomerActionView):
    form_class = RepayForm
    template_name = "debts/repay.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["balance"] = self.get_customer().balance
        return kw

    def form_valid(self, form):
        c = self.get_customer()
        if form.cleaned_data["mode"] == "full":
            amount, note = c.balance, "@full"
        else:
            amount, note = form.cleaned_data["amount"], "@partial"
        Transaction.objects.create(
            customer=c, kind="payment", amount=amount, note=note, created_by=self.request.user,
        )
        if amount >= c.balance:
            messages.success(self.request, tr("msg_closed", name=c.name))
        else:
            messages.success(self.request, tr("msg_repaid", name=c.name, n=fmt_money(amount)))
        return super().form_valid(form)
