from django.core.cache import cache


def hit(key, limit, window):
    """True, если попытка ещё в пределах лимита (limit попыток за window секунд)."""
    k = f"depter-throttle:{key}"
    cache.add(k, 0, window)
    try:
        count = cache.incr(k)
    except ValueError:
        cache.set(k, 1, window)
        count = 1
    return count <= limit
