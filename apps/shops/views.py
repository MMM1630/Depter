from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.accounts.mixins import FlashMixin, OwnerRequiredMixin, TitleMixin
from .forms import BranchForm
from .models import Branch


class OwnBranches(OwnerRequiredMixin):
    def get_queryset(self):
        return Branch.objects.filter(owner=self.request.user)


class BranchList(OwnBranches, ListView):
    template_name = "shops/branch_list.html"


class BranchCreate(OwnerRequiredMixin, TitleMixin, FlashMixin, CreateView):
    form_class = BranchForm
    template_name = "form.html"
    success_url = reverse_lazy("branch_list")
    title_key = "title_new_branch"

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class BranchUpdate(OwnBranches, TitleMixin, FlashMixin, UpdateView):
    form_class = BranchForm
    template_name = "form.html"
    success_url = reverse_lazy("branch_list")
    title_key = "title_edit_branch"


class BranchDelete(OwnBranches, FlashMixin, DeleteView):
    template_name = "confirm_delete.html"
    success_url = reverse_lazy("branch_list")
    flash_key = "msg_deleted"
