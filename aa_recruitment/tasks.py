import requests
from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger
from celery import shared_task
from django.conf import settings

from .models import Application, ApplicationStatus, RecruitmentConfig

logger = get_extension_logger(__name__)


@shared_task(name="aa_recruitment.tasks.send_recruitment_discord_notification")
def send_recruitment_discord_notification(
    application_id: int,
    event_type: str = "new_application",
    actor_username: str | None = None,
    note: str | None = None,
) -> None:
    """Send a Discord webhook notification for application events."""
    try:
        app = Application.objects.select_related("form", "user", "reviewer").get(id=application_id)
    except Application.DoesNotExist:
        logger.warning(f"Cannot send recruitment notification: Application {application_id} not found.")
        return

    config = RecruitmentConfig.get_solo()
    webhook_url = app.form.discord_webhook_url or config.discord_webhook_url
    if not webhook_url:
        return

    color_map = {
        ApplicationStatus.PENDING: 0x3498DB,  # Blue
        ApplicationStatus.IN_PROGRESS: 0xF39C12,  # Orange
        ApplicationStatus.ACCEPTED: 0x2ECC71,  # Green
        ApplicationStatus.REJECTED: 0xE74C3C,  # Red
        ApplicationStatus.WITHDRAWN: 0x95A5A6,  # Gray
    }
    color = color_map.get(app.status, 0x3498DB)

    title_map = {
        "new_application": f"New Application: {app.form.title}",
        "status_update": f"Application Status Changed: {app.get_status_display()}",
        "new_comment": f"New Comment on App #{app.pk}",
    }
    title = title_map.get(event_type, f"Recruitment Notification: App #{app.pk}")

    fields = [
        {"name": "Applicant", "value": app.user.username, "inline": True},
        {
            "name": "Main Character",
            "value": app.main_character_name or "Unknown",
            "inline": True,
        },
        {"name": "Status", "value": app.get_status_display(), "inline": True},
        {"name": "Form", "value": app.form.title, "inline": True},
        {
            "name": "Reviewer",
            "value": app.reviewer.username if app.reviewer else "Unassigned",
            "inline": True,
        },
    ]

    if actor_username:
        fields.append({"name": "Updated By", "value": actor_username, "inline": True})

    if note:
        fields.append({"name": "Details", "value": note[:1000], "inline": False})

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "footer": {"text": "Alliance Auth Recruitment Module"},
    }

    payload = {"embeds": [embed]}

    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as exc:
        logger.error(f"Failed to post recruitment webhook to Discord for App #{application_id}: {exc}")


@shared_task(name="aa_recruitment.tasks.notify_applicant_in_app")
def notify_applicant_in_app(
    application_id: int,
    title: str,
    message: str,
    level: str = "info",
) -> None:
    """Send an in-app Auth notification (and optional Discord DM) to the applicant."""
    try:
        app = Application.objects.select_related("user").get(id=application_id)
    except Application.DoesNotExist:
        return

    # In-app Alliance Auth notification
    notify(
        user=app.user,
        title=title,
        message=message,
        level=level,
    )

    # Optional Discord DM via aadiscordbot if installed
    if "aadiscordbot" in settings.INSTALLED_APPS:
        try:
            from aadiscordbot.tasks import send_direct_message_by_user_id

            dm_text = f"**{title}**\n{message}"
            send_direct_message_by_user_id.delay(app.user_id, dm_text)
        except Exception as exc:
            logger.debug(f"Could not send Discord DM for applicant {app.user_id}: {exc}")


@shared_task(name="aa_recruitment.tasks.run_applicant_vetting")
def run_applicant_vetting(application_id: int) -> None:
    """Asynchronously execute automated security vetting audit on an application."""
    try:
        app = Application.objects.get(id=application_id)
    except Application.DoesNotExist:
        logger.warning(f"Cannot run vetting: Application #{application_id} does not exist.")
        return

    from .vetting import VettingEngine

    try:
        report = VettingEngine.run(app)
        logger.info(
            f"Automated vetting task finished for Application #{application_id}: "
            f"Verdict={report.verdict}, Score={report.risk_score}"
        )
    except Exception as exc:
        logger.error(
            f"Automated vetting task failed for Application #{application_id}: {exc}",
            exc_info=True,
        )


@shared_task(name="aa_recruitment.tasks.sync_discord_intel_channel_task")
def sync_discord_intel_channel_task(channel_id: int) -> None:
    """Synchronize archived messages for a specific Discord intel channel."""
    from .models import DiscordIntelChannel
    from .services.discord_intel import fetch_and_store_channel_messages

    try:
        channel = DiscordIntelChannel.objects.get(pk=channel_id)
    except DiscordIntelChannel.DoesNotExist:
        logger.warning(f"Cannot sync Discord channel #{channel_id}: channel not found.")
        return

    if not channel.is_active:
        logger.info(f"Skipping sync for inactive Discord channel '{channel.name}'.")
        return

    count, err = fetch_and_store_channel_messages(channel)
    if err:
        logger.warning(f"Sync error for Discord channel '{channel.name}': {err}")
    else:
        logger.info(f"Successfully synced Discord channel '{channel.name}' (+{count} messages).")


@shared_task(name="aa_recruitment.tasks.sync_all_active_discord_channels_task")
def sync_all_active_discord_channels_task(force: bool = False) -> None:
    """Periodic Celery task checking all active Discord intel channels

    and dispatching sync tasks for those due according to their configured interval.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import DiscordIntelChannel

    now = timezone.now()
    active_channels = DiscordIntelChannel.objects.filter(is_active=True)

    dispatched = 0
    for ch in active_channels:
        due = False
        if force or not ch.last_synced_at:
            due = True
        else:
            time_elapsed = now - ch.last_synced_at
            if time_elapsed >= timedelta(minutes=ch.sync_interval_minutes):
                due = True

        if due:
            sync_discord_intel_channel_task.delay(ch.pk)
            dispatched += 1

    logger.info(f"Periodic Discord channel sync: dispatched {dispatched} channel sync task(s).")
