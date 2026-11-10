from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from apps.shops.models import Branch
from .i18n import tr
from .models import User


def _auth_fields(form):
    f = form.fields
    f["username"].label = tr("f_username")
    f["username"].help_text = ""
    f["password1"].label = tr("f_password")
    f["password1"].help_text = tr("pw_hint")
    f["password2"].label = tr("f_password2")
    f["password2"].help_text = ""


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = tr("f_username")
        self.fields["password"].label = tr("f_password")
        self.error_messages = {
            **self.error_messages,
            "invalid_login": tr("err_login"),
            "inactive": tr("err_inactive"),
        }


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _auth_fields(self)
        self.fields["first_name"].label = tr("f_your_name")
        self.fields["first_name"].required = True


class WorkerCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "branch")

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        _auth_fields(self)
        self.fields["first_name"].label = tr("f_name")
        self.fields["branch"].label = tr("f_branch")
        self.fields["branch"].queryset = Branch.objects.filter(owner=owner)
        self.fields["branch"].required = True

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.SELLER
        if commit:
            user.save()
        return user


class WorkerEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "branch", "is_active")

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].label = tr("f_name")
        self.fields["branch"].label = tr("f_branch")
        self.fields["is_active"].label = tr("f_active")
        self.fields["branch"].queryset = Branch.objects.filter(owner=owner)
        self.fields["branch"].required = True
