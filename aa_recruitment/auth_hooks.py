from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import app_settings, urls


class ApplyMenuItem(MenuItemHook):
    """Menu item hook for standard users to apply to corporations."""

    def __init__(self):
        super().__init__(
            self.get_title(),
            "fas fa-file-signature fa-fw",
            "aa_recruitment:applicant_portal",
            navactive=[
                "aa_recruitment:applicant_portal",
                "aa_recruitment:my_applications",
                "aa_recruitment:apply",
                "aa_recruitment:application_detail",
            ],
        )

    @classmethod
    def get_title(cls):
        try:
            from .models import RecruitmentConfig

            config = RecruitmentConfig.get_solo()
            if config.portal_menu_title:
                return config.portal_menu_title
        except Exception:
            pass
        return app_settings.AA_RECRUITMENT_APPLY_MENU_NAME

    def render(self, request):
        if not request.user.has_perm("aa_recruitment.basic_access"):
            return ""
        self.text = self.get_title()
        return super().render(request)


class RecruitmentMenuItem(MenuItemHook):
    """Menu item hook for recruiters to review applications and manage candidates."""

    def __init__(self):
        super().__init__(
            self.get_title(),
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

    @classmethod
    def get_title(cls):
        try:
            from .models import RecruitmentConfig

            config = RecruitmentConfig.get_solo()
            if config.recruiter_menu_title:
                return config.recruiter_menu_title
        except Exception:
            pass
        return app_settings.AA_RECRUITMENT_MENU_NAME

    def render(self, request):
        if not request.user.has_perm("aa_recruitment.manage_recruitment"):
            return ""
        self.text = self.get_title()
        try:
            from .models import Application, ApplicationStatus

            pending_count = Application.objects.filter(
                status__in=[ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS]
            ).count()
            self.count = pending_count if pending_count > 0 else None
        except Exception:
            self.count = None
        return super().render(request)


@hooks.register("menu_item_hook")
def register_apply_menu():
    return ApplyMenuItem()


@hooks.register("menu_item_hook")
def register_recruitment_menu():
    return RecruitmentMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_recruitment", r"^recruitment/")
