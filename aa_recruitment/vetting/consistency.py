import re
from typing import Any, Dict, List, Set

# pyrefly: ignore [missing-import]
from aa_recruitment.models import Application, FindingSeverity


class ConsistencyAnalyzer:
    """Cross-references declared playstyles and character disclosure against telemetry and Auth."""

    def __init__(self, application: Application):
        self.application = application
        self.user = application.user

    def get_known_auth_character_names(self) -> Set[str]:
        """Fetch all character names linked to applicant's Auth account."""
        names = set()
        ownerships = getattr(self.user, "character_ownerships", None)
        if ownerships:
            for co in ownerships.select_related("character").all():
                if co.character and co.character.character_name:
                    names.add(co.character.character_name.strip())
        if self.application.main_character_name:
            names.add(self.application.main_character_name.strip())
        return names

    def extract_declared_characters(self) -> Set[str]:
        """Extract declared character names from application answers."""
        declared = set()
        answers = self.application.answers.select_related("question").all()
        for ans in answers:
            q_text = ans.question.question_text.lower()
            if any(term in q_text for term in ["alts", "characters", "personages", "names", "namen"]):
                # Split on commas, newlines, semicolons
                tokens = re.split(r"[,;\n\r]+", ans.answer_text)
                for t in tokens:
                    cleaned = t.strip()
                    if cleaned and len(cleaned) >= 3 and len(cleaned) <= 37:
                        declared.add(cleaned)
        return declared

    def analyze(self, zkill_findings: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
        """Run consistency checks and character disclosure cross-checks."""
        findings: List[Dict[str, Any]] = []

        known_auth_chars = self.get_known_auth_character_names()
        declared_chars = self.extract_declared_characters()

        def norm(s: str) -> str:
            return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

        known_norms = {norm(n): n for n in known_auth_chars}
        declared_norms = {norm(n): n for n in declared_chars}

        # 1. Undisclosed characters check: known in Auth, but not declared on application form
        if declared_chars:
            undeclared = [
                name
                for k_norm, name in known_norms.items()
                if k_norm not in declared_norms and k_norm != norm(self.application.main_character_name or "")
            ]
            if undeclared:
                findings.append(
                    {
                        "section": "consistency",
                        "severity": FindingSeverity.HIGH,
                        "title": "Incomplete character disclosure",
                        "evidence": f"Characters linked on Auth but not mentioned on form: {', '.join(undeclared)}",
                        "recruiter_action": "Ask candidate why these characters were omitted from the application.",
                    }
                )

        # 2. Declared characters not added to Auth
        missing_on_auth = [name for d_norm, name in declared_norms.items() if d_norm not in known_norms]
        if missing_on_auth:
            findings.append(
                {
                    "section": "consistency",
                    "severity": FindingSeverity.MEDIUM,
                    "title": "Declared characters not registered in Auth",
                    "evidence": f"Candidate mentioned characters on form not yet linked in Auth: {', '.join(missing_on_auth)}",
                    "recruiter_action": "Instruct candidate to add all declared alts to Alliance Auth before final approval.",
                }
            )

        # 3. Application claims vs Telemetry consistency
        full_text = " ".join(ans.answer_text.lower() for ans in self.application.answers.all())
        claims_pvp = bool(re.search(r"\b(pvp|combat|fleet|roaming|hunting|small gang)\b", full_text))

        # Cross-reference with zKill findings
        has_zero_kills = False
        if zkill_findings:
            for zf in zkill_findings:
                if "No zKill activity" in zf.get("title", "") or "0 kills" in zf.get("evidence", ""):
                    has_zero_kills = True
                    break

        if claims_pvp and has_zero_kills:
            findings.append(
                {
                    "section": "consistency",
                    "severity": FindingSeverity.MEDIUM,
                    "title": "Applicant claims PvP activity but has 0 combat kills",
                    "evidence": "Application text highlights PvP experience, but zKillboard shows 0 kills in past 6 months.",
                    "recruiter_action": "Verify if candidate primarily flew logistics, scouting, or used a separate undisclosed combat alt.",
                }
            )

        return findings
