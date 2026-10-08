from typing import Any, Dict, List
import requests
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import FindingSeverity
from .constants import ESI_BASE_URL, HOSTILE_ALLIANCE_TERMS

logger = get_extension_logger(__name__)


class EveWhoAnalyzer:
    """Evaluates corporation hopping, hostile association history, and current affiliation."""

    def __init__(self, character_id: int):
        self.character_id = character_id

    def fetch_corporation_history(self) -> List[Dict[str, Any]]:
        """Fetch corporation history from ESI."""
        url = f"{ESI_BASE_URL}/characters/{self.character_id}/corporation_history/"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
        except Exception as exc:
            logger.warning(
                f"Failed to fetch corporation history for character {self.character_id}: {exc}"
            )
        return []

    def resolve_corporations(self, corp_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Resolve corp IDs to corp and alliance info via ESI."""
        resolved: Dict[int, Dict[str, Any]] = {}
        for cid in corp_ids[:20]:  # Limit to 20 most recent to keep execution fast
            try:
                resp = requests.get(f"{ESI_BASE_URL}/corporations/{cid}/", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    c_name = data.get("name", "")
                    a_id = data.get("alliance_id")
                    a_name = ""
                    if a_id:
                        a_resp = requests.get(
                            f"{ESI_BASE_URL}/alliances/{a_id}/", timeout=5
                        )
                        if a_resp.status_code == 200:
                            a_name = a_resp.json().get("name", "")
                    resolved[cid] = {"corp_name": c_name, "alliance_name": a_name}
            except Exception:
                continue
        return resolved

    def analyze(self) -> List[Dict[str, Any]]:
        """Analyze corporation history and check against hostile alliance/corp lists."""
        findings: List[Dict[str, Any]] = []
        history = self.fetch_corporation_history()

        if not history:
            return findings

        corp_ids = [entry["corporation_id"] for entry in history]
        resolved_corps = self.resolve_corporations(corp_ids)

        current_entry = history[0]
        current_corp = resolved_corps.get(current_entry["corporation_id"], {})
        current_cname = current_corp.get("corp_name", "").lower()
        current_aname = current_corp.get("alliance_name", "").lower()

        # 1. Check if CURRENTLY in known hostile
        is_current_hostile = False
        for term in HOSTILE_ALLIANCE_TERMS:
            if term in current_aname or term in current_cname:
                findings.append(
                    {
                        "section": "evewho",
                        "severity": FindingSeverity.CRITICAL,
                        "title": "CURRENTLY in a known hostile entity",
                        "evidence": f"Currently in {current_corp.get('corp_name')} / {current_corp.get('alliance_name')}",
                        "recruiter_action": "Do not invite until candidate leaves the hostile corp/alliance.",
                    }
                )
                is_current_hostile = True
                break

        # 2. Check past hostile history
        past_hostiles = []
        for entry in history[1:]:
            c_info = resolved_corps.get(entry["corporation_id"], {})
            cname = c_info.get("corp_name", "").lower()
            aname = c_info.get("alliance_name", "").lower()
            for term in HOSTILE_ALLIANCE_TERMS:
                if term in aname or term in cname:
                    display = f"{c_info.get('corp_name')} ({c_info.get('alliance_name') or 'No Alliance'})"
                    if display not in past_hostiles:
                        past_hostiles.append(display)

        if past_hostiles:
            findings.append(
                {
                    "section": "evewho",
                    "severity": FindingSeverity.HIGH,
                    "title": "EVEWho history contains known hostile alliance term",
                    "evidence": f"Past affiliation with: {', '.join(past_hostiles[:3])}",
                    "recruiter_action": "Inquire about circumstances of leaving and verify vouch/reputation.",
                }
            )

        # 3. Corporation hopping check (>10 corporations)
        if len(history) >= 12:
            findings.append(
                {
                    "section": "evewho",
                    "severity": FindingSeverity.LOW,
                    "title": "Frequent corporation hopping",
                    "evidence": f"Character has been in {len(history)} distinct corporations.",
                    "recruiter_action": "Check reasons for frequent corp hopping.",
                }
            )

        # Summary info
        findings.append(
            {
                "section": "evewho",
                "severity": FindingSeverity.INFO,
                "title": "Corporation Affiliation Overview",
                "evidence": f"Current: {current_corp.get('corp_name') or 'Unknown'} ({current_corp.get('alliance_name') or 'No Alliance'}) - {len(history)} total corp records.",
            }
        )

        return findings
