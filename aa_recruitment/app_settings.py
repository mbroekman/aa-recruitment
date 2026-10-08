"""App settings for aa-recruitment."""

from django.conf import settings
from django.utils.translation import gettext_lazy as _

# Navigation Sidebar Menu Defaults (can also be configured dynamically in database via UI)
AA_RECRUITMENT_MENU_NAME = getattr(
    settings, "AA_RECRUITMENT_MENU_NAME", _("Recruitment")
)
AA_RECRUITMENT_APPLY_MENU_NAME = getattr(
    settings,
    "AA_RECRUITMENT_PORTAL_MENU_NAME",
    getattr(settings, "AA_RECRUITMENT_APPLY_MENU_NAME", _("Apply")),
)
