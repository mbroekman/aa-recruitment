from typing import Any, Dict, List
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import (
    Application,
    VettingFinding,
    VettingReport,
)
from .altdetect import AltDetector
from .blacklist import BlacklistAnalyzer
from .consistency import ConsistencyAnalyzer
from .evewho import EveWhoAnalyzer
from .recommendation import (
    calculate_risk_score,
    determine_verdict,
    enrich_finding,
)
from .zkill import ZKillAnalyzer

logger = get_extension_logger(__name__)


class VettingEngine:
    """Core security vetting orchestrator for recruitment applications."""

    @classmethod
    def run(cls, application: Application) -> VettingReport:
        """Run all vetting checks, compute risk score and verdict, and persist results."""
        logger.info(f"Starting automated vetting audit for Application #{application.pk}")

        all_findings: List[Dict[str, Any]] = []

        # 1. Collect all known character names & IDs for applicant
        known_char_names: List[str] = []
        main_char_id: int | None = None

        profile = getattr(application.user, "profile", None)
        main_char = getattr(profile, "main_character", None) if profile else None
        if main_char:
            main_char_id = main_char.character_id
            known_char_names.append(main_char.character_name)
        elif application.main_character_name:
            known_char_names.append(application.main_character_name)

        ownerships = getattr(application.user, "character_ownerships", None)
        if ownerships:
            for co in ownerships.select_related("character").all():
                if co.character and co.character.character_name:
                    known_char_names.append(co.character.character_name)
                    if not main_char_id:
                        main_char_id = co.character.character_id

        known_char_names = list(set(known_char_names))

        # 2. Blacklist Check
        try:
            bl_analyzer = BlacklistAnalyzer(known_char_names)
            bl_findings = bl_analyzer.analyze()
            all_findings.extend(bl_findings)
        except Exception as exc:
            logger.error(f"Blacklist check error for App #{application.pk}: {exc}")

        # 3. EveWho & Corporation History Check
        ew_history: List[Dict[str, Any]] = []
        if main_char_id:
            try:
                ew_analyzer = EveWhoAnalyzer(main_char_id)
                ew_findings = ew_analyzer.analyze()
                ew_history = ew_analyzer.get_history_list()
                all_findings.extend(ew_findings)
            except Exception as exc:
                logger.error(f"EVEWho check error for App #{application.pk}: {exc}")

        # 4. zKillboard Combat Activity Check
        zk_findings: List[Dict[str, Any]] = []
        zk_data: Dict[str, Any] = {}
        if main_char_id:
            try:
                zk_analyzer = ZKillAnalyzer(main_char_id)
                zk_findings = zk_analyzer.analyze()
                zk_data = zk_analyzer.get_summary_dict()
                all_findings.extend(zk_findings)
            except Exception as exc:
                logger.error(f"zKillboard check error for App #{application.pk}: {exc}")

        # 5. Consistency & Character Disclosure Check
        try:
            cons_analyzer = ConsistencyAnalyzer(application)
            cons_findings = cons_analyzer.analyze(zkill_findings=zk_findings)
            all_findings.extend(cons_findings)
        except Exception as exc:
            logger.error(f"Consistency check error for App #{application.pk}: {exc}")

        # 6. Undeclared Alt Detection
        try:
            alt_detector = AltDetector(application, set(known_char_names))
            alt_findings = alt_detector.analyze()
            all_findings.extend(alt_findings)
        except Exception as exc:
            logger.error(f"Alt detection check error for App #{application.pk}: {exc}")

        # 7. Enrich findings with recruiter actions & questions
        enriched_findings = [enrich_finding(f) for f in all_findings]

        # 8. Calculate risk score, risk level, and verdict
        risk_score, risk_level = calculate_risk_score(enriched_findings)
        verdict, verdict_reason = determine_verdict(
            enriched_findings, risk_score, risk_level
        )

        # 9. Format Executive Summary & AI Context Package
        summary_lines = [
            f"Vetting audit completed for {application.user.username} (Main: {application.main_character_name or 'Unknown'}).",
            f"Verdict: {verdict.upper()} (Risk Level: {risk_level.upper()}, Score: {risk_score}).",
        ]
        if verdict_reason:
            summary_lines.append(f"Primary factor: {verdict_reason}.")

        summary_text = "\n".join(summary_lines)

        ai_package_lines = [
            "### RECRUITMENT SECURITY VETTING REPORT",
            f"Applicant: {application.user.username}",
            f"Main Character: {application.main_character_name}",
            f"Known Auth Characters: {', '.join(known_char_names)}",
            f"Calculated Risk Score: {risk_score} [{risk_level.upper()}]",
            f"Recommended Verdict: {verdict.upper()}",
            f"Verdict Justification: {verdict_reason or 'Standard review profile'}",
            "",
            "#### SECURITY FINDINGS & EVIDENCE:",
        ]

        for idx, f in enumerate(enriched_findings, 1):
            ai_package_lines.append(
                f"{idx}. [{f.get('severity', 'info').upper()}] {f.get('title')}: {f.get('evidence')}"
            )
            if f.get("suggested_question"):
                ai_package_lines.append(f"   -> Suggested Interview Question: {f.get('suggested_question')}")
            if f.get("recruiter_action"):
                ai_package_lines.append(f"   -> Recruiter Action: {f.get('recruiter_action')}")

        ai_package_lines.append("")
        ai_package_lines.append("#### APPLICATION QUESTIONNAIRE RESPONSES:")
        for ans in application.answers.select_related("question").all():
            ai_package_lines.append(f"Q: {ans.question.question_text}")
            ai_package_lines.append(f"A: {ans.answer_text}")

        ai_package_text = "\n".join(ai_package_lines)

        # 10. Persist Report & Findings in Database
        report, _ = VettingReport.objects.update_or_create(
            application=application,
            defaults={
                "risk_score": risk_score,
                "risk_level": risk_level,
                "verdict": verdict,
                "verdict_reason": verdict_reason,
                "summary": summary_text,
                "ai_package": ai_package_text,
                "zkill_data": zk_data,
                "corp_history": ew_history,
            },
        )

        # Clean existing findings for fresh report
        report.findings.all().delete()

        for f in enriched_findings:
            VettingFinding.objects.create(
                report=report,
                section=f.get("section", "general"),
                severity=f.get("severity", "info"),
                title=f.get("title", ""),
                evidence=f.get("evidence", ""),
                recruiter_action=f.get("recruiter_action", ""),
                suggested_question=f.get("suggested_question", ""),
            )

        logger.info(
            f"Vetting audit finished for Application #{application.pk}: "
            f"Score {risk_score}, Verdict {verdict}"
        )
        return report
