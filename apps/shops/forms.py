from django import forms

from apps.accounts.i18n import tr
from .models import Branch


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ("name", "address")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = tr("f_title")
        self.fields["address"].label = tr("f_address")
