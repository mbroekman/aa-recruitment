from typing import Any, Dict, List, Set

from aa_recruitment.models import DiscordIntelMessage


class DiscordIntelAnalyzer:
    """Scans archived Discord intel messages from active monitored channels

    for mentions of applicant characters and known alts.
    """

    def __init__(self, character_names: List[str]):
        # Filter and deduplicate names
        cleaned_names: Set[str] = set()
        for name in character_names:
            n = name.strip()
            if len(n) >= 3:
                cleaned_names.add(n)
        self.character_names = sorted(cleaned_names)

    def analyze(self) -> List[Dict[str, Any]]:
        """Search all active Discord channels for applicant character mentions."""
        findings: List[Dict[str, Any]] = []
        if not self.character_names:
            return findings

        seen_messages: Set[int] = set()

        for name in self.character_names:
            # Query messages in active channels containing the character name
            matches = (
                DiscordIntelMessage.objects.filter(
                    channel__is_active=True,
                    content__icontains=name,
                )
                .select_related("channel")
                .order_by("-sent_at")[:5]
            )

            for msg in matches:
                if msg.pk in seen_messages:
                    continue
                seen_messages.add(msg.pk)

                # Extract context snippet around the character name
                content = msg.content.strip()
                pos = content.lower().find(name.lower())
                start = max(0, pos - 60)
                end = min(len(content), pos + len(name) + 60)
                snippet = content[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."

                channel = msg.channel
                server_desc = f" ({channel.guild_name})" if channel.guild_name else ""
                sent_date_str = msg.sent_at.strftime("%Y-%m-%d %H:%M UTC")

                findings.append(
                    {
                        "section": "discord",
                        "severity": channel.default_severity,
                        "title": f"Candidate '{name}' mentioned in #{channel.name}{server_desc}",
                        "evidence": (
                            f"Archived message from {sent_date_str} by {msg.author_name or 'Unknown'} "
                            f'(Msg ID: {msg.discord_message_id}) in #{channel.name}: "{snippet}"'
                        ),
                        "recruiter_action": (
                            f"Review full message context in #{channel.name}{server_desc} to assess "
                            f"if the mention involves blacklist, theft, drama, or past recruitment."
                        ),
                        "suggested_question": (
                            f"Were you involved in any discussions or incidents mentioned on "
                            f"the #{channel.name} Discord server?"
                        ),
                    }
                )

        return findings
