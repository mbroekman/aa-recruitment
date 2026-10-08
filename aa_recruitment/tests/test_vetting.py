from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase

from aa_recruitment.models import (
    Application,
    ApplicationForm,
    ApplicationStatus,
    FindingSeverity,
    RiskLevel,
    VettingVerdict,
)
from aa_recruitment.vetting.engine import VettingEngine
from aa_recruitment.vetting.recommendation import (
    calculate_risk_score,
    determine_verdict,
    enrich_finding,
)


class VettingRecommendationTests(TestCase):
    def test_enrich_finding_suggests_action_and_question(self):
        raw_finding = {
            "title": "Character found on INIT blacklist",
            "evidence": "CharacterName: listed for intel leak",
            "severity": "critical",
        }
        enriched = enrich_finding(raw_finding)
        self.assertEqual(enriched.get("rule_weight"), "reject")
        self.assertIn("Read the blacklist entry", enriched.get("recruiter_action", ""))

    def test_calculate_risk_score_and_caps(self):
        findings = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        score, level = calculate_risk_score(findings)
        # 40 + 20 + 10 + 2 = 72 (Orange)
        self.assertEqual(score, 72)
        self.assertEqual(level, RiskLevel.ORANGE)

    def test_determine_verdict_reject_on_blacklist(self):
        findings = [
            {
                "rule_weight": "reject",
                "rule_why": "On the INIT blacklist",
                "title": "Character found on INIT blacklist",
            }
        ]
        verdict, reason = determine_verdict(findings, 40, RiskLevel.ORANGE)
        self.assertEqual(verdict, VettingVerdict.REJECT)
        self.assertEqual(reason, "On the INIT blacklist")


class VettingEngineIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="candidate_pilot", password="password123"
        )
        self.form = ApplicationForm.objects.create(
            title="Standard Application",
            slug="standard-application",
            description="Recruitment guidelines.",
            is_active=True,
        )
        self.application = Application.objects.create(
            form=self.form,
            user=self.user,
            main_character_name="Candidate Pilot",
            status=ApplicationStatus.PENDING,
        )

    @patch("aa_recruitment.vetting.blacklist.BlacklistAnalyzer.search_blacklist")
    @patch("aa_recruitment.vetting.evewho.EveWhoAnalyzer.fetch_corporation_history")
    @patch("aa_recruitment.vetting.zkill.ZKillAnalyzer.fetch_kills_and_losses")
    def test_run_vetting_creates_report(self, mock_zkill, mock_evewho, mock_bl):
        mock_bl.return_value = []
        mock_evewho.return_value = []
        mock_zkill.return_value = []

        report = VettingEngine.run(self.application)

        self.assertIsNotNone(report)
        self.assertEqual(report.application, self.application)
        self.assertIn(report.verdict, [VettingVerdict.ACCEPT_LOW, VettingVerdict.ACCEPT_MED, VettingVerdict.ACCEPT_HIGH, VettingVerdict.REJECT])
        self.assertTrue(report.findings.exists())
        self.assertIn("RECRUITMENT SECURITY VETTING REPORT", report.ai_package)

    @patch("aa_recruitment.vetting.blacklist.BlacklistAnalyzer.search_blacklist")
    @patch("aa_recruitment.vetting.evewho.EveWhoAnalyzer.fetch_corporation_history")
    @patch("aa_recruitment.vetting.zkill.ZKillAnalyzer.fetch_kills_and_losses")
    def test_vetting_flags_blacklist_match(self, mock_zkill, mock_evewho, mock_bl):
        mock_bl.return_value = [
            {
                "name": "Candidate Pilot",
                "raw_col1": "corp/alliance",
                "reason": "Hostile intel spy and awoxer",
                "category": "character",
            }
        ]
        mock_evewho.return_value = []
        mock_zkill.return_value = []

        report = VettingEngine.run(self.application)

        self.assertEqual(report.verdict, VettingVerdict.REJECT)
        self.assertTrue(
            report.findings.filter(title="Character found on INIT blacklist").exists()
        )
        bl_finding = report.findings.get(title="Character found on INIT blacklist")
        self.assertEqual(bl_finding.severity, FindingSeverity.CRITICAL)
        self.assertIn("Hostile intel spy", bl_finding.evidence)
