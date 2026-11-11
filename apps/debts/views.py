import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from apps.accounts import audit
from apps.accounts.i18n import fmt_money, tr
from apps.accounts.mixins import OwnerRequiredMixin

from . import selectors, services
from .exports import stream_csv
from .forms import AmountForm, DebtForm, RepayForm, ReverseForm
from .models import Transaction
from .services import DomainError

ZERO = Decimal("0")
HISTORY_PAGE_SIZE = 30


class TokenFormMixin:
    """Каждая отрисовка формы получает новый токен идемпотентности."""

    def get_initial(self):
        return {**super().get_initial(), "token": uuid.uuid4()}


class Dashboard(LoginRequiredMixin, TemplateView):
    template_name = "debts/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        try:
            n = int(self.request.GET.get("days", 7))
        except ValueError:
            n = 7
        if n not in (7, 14, 30):
            n = 7
        ctx["who"] = user.first_name or user.username
        ctx.update(selectors.dashboard_data(user, n))
        return ctx


class AddDebt(LoginRequiredMixin, TokenFormMixin, FormView):
    form_class = DebtForm
    template_name = "debts/debt_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["user"] = self.request.user
        return kw

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["names"] = (selectors.visible_customers(self.request.user)
                        .filter(is_archived=False).values_list("name", flat=True).distinct())
        return ctx

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            out = services.add_debt_by_name(
                user=self.request.user, branch_id=d["branch"].pk, name=d["customer_name"],
                phone=d["phone"], amount=d["amount"], on_date=d["date"], note=d["note"], key=d["token"],
            )
        except DomainError as e:
            form.add_error(None, e.message())
            return self.form_invalid(form)
        flash_debt(self.request, out, d["amount"])
        return redirect("customer_detail", pk=out.customer.pk)


def flash_debt(request, out, amount):
    if out.duplicate:
        messages.info(request, tr("msg_already"))
    else:
        messages.success(request, tr("msg_debt", name=out.customer.name, n=fmt_money(amount)))


class CustomerList(LoginRequiredMixin, ListView):
    template_name = "debts/customer_list.html"
    paginate_by = 25

    def _filters(self):
        g = self.request.GET
        return g.get("q", "").strip(), bool(g.get("all")), bool(g.get("archived"))

    def get_queryset(self):
        q, show_all, archived = self._filters()
        qs = selectors.customers_base(self.request.user, q, archived).with_balance().select_related("branch")
        if not show_all and not archived:
            qs = qs.filter(balance__gt=0)
        return qs.order_by("-balance", "name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q, show_all, archived = self._filters()
        ctx.update(
            q=q, show_all=show_all, archived=archived,
            total=selectors.total_owed(selectors.customers_base(self.request.user, q, archived)),
            today=timezone.localdate(),
            month_ago=timezone.localdate() - timedelta(days=30),
        )
        return ctx


class CustomerDetail(LoginRequiredMixin, DetailView):
    template_name = "debts/customer_detail.html"

    def get_queryset(self):
        return selectors.visible_customers(self.request.user).with_balance().select_related("branch")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = selectors.with_reversal_flag(self.object.transactions.select_related("created_by"))
        page = Paginator(qs, HISTORY_PAGE_SIZE).get_page(self.request.GET.get("page"))
        days, by_day = [], {}
        for t in page.object_list:
            occurred = timezone.localtime(t.occurred_at)
            t.backdated = timezone.localdate(t.created_at) != occurred.date()
            g = by_day.get(occurred.date())
            if g is None:
                g = by_day[occurred.date()] = {"date": occurred.date(), "debt": ZERO, "paid": ZERO, "items": []}
                days.append(g)
            if not t.is_reversal and not t.is_reversed:
                g["debt" if t.kind == Transaction.Kind.DEBT else "paid"] += t.amount
            g["items"].append(t)
        ctx["days"] = days
        ctx["page_obj"] = page
        return ctx


class CustomerActionView(LoginRequiredMixin, TokenFormMixin, FormView):
    def get_customer(self):
        if not hasattr(self, "_customer"):
            self._customer = get_object_or_404(
                selectors.visible_customers(self.request.user).with_balance().select_related("branch"),
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
        d = form.cleaned_data
        try:
            out = services.add_debt(user=self.request.user, customer_id=self.kwargs["pk"],
                                    amount=d["amount"], on_date=d["date"], note=d["note"], key=d["token"])
        except DomainError as e:
            form.add_error(None, e.message())
            return self.form_invalid(form)
        flash_debt(self.request, out, d["amount"])
        return super().form_valid(form)


class CustomerRepay(CustomerActionView):
    form_class = RepayForm
    template_name = "debts/repay.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["balance"] = self.get_customer().balance
        return kw

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            out = services.repay(user=self.request.user, customer_id=self.kwargs["pk"],
                                 mode=d["mode"], amount=d.get("amount"), key=d["token"])
        except DomainError as e:
            form.add_error(None, e.message())
            return self.form_invalid(form)
        c = out.customer
        if out.duplicate:
            messages.info(self.request, tr("msg_already"))
        elif out.txn.note == "@full":
            messages.success(self.request, tr("msg_closed", name=c.name))
        else:
            messages.success(self.request, tr("msg_repaid", name=c.name, n=fmt_money(out.txn.amount)))
        return super().form_valid(form)


class TransactionReverse(OwnerRequiredMixin, TokenFormMixin, FormView):
    """Отмена операции: исходная запись остаётся, создаётся обратная."""

    form_class = ReverseForm
    template_name = "debts/reverse.html"

    @property
    def txn(self):
        if not hasattr(self, "_txn"):
            self._txn = get_object_or_404(
                selectors.visible_transactions(self.request.user).select_related("customer"),
                pk=self.kwargs["pk"],
            )
        return self._txn

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["txn"] = self.txn
        return ctx

    def get_success_url(self):
        return reverse("customer_detail", args=[self.txn.customer_id])

    def form_valid(self, form):
        d = form.cleaned_data
        try:
            out = services.reverse_transaction(user=self.request.user, txn_id=self.txn.pk,
                                               reason=d["reason"], key=d["token"])
        except DomainError as e:
            form.add_error(None, e.message())
            return self.form_invalid(form)
        if out.duplicate:
            messages.info(self.request, tr("msg_already"))
        else:
            messages.success(self.request, tr("msg_reversed"))
        return super().form_valid(form)


class CustomerFlag(OwnerRequiredMixin, View):
    """POST-переключатели клиента: запрет долга и архив."""

    http_method_names = ["post"]
    flag = ""
    value = True
    message_key = ""

    def post(self, request, pk):
        try:
            customer = services.set_customer_flag(user=request.user, customer_id=pk,
                                                  flag=self.flag, value=self.value)
        except DomainError as e:
            messages.error(request, e.message())
        else:
            messages.success(request, tr(self.message_key))
            pk = customer.pk
        return redirect("customer_detail", pk=pk)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ExportCSV(OwnerRequiredMixin, View):
    """Выгрузка операций за период (CSV, открывается в Excel)."""

    def get(self, request):
        today = timezone.localdate()
        d_to = parse_date(request.GET.get("to", "") or "") or today
        d_from = parse_date(request.GET.get("from", "") or "") or d_to - timedelta(days=30)
        if d_from > d_to:
            raise Http404
        audit.log(request.user, "export.csv", date_from=d_from, date_to=d_to)
        response = StreamingHttpResponse(
            stream_csv(selectors.export_rows(request.user, d_from, d_to)),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="depter-{d_from}_{d_to}.csv"'
        return response
