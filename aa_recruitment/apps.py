from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AaRecruitmentConfig(AppConfig):
    name = "aa_recruitment"
    label = "aa_recruitment"
    verbose_name = _("Recruitment")

    def ready(self):
        import aa_recruitment.signals  # noqa: F401
