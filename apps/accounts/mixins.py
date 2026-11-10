from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from .i18n import tr


class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_owner


def user_branches(user):
    from apps.shops.models import Branch
    if user.is_owner:
        return Branch.objects.filter(owner=user)
    return Branch.objects.filter(pk=user.branch_id)


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
