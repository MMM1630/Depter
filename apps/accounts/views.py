from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, FormView, ListView, UpdateView

from apps.shops.models import Branch

from . import audit, throttle
from .forms import LoginForm, RegisterForm, WorkerCreateForm, WorkerEditForm
from .i18n import LANGS, tr
from .middleware import client_ip
from .mixins import FlashMixin, OwnerRequiredMixin, TitleMixin
from .models import AuditLog, Organization, User


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

    def post(self, request, *args, **kwargs):
        # не больше 5 попыток регистрации в час с одного IP
        if not throttle.hit(f"register:{client_ip(request)}", 5, 3600):
            form = self.get_form()
            form.add_error(None, tr("err_throttle"))
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        with transaction.atomic():
            org = Organization.objects.create(name=form.cleaned_data["organization_name"].strip())
            user = form.save(commit=False)
            user.role = User.Role.OWNER
            user.organization = org
            user.save()
            Branch.objects.create(organization=org, name=tr("main_branch"))
            audit.log(user, "org.register", org, name=org.name)
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return super().form_valid(form)


class WorkerQuerysetMixin(OwnerRequiredMixin):
    def get_queryset(self):
        return User.objects.filter(role=User.Role.SELLER, organization_id=self.request.user.organization_id)


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

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "worker.create", self.object,
                  username=self.object.username, branch=str(self.object.branch))
        return response


class WorkerUpdate(WorkerQuerysetMixin, TitleMixin, FlashMixin, UpdateView):
    form_class = WorkerEditForm
    template_name = "form.html"
    success_url = reverse_lazy("worker_list")
    title_key = "title_edit_worker"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["owner"] = self.request.user
        return kw

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(self.request.user, "worker.update", self.object,
                  username=self.object.username, branch=str(self.object.branch),
                  active=self.object.is_active, changed=form.changed_data)
        return response


class AuditList(OwnerRequiredMixin, ListView):
    template_name = "accounts/audit_list.html"
    paginate_by = 50

    def get_queryset(self):
        return AuditLog.objects.filter(organization_id=self.request.user.organization_id)
