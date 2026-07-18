import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-local-siaw-visual-editor-mvp")
DEBUG = os.environ.get("DEBUG", "true").lower() in {"1", "true", "yes"}
_RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"

_default_hosts = ["127.0.0.1", "localhost", ".localhost"]
_extra_hosts = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
ALLOWED_HOSTS = _default_hosts + _extra_hosts
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)

_csrf_origins = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
CSRF_TRUSTED_ORIGINS = _csrf_origins
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "builder",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Before CSRF/X-Frame so Vite runtime hosts can short-circuit as a website root.
    "builder.middleware.RuntimeHostMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "siaw_editor.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "builder.context_processors.site_edit",
            ],
        },
    },
]

WSGI_APPLICATION = "siaw_editor.wsgi.application"
ASGI_APPLICATION = "siaw_editor.asgi.application"

# Render free disks are ephemeral. Set DATA_DIR to a persistent disk mount when available.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))

_database_url = (os.environ.get("DATABASE_URL") or "").strip()
if _database_url and not _RUNNING_TESTS:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=600,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_ROOT = DATA_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "builder:login"
# Named URL only; LoginView.get_default_redirect_url appends #workspace.
LOGIN_REDIRECT_URL = "builder:dashboard"
LOGOUT_REDIRECT_URL = "builder:dashboard"

# Default account shown on the login form for local / MVP demos.
SIAW_DEMO_USERNAME = os.environ.get("SIAW_DEMO_USERNAME", "demo")
SIAW_DEMO_PASSWORD = os.environ.get("SIAW_DEMO_PASSWORD", "siawdemo123")
SIAW_DEMO_EMAIL = os.environ.get("SIAW_DEMO_EMAIL", "demo@siaw.local")

# Local MVP upload limits. ZIP validation also enforces independent limits.
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

X_FRAME_OPTIONS = "SAMEORIGIN"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Optional tooling for Vite/JS projects and GitHub imports.
ENABLE_JS_BUILD = os.environ.get("ENABLE_JS_BUILD", "true").lower() in {"1", "true", "yes"}
JS_BUILD_TIMEOUT_SECONDS = int(os.environ.get("JS_BUILD_TIMEOUT_SECONDS", "300"))
SSR_PREVIEW_BOOT_SECONDS = int(os.environ.get("SSR_PREVIEW_BOOT_SECONDS", "25"))
ENABLE_GITHUB_IMPORT = os.environ.get("ENABLE_GITHUB_IMPORT", "false").lower() in {"1", "true", "yes"}
GITHUB_CLONE_TIMEOUT_SECONDS = int(os.environ.get("GITHUB_CLONE_TIMEOUT_SECONDS", "120"))

# AI website builder. Providers: auto | ollama | openai | offline
# auto prefers local Ollama when running, else OpenAI if a key is set, else offline templates.
SIAW_AI_PROVIDER = (os.environ.get("SIAW_AI_PROVIDER", "auto") or "auto").strip().lower()
SIAW_AI_API_KEY = os.environ.get("SIAW_AI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SIAW_AI_BASE_URL = os.environ.get("SIAW_AI_BASE_URL", "")
SIAW_AI_MODEL = os.environ.get("SIAW_AI_MODEL", "")
SIAW_OLLAMA_HOST = os.environ.get("SIAW_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
SIAW_AI_TIMEOUT_SECONDS = int(os.environ.get("SIAW_AI_TIMEOUT_SECONDS", "0") or "0")
SIAW_AI_FORCE_OFFLINE = os.environ.get("SIAW_AI_FORCE_OFFLINE", "false").lower() in {"1", "true", "yes"}

# Localhost marketing-page edits that write back into templates/. Never enable on live.
SIAW_SITE_EDIT = os.environ.get("SIAW_SITE_EDIT", "true").lower() in {"1", "true", "yes"}
