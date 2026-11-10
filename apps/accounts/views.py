from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, DeleteView, FormView, ListView, UpdateView

from apps.shops.models import Branch
from .forms import LoginForm, RegisterForm, WorkerCreateForm, WorkerEditForm
from .i18n import LANGS, tr
from .mixins import FlashMixin, OwnerRequiredMixin, TitleMixin
from .models import User


def set_language(request, code):
    if code not in LANGS:
        raise Http404
    nxt = request.GET.get("next") or request.META.get("HTTP_REFERER") or "/"
    if not url_has_allowed_host_and_scheme(nxt, {request.get_host()}, request.is_secure()):
        nxt = "/"
    response = redirect(nxt)
    response.set_cookie("depter_lang", code, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


class Login(LoginView):
    form_class = LoginForm
    redirect_authenticated_user = True
    template_name = "registration/login.html"


class Register(FormView):
    form_class = RegisterForm
    template_name = "registration/register.html"
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.role = User.Role.OWNER
        user.save()
        Branch.objects.create(owner=user, name=tr("main_branch"))
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return super().form_valid(form)


class WorkerQuerysetMixin(OwnerRequiredMixin):
    def get_queryset(self):
        return User.objects.filter(role=User.Role.SELLER, branch__owner=self.request.user)


class WorkerList(WorkerQuerysetMixin, ListView):
    template_name = "accounts/worker_list.html"

    def get_queryset(self):
        return super().get_queryset().select_related("branch").order_by("branch__name", "username")


class WorkerCreate(OwnerRequiredMixin, TitleMixin, FlashMixin, CreateView):
    form_class = WorkerCreateForm
    template_name = "form.html"
    success_url = reverse_lazy("worker_list")
    title_key = "title_new_worker"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["owner"] = self.request.user
        return kw


class WorkerUpdate(WorkerQuerysetMixin, TitleMixin, FlashMixin, UpdateView):
    form_class = WorkerEditForm
    template_name = "form.html"
    success_url = reverse_lazy("worker_list")
    title_key = "title_edit_worker"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["owner"] = self.request.user
        return kw


class WorkerDelete(WorkerQuerysetMixin, FlashMixin, DeleteView):
    template_name = "confirm_delete.html"
    success_url = reverse_lazy("worker_list")
    flash_key = "msg_deleted"
