from django import forms

from apps.accounts.i18n import tr

from .models import Branch


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ("name", "address")

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["name"].label = tr("f_title")
        self.fields["address"].label = tr("f_address")

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        taken = Branch.objects.filter(organization=self.organization)
        if self.instance.pk:
            taken = taken.exclude(pk=self.instance.pk)
        if any(n.casefold() == name.casefold() for n in taken.values_list("name", flat=True)):
            raise forms.ValidationError(tr("err_branch_name_taken"))
        return name
