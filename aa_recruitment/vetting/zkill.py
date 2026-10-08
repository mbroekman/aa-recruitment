from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
import requests
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import FindingSeverity
from .constants import BREAK_MIN_DAYS, SESSION_GAP_SECONDS, ZKILLBOARD_API_BASE

logger = get_extension_logger(__name__)

USER_AGENT = "AllianceAuth-Recruitment/0.1.0 (Alliance Security Vetting Tool)"


class ZKillAnalyzer:
    """Fetches and evaluates PvP combat activity and fleet patterns from zKillboard."""

    def __init__(self, character_id: int):
        self.character_id = character_id
        self.headers = {"User-Agent": USER_AGENT}

    def fetch_kills_and_losses(self, max_items: int = 200) -> List[Dict[str, Any]]:
        """Fetch recent killmails from zKillboard API."""
        url = f"{ZKILLBOARD_API_BASE}/characterID/{self.character_id}/pastSeconds/15552000/"  # Past 180 days (6 months)
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data[:max_items]
        except Exception as exc:
            logger.warning(
                f"Failed to fetch zKillboard data for character {self.character_id}: {exc}"
            )
        return []

    def analyze(self) -> List[Dict[str, Any]]:
        """Perform activity analysis on killmails and return structured findings."""
        findings: List[Dict[str, Any]] = []
        killmails = self.fetch_kills_and_losses()

        now = datetime.now(timezone.utc)
        six_months_ago = now - timedelta(days=180)

        if not killmails:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.LOW,
                    "title": "No zKill activity in last 6 months",
                    "evidence": f"0 killmails recorded for character ID {self.character_id} in the past 180 days.",
                    "recruiter_action": "Check if character is an industrialist, miner, or non-combat alt.",
                }
            )
            return findings

        # Parse timestamps and determine kill vs loss
        events = []
        kills_count = 0
        losses_count = 0

        for km in killmails:
            raw_time = km.get("killmail_time") or km.get("killTime")
            if not raw_time:
                continue
            try:
                # EVE ISO format: 2026-05-12T19:30:00Z or similar
                dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except Exception:
                continue

            victim = km.get("victim", {})
            victim_id = victim.get("character_id")
            is_loss = victim_id == self.character_id

            if is_loss:
                losses_count += 1
            else:
                kills_count += 1

            events.append((dt, is_loss))

        events.sort(key=lambda x: x[0])
        total_events = len(events)

        # 1. Kill vs Loss ratio
        if total_events >= 5 and kills_count == 0:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.LOW,
                    "title": "Killboard consists only of losses",
                    "evidence": f"{losses_count} losses and 0 kills recorded in the past 6 months.",
                    "recruiter_action": "Ask if player engages in PvP or primarily gets caught while ratting/hauling.",
                }
            )

        # 2. Distinct active days & fleet sessions (>2 hours gap = new fleet/session)
        active_days = set(dt.date() for dt, _ in events)
        sessions_count = 1
        last_dt = events[0][0]

        for dt, _ in events[1:]:
            diff_seconds = (dt - last_dt).total_seconds()
            if diff_seconds > SESSION_GAP_SECONDS:
                sessions_count += 1
            last_dt = dt

        # 3. Burst of activity detection
        recent_30d_events = [dt for dt, _ in events if dt >= now - timedelta(days=30)]
        if total_events >= 15 and len(recent_30d_events) / total_events > 0.8:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.INFO,
                    "title": "Burst of activity before applying",
                    "evidence": f"{len(recent_30d_events)} of {total_events} kills occurred in the last 30 days.",
                    "recruiter_action": "Verify whether candidate suddenly farmed killboard activity right before applying.",
                }
            )

        # Summary info finding
        findings.append(
            {
                "section": "zkill",
                "severity": FindingSeverity.INFO,
                "title": "zKillboard 6-Month Activity Profile",
                "evidence": (
                    f"{total_events} total combat events ({kills_count} kills, {losses_count} losses) "
                    f"across {len(active_days)} active days and ~{sessions_count} fleet sessions."
                ),
            }
        )

        return findings
