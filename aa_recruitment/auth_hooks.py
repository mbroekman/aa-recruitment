from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from . import urls


class ApplyMenuItem(MenuItemHook):
    """Menu item hook for standard users to apply to corporations."""

    def __init__(self):
        super().__init__(
            getattr(settings, "AA_RECRUITMENT_APPLY_MENU_NAME", _("Apply")),
            "fas fa-file-signature fa-fw",
            "aa_recruitment:applicant_portal",
            navactive=[
                "aa_recruitment:applicant_portal",
                "aa_recruitment:my_applications",
                "aa_recruitment:apply",
                "aa_recruitment:application_detail",
            ],
        )

    def render(self, request):
        if request.user.has_perm("aa_recruitment.basic_access"):
            return super().render(request)
        return ""


class RecruitmentMenuItem(MenuItemHook):
    """Menu item hook for recruiters to review applications and manage candidates."""

    def __init__(self):
        super().__init__(
            getattr(settings, "AA_RECRUITMENT_MENU_NAME", _("Recruitment")),
            "fas fa-user-plus fa-fw",
            "aa_recruitment:recruiter_queue",
            navactive=[
                "aa_recruitment:recruiter_queue",
                "aa_recruitment:recruiter_detail",
                "aa_recruitment:manage_forms",
                "aa_recruitment:form_edit",
                "aa_recruitment:manage_questions",
                "aa_recruitment:question_edit",
            ],
        )

    def render(self, request):
        if request.user.has_perm("aa_recruitment.manage_recruitment"):
            return super().render(request)
        return ""


@hooks.register("menu_item_hook")
def register_apply_menu():
    return ApplyMenuItem()


@hooks.register("menu_item_hook")
def register_recruitment_menu():
    return RecruitmentMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_recruitment", r"^recruitment/")
