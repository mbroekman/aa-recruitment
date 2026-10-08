from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    Application,
    ApplicationAnswer,
    ApplicationComment,
    ApplicationForm,
    ApplicationLog,
    Question,
    RecruitmentConfig,
    VettingFinding,
    VettingReport,
)


@admin.register(RecruitmentConfig)
class RecruitmentConfigAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "portal_menu_title",
        "recruiter_menu_title",
        "allow_multiple_active",
        "notify_on_status_change",
        "discord_webhook_url",
    )
    fieldsets = (
        (
            _("Navigation & Menu"),
            {
                "fields": (
                    "portal_menu_title",
                    "recruiter_menu_title",
                ),
                "description": _(
                    "Customize the sidebar menu labels. Can also be configured directly via the frontend 'Forms & Config' interface."
                ),
            },
        ),
        (
            _("Application Settings"),
            {
                "fields": (
                    "allow_multiple_active",
                    "notify_on_status_change",
                ),
            },
        ),
        (
            _("Technical Infrastructure"),
            {
                "fields": ("discord_webhook_url",),
                "description": _("Technical Discord alerts webhook for recruitment activity."),
            },
        ),
    )

    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    fields = (
        "order",
        "question_text",
        "question_type",
        "choices",
        "is_required",
        "help_text",
    )


@admin.register(ApplicationForm)
class ApplicationFormAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "corporation",
        "is_active",
        "questions_count",
        "applications_count",
        "created_at",
    )
    list_filter = ("is_active", "corporation")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [QuestionInline]

    @admin.display(description=_("Questions"))
    def questions_count(self, obj):
        return obj.questions.count()

    @admin.display(description=_("Applications"))
    def applications_count(self, obj):
        return obj.applications.count()


class ApplicationAnswerInline(admin.TabularInline):
    model = ApplicationAnswer
    extra = 0
    can_delete = False
    readonly_fields = ("question", "answer_text")


class ApplicationCommentInline(admin.TabularInline):
    model = ApplicationComment
    extra = 0
    fields = ("author", "comment", "is_internal", "created_at")
    readonly_fields = ("created_at",)


class ApplicationLogInline(admin.TabularInline):
    model = ApplicationLog
    extra = 0
    can_delete = False
    readonly_fields = ("actor", "action", "created_at")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "main_character_name",
        "form",
        "status",
        "reviewer",
        "created_at",
    )
    list_filter = ("status", "form", "created_at")
    search_fields = (
        "user__username",
        "main_character_name",
        "form__title",
    )
    raw_id_fields = ("user", "reviewer")
    inlines = [
        ApplicationAnswerInline,
        ApplicationCommentInline,
        ApplicationLogInline,
    ]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "question_text",
        "form",
        "question_type",
        "order",
        "is_required",
    )
    list_filter = ("form", "question_type", "is_required")
    search_fields = ("question_text", "form__title")


@admin.register(ApplicationComment)
class ApplicationCommentAdmin(admin.ModelAdmin):
    list_display = ("application", "author", "is_internal", "created_at")
    list_filter = ("is_internal", "created_at")
    search_fields = ("comment", "author__username")


class VettingFindingInline(admin.TabularInline):
    model = VettingFinding
    extra = 0
    can_delete = False
    fields = (
        "severity",
        "section",
        "title",
        "evidence",
        "suggested_question",
        "recruiter_action",
    )
    readonly_fields = (
        "severity",
        "section",
        "title",
        "evidence",
        "suggested_question",
        "recruiter_action",
    )


@admin.register(VettingReport)
class VettingReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "risk_level",
        "risk_score",
        "verdict",
        "verdict_reason",
        "updated_at",
    )
    list_filter = ("risk_level", "verdict")
    search_fields = (
        "application__user__username",
        "application__main_character_name",
        "verdict_reason",
    )
    inlines = [VettingFindingInline]
    readonly_fields = ("created_at", "updated_at")
