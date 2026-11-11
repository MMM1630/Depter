from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from .i18n import tr


class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Только владелец организации. Анонима отправляет на вход, продавцу отдаёт 403."""

    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.is_owner and bool(u.organization_id)


def visible_branches(user):
    """Филиалы, данные которых пользователь вправе видеть (всегда в рамках своей организации)."""
    from apps.shops.models import Branch

    if not getattr(user, "is_authenticated", False) or not user.organization_id:
        return Branch.objects.none()
    if user.is_owner:
        return Branch.objects.filter(organization_id=user.organization_id)
    if user.branch_id:
        return Branch.objects.filter(pk=user.branch_id, organization_id=user.organization_id)
    return Branch.objects.none()


def writable_branches(user):
    """Филиалы, в которых можно записывать новые долги (архивные исключены)."""
    return visible_branches(user).filter(is_active=True)


class TitleMixin:
    title_key = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.title_key:
            ctx["title"] = tr(self.title_key)
        return ctx


class FlashMixin:
    flash_key = "msg_saved"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, tr(self.flash_key))
        return response
