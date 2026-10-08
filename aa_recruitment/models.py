from allianceauth.eveonline.models import EveCorporationInfo
from django.contrib.auth.models import Group, User
from django.db import models
from django.utils.translation import gettext_lazy as _


class RecruitmentConfig(models.Model):
    """Global configuration for the recruitment plugin."""

    discord_webhook_url = models.URLField(
        blank=True,
        null=True,
        help_text=_("Default Discord Webhook URL for recruitment alerts (can be overridden per form)."),
    )
    allow_multiple_active = models.BooleanField(
        default=False,
        help_text=_("Allow applicants to have multiple active pending applications simultaneously."),
    )
    notify_on_status_change = models.BooleanField(
        default=True,
        help_text=_("Send in-app notifications to applicants when their application status changes."),
    )
    portal_menu_title = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text=_(
            "Custom title for the Candidate / Apply portal in the navigation menu (e.g. 'Apply', 'Join Us', 'Solliciteren'). Leave blank for default."
        ),
    )
    recruiter_menu_title = models.CharField(
        max_length=60,
        blank=True,
        default="",
        help_text=_(
            "Custom title for the Recruiter desk in the navigation menu (e.g. 'Recruitment', 'Werving'). Leave blank for default."
        ),
    )
    discord_user_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Default Discord User Token to access and synchronize configured intel channels."),
    )

    class Meta:
        verbose_name = _("Recruitment Config")
        verbose_name_plural = _("Recruitment Config")

    def __str__(self) -> str:
        return str(_("Recruitment Configuration"))

    @classmethod
    def get_solo(cls) -> "RecruitmentConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ApplicationForm(models.Model):
    """A recruitment posting/form for a corporation or alliance division."""

    title = models.CharField(
        max_length=150,
        help_text=_("e.g. 'Main Fleet Corp Recruitment' or 'Capital Pilot Application'"),
    )
    slug = models.SlugField(
        max_length=150,
        unique=True,
        help_text=_("URL identifier for this application form"),
    )
    corporation = models.ForeignKey(
        EveCorporationInfo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recruitment_forms",
        help_text=_("Associated EVE corporation, if applicable."),
    )
    description = models.TextField(
        help_text=_("Recruitment requirements, instructions, and guidelines for applicants.")
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether this form is currently open for submissions."),
    )
    discord_webhook_url = models.URLField(
        blank=True,
        null=True,
        help_text=_("Specific Discord Webhook URL for submissions to this form. Leave blank to use global default."),
    )
    reviewers_group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recruitment_forms",
        help_text=_("Optional dedicated reviewer group for this specific form."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Application Form")
        verbose_name_plural = _("Application Forms")
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class QuestionType(models.TextChoices):
    TEXT = "text", _("Short Text")
    TEXTAREA = "textarea", _("Long Text (Paragraph)")
    CHOICE = "choice", _("Single Choice (Select)")
    CHECKBOX = "checkbox", _("Checkbox (Yes / No)")
    INTEGER = "integer", _("Number")


class Question(models.Model):
    """Custom question attached to an ApplicationForm."""

    form = models.ForeignKey(
        ApplicationForm,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    question_text = models.CharField(max_length=255)
    help_text = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Optional hint displayed under the question."),
    )
    question_type = models.CharField(
        max_length=20,
        choices=QuestionType.choices,
        default=QuestionType.TEXT,
    )
    choices = models.TextField(
        blank=True,
        null=True,
        help_text=_("Comma-separated options for Single Choice questions (e.g. 'EU, US, AU')."),
    )
    is_required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(
        default=0,
        help_text=_("Sort order of the question in the form."),
    )

    class Meta:
        verbose_name = _("Question")
        verbose_name_plural = _("Questions")
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.form.title} - Q{self.order}: {self.question_text[:40]}"

    def get_choice_list(self) -> list[str]:
        if not self.choices:
            return []
        return [c.strip() for c in self.choices.split(",") if c.strip()]


class ApplicationStatus(models.TextChoices):
    PENDING = "pending", _("Pending Review")
    IN_PROGRESS = "in_progress", _("Under Review")
    ACCEPTED = "accepted", _("Accepted")
    REJECTED = "rejected", _("Rejected")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class Application(models.Model):
    """A submitted recruitment application."""

    form = models.ForeignKey(
        ApplicationForm,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recruitment_applications",
    )
    main_character_name = models.CharField(
        max_length=150,
        blank=True,
        help_text=_("Main character name at time of application."),
    )
    status = models.CharField(
        max_length=20,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.PENDING,
        db_index=True,
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_recruitment_applications",
        help_text=_("Assigned recruitment officer."),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Application")
        verbose_name_plural = _("Applications")
        ordering = ["-created_at"]
        permissions = (
            ("basic_access", _("Can view and submit recruitment applications")),
            (
                "manage_recruitment",
                _("Can review applications, conduct interviews and change application status"),
            ),
            (
                "admin_recruitment",
                _("Can create and configure application forms and questions"),
            ),
        )

    def __str__(self) -> str:
        return f"App #{self.pk}: {self.user.username} ({self.form.title}) - [{self.get_status_display()}]"

    @property
    def is_open(self) -> bool:
        return self.status in (ApplicationStatus.PENDING, ApplicationStatus.IN_PROGRESS)


class ApplicationAnswer(models.Model):
    """Answer provided by applicant for a specific question."""

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    answer_text = models.TextField()

    class Meta:
        verbose_name = _("Application Answer")
        verbose_name_plural = _("Application Answers")
        unique_together = ("application", "question")

    def __str__(self) -> str:
        return f"Answer #{self.pk} for App #{self.application_id}: {self.question.question_text[:30]}"


class ApplicationComment(models.Model):
    """Recruiter note or applicant interaction message."""

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="recruitment_comments",
    )
    comment = models.TextField()
    is_internal = models.BooleanField(
        default=True,
        help_text=_("Internal recruiter note (hidden from applicant)."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Application Comment")
        verbose_name_plural = _("Application Comments")
        ordering = ["created_at"]

    def __str__(self) -> str:
        tag = "[INTERNAL]" if self.is_internal else "[PUBLIC]"
        return f"{tag} {self.author.username} on #{self.application_id}"


class ApplicationLog(models.Model):
    """Audit log of status changes and administrative actions."""

    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Application Log")
        verbose_name_plural = _("Application Logs")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Log #{self.application_id}: {self.action} ({self.created_at})"


class RiskLevel(models.TextChoices):
    GREEN = "green", _("Low Risk (Green)")
    YELLOW = "yellow", _("Minor Concern (Yellow)")
    ORANGE = "orange", _("High Concern (Orange)")
    RED = "red", _("Critical Risk (Red)")


class VettingVerdict(models.TextChoices):
    REJECT = "reject", _("Reject (Hard Stop)")
    ACCEPT_HIGH = "accept_high", _("Accept - High Risk")
    ACCEPT_MED = "accept_med", _("Accept - Medium Risk")
    ACCEPT_LOW = "accept_low", _("Accept - Low Risk")
    PENDING = "pending", _("Pending Analysis")


class FindingSeverity(models.TextChoices):
    CRITICAL = "critical", _("Critical")
    HIGH = "high", _("High")
    MEDIUM = "medium", _("Medium")
    LOW = "low", _("Low")
    INFO = "info", _("Info")


class VettingReport(models.Model):
    """Automated security vetting audit report for an application."""

    application = models.OneToOneField(
        Application,
        on_delete=models.CASCADE,
        related_name="vetting_report",
    )
    risk_score = models.IntegerField(default=0, help_text=_("Calculated aggregate risk score"))
    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.GREEN,
        db_index=True,
    )
    verdict = models.CharField(
        max_length=20,
        choices=VettingVerdict.choices,
        default=VettingVerdict.PENDING,
        db_index=True,
    )
    verdict_reason = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Key justification for the recommended verdict"),
    )
    summary = models.TextField(blank=True, help_text=_("Executive summary of vetting findings"))
    ai_package = models.TextField(
        blank=True,
        help_text=_("Formatted context package for AI Sitrep / LLM analysis"),
    )
    zkill_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Raw zKillboard combat metrics and activity heatmap cache"),
    )
    corp_history = models.JSONField(
        default=list,
        blank=True,
        help_text=_("EVEWho / ESI corporation membership history cache"),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Vetting Report")
        verbose_name_plural = _("Vetting Reports")
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return (
            f"Vetting #{self.pk} for App #{self.application_id}: "
            f"[{self.get_risk_level_display()}] - {self.get_verdict_display()}"
        )


class VettingFinding(models.Model):
    """An individual security finding / flag generated by the vetting engine."""

    report = models.ForeignKey(
        VettingReport,
        on_delete=models.CASCADE,
        related_name="findings",
    )
    section = models.CharField(
        max_length=50,
        db_index=True,
        help_text=_("Check section identifier (e.g. zkill, blacklist, wallet, altdetect)"),
    )
    severity = models.CharField(
        max_length=20,
        choices=FindingSeverity.choices,
        default=FindingSeverity.INFO,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    evidence = models.TextField(blank=True, help_text=_("Specific telemetry, timestamp, or counterparty"))
    recruiter_action = models.TextField(
        blank=True,
        help_text=_("Actionable instruction for the recruitment team"),
    )
    suggested_question = models.TextField(
        blank=True,
        help_text=_("Concrete interview question to ask the candidate"),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Vetting Finding")
        verbose_name_plural = _("Vetting Findings")
        ordering = ["-severity", "created_at"]

    def __str__(self) -> str:
        return f"[{self.get_severity_display()}] {self.section}: {self.title}"


class DiscordIntelChannel(models.Model):
    """Monitored external or internal Discord channel for applicant intelligence."""

    name = models.CharField(
        max_length=100,
        help_text=_("Human-readable label for this channel (e.g. 'Imperium Blacklist', 'Public Intel')"),
    )
    guild_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=_("Discord Server / Guild ID"),
    )
    guild_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=_("Discord Server Name for reference (e.g. 'The Initiative Public')"),
    )
    channel_id = models.CharField(
        max_length=64,
        help_text=_("Discord Channel Snowflake ID to fetch messages from"),
    )
    user_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=_("Discord user token override for this specific channel. If blank, uses global token from config."),
    )
    sync_interval_minutes = models.PositiveIntegerField(
        default=60,
        help_text=_("Sync interval in minutes (e.g. 15, 30, 60, 360, 1440)"),
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_("Whether background synchronization and vetting scanning is active for this channel"),
    )
    default_severity = models.CharField(
        max_length=20,
        choices=FindingSeverity.choices,
        default=FindingSeverity.HIGH,
        help_text=_("Risk severity flagged when an applicant's name is mentioned in this channel"),
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_message_id = models.CharField(max_length=64, blank=True, default="")
    total_messages_stored = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Discord Intel Channel")
        verbose_name_plural = _("Discord Intel Channels")
        ordering = ["name"]

    def __str__(self) -> str:
        server_str = f" ({self.guild_name})" if self.guild_name else ""
        return f"#{self.name}{server_str}"


class DiscordIntelMessage(models.Model):
    """Archived Discord message collected from a monitored channel for applicant search."""

    channel = models.ForeignKey(
        DiscordIntelChannel,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    discord_message_id = models.CharField(max_length=64, db_index=True)
    author_id = models.CharField(max_length=64, blank=True, default="")
    author_name = models.CharField(max_length=128, blank=True, default="")
    content = models.TextField()
    sent_at = models.DateTimeField(db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Discord Intel Message")
        verbose_name_plural = _("Discord Intel Messages")
        unique_together = ("channel", "discord_message_id")
        ordering = ["-sent_at"]

    def __str__(self) -> str:
        return f"Msg #{self.discord_message_id} in #{self.channel.name} by {self.author_name}"


class CorpCombatStats(models.Model):
    """Aggregate monthly PvP combat trends and telemetry cached from zKillboard for a corporation."""

    corporation_id = models.BigIntegerField(unique=True, db_index=True)
    corporation_name = models.CharField(max_length=150)
    corporation_ticker = models.CharField(max_length=10, blank=True, default="")
    alliance_id = models.BigIntegerField(null=True, blank=True)
    alliance_name = models.CharField(max_length=150, blank=True, default="")
    member_count = models.PositiveIntegerField(default=0)
    is_auth_corp = models.BooleanField(
        default=False,
        help_text=_("Whether this corporation is an active internal member corporation in Alliance Auth"),
    )
    ships_destroyed = models.PositiveIntegerField(default=0)
    ships_lost = models.PositiveIntegerField(default=0)
    isk_destroyed = models.BigIntegerField(default=0)
    isk_lost = models.BigIntegerField(default=0)
    months_data = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Structured monthly breakdown: kills, losses, isk destroyed, and isk lost per YYYYMM"),
    )
    raw_stats = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Corp Combat Stats")
        verbose_name_plural = _("Corp Combat Stats")
        ordering = ["corporation_name"]

    def __str__(self) -> str:
        ticker = f" [{self.corporation_ticker}]" if self.corporation_ticker else ""
        return f"{self.corporation_name}{ticker} ({self.corporation_id})"


class CorpActivitySnapshot(models.Model):
    """Historical snapshot of corporation member activity distribution (Active, Low, Inactive, Dormant)."""

    corporation_id = models.BigIntegerField(db_index=True)
    corporation_name = models.CharField(max_length=150)
    snapshot_date = models.DateField(db_index=True)
    active_count = models.PositiveIntegerField(default=0)
    low_count = models.PositiveIntegerField(default=0)
    inactive_count = models.PositiveIntegerField(default=0)
    dormant_count = models.PositiveIntegerField(default=0)
    total_members = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Corp Activity Snapshot")
        verbose_name_plural = _("Corp Activity Snapshots")
        ordering = ["snapshot_date", "created_at"]

    def __str__(self) -> str:
        return (
            f"{self.corporation_name} @ {self.snapshot_date}: "
            f"Active={self.active_count}, Low={self.low_count}, Inactive={self.inactive_count}, Dormant={self.dormant_count}"
        )


class MemberActivityStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    LOW = "low", _("Low")
    INACTIVE = "inactive", _("Inactive")
    DORMANT = "dormant", _("Dormant")


class CorpMemberActivity(models.Model):
    """Tracked participation metrics and combat status for an individual corporation member."""

    corporation_id = models.BigIntegerField(db_index=True)
    character_id = models.BigIntegerField(db_index=True)
    character_name = models.CharField(max_length=150, db_index=True)
    main_character_name = models.CharField(max_length=150, blank=True, default="")
    is_main = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=MemberActivityStatus.choices,
        default=MemberActivityStatus.INACTIVE,
        db_index=True,
    )
    kills_30d = models.PositiveIntegerField(default=0)
    losses_30d = models.PositiveIntegerField(default=0)
    isk_destroyed_30d = models.BigIntegerField(default=0)
    isk_lost_30d = models.BigIntegerField(default=0)
    kills_90d = models.PositiveIntegerField(default=0)
    losses_90d = models.PositiveIntegerField(default=0)
    isk_destroyed_90d = models.BigIntegerField(default=0)
    isk_lost_90d = models.BigIntegerField(default=0)
    kills_120d = models.PositiveIntegerField(default=0)
    losses_120d = models.PositiveIntegerField(default=0)
    isk_destroyed_120d = models.BigIntegerField(default=0)
    isk_lost_120d = models.BigIntegerField(default=0)
    kills_alltime = models.PositiveIntegerField(default=0)
    losses_alltime = models.PositiveIntegerField(default=0)
    isk_destroyed_alltime = models.BigIntegerField(default=0)
    isk_lost_alltime = models.BigIntegerField(default=0)
    last_activity_date = models.DateTimeField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Corp Member Activity")
        verbose_name_plural = _("Corp Member Activities")
        unique_together = ("corporation_id", "character_id")
        ordering = ["-kills_30d", "character_name"]

    def __str__(self) -> str:
        return f"{self.character_name} ({self.get_status_display()}) - {self.kills_30d} kills"
