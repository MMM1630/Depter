import ipaddress

from django.utils import translation

from . import audit
from .i18n import DEFAULT, LANGS, set_lang


def client_ip(request):
    """IP клиента по правилам axes (учитывает DJANGO_BEHIND_PROXY)."""
    try:
        from axes.helpers import get_client_ip_address

        value = get_client_ip_address(request)
    except Exception:
        value = request.META.get("REMOTE_ADDR")
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.COOKIES.get("depter_lang", DEFAULT)
        if lang not in LANGS:
            lang = DEFAULT
        set_lang(lang)
        try:
            translation.activate(lang)
        except Exception:
            pass
        return self.get_response(request)


class AuditContextMiddleware:
    """Запоминает IP запроса, чтобы журнал аудита писал его автоматически."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        audit.set_ip(client_ip(request))
        return self.get_response(request)
