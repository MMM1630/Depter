from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-t-a)*w2b)@3)^ewg8xq^qq*lafoyx5y@1w_rvbimlz+2=+zljx'

DEBUG = True

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "192.168.10.231",
    "*"
]



INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'conf.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'conf.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Bishkek'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Depter ---
INSTALLED_APPS += ["apps.accounts", "apps.shops", "apps.debts"]
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- Depter i18n (RU / KY) ---
MIDDLEWARE += ["apps.accounts.middleware.LanguageMiddleware"]


# --- Depter hardening ---
import os as _os
from datetime import timedelta as _timedelta
from pathlib import Path as _Path

from django.core.exceptions import ImproperlyConfigured as _Improper

from conf.env import env_bool as _env_bool, env_list as _env_list, load_env as _load_env

_ROOT = _Path(__file__).resolve().parent.parent
_load_env(_ROOT / ".env")

# ── окружение: ничего секретного в исходниках ──
DEBUG = _env_bool("DJANGO_DEBUG", False)
SECRET_KEY = _os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise _Improper("DJANGO_SECRET_KEY не задан (см. .env.example)")
    SECRET_KEY = "dev-only-" + "x" * 60

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if DEBUG else "")
if not DEBUG and not ALLOWED_HOSTS:
    raise _Improper("DJANGO_ALLOWED_HOSTS не задан (см. .env.example)")
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
ADMIN_URL = (_os.environ.get("DJANGO_ADMIN_URL", "control-panel").strip("/") or "control-panel") + "/"

# ── приложения, middleware, шаблоны ──
for _app in ("apps.accounts", "apps.shops", "apps.debts", "axes"):
    if _app not in INSTALLED_APPS:
        INSTALLED_APPS.append(_app)

_OURS = [
    "apps.accounts.middleware.LanguageMiddleware",
    "apps.accounts.middleware.AuditContextMiddleware",
    "axes.middleware.AxesMiddleware",  # должен быть последним
]
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _OURS] + _OURS

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

_tpl_dir = _ROOT / "templates"
if _tpl_dir not in [_Path(d) for d in TEMPLATES[0]["DIRS"]]:
    TEMPLATES[0]["DIRS"] = [*TEMPLATES[0]["DIRS"], _tpl_dir]

TIME_ZONE = "Asia/Bishkek"
USE_TZ = True

# Приложение не отправляет почту: на сервере используем заглушку вместо консольного бэкенда
if not DEBUG and "MAILERS" in globals():
    MAILERS = {"default": {"BACKEND": "django.core.mail.backends.dummy.EmailBackend"}}

# PostgreSQL включается переменными окружения (иначе остаётся база из settings.py)
if _os.environ.get("DB_NAME"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _os.environ["DB_NAME"],
        "USER": _os.environ.get("DB_USER", ""),
        "PASSWORD": _os.environ.get("DB_PASSWORD", ""),
        "HOST": _os.environ.get("DB_HOST", "localhost"),
        "PORT": _os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }

# Каждый запрос — одна транзакция БД (бизнес-логика + журнал аудита пишутся вместе)
DATABASES["default"]["ATOMIC_REQUESTS"] = True

# ── HTTPS, cookies, заголовки ──
_SECURE = _env_bool("DJANGO_SECURE", not DEBUG)
SESSION_COOKIE_SECURE = _SECURE
CSRF_COOKIE_SECURE = _SECURE
SECURE_SSL_REDIRECT = _SECURE
SECURE_HSTS_SECONDS = int(_os.environ.get("DJANGO_HSTS_SECONDS", "31536000" if _SECURE else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_HSTS_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_HSTS_PRELOAD", False)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# За Nginx: DJANGO_BEHIND_PROXY=1 и в Nginx
#   proxy_set_header X-Forwarded-Proto $scheme;
#   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
_BEHIND_PROXY = _env_bool("DJANGO_BEHIND_PROXY", False)
if _BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    AXES_IPWARE_PROXY_COUNT = 1
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]
else:
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["REMOTE_ADDR"]

# ── защита входа (django-axes) ──
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = _timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]  # блокируем пару IP+логин: офис за одним NAT не страдает целиком
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/locked.html"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
