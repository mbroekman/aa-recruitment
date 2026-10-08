from datetime import date
from unittest.mock import patch

from allianceauth.eveonline.models import EveCorporationInfo
from allianceauth.tests.auth_utils import AuthUtils
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aa_recruitment.models import (
    CorpActivitySnapshot,
    CorpCombatStats,
    CorpMemberActivity,
    MemberActivityStatus,
)
from aa_recruitment.services.corp_trends import CorpTrendsService


class CorpTrendsModelTests(TestCase):
    def setUp(self):
        self.stats = CorpCombatStats.objects.create(
            corporation_id=98089258,
            corporation_name="Game of Drones",
            corporation_ticker="GOD",
            alliance_name="Northern Coalition.",
            member_count=273,
            is_auth_corp=True,
            ships_destroyed=1250,
            ships_lost=340,
            isk_destroyed=450000000000,
            isk_lost=85000000000,
            months_data={
                "202609": {
                    "key": "202609",
                    "label": "2026-09",
                    "year": 2026,
                    "month": 9,
                    "kills": 150,
                    "losses": 30,
                    "isk_destroyed": 50000000000,
                    "isk_lost": 10000000000,
                    "is_current": False,
                }
            },
        )

    def test_model_str(self):
        self.assertIn("Game of Drones", str(self.stats))
        self.assertIn("[GOD]", str(self.stats))
        self.assertIn("98089258", str(self.stats))

    def test_snapshot_model(self):
        snap = CorpActivitySnapshot.objects.create(
            corporation_id=98089258,
            corporation_name="Game of Drones",
            snapshot_date=date(2026, 10, 8),
            active_count=25,
            low_count=15,
            inactive_count=8,
            dormant_count=2,
            total_members=50,
        )
        self.assertIn("Game of Drones", str(snap))
        self.assertIn("Active=25", str(snap))

    def test_member_activity_model(self):
        member = CorpMemberActivity.objects.create(
            corporation_id=98089258,
            character_id=12345678,
            character_name="Ace Pilot",
            status=MemberActivityStatus.ACTIVE,
            kills_30d=14,
            losses_30d=2,
            isk_destroyed_30d=2500000000,
            isk_lost_30d=300000000,
        )
        self.assertIn("Ace Pilot", str(member))
        self.assertIn("14 kills", str(member))


class CorpTrendsServiceTests(TestCase):
    def setUp(self):
        self.corp_info = EveCorporationInfo.objects.create(
            corporation_id=98000001,
            corporation_name="Test Vanguard Corp",
            corporation_ticker="TVC",
            member_count=50,
        )

    @patch.object(CorpTrendsService, "fetch_zkill_stats")
    @patch.object(CorpTrendsService, "fetch_zkill_killmails")
    def test_sync_corporation(self, mock_killmails, mock_stats):
        mock_stats.return_value = {
            "info": {
                "name": "Test Vanguard Corp",
                "ticker": "TVC",
                "memberCount": 50,
            },
            "shipsDestroyed": 100,
            "shipsLost": 20,
            "iskDestroyed": 25000000000,
            "iskLost": 5000000000,
            "months": {
                "202609": {
                    "shipsDestroyed": 45,
                    "shipsLost": 10,
                    "iskDestroyed": 12000000000,
                    "iskLost": 2000000000,
                }
            },
            "topLists": [
                {
                    "type": "character",
                    "values": [{"id": 999001, "name": "Fleet Commander Bob", "kills": 20, "isk": 5000000000}],
                }
            ],
        }
        mock_killmails.return_value = [
            {
                "killmail_time": timezone.now().isoformat(),
                "zkb": {"totalValue": 500000000},
                "attackers": [
                    {"corporation_id": 98000001, "character_id": 999001, "character_name": "Fleet Commander Bob"}
                ],
                "victim": {"corporation_id": 99999999, "character_id": 111111, "character_name": "Hostile Target"},
            }
        ]

        service = CorpTrendsService()
        combat_stats = service.sync_corporation(98000001)

        self.assertIsNotNone(combat_stats)
        self.assertEqual(combat_stats.corporation_name, "Test Vanguard Corp")
        self.assertTrue(combat_stats.is_auth_corp)
        self.assertIn("202609", combat_stats.months_data)

        # Check member activity
        member = CorpMemberActivity.objects.filter(character_id=999001).first()
        self.assertIsNotNone(member)
        self.assertEqual(member.character_name, "Fleet Commander Bob")
        self.assertEqual(member.kills_30d, 1)

        # Check snapshot
        snapshot = CorpActivitySnapshot.objects.filter(corporation_id=98000001).first()
        self.assertIsNotNone(snapshot)


class CorpTrendsViewsTests(TestCase):
    def setUp(self):
        self.user = AuthUtils.create_user("recruiter_bob")
        AuthUtils.add_main_character_2(
            self.user,
            "Recruiter Bob",
            90010,
            corp_id=98000099,
            corp_name="Frontline Heavy Industries",
            corp_ticker="FHI",
        )
        AuthUtils.add_permissions_to_user_by_name(
            ["aa_recruitment.basic_access", "aa_recruitment.manage_recruitment"],
            self.user,
        )

        self.regular_user = AuthUtils.create_user("regular_joe")
        AuthUtils.add_main_character_2(
            self.regular_user,
            "Regular Joe",
            90011,
            corp_id=98000099,
            corp_name="Frontline Heavy Industries",
            corp_ticker="FHI",
        )
        AuthUtils.add_permissions_to_user_by_name(
            ["aa_recruitment.basic_access"],
            self.regular_user,
        )

        self.corp = EveCorporationInfo.objects.create(
            corporation_id=98000099,
            corporation_name="Frontline Heavy Industries",
            corporation_ticker="FHI",
            member_count=60,
        )

        self.stats = CorpCombatStats.objects.create(
            corporation_id=98000099,
            corporation_name="Frontline Heavy Industries",
            corporation_ticker="FHI",
            is_auth_corp=True,
            months_data={
                "202609": {
                    "key": "202609",
                    "label": "2026-09",
                    "kills": 80,
                    "losses": 15,
                    "isk_destroyed": 15000000000,
                    "isk_lost": 3000000000,
                    "is_current": False,
                }
            },
        )

        CorpActivitySnapshot.objects.create(
            corporation_id=98000099,
            corporation_name="Frontline Heavy Industries",
            snapshot_date=timezone.now().date(),
            active_count=18,
            low_count=12,
            inactive_count=5,
            dormant_count=1,
            total_members=36,
        )

        CorpMemberActivity.objects.create(
            corporation_id=98000099,
            character_id=555001,
            character_name="Top Gunner",
            status=MemberActivityStatus.ACTIVE,
            kills_30d=15,
            losses_30d=1,
            isk_destroyed_30d=3500000000,
            isk_lost_30d=100000000,
        )

    def test_anonymous_redirects_to_login(self):
        url = reverse("aa_recruitment:corp_trends")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_regular_user_permission_denied(self):
        self.client.force_login(self.regular_user)
        url = reverse("aa_recruitment:corp_trends")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)  # permission_required redirects

    def test_recruiter_view_trends_renders_page(self):
        self.client.force_login(self.user)
        url = reverse("aa_recruitment:corp_trends", kwargs={"corp_id": 98000099})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Frontline Heavy Industries trend")
        self.assertContains(resp, "Top Gunner")
        self.assertContains(resp, "Kills and losses per month")
        self.assertContains(resp, "Members by status, per update")

    @patch.object(CorpTrendsService, "sync_corporation")
    def test_recruiter_sync_trends_post(self, mock_sync):
        mock_sync.return_value = self.stats
        self.client.force_login(self.user)
        url = reverse("aa_recruitment:corp_trends_sync", kwargs={"corp_id": 98000099})
        resp = self.client.post(url)
        self.assertRedirects(resp, reverse("aa_recruitment:corp_trends", kwargs={"corp_id": 98000099}))
        mock_sync.assert_called_once_with(98000099)

    def test_api_corp_search(self):
        self.client.force_login(self.user)
        url = reverse("aa_recruitment:api_corp_search")
        resp = self.client.get(url, {"q": "Frontline"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("results", data)
        self.assertTrue(len(data["results"]) >= 1)
        self.assertEqual(data["results"][0]["name"], "Frontline Heavy Industries")
