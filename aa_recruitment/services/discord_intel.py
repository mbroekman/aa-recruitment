import logging
import time
from typing import Any, Dict, Optional, Tuple

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


def fetch_and_store_channel_messages(
    channel: DiscordIntelChannel,
    max_pages: int = 5,
) -> Tuple[int, Optional[str]]:
    """Fetch new messages incrementally from a Discord channel and store them.

    Returns (new_messages_count, error_message).
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

    total_new = 0
    newest_snowflake = channel.last_message_id

    for page_idx in range(max_pages):
        params: Dict[str, Any] = {"limit": 100}
        if newest_snowflake:
            params["after"] = newest_snowflake

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
        except requests.RequestException as e:
            err = f"Network connection error: {e}"
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code == 429:
            retry_after = resp.json().get("retry_after", 5.0)
            if retry_after <= 5.0:
                time.sleep(retry_after)
                continue
            err = f"Rate limited by Discord. Retry after {retry_after}s."
            channel.last_error = err
            channel.save(update_fields=["last_error"])
            return total_new, err

        if resp.status_code in (401, 403):
            err = f"Discord authentication/permission failure (HTTP {resp.status_code}). Check user token and channel access."
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

        records_to_create = []
        for msg in messages_data:
            msg_id = str(msg.get("id", ""))
            if not msg_id:
                continue

            # Update highest snowflake seen
            if not newest_snowflake or int(msg_id) > int(newest_snowflake):
                newest_snowflake = msg_id

            author = msg.get("author", {})
            author_name = author.get("global_name") or author.get("username") or ""
            author_id = str(author.get("id", ""))
            content = msg.get("content", "")

            # Parse timestamp (e.g. 2026-10-08T14:30:00.000000+00:00)
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

        if records_to_create:
            created = DiscordIntelMessage.objects.bulk_create(
                records_to_create,
                ignore_conflicts=True,
            )
            total_new += len(created)

        # If fewer than 100 messages returned, reached end of stream
        if len(messages_data) < 100:
            break

    channel.last_synced_at = timezone.now()
    channel.last_message_id = newest_snowflake or channel.last_message_id
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
