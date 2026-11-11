from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.accounts import audit
from apps.accounts.i18n import tr
from apps.accounts.mixins import FlashMixin, OwnerRequiredMixin, TitleMixin

from .forms import BranchForm
from .models import Branch


class OwnBranches(OwnerRequiredMixin):
    def get_queryset(self):
        return Branch.objects.filter(organization_id=self.request.user.organization_id)


class BranchFormMixin:
    form_class = BranchForm
    template_name = "form.html"
    success_url = reverse_lazy("branch_list")

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["organization"] = self.request.user.organization
        return kw


class BranchList(OwnBranches, ListView):
    template_name = "shops/branch_list.html"


class BranchCreate(OwnerRequiredMixin, BranchFormMixin, TitleMixin, FlashMixin, CreateView):
    title_key = "title_new_branch"

    def form_valid(self, form):
        form.instance.organization = self.request.user.organization
        response = super().form_valid(form)
        audit.log(self.request.user, "branch.create", self.object, name=self.object.name)
        return response


class BranchUpdate(OwnBranches, BranchFormMixin, TitleMixin, FlashMixin, UpdateView):
    title_key = "title_edit_branch"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "branch.update", self.object, name=self.object.name)
        return response


class BranchToggle(OwnBranches, View):
    """Архивировать / вернуть филиал (удаления нет, история сохраняется)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        branch = get_object_or_404(self.get_queryset(), pk=pk)
        branch.is_active = not branch.is_active
        branch.save(update_fields=["is_active"])
        audit.log(request.user, "branch.restore" if branch.is_active else "branch.archive",
                  branch, name=branch.name)
        messages.success(request, tr("msg_branch_restored" if branch.is_active else "msg_branch_archived"))
        return redirect("branch_list")
