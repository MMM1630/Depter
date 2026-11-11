"""Запись в журнал действий. IP берётся из middleware (contextvar)."""
import contextvars
import json

_ip = contextvars.ContextVar("depter_audit_ip", default=None)


def set_ip(value):
    _ip.set(value or None)


def log(user, action, obj=None, **details):
    from .models import AuditLog

    authenticated = bool(user is not None and getattr(user, "pk", None))
    return AuditLog.objects.create(
        organization_id=getattr(user, "organization_id", None) if authenticated else None,
        user=user if authenticated else None,
        username=getattr(user, "username", "") if authenticated else "",
        action=action,
        object_type=type(obj).__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        details=json.loads(json.dumps(details, default=str, ensure_ascii=False)),
        ip=_ip.get(),
    )
