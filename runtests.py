import os
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
        INSTALLED_APPS=[
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "allianceauth",
            "allianceauth.eveonline",
            "allianceauth.authentication",
            "allianceauth.notifications",
            "aa_recruitment",
        ],
        ROOT_URLCONF="aa_recruitment.urls",
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
        LANGUAGE_CODE="en-us",
        TIME_ZONE="UTC",
        USE_I18N=True,
        USE_TZ=True,
        STATIC_URL="/static/",
    )


def run_tests():
    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False)
    failures = test_runner.run_tests(["aa_recruitment.tests"])
    sys.exit(bool(failures))


if __name__ == "__main__":
    run_tests()
