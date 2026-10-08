from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import requests
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import FindingSeverity
from .constants import SESSION_GAP_SECONDS, ZKILLBOARD_API_BASE

logger = get_extension_logger(__name__)

USER_AGENT = "AllianceAuth-Recruitment/0.1.0 (Alliance Security Vetting Tool)"


class ZKillAnalyzer:
    """Fetches and evaluates PvP combat activity, fleet patterns, activity heatmap,

    and FC stats from zKillboard APIs.
    """

    def __init__(self, character_id: int):
        self.character_id = character_id
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
        }
        self.stats: Optional[Dict[str, Any]] = None
        self.recent_killmails: Optional[List[Dict[str, Any]]] = None

    def fetch_stats(self) -> Dict[str, Any]:
        """Fetch pre-aggregated statistics, activity heatmap, and FC score from zKillboard stats API."""
        if self.stats is not None:
            return self.stats
        url = f"{ZKILLBOARD_API_BASE}/stats/characterID/{self.character_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "error" not in data:
                    self.stats = data
                    return data
        except Exception as exc:
            logger.warning(
                f"Failed to fetch zKillboard stats for character {self.character_id}: {exc}"
            )
        self.stats = {}
        return {}

    def fetch_recent_killmails(self, max_items: int = 200) -> List[Dict[str, Any]]:
        """Fetch recent raw killmails (page 1 up to 200) from zKillboard API."""
        # Note: zKillboard caps 'pastSeconds' to max 7 days, so we query the base endpoint
        # which returns the most recent 200 killmails by default.
        url = f"{ZKILLBOARD_API_BASE}/characterID/{self.character_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data[:max_items]
        except Exception as exc:
            logger.warning(
                f"Failed to fetch zKillboard killmails for character {self.character_id}: {exc}"
            )
        return []

    def _resolve_ship_name(self, ship_type_id: int) -> str:
        """Resolve ship type ID to human-readable ship name using EveType if available."""
        try:
            from eveuniverse.models import EveType

            eve_type = EveType.objects.filter(id=ship_type_id).first()
            if eve_type:
                return eve_type.name
        except Exception:
            pass
        return f"Ship #{ship_type_id}"

    def analyze(self) -> List[Dict[str, Any]]:
        """Perform comprehensive activity and combat analysis and return structured findings."""
        findings: List[Dict[str, Any]] = []

        stats = self.fetch_stats()
        killmails = self.fetch_recent_killmails()

        # ------------------------------------------------------------------
        # 1. Evaluate All-Time and Monthly Activity from Stats Endpoint
        # ------------------------------------------------------------------
        total_kills = stats.get("shipsDestroyed", 0)
        total_losses = stats.get("shipsLost", 0)
        isk_destroyed = stats.get("iskDestroyed", 0)
        isk_lost = stats.get("iskLost", 0)
        danger_ratio = stats.get("dangerRatio", 0)
        gang_ratio = stats.get("gangRatio", 0)
        avg_gang_size = stats.get("avgGangSize", 0.0)

        # Monthly breakdown (last 6 months)
        months_dict = stats.get("months", {})
        recent_6m_keys = sorted(months_dict.keys(), reverse=True)[:6]
        kills_last_6m = 0
        losses_last_6m = 0
        isk_last_6m = 0

        for m_key in recent_6m_keys:
            m_data = months_dict[m_key]
            kills_last_6m += m_data.get("shipsDestroyed", 0)
            losses_last_6m += m_data.get("shipsLost", 0)
            isk_last_6m += m_data.get("iskDestroyed", 0)

        # Check for absolute zero activity
        if total_kills == 0 and total_losses == 0 and not killmails:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.LOW,
                    "title": "No zKillboard Combat History",
                    "evidence": f"0 kills and 0 losses recorded on zKillboard for character ID {self.character_id}.",
                    "recruiter_action": "Check whether character is an industrialist, trader, miner, or non-combat alt.",
                }
            )
            return findings

        # Check for 6-month inactivity
        if kills_last_6m == 0 and losses_last_6m == 0:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.LOW,
                    "title": "Inactive on zKillboard in last 6 months",
                    "evidence": (
                        f"0 kills and 0 losses recorded in the last 6 months (All-time: {total_kills} kills, "
                        f"{total_losses} losses)."
                    ),
                    "recruiter_action": "Inquire about player hiatus or if they were playing on a different alt.",
                }
            )

        # ------------------------------------------------------------------
        # 2. Activity Profile Summary
        # ------------------------------------------------------------------
        isk_destroyed_str = f"{isk_destroyed / 1_000_000_000:.1f}B" if isk_destroyed < 1_000_000_000_000 else f"{isk_destroyed / 1_000_000_000_000:.2f}T"
        isk_lost_str = f"{isk_lost / 1_000_000_000:.1f}B" if isk_lost < 1_000_000_000_000 else f"{isk_lost / 1_000_000_000_000:.2f}T"

        evidence_parts = [
            f"All-time: {total_kills:,} kills / {total_losses:,} losses ({danger_ratio}% danger rating).",
            f"ISK: {isk_destroyed_str} destroyed vs {isk_lost_str} lost.",
        ]
        if recent_6m_keys:
            evidence_parts.append(
                f"Past 6 months: {kills_last_6m} kills, {losses_last_6m} losses across {len(recent_6m_keys)} active months."
            )
        evidence_parts.append(
            f"Fleet style: {gang_ratio}% fleet activity (average fleet size: ~{avg_gang_size:.0f} pilots)."
        )

        findings.append(
            {
                "section": "zkill",
                "severity": FindingSeverity.INFO,
                "title": "zKillboard Combat Profile",
                "evidence": " ".join(evidence_parts),
                "recruiter_action": "General combat baseline and experience profile.",
            }
        )

        # ------------------------------------------------------------------
        # 3. Timezone & Activity Heatmap Matrix
        # ------------------------------------------------------------------
        activity_data = stats.get("activity", {})
        if activity_data:
            days_names = activity_data.get(
                "days", ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
            )
            hour_totals = {h: 0 for h in range(24)}
            day_totals = {d: 0 for d in range(7)}

            for day_idx in range(7):
                day_map = activity_data.get(str(day_idx), {})
                for hour_str, count in day_map.items():
                    h = int(hour_str)
                    hour_totals[h] += count
                    day_totals[day_idx] += count

            total_activity_events = sum(hour_totals.values())
            if total_activity_events > 0:
                # Top active 4-hour window
                best_window_start = max(
                    range(24),
                    key=lambda start: sum(hour_totals[(start + i) % 24] for i in range(4)),
                )
                window_end = (best_window_start + 4) % 24
                window_events = sum(
                    hour_totals[(best_window_start + i) % 24] for i in range(4)
                )
                window_pct = int((window_events / total_activity_events) * 100)

                # Classify timezone
                if 17 <= best_window_start <= 22 or (best_window_start + 4) >= 18 and best_window_start < 23:
                    tz_name = "EU Timezone (Prime EU)"
                elif 0 <= best_window_start <= 4:
                    tz_name = "US Timezone (USTZ East / Central)"
                elif 5 <= best_window_start <= 9:
                    tz_name = "US West / Late USTZ"
                elif 10 <= best_window_start <= 16:
                    tz_name = "AU / Asian Timezone (AUTZ)"
                else:
                    tz_name = "Mixed Timezone"

                peak_day_idx = max(day_totals, key=day_totals.get)
                peak_day = (
                    days_names[peak_day_idx]
                    if peak_day_idx < len(days_names)
                    else str(peak_day_idx)
                )

                findings.append(
                    {
                        "section": "zkill",
                        "severity": FindingSeverity.INFO,
                        "title": f"Activity Heatmap & Primary Timezone: {tz_name}",
                        "evidence": (
                            f"Peak combat window: {best_window_start:02d}:00 - {window_end:02d}:00 UTC "
                            f"({window_pct}% of tracked activity). Most active day: {peak_day} "
                            f"({day_totals[peak_day_idx]} events recorded)."
                        ),
                        "recruiter_action": "Compare against declared play schedule in application questionnaire.",
                    }
                )

        # ------------------------------------------------------------------
        # 4. Fleet Commander (FC) Assessment
        # ------------------------------------------------------------------
        fc_data = stats.get("fc", {})
        if fc_data:
            fc_score = fc_data.get("score", 0)
            large_fleets = fc_data.get("largeFleetAppearances", 0)
            command_ships = fc_data.get("commandShipAppearances", 0)
            monitor_count = fc_data.get("monitorAppearances", 0)

            if fc_score > 30 or monitor_count > 0 or command_ships >= 10:
                fc_level = fc_data.get("level", "active")
                findings.append(
                    {
                        "section": "zkill",
                        "severity": FindingSeverity.INFO,
                        "title": f"Fleet Commander Indicators (Level: {fc_level.title()})",
                        "evidence": (
                            f"FC Score: {fc_score}/100. Flown in {large_fleets} large fleet engagements, "
                            f"{command_ships} Command Ship appearances, {monitor_count} Flag Cruiser (Monitor) appearances."
                        ),
                        "recruiter_action": "Ask if candidate has FC experience or wishes to lead alliance/corp fleets.",
                    }
                )

        # ------------------------------------------------------------------
        # 5. Top Combat Ships
        # ------------------------------------------------------------------
        top_ships = stats.get("topShips", [])[:4]
        if top_ships:
            ship_summaries = []
            for s in top_ships:
                ship_name = self._resolve_ship_name(s.get("shipTypeID", 0))
                kills = s.get("kills", 0)
                losses = s.get("losses", 0)
                ship_summaries.append(f"{ship_name} ({kills}K/{losses}L)")

            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.INFO,
                    "title": "Favorite Combat Ships",
                    "evidence": "Most flown ships: " + ", ".join(ship_summaries),
                    "recruiter_action": "Check ship capabilities against corporation doctrine requirements.",
                }
            )

        # ------------------------------------------------------------------
        # 6. Loss-only / Pure Victim Check
        # ------------------------------------------------------------------
        if total_kills == 0 and total_losses >= 5:
            findings.append(
                {
                    "section": "zkill",
                    "severity": FindingSeverity.LOW,
                    "title": "Killboard consists entirely of losses",
                    "evidence": f"{total_losses} losses and 0 kills recorded on zKillboard.",
                    "recruiter_action": "Check if player gets caught while ratting/hauling and has no PvP orientation.",
                }
            )

        # ------------------------------------------------------------------
        # 7. Burst of Activity before Applying
        # ------------------------------------------------------------------
        if recent_6m_keys and len(recent_6m_keys) >= 3:
            latest_month_kills = months_dict.get(recent_6m_keys[0], {}).get("shipsDestroyed", 0)
            prior_months_avg = (
                sum(months_dict.get(m, {}).get("shipsDestroyed", 0) for m in recent_6m_keys[1:])
                / len(recent_6m_keys[1:])
            )
            if latest_month_kills >= 20 and prior_months_avg <= 2:
                findings.append(
                    {
                        "section": "zkill",
                        "severity": FindingSeverity.INFO,
                        "title": "Sudden Spike in Combat Activity Before Applying",
                        "evidence": (
                            f"{latest_month_kills} kills recorded this month vs an average of "
                            f"{prior_months_avg:.1f} kills/month in previous months."
                        ),
                        "recruiter_action": "Verify if applicant suddenly activated this character specifically for recruitment.",
                    }
                )

        return findings

    def get_summary_dict(self) -> Dict[str, Any]:
        """Return a structured summary of zKillboard statistics and activity heatmap for caching."""
        stats = self.fetch_stats()
        return {
            "character_id": self.character_id,
            "total_kills": stats.get("shipsDestroyed", 0),
            "total_losses": stats.get("shipsLost", 0),
            "danger_ratio": stats.get("dangerRatio", 0),
            "gang_ratio": stats.get("gangRatio", 0),
            "avg_gang_size": stats.get("avgGangSize", 0.0),
            "isk_destroyed": stats.get("iskDestroyed", 0),
            "isk_lost": stats.get("iskLost", 0),
            "fc": stats.get("fc", {}),
            "months": stats.get("months", {}),
            "activity": stats.get("activity", {}),
            "top_ships": [
                {
                    "type_id": s.get("shipTypeID", 0),
                    "name": self._resolve_ship_name(s.get("shipTypeID", 0)),
                    "kills": s.get("kills", 0),
                    "losses": s.get("losses", 0),
                }
                for s in stats.get("topShips", [])[:5]
            ],
        }


def build_activity_heatmap(activity_dict: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build a 7x24 heatmap matrix from zKillboard's raw activity dictionary.

    Returns structured rows for templates with intensity levels (0-4),
    hover tooltips, and calculated prime active timezone.
    """
    if not activity_dict or not isinstance(activity_dict, dict):
        return None

    days_short = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    days_full = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]

    max_val = 0
    hour_totals = {h: 0 for h in range(24)}
    day_totals = {d: 0 for d in range(7)}

    for d in range(7):
        d_map = activity_dict.get(str(d), {})
        for h in range(24):
            v = int(d_map.get(str(h), 0))
            if v > max_val:
                max_val = v
            hour_totals[h] += v
            day_totals[d] += v

    if max_val == 0:
        max_val = 1

    rows = []
    for d in range(7):
        d_map = activity_dict.get(str(d), {})
        hours = []
        for h in range(24):
            count = int(d_map.get(str(h), 0))
            pct = int((count / max_val) * 100) if max_val > 0 else 0
            if count == 0:
                level = 0
            elif pct <= 25:
                level = 1
            elif pct <= 50:
                level = 2
            elif pct <= 75:
                level = 3
            else:
                level = 4
            hours.append(
                {
                    "hour": h,
                    "hour_str": f"{h:02d}:00",
                    "count": count,
                    "pct": pct,
                    "level": level,
                }
            )
        rows.append(
            {
                "day_short": days_short[d],
                "day_full": days_full[d],
                "day_total": day_totals[d],
                "hours": hours,
            }
        )

    total_activity = sum(day_totals.values())
    if total_activity == 0:
        return None

    peak_day_idx = max(day_totals, key=day_totals.get)
    peak_day = days_full[peak_day_idx]

    best_start = max(
        range(24),
        key=lambda s: sum(hour_totals[(s + i) % 24] for i in range(4)),
    )
    best_end = (best_start + 4) % 24
    window_total = sum(hour_totals[(best_start + i) % 24] for i in range(4))
    window_pct = int((window_total / total_activity) * 100)

    if 17 <= best_start <= 22 or (best_start + 4) >= 18 and best_start < 23:
        tz_name = "EU Timezone (Prime EU)"
    elif 0 <= best_start <= 4:
        tz_name = "US Timezone (USTZ East / Central)"
    elif 5 <= best_start <= 9:
        tz_name = "US West / Late USTZ"
    elif 10 <= best_start <= 16:
        tz_name = "AU / Asian Timezone (AUTZ)"
    else:
        tz_name = "Mixed / Global Timezone"

    return {
        "rows": rows,
        "max_val": max_val,
        "total_activity": total_activity,
        "peak_day": peak_day,
        "peak_day_count": day_totals[peak_day_idx],
        "peak_window": f"{best_start:02d}:00 - {best_end:02d}:00 UTC",
        "window_pct": window_pct,
        "tz_name": tz_name,
        "hours_header": [f"{h:02d}" for h in range(24)],
    }

