import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from aa_recruitment.models import DiscordIntelChannel, DiscordIntelMessage, RecruitmentConfig

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v9"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def get_channel_token(channel: DiscordIntelChannel) -> Optional[str]:
    """Resolve the effective Discord user token for a given channel."""
    if channel.user_token and channel.user_token.strip():
        return channel.user_token.strip()
    config = RecruitmentConfig.get_solo()
    if config.discord_user_token and config.discord_user_token.strip():
        return config.discord_user_token.strip()
    return None


def _parse_and_store_message_batch(
    channel: DiscordIntelChannel,
    messages_data: List[Dict[str, Any]],
) -> Tuple[int, Optional[int], Optional[int]]:
    """Parse a list of raw Discord message dicts and bulk create them.

    Returns:
        (created_count, lowest_snowflake_int, highest_snowflake_int)
    """
    if not messages_data:
        return 0, None, None

    records_to_create = []
    snowflakes: List[int] = []

    for msg in messages_data:
        msg_id = str(msg.get("id", "")).strip()
        if not msg_id or not msg_id.isdigit():
            continue

        snowflake_int = int(msg_id)
        snowflakes.append(snowflake_int)

        author = msg.get("author", {})
        author_name = author.get("global_name") or author.get("username") or ""
        author_id = str(author.get("id", ""))
        content = msg.get("content", "")

        raw_ts = msg.get("timestamp", "")
        sent_at = parse_datetime(raw_ts) if raw_ts else None
        if not sent_at:
            sent_at = timezone.now()

        records_to_create.append(
            DiscordIntelMessage(
                channel=channel,
                discord_message_id=msg_id,
                author_id=author_id,
                author_name=author_name,
                content=content,
                sent_at=sent_at,
                raw_data={
                    "attachments": [a.get("url") for a in msg.get("attachments", [])],
                    "mentions": [m.get("username") for m in msg.get("mentions", [])],
                },
            )
        )

    created_count = 0
    if records_to_create:
        created = DiscordIntelMessage.objects.bulk_create(
            records_to_create,
            ignore_conflicts=True,
        )
        created_count = len(created)

    min_sf = min(snowflakes) if snowflakes else None
    max_sf = max(snowflakes) if snowflakes else None
    return created_count, min_sf, max_sf


def backfill_channel_history(
    channel: DiscordIntelChannel,
    max_messages: int = 1000,
) -> Tuple[int, Optional[str]]:
    """Fetch historical messages backwards in time (using Discord 'before' parameter).

    Starts from the oldest message currently archived for this channel, or from the current
    channel head if the channel is empty.

    Args:
        channel: The DiscordIntelChannel model instance.
        max_messages: Maximum number of historical messages to retrieve in this backfill run.

    Returns:
        (total_new_messages_created, error_message)
    """
    token = get_channel_token(channel)
    if not token:
        err = "No Discord user token configured (neither on channel nor globally)."
        channel.last_error = err
        channel.save(update_fields=["last_error"])
        return 0, err

    headers = {
        "Authorization": token,
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
    }
    url = f"{DISCORD_API_BASE}/channels/{channel.channel_id}/messages"

    # Find oldest message currently archived for this channel
    oldest_msg = channel.messages.order_by("sent_at").first()
    current_before = oldest_msg.discord_message_id if oldest_msg else None

    total_new = 0
    newest_head_snowflake: Optional[int] = None

    while total_new < max_messages:
        batch_limit = min(100, max_messages - total_new)
        params: Dict[str, Any] = {"limit": batch_limit}
        if current_before:
            params["before"] = current_before

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as e:
            err = f"Network connection error: {e}"
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 5.0)
            if retry_after <= 15.0:
                time.sleep(retry_after)
                continue
            err = f"Rate limited by Discord. Retry after {retry_after}s."
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code in (401, 403):
            err = f"Discord authentication failure (HTTP {resp.status_code}). Check token and permissions."
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code != 200:
            err = f"Discord API error (HTTP {resp.status_code}): {resp.text[:200]}"
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        messages_data = resp.json()
        if not isinstance(messages_data, list) or not messages_data:
            break

        created_count, min_sf, max_sf = _parse_and_store_message_batch(channel, messages_data)
        total_new += created_count

        if max_sf and (newest_head_snowflake is None or max_sf > newest_head_snowflake):
            newest_head_snowflake = max_sf

        if min_sf:
            current_before = str(min_sf)

        if len(messages_data) < batch_limit:
            break

        time.sleep(0.35)

    channel.last_synced_at = timezone.now()
    if newest_head_snowflake:
        if not channel.last_message_id or (
            channel.last_message_id.isdigit() and newest_head_snowflake > int(channel.last_message_id)
        ):
            channel.last_message_id = str(newest_head_snowflake)
    channel.total_messages_stored = channel.messages.count()
    channel.last_error = ""
    channel.save(
        update_fields=[
            "last_synced_at",
            "last_message_id",
            "total_messages_stored",
            "last_error",
            "updated_at",
        ]
    )

    logger.info("Backfilled Discord intel channel '%s': %d older messages stored.", channel.name, total_new)
    return total_new, None


def fetch_and_store_channel_messages(
    channel: DiscordIntelChannel,
    max_pages: int = 10,
) -> Tuple[int, Optional[str]]:
    """Fetch new messages incrementally from a Discord channel and store them.

    If the channel has never been synced (or has 0 messages stored), runs an initial backfill
    of up to 1,000 historical messages. Otherwise, polls forward in time using 'after'.

    Returns (new_messages_count, error_message).
    """
    token = get_channel_token(channel)
    if not token:
        err = "No Discord user token configured (neither on channel nor globally)."
        channel.last_error = err
        channel.save(update_fields=["last_error"])
        return 0, err

    if not channel.last_message_id and channel.total_messages_stored == 0:
        return backfill_channel_history(channel, max_messages=1000)

    headers = {
        "Authorization": token,
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
    }
    url = f"{DISCORD_API_BASE}/channels/{channel.channel_id}/messages"

    total_new = 0
    current_after = channel.last_message_id
    highest_seen_snowflake: Optional[int] = int(channel.last_message_id) if channel.last_message_id.isdigit() else None

    for _ in range(max_pages):
        params: Dict[str, Any] = {"limit": 100}
        if current_after:
            params["after"] = current_after

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as e:
            err = f"Network connection error: {e}"
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 5.0)
            if retry_after <= 15.0:
                time.sleep(retry_after)
                continue
            err = f"Rate limited by Discord. Retry after {retry_after}s."
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code in (401, 403):
            err = f"Discord authentication failure (HTTP {resp.status_code}). Check user token and channel access."
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code != 200:
            err = f"Discord API error (HTTP {resp.status_code}): {resp.text[:200]}"
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        messages_data = resp.json()
        if not isinstance(messages_data, list) or not messages_data:
            break

        created_count, min_sf, max_sf = _parse_and_store_message_batch(channel, messages_data)
        total_new += created_count

        if max_sf:
            if highest_seen_snowflake is None or max_sf > highest_seen_snowflake:
                highest_seen_snowflake = max_sf
            current_after = str(max_sf)

        if len(messages_data) < 100:
            break

        time.sleep(0.25)

    channel.last_synced_at = timezone.now()
    if highest_seen_snowflake:
        channel.last_message_id = str(highest_seen_snowflake)
    channel.total_messages_stored = channel.messages.count()
    channel.last_error = ""
    channel.save(
        update_fields=[
            "last_synced_at",
            "last_message_id",
            "total_messages_stored",
            "last_error",
            "updated_at",
        ]
    )

    logger.info("Synced Discord intel channel '%s': %d new messages stored.", channel.name, total_new)
    return total_new, None


def import_messages_from_json(
    channel: DiscordIntelChannel,
    raw_json_data: Any,
) -> int:
    """Import messages from a DiscordChatExporter JSON payload or list of messages."""
    if isinstance(raw_json_data, dict):
        messages_list = raw_json_data.get("messages", [])
    elif isinstance(raw_json_data, list):
        messages_list = raw_json_data
    else:
        return 0

    records = []
    highest_snowflake = channel.last_message_id

    for m in messages_list:
        msg_id = str(m.get("id", ""))
        if not msg_id:
            continue

        if not highest_snowflake or (msg_id.isdigit() and int(msg_id) > int(highest_snowflake)):
            highest_snowflake = msg_id

        author = m.get("author", {})
        if isinstance(author, dict):
            author_name = author.get("name") or author.get("nickname") or author.get("username") or ""
            author_id = str(author.get("id", ""))
        else:
            author_name = str(author)
            author_id = ""

        content = m.get("content", "")
        raw_ts = m.get("timestamp", "")
        sent_at = parse_datetime(raw_ts) if raw_ts else None
        if not sent_at:
            sent_at = timezone.now()

        records.append(
            DiscordIntelMessage(
                channel=channel,
                discord_message_id=msg_id,
                author_id=author_id,
                author_name=author_name,
                content=content,
                sent_at=sent_at,
                raw_data={"attachments": m.get("attachments", [])},
            )
        )

    if records:
        DiscordIntelMessage.objects.bulk_create(records, ignore_conflicts=True)

    channel.last_synced_at = timezone.now()
    if highest_snowflake:
        channel.last_message_id = highest_snowflake
    channel.total_messages_stored = channel.messages.count()
    channel.save(
        update_fields=[
            "last_synced_at",
            "last_message_id",
            "total_messages_stored",
            "updated_at",
        ]
    )
    return len(records)
