from django import template

from ..i18n import T, fmt_money, get_lang, tr

register = template.Library()

NOTE_MAP = {
    "@full": "note_full", "Полное погашение": "note_full",
    "@partial": "note_partial", "Частичное погашение": "note_partial",
}


@register.simple_tag
def t(key, **kw):
    return tr(key, **kw)


@register.simple_tag
def lang():
    return get_lang()


@register.simple_tag(takes_context=True)
def qs_page(context, page):
    """Строка запроса с новым номером страницы, остальные параметры сохраняются."""
    params = context["request"].GET.copy()
    params["page"] = page
    return params.urlencode()


@register.filter
def money(value):
    try:
        return fmt_money(value)
    except Exception:
        return value


@register.filter
def hue(pk):
    try:
        return (int(pk) * 67) % 360
    except Exception:
        return 150


@register.filter
def initial(name):
    name = str(name).strip()
    return name[:1].upper() if name else "?"


@register.filter
def note_text(note):
    key = NOTE_MAP.get(note)
    return tr(key) if key else note


@register.filter
def action_label(action):
    key = "act_" + str(action).replace(".", "_")
    return tr(key) if key in T else action
