from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from . import audit


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.log(user, "auth.login")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None and getattr(user, "pk", None):
        audit.log(user, "auth.logout")
