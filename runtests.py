import sys

import django
from django.conf import settings
from django.test.utils import get_runner

if not settings.configured:
    settings.configure(
        SECRET_KEY="test-secret-key-recruitment-testsuite",
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
        CACHES={
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": "redis://127.0.0.1:6379/1",
                "OPTIONS": {
                    "CLIENT_CLASS": "django_redis.client.DefaultClient",
                },
            }
        },
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "django.contrib.humanize",
            "django_bootstrap5",
            "esi",
            "allianceauth",
            "allianceauth.framework",
            "allianceauth.eveonline",
            "allianceauth.groupmanagement",
            "allianceauth.authentication",
            "allianceauth.services",
            "allianceauth.notifications",
            "allianceauth.thirdparty.navhelper",
            "allianceauth.theme",
            "allianceauth.theme.flatly",
            "allianceauth.custom_css",
            "allianceauth.menu",
            "sri",
            "aa_recruitment",
        ],
        ROOT_URLCONF="aa_recruitment.tests.urls",
        MIDDLEWARE=[
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            },
        ],
        CELERY_ALWAYS_EAGER=True,
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        CELERY_BROKER_URL="memory://",
        CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP=True,
        SITE_URL="https://example.com",
        CSRF_TRUSTED_ORIGINS=["https://example.com"],
        ESI_USER_CONTACT_EMAIL="admin@example.com",
        ESI_SSO_CLIENT_ID="mock-client-id",
        ESI_SSO_CLIENT_SECRET="mock-client-secret",
        ESI_SSO_CALLBACK_URL="https://example.com/sso/callback",
        LOGIN_TOKEN_SCOPES=["publicData"],
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
        DEFAULT_THEME="allianceauth.theme.flatly.auth_hooks.FlatlyThemeHook",
        SILENCED_SYSTEM_CHECKS=[
            "allianceauth.checks.B003",
            "allianceauth.checks.B004",
            "allianceauth.checks.B006",
            "allianceauth.checks.B008",
            "allianceauth.checks.B010",
            "esi.E001",
            "esi.E003",
            "LOGIN_TOKEN_SCOPES",
            "models.W042",
        ],
        LANGUAGE_CODE="en-us",
        TIME_ZONE="UTC",
        USE_I18N=True,
        USE_TZ=True,
        STATIC_URL="/static/",
        USE_SRI=False,
    )


def run_tests():
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False)
    tests = sys.argv[1:] if len(sys.argv) > 1 else ["aa_recruitment.tests"]
    failures = test_runner.run_tests(tests)
    sys.exit(bool(failures))


if __name__ == "__main__":
    run_tests()
