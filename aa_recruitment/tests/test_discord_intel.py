from datetime import timedelta
from unittest.mock import MagicMock, patch

from allianceauth.tests.auth_utils import AuthUtils
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aa_recruitment.models import (
    DiscordIntelChannel,
    DiscordIntelMessage,
    FindingSeverity,
)
from aa_recruitment.vetting.discord_intel import DiscordIntelAnalyzer


class DiscordIntelModelTests(TestCase):
    def setUp(self):
        self.channel = DiscordIntelChannel.objects.create(
            name="Test Blacklist",
            guild_name="Allied Coalition",
            guild_id="111222333",
            channel_id="999888777",
            sync_interval_minutes=30,
            default_severity=FindingSeverity.HIGH,
        )

    def test_channel_str(self):
        self.assertIn("#Test Blacklist", str(self.channel))
        self.assertIn("Allied Coalition", str(self.channel))

    def test_message_creation_and_str(self):
        msg = DiscordIntelMessage.objects.create(
            channel=self.channel,
            discord_message_id="1234567890",
            author_id="444555",
            author_name="IntelOfficer",
            content="Warning: Pilot BadGuy was caught stealing corp assets.",
            sent_at=timezone.now(),
        )
        self.assertEqual(self.channel.messages.count(), 1)
        self.assertIn("1234567890", str(msg))
        self.assertIn("IntelOfficer", str(msg))


class DiscordIntelAnalyzerTests(TestCase):
    def setUp(self):
        self.channel = DiscordIntelChannel.objects.create(
            name="Coalition Intel",
            guild_name="Imperium",
            channel_id="123123123",
            default_severity=FindingSeverity.HIGH,
            is_active=True,
        )
        self.msg = DiscordIntelMessage.objects.create(
            channel=self.channel,
            discord_message_id="987654321",
            author_name="Spymaster",
            content="Suspect alert: Pilot SuspiciousGuy awoxed a Rorqual in Delve yesterday.",
            sent_at=timezone.now() - timedelta(days=2),
        )

    def test_match_found(self):
        analyzer = DiscordIntelAnalyzer(["SuspiciousGuy"])
        findings = analyzer.analyze()
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["section"], "discord")
        self.assertEqual(f["severity"], FindingSeverity.HIGH)
        self.assertIn("SuspiciousGuy", f["title"])
        self.assertIn("#Coalition Intel", f["title"])
        self.assertIn("Spymaster", f["evidence"])
        self.assertIn("awoxed", f["evidence"])

    def test_no_match(self):
        analyzer = DiscordIntelAnalyzer(["CleanPilot"])
        findings = analyzer.analyze()
        self.assertEqual(len(findings), 0)

    def test_inactive_channel_ignored(self):
        self.channel.is_active = False
        self.channel.save()

        analyzer = DiscordIntelAnalyzer(["SuspiciousGuy"])
        findings = analyzer.analyze()
        self.assertEqual(len(findings), 0)

    def test_detailed_matches_found(self):
        analyzer = DiscordIntelAnalyzer(["SuspiciousGuy"])
        matches = analyzer.get_detailed_matches()
        self.assertEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["matched_name"], "SuspiciousGuy")
        self.assertEqual(m["channel_name"], "Coalition Intel")
        self.assertIn("<mark", m["highlighted_content"])
        self.assertIn("SuspiciousGuy", m["highlighted_content"])


class DiscordIntelViewsTests(TestCase):
    def setUp(self):
        self.admin_user = AuthUtils.create_user("admin_user")
        AuthUtils.add_main_character_2(
            self.admin_user,
            "Admin Pilot",
            90001,
            corp_id=1001,
            corp_name="Admin Corp",
            corp_ticker="ADM",
        )
        AuthUtils.add_permissions_to_user_by_name(["aa_recruitment.admin_recruitment"], self.admin_user)

        self.channel = DiscordIntelChannel.objects.create(
            name="Drama Channel",
            guild_name="Server A",
            channel_id="555666777",
            sync_interval_minutes=60,
        )

    def test_manage_forms_displays_discord_channels(self):
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("aa_recruitment:manage_forms"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Discord Intel Channels")
        self.assertContains(res, "Drama Channel")

    def test_channel_create_view(self):
        self.client.force_login(self.admin_user)
        res = self.client.post(
            reverse("aa_recruitment:discord_channel_create"),
            {
                "name": "New Intel",
                "guild_name": "Test Server",
                "guild_id": "111",
                "channel_id": "222333444",
                "sync_interval_minutes": 30,
                "default_severity": FindingSeverity.CRITICAL,
                "is_active": True,
            },
        )
        self.assertRedirects(res, f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
        self.assertTrue(DiscordIntelChannel.objects.filter(name="New Intel").exists())

    def test_channel_edit_view(self):
        self.client.force_login(self.admin_user)
        res = self.client.post(
            reverse("aa_recruitment:discord_channel_edit", kwargs={"channel_id": self.channel.pk}),
            {
                "name": "Updated Drama Channel",
                "guild_name": "Server A",
                "channel_id": self.channel.channel_id,
                "sync_interval_minutes": 45,
                "default_severity": FindingSeverity.MEDIUM,
                "is_active": True,
            },
        )
        self.assertRedirects(res, f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.name, "Updated Drama Channel")
        self.assertEqual(self.channel.sync_interval_minutes, 45)

    def test_channel_delete_view(self):
        self.client.force_login(self.admin_user)
        res = self.client.post(reverse("aa_recruitment:discord_channel_delete", kwargs={"channel_id": self.channel.pk}))
        self.assertRedirects(res, f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
        self.assertFalse(DiscordIntelChannel.objects.filter(pk=self.channel.pk).exists())

    def test_save_global_discord_token(self):
        from aa_recruitment.models import RecruitmentConfig

        self.client.force_login(self.admin_user)
        res = self.client.post(
            reverse("aa_recruitment:manage_forms"),
            {
                "save_discord_token": "1",
                "global_discord_user_token": "DISCORD_SECRET_12345",
            },
        )
        self.assertRedirects(res, f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
        config = RecruitmentConfig.get_solo()
        self.assertEqual(config.discord_user_token, "DISCORD_SECRET_12345")

    @patch("aa_recruitment.services.discord_intel.requests.get")
    def test_backfill_channel_history_service(self, mock_get):
        from aa_recruitment.services.discord_intel import backfill_channel_history

        self.channel.user_token = "TEST_TOKEN"
        self.channel.save()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "id": "200",
                "content": "Message 200",
                "author": {"username": "UserA"},
                "timestamp": "2026-10-08T12:00:00Z",
            },
            {
                "id": "150",
                "content": "Message 150",
                "author": {"username": "UserB"},
                "timestamp": "2026-10-08T11:00:00Z",
            },
        ]
        mock_get.return_value = mock_resp

        count, err = backfill_channel_history(self.channel, max_messages=2)
        self.assertIsNone(err)
        self.assertEqual(count, 2)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.last_message_id, "200")
        self.assertEqual(self.channel.total_messages_stored, 2)

    def test_discord_channel_backfill_view(self):
        self.client.force_login(self.admin_user)
        with patch("aa_recruitment.views.backfill_channel_history", return_value=(50, None)) as mock_backfill:
            res = self.client.post(
                reverse("aa_recruitment:discord_channel_backfill", kwargs={"channel_id": self.channel.pk}),
                {"max_messages": "500"},
            )
            self.assertRedirects(res, f"{reverse('aa_recruitment:manage_forms')}?tab=discord")
            mock_backfill.assert_called_once_with(self.channel, max_messages=500)

    def test_recruiter_detail_renders_discord_intel_tab_when_matches_found(self):
        from aa_recruitment.models import Application, ApplicationForm, ApplicationStatus

        form = ApplicationForm.objects.create(title="Main Form", slug="main-form", is_active=True)
        app = Application.objects.create(
            form=form,
            user=self.admin_user,
            main_character_name="SuspiciousGuy",
            status=ApplicationStatus.PENDING,
        )

        DiscordIntelMessage.objects.create(
            channel=self.channel,
            discord_message_id="555666777",
            author_name="CounterIntel",
            content="Alert: SuspiciousGuy joined blacklisted entity.",
            sent_at=timezone.now(),
        )

        AuthUtils.add_permissions_to_user_by_name(["aa_recruitment.manage_recruitment"], self.admin_user)
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("aa_recruitment:recruiter_detail", kwargs={"application_id": app.pk}))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode()
        self.assertIn("Discord Intel Mentions Detected!", content)
        self.assertIn("tab-discord", content)
        self.assertIn("Alert: <mark", content)
