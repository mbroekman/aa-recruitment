from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from . import urls


class AaRecruitmentMenuItem(MenuItemHook):
    """Menu item hook for the recruitment plugin."""

    def __init__(self):
        super().__init__(
            getattr(settings, "AA_RECRUITMENT_APP_NAME", _("Recruitment")),
            "fas fa-user-plus fa-fw",
            "aa_recruitment:index",
            navactive=["aa_recruitment:"],
        )

    def render(self, request):
        if request.user.has_perm("aa_recruitment.basic_access"):
            return super().render(request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return AaRecruitmentMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_recruitment", r"^recruitment/")
