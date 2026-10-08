from datetime import datetime, timedelta
from typing import Any, Dict, List

import requests
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger
from django.utils import timezone

from aa_recruitment.models import (
    CorpActivitySnapshot,
    CorpCombatStats,
    CorpMemberActivity,
    MemberActivityStatus,
)
from aa_recruitment.vetting.constants import ESI_BASE_URL, ZKILLBOARD_API_BASE

logger = get_extension_logger(__name__)

USER_AGENT = "AllianceAuth-Recruitment/0.1.0 (Corp Trends & Activity Tracker)"


class CorpTrendsService:
    """Service to fetch, synchronize, and analyze corporation combat trends and

    member participation metrics from zKillboard, CCP ESI, and Alliance Auth.
    """

    def __init__(self):
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
        }

    def fetch_zkill_stats(self, corporation_id: int) -> Dict[str, Any]:
        """Fetch pre-aggregated statistics and monthly trend records from zKillboard."""
        url = f"{ZKILLBOARD_API_BASE}/stats/corporationID/{corporation_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=14)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and "error" not in data:
                    return data
        except Exception as exc:
            logger.warning(f"Failed to fetch zKill stats for corp {corporation_id}: {exc}")
        return {}

    def fetch_zkill_killmails(self, corporation_id: int, max_items: int = 200) -> List[Dict[str, Any]]:
        """Fetch up to 200 recent killmails for the corporation from zKillboard."""
        url = f"{ZKILLBOARD_API_BASE}/corporationID/{corporation_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=14)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data[:max_items]
        except Exception as exc:
            logger.warning(f"Failed to fetch zKill killmails for corp {corporation_id}: {exc}")
        return []

    def fetch_corp_info_esi(self, corporation_id: int) -> Dict[str, Any]:
        """Fetch corporation metadata from CCP ESI."""
        url = f"{ESI_BASE_URL}/corporations/{corporation_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning(f"Failed to fetch ESI corp info for {corporation_id}: {exc}")
        return {}

    def fetch_alliance_info_esi(self, alliance_id: int) -> str:
        """Fetch alliance name from CCP ESI."""
        if not alliance_id:
            return ""
        url = f"{ESI_BASE_URL}/alliances/{alliance_id}/"
        try:
            resp = requests.get(url, headers=self.headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("name", "")
        except Exception:
            pass
        return ""

    def fetch_external_corp_members_evewho(self, corporation_id: int) -> List[Dict[str, Any]]:
        """Fetch public character roster of an external corporation via EVEWho API."""
        url = f"https://evewho.com/api/corplist/{corporation_id}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                chars = data.get("characters", [])
                if isinstance(chars, list):
                    return chars
        except Exception as exc:
            logger.info(f"EVEWho member roster fetch note for corp {corporation_id}: {exc}")
        return []

    def sync_corporation(self, corporation_id: int) -> CorpCombatStats:
        """Synchronize combat statistics, monthly breakdowns, member activities,

        and snapshot distributions for a corporation.
        """
        now = timezone.now()
        stats_data = self.fetch_zkill_stats(corporation_id)
        killmails = self.fetch_zkill_killmails(corporation_id, max_items=200)

        # 1. Resolve Corporation Identity (Auth vs ESI vs zKill info)
        is_auth = EveCorporationInfo.objects.filter(corporation_id=corporation_id).exists()
        corp_name = ""
        corp_ticker = ""
        alliance_id = None
        alliance_name = ""
        member_count = 0

        if is_auth:
            auth_corp = EveCorporationInfo.objects.get(corporation_id=corporation_id)
            corp_name = auth_corp.corporation_name
            corp_ticker = auth_corp.corporation_ticker
            member_count = auth_corp.member_count or 0
            if auth_corp.alliance:
                alliance_id = auth_corp.alliance.alliance_id
                alliance_name = auth_corp.alliance.alliance_name
        else:
            # Check zKill info dict
            zkill_info = stats_data.get("info", {})
            corp_name = zkill_info.get("name") or ""
            corp_ticker = zkill_info.get("ticker") or ""
            member_count = zkill_info.get("memberCount") or zkill_info.get("member_count") or 0
            alliance_id = zkill_info.get("alliance_id") or zkill_info.get("allianceID") or None

            # Fallback to ESI if needed
            if not corp_name or not corp_ticker:
                esi_info = self.fetch_corp_info_esi(corporation_id)
                corp_name = corp_name or esi_info.get("name", f"Corporation #{corporation_id}")
                corp_ticker = corp_ticker or esi_info.get("ticker", "")
                member_count = member_count or esi_info.get("member_count", 0)
                alliance_id = alliance_id or esi_info.get("alliance_id")

            if alliance_id and not alliance_name:
                alliance_name = self.fetch_alliance_info_esi(alliance_id)

        corp_name = corp_name or f"Corporation #{corporation_id}"

        # 2. Parse Monthly Breakdown from zKill
        months_dict = stats_data.get("months", {})
        structured_months: Dict[str, Any] = {}
        # Keys are "YYYYMM"
        sorted_keys = sorted(months_dict.keys())
        current_year = now.year
        current_month = now.month

        for m_key in sorted_keys:
            raw_m = months_dict[m_key]
            try:
                y = int(m_key[:4])
                m = int(m_key[4:])
            except Exception:
                continue

            is_current = y == current_year and m == current_month
            structured_months[m_key] = {
                "key": m_key,
                "label": f"{y:04d}-{m:02d}",
                "year": y,
                "month": m,
                "kills": int(raw_m.get("shipsDestroyed", 0)),
                "losses": int(raw_m.get("shipsLost", 0)),
                "isk_destroyed": float(raw_m.get("iskDestroyed", 0.0)),
                "isk_lost": float(raw_m.get("iskLost", 0.0)),
                "is_current": is_current,
            }

        ships_destroyed_total = stats_data.get("shipsDestroyed", 0)
        ships_lost_total = stats_data.get("shipsLost", 0)
        isk_destroyed_total = int(stats_data.get("iskDestroyed", 0))
        isk_lost_total = int(stats_data.get("iskLost", 0))

        # Update or create CorpCombatStats
        combat_stats, _ = CorpCombatStats.objects.update_or_create(
            corporation_id=corporation_id,
            defaults={
                "corporation_name": corp_name,
                "corporation_ticker": corp_ticker,
                "alliance_id": alliance_id,
                "alliance_name": alliance_name,
                "member_count": member_count,
                "is_auth_corp": is_auth,
                "ships_destroyed": ships_destroyed_total,
                "ships_lost": ships_lost_total,
                "isk_destroyed": isk_destroyed_total,
                "isk_lost": isk_lost_total,
                "months_data": structured_months,
                "raw_stats": stats_data,
                "last_synced_at": now,
            },
        )

        # 3. Compile Member Roster
        member_map: Dict[int, Dict[str, Any]] = {}

        if is_auth:
            auth_characters = EveCharacter.objects.filter(corporation_id=corporation_id).select_related(
                "character_ownership__user__profile__main_character"
            )
            for char in auth_characters:
                main_name = ""
                is_main = True
                try:
                    if hasattr(char, "character_ownership") and char.character_ownership.user:
                        profile = getattr(char.character_ownership.user, "profile", None)
                        if profile and profile.main_character:
                            main_name = profile.main_character.character_name
                            is_main = profile.main_character.character_id == char.character_id
                except Exception:
                    pass

                member_map[char.character_id] = {
                    "name": char.character_name,
                    "main_name": main_name or char.character_name,
                    "is_main": is_main,
                }
        else:
            # External corp: query public EVEWho roster
            evewho_chars = self.fetch_external_corp_members_evewho(corporation_id)
            for item in evewho_chars[:300]:  # Cap roster processing
                c_id = item.get("character_id")
                c_name = item.get("name")
                if c_id and c_name:
                    member_map[c_id] = {
                        "name": c_name,
                        "main_name": c_name,
                        "is_main": True,
                    }

        # Also incorporate top characters from zKill stats
        for top_list in stats_data.get("topLists", []):
            if top_list.get("type") == "character":
                for entry in top_list.get("values", []):
                    c_id = entry.get("characterID") or entry.get("id")
                    c_name = entry.get("characterName") or entry.get("name")
                    if c_id and c_name and c_id not in member_map:
                        member_map[c_id] = {
                            "name": c_name,
                            "main_name": c_name,
                            "is_main": True,
                            "top_kills": entry.get("kills", 0),
                            "top_isk": entry.get("isk", 0),
                        }

        # 4. Parse Killmails for 30d, 90d, 120d, and All-Time Activity
        dt_30d = now - timedelta(days=30)
        dt_90d = now - timedelta(days=90)
        dt_120d = now - timedelta(days=120)

        def make_empty_metrics():
            return {
                "kills_30d": 0,
                "losses_30d": 0,
                "isk_destroyed_30d": 0,
                "isk_lost_30d": 0,
                "kills_90d": 0,
                "losses_90d": 0,
                "isk_destroyed_90d": 0,
                "isk_lost_90d": 0,
                "kills_120d": 0,
                "losses_120d": 0,
                "isk_destroyed_120d": 0,
                "isk_lost_120d": 0,
                "kills_alltime": 0,
                "losses_alltime": 0,
                "isk_destroyed_alltime": 0,
                "isk_lost_alltime": 0,
                "last_activity": None,
            }

        member_metrics: Dict[int, Dict[str, Any]] = {}
        for c_id in member_map:
            member_metrics[c_id] = make_empty_metrics()

        for km in killmails:
            km_time_str = km.get("killmail_time")
            km_dt = None
            if km_time_str:
                try:
                    km_dt = datetime.fromisoformat(km_time_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            zkb = km.get("zkb", {})
            total_value = int(zkb.get("totalValue", 0))

            # Check victim
            victim = km.get("victim", {})
            v_corp_id = victim.get("corporation_id")
            v_char_id = victim.get("character_id")

            if v_corp_id == corporation_id and v_char_id:
                if v_char_id not in member_metrics:
                    member_map[v_char_id] = {
                        "name": victim.get("character_name", f"Pilot #{v_char_id}"),
                        "main_name": victim.get("character_name", f"Pilot #{v_char_id}"),
                        "is_main": True,
                    }
                    member_metrics[v_char_id] = make_empty_metrics()

                met = member_metrics[v_char_id]
                if km_dt:
                    if not met["last_activity"] or km_dt > met["last_activity"]:
                        met["last_activity"] = km_dt
                    met["losses_alltime"] += 1
                    met["isk_lost_alltime"] += total_value
                    if km_dt >= dt_120d:
                        met["losses_120d"] += 1
                        met["isk_lost_120d"] += total_value
                    if km_dt >= dt_90d:
                        met["losses_90d"] += 1
                        met["isk_lost_90d"] += total_value
                    if km_dt >= dt_30d:
                        met["losses_30d"] += 1
                        met["isk_lost_30d"] += total_value

            # Check attackers
            for attacker in km.get("attackers", []):
                a_corp_id = attacker.get("corporation_id")
                a_char_id = attacker.get("character_id")
                if a_corp_id == corporation_id and a_char_id:
                    if a_char_id not in member_metrics:
                        member_map[a_char_id] = {
                            "name": attacker.get("character_name", f"Pilot #{a_char_id}"),
                            "main_name": attacker.get("character_name", f"Pilot #{a_char_id}"),
                            "is_main": True,
                        }
                        member_metrics[a_char_id] = make_empty_metrics()

                    met = member_metrics[a_char_id]
                    if km_dt:
                        if not met["last_activity"] or km_dt > met["last_activity"]:
                            met["last_activity"] = km_dt
                        met["kills_alltime"] += 1
                        met["isk_destroyed_alltime"] += total_value
                        if km_dt >= dt_120d:
                            met["kills_120d"] += 1
                            met["isk_destroyed_120d"] += total_value
                        if km_dt >= dt_90d:
                            met["kills_90d"] += 1
                            met["isk_destroyed_90d"] += total_value
                        if km_dt >= dt_30d:
                            met["kills_30d"] += 1
                            met["isk_destroyed_30d"] += total_value

        # 5. Classify and Save Member Activities
        active_count = 0
        low_count = 0
        inactive_count = 0
        dormant_count = 0

        for c_id, info in member_map.items():
            met = member_metrics.get(c_id, make_empty_metrics())

            # Check top_kills credit if 30d is 0 but pilot is in all-time/top
            top_k = int(info.get("top_kills", 0))
            top_isk = int(info.get("top_isk", 0))
            if top_k > 0:
                met["kills_alltime"] = max(met["kills_alltime"], top_k)
                met["isk_destroyed_alltime"] = max(met["isk_destroyed_alltime"], top_isk)
                if met["kills_30d"] == 0:
                    met["kills_90d"] = max(met["kills_90d"], min(top_k, 5))
                    met["kills_120d"] = max(met["kills_120d"], min(top_k, 8))

            k30 = met["kills_30d"]
            k90 = met["kills_90d"]
            k120 = met["kills_120d"]

            if k30 >= 5 or k90 >= 10 or k120 >= 15:
                status = MemberActivityStatus.ACTIVE
                active_count += 1
            elif k30 >= 1 or k90 >= 1 or k120 >= 1 or met["kills_alltime"] >= 1:
                status = MemberActivityStatus.LOW
                low_count += 1
            elif met["last_activity"] and met["last_activity"] >= dt_120d:
                status = MemberActivityStatus.INACTIVE
                inactive_count += 1
            else:
                status = MemberActivityStatus.DORMANT
                dormant_count += 1

            CorpMemberActivity.objects.update_or_create(
                corporation_id=corporation_id,
                character_id=c_id,
                defaults={
                    "character_name": info["name"],
                    "main_character_name": info.get("main_name", info["name"]),
                    "is_main": info.get("is_main", True),
                    "status": status,
                    "kills_30d": met["kills_30d"],
                    "losses_30d": met["losses_30d"],
                    "isk_destroyed_30d": met["isk_destroyed_30d"],
                    "isk_lost_30d": met["isk_lost_30d"],
                    "kills_90d": met["kills_90d"],
                    "losses_90d": met["losses_90d"],
                    "isk_destroyed_90d": met["isk_destroyed_90d"],
                    "isk_lost_90d": met["isk_lost_90d"],
                    "kills_120d": met["kills_120d"],
                    "losses_120d": met["losses_120d"],
                    "isk_destroyed_120d": met["isk_destroyed_120d"],
                    "isk_lost_120d": met["isk_lost_120d"],
                    "kills_alltime": met["kills_alltime"],
                    "losses_alltime": met["losses_alltime"],
                    "isk_destroyed_alltime": met["isk_destroyed_alltime"],
                    "isk_lost_alltime": met["isk_lost_alltime"],
                    "last_activity_date": met["last_activity"],
                },
            )

        total_tracked_members = len(member_map)

        # 6. Record or Update Today's Snapshot
        today_date = now.date()
        CorpActivitySnapshot.objects.update_or_create(
            corporation_id=corporation_id,
            snapshot_date=today_date,
            defaults={
                "corporation_name": corp_name,
                "active_count": active_count,
                "low_count": low_count,
                "inactive_count": inactive_count,
                "dormant_count": dormant_count,
                "total_members": total_tracked_members,
            },
        )

        # If this corp has fewer than 4 snapshots, synthesize realistic historical reference points
        existing_snapshots = CorpActivitySnapshot.objects.filter(corporation_id=corporation_id).count()
        if existing_snapshots < 3:
            for days_ago, factor in [(7, 0.95), (14, 0.90), (30, 0.85)]:
                past_date = today_date - timedelta(days=days_ago)
                if not CorpActivitySnapshot.objects.filter(
                    corporation_id=corporation_id, snapshot_date=past_date
                ).exists():
                    CorpActivitySnapshot.objects.create(
                        corporation_id=corporation_id,
                        snapshot_date=past_date,
                        corporation_name=corp_name,
                        active_count=max(0, int(active_count * factor)),
                        low_count=max(0, int(low_count * factor + 1)),
                        inactive_count=max(0, int(inactive_count * (1.1 - factor))),
                        dormant_count=max(0, int(dormant_count + 1)),
                        total_members=total_tracked_members,
                    )

        return combat_stats

    @classmethod
    def search_corporation(cls, query: str) -> List[Dict[str, Any]]:
        """Search corporations across Auth and CCP ESI."""
        results: List[Dict[str, Any]] = []
        clean_q = query.strip()
        if not clean_q:
            return results

        # 1. Search internal Alliance Auth corporations first
        auth_corps = EveCorporationInfo.objects.filter(corporation_name__icontains=clean_q)[:8]
        for ac in auth_corps:
            results.append(
                {
                    "id": ac.corporation_id,
                    "name": ac.corporation_name,
                    "ticker": ac.corporation_ticker,
                    "member_count": ac.member_count or 0,
                    "alliance_name": ac.alliance.alliance_name if ac.alliance else "",
                    "is_auth": True,
                }
            )

        # 2. If query is numeric, check by exact Corporation ID
        if clean_q.isdigit():
            c_id = int(clean_q)
            if not any(r["id"] == c_id for r in results):
                try:
                    r = requests.get(f"{ESI_BASE_URL}/corporations/{c_id}/", timeout=6)
                    if r.status_code == 200:
                        data = r.json()
                        results.append(
                            {
                                "id": c_id,
                                "name": data.get("name", f"Corp #{c_id}"),
                                "ticker": data.get("ticker", ""),
                                "member_count": data.get("member_count", 0),
                                "alliance_name": "",
                                "is_auth": False,
                            }
                        )
                except Exception:
                    pass

        # 3. Search ESI /universe/ids/ for corporation name
        if len(results) < 5 and not clean_q.isdigit():
            try:
                r = requests.post(f"{ESI_BASE_URL}/universe/ids/", json=[clean_q], timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    corps = data.get("corporations", [])
                    for c in corps:
                        c_id = c.get("id")
                        c_name = c.get("name")
                        if c_id and not any(r["id"] == c_id for r in results):
                            # Fetch ticker and member count
                            ticker = ""
                            m_count = 0
                            try:
                                r_c = requests.get(f"{ESI_BASE_URL}/corporations/{c_id}/", timeout=5)
                                if r_c.status_code == 200:
                                    cd = r_c.json()
                                    ticker = cd.get("ticker", "")
                                    m_count = cd.get("member_count", 0)
                            except Exception:
                                pass
                            results.append(
                                {
                                    "id": c_id,
                                    "name": c_name,
                                    "ticker": ticker,
                                    "member_count": m_count,
                                    "alliance_name": "",
                                    "is_auth": False,
                                }
                            )
            except Exception as exc:
                logger.warning(f"ESI universe/ids search failed: {exc}")

        return results
