from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.accounts.i18n import fmt_money, tr
from apps.accounts.mixins import writable_branches
from apps.shops.models import Branch


def _amount_field():
    return forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=12)


def _date_field():
    return forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )


def _token_field():
    return forms.UUIDField(widget=forms.HiddenInput)


class TokenMixin:
    """Одноразовый токен формы: повторная отправка не создаёт вторую операцию."""

    def setup_token(self):
        msg = tr("err_token")
        self.fields["token"].error_messages.update({"required": msg, "invalid": msg})


class DateCleanMixin:
    def setup_date(self):
        self.fields["date"].label = tr("f_date")
        self.fields["date"].widget.attrs["max"] = timezone.localdate().isoformat()

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > timezone.localdate():
            raise forms.ValidationError(tr("err_future"))
        return d


class DebtForm(TokenMixin, DateCleanMixin, forms.Form):
    branch = forms.ModelChoiceField(Branch.objects.none())
    customer_name = forms.CharField(
        max_length=120,
        widget=forms.TextInput(attrs={"list": "names", "autocomplete": "off"}),
    )
    phone = forms.CharField(
        max_length=30, required=False,
        widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "placeholder": "+996 700 123 456"}),
    )
    amount = _amount_field()
    date = _date_field()
    note = forms.CharField(max_length=255, required=False)
    token = _token_field()

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        f = self.fields
        f["branch"].label = tr("f_branch")
        f["customer_name"].label = tr("f_who")
        f["phone"].label = tr("f_phone")
        f["amount"].label = tr("f_amount")
        f["note"].label = tr("f_note")
        f["amount"].widget.attrs["inputmode"] = "decimal"
        self.setup_date()
        self.setup_token()
        qs = writable_branches(user)
        f["branch"].queryset = qs
        if qs.count() == 1:
            f["branch"].initial = qs.first()
            f["branch"].widget = forms.HiddenInput()


class AmountForm(TokenMixin, DateCleanMixin, forms.Form):
    amount = _amount_field()
    date = _date_field()
    note = forms.CharField(max_length=255, required=False)
    token = _token_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount"].label = tr("f_amount")
        self.fields["amount"].widget.attrs.update({"autofocus": True, "inputmode": "decimal"})
        self.fields["note"].label = tr("f_note")
        self.setup_date()
        self.setup_token()


class RepayForm(TokenMixin, forms.Form):
    mode = forms.ChoiceField(choices=[("full", "full"), ("partial", "partial")], initial="full")
    amount = forms.DecimalField(required=False, min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    token = _token_field()

    def __init__(self, *args, balance, **kwargs):
        super().__init__(*args, **kwargs)
        self.balance = balance
        self.setup_token()

    def clean(self):
        d = super().clean()
        if self.balance <= 0:
            raise forms.ValidationError(tr("err_no_debt"))
        if d.get("mode") == "partial" and "amount" not in self.errors:
            a = d.get("amount")
            if a is None:
                self.add_error("amount", tr("err_enter_amount"))
            elif a > self.balance:
                self.add_error("amount", tr("err_too_much", n=fmt_money(self.balance)))
        return d


class ReverseForm(TokenMixin, forms.Form):
    reason = forms.CharField(max_length=200)
    token = _token_field()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].label = tr("f_reason")
        self.fields["reason"].widget.attrs["autofocus"] = True
        self.setup_token()
