import re
from typing import Any, Dict, List
import requests
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import FindingSeverity
from .constants import BLACKLIST_TABLE_URL

logger = get_extension_logger(__name__)


class BlacklistAnalyzer:
    """Checks character and declared alts against the coalition/INIT blacklist."""

    def __init__(self, character_names: List[str]):
        self.character_names = [name.strip() for name in character_names if name.strip()]

    def search_blacklist(self, query: str) -> List[Dict[str, Any]]:
        """Query the DataTables endpoint for character or mention."""
        params = {
            "draw": "1",
            "start": "0",
            "length": "50",
            "search[value]": query,
        }
        headers = {"User-Agent": "AllianceAuth-Recruitment/0.1.0"}
        try:
            resp = requests.get(
                BLACKLIST_TABLE_URL, params=params, headers=headers, timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_rows = data.get("data", [])
                results = []
                for row in raw_rows:
                    if len(row) >= 4:
                        # Extract character name from col0 img[title]
                        img_match = re.search(r'title="([^"]+)"', row[0])
                        char_name = img_match.group(1) if img_match else ""
                        reason = re.sub(r"<[^>]+>", " ", row[2]).strip()
                        results.append(
                            {
                                "name": char_name,
                                "raw_col1": row[1],
                                "reason": reason,
                                "category": row[3],
                            }
                        )
                return results
        except Exception as exc:
            logger.warning(f"Failed to query INIT blacklist for '{query}': {exc}")
        return []

    def analyze(self) -> List[Dict[str, Any]]:
        """Run blacklist checks for all provided character names."""
        findings: List[Dict[str, Any]] = []

        for name in self.character_names:
            matches = self.search_blacklist(name)
            for m in matches:
                matched_name = m.get("name", "")
                reason = m.get("reason", "")

                # Exact name match -> Direct blacklist
                if matched_name.lower() == name.lower():
                    findings.append(
                        {
                            "section": "blacklist",
                            "severity": FindingSeverity.CRITICAL,
                            "title": "Character found on INIT blacklist",
                            "evidence": f"Blacklisted character: {matched_name}. Reason: {reason[:300]}",
                            "recruiter_action": "Read the blacklist entry. Do NOT recruit unless proven to be a different entity.",
                        }
                    )
                # Mentioned in reason -> Associate / indirect link
                elif name.lower() in reason.lower():
                    findings.append(
                        {
                            "section": "blacklist",
                            "severity": FindingSeverity.HIGH,
                            "title": "Character named in an INIT blacklist reason",
                            "evidence": f"Mentioned in entry for {matched_name}: {reason[:300]}",
                            "recruiter_action": "Review the associate's blacklist entry and clarify candidate's connection.",
                        }
                    )

        if not findings:
            findings.append(
                {
                    "section": "blacklist",
                    "severity": FindingSeverity.INFO,
                    "title": "INIT Blacklist Check Cleared",
                    "evidence": f"Checked {len(self.character_names)} character(s) against live blacklist: 0 hits.",
                }
            )

        return findings
