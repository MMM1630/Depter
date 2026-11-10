from django.utils import translation

from .i18n import DEFAULT, LANGS, set_lang


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
