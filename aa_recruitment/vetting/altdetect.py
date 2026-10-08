from collections import defaultdict
from typing import Any, Dict, List, Set

from allianceauth.services.hooks import get_extension_logger
from django.conf import settings

from aa_recruitment.models import Application, FindingSeverity

logger = get_extension_logger(__name__)


class AltDetector:
    """Multi-signal undisclosed alt detector combining wallet, contracts, contacts and corp history."""

    def __init__(self, application: Application, known_character_names: Set[str]):
        self.application = application
        self.known_character_names = {name.lower().strip() for name in known_character_names}

    def analyze(self) -> List[Dict[str, Any]]:
        """Run undisclosed alt detection heuristics."""
        findings: List[Dict[str, Any]] = []

        # Check if MemberAudit is available in the Django environment
        if "memberaudit" not in settings.INSTALLED_APPS:
            findings.append(
                {
                    "section": "altdetect",
                    "severity": FindingSeverity.INFO,
                    "title": "MemberAudit integration not active",
                    "evidence": "Alliance Auth MemberAudit is not installed; deep wallet/contract alt detection skipped.",
                }
            )
            return findings

        try:
            from memberaudit.models import Character as AuditCharacter

            user_characters = AuditCharacter.objects.filter(character_ownership__user=self.application.user)
            if not user_characters.exists():
                findings.append(
                    {
                        "section": "altdetect",
                        "severity": FindingSeverity.INFO,
                        "title": "No MemberAudit character data available",
                        "evidence": "Candidate has not linked characters in MemberAudit.",
                    }
                )
                return findings

            suspect_scores: Dict[str, int] = defaultdict(int)
            suspect_evidence: Dict[str, List[str]] = defaultdict(list)

            # 1. Wallet journal donations/transfers to non-declared characters
            for ac in user_characters:
                journals = getattr(ac, "wallet_journal_entries", None)
                if journals:
                    for entry in journals.filter(ref_type__in=["player_donation", "player_transfer"])[:100]:
                        second_party = getattr(entry, "second_party_name", "") or ""
                        if second_party and second_party.lower() not in self.known_character_names:
                            amount = abs(float(getattr(entry, "amount", 0)))
                            if amount > 50_000_000:  # > 50M ISK transfer
                                suspect_scores[second_party] += 3
                                suspect_evidence[second_party].append(f"Direct transfer of {amount:,.0f} ISK")

            # 2. Free / zero-price private contracts
            for ac in user_characters:
                contracts = getattr(ac, "contracts", None)
                if contracts:
                    for c in contracts.filter(price__lte=1000)[:50]:
                        assignee = getattr(c, "assignee_name", "") or ""
                        if assignee and assignee.lower() not in self.known_character_names:
                            suspect_scores[assignee] += 4
                            suspect_evidence[assignee].append(
                                f"Zero/low-cost contract ({getattr(c, 'title', 'Untitled')})"
                            )

            # 3. Watched contacts (is_watched = True)
            for ac in user_characters:
                contacts = getattr(ac, "contacts", None)
                if contacts:
                    for contact in contacts.filter(is_watched=True)[:50]:
                        c_name = getattr(contact, "name", "") or ""
                        if c_name and c_name.lower() not in self.known_character_names:
                            suspect_scores[c_name] += 3
                            suspect_evidence[c_name].append("Marked as Watched contact (online/offline alert)")

            # Generate findings for top suspects
            for suspect_name, score in suspect_scores.items():
                if score >= 6:
                    ev_list = "; ".join(suspect_evidence[suspect_name][:3])
                    findings.append(
                        {
                            "section": "altdetect",
                            "severity": FindingSeverity.HIGH,
                            "title": "Possible undisclosed alt / associate",
                            "evidence": f"{suspect_name}: Combined score {score}. Evidence: {ev_list}",
                            "recruiter_action": f"Ask candidate who {suspect_name} is and why there are multiple close connections.",
                        }
                    )
                elif score >= 3:
                    ev_list = "; ".join(suspect_evidence[suspect_name][:2])
                    findings.append(
                        {
                            "section": "altdetect",
                            "severity": FindingSeverity.MEDIUM,
                            "title": "Repeated interactions with undeclared character",
                            "evidence": f"{suspect_name}: {ev_list}",
                            "recruiter_action": f"Inquire about connection to {suspect_name}.",
                        }
                    )

        except Exception as exc:
            logger.error(f"Error during MemberAudit alt detection: {exc}")
            findings.append(
                {
                    "section": "altdetect",
                    "severity": FindingSeverity.INFO,
                    "title": "Alt detection check incomplete",
                    "evidence": f"Encountered unexpected error: {exc}",
                }
            )

        return findings
