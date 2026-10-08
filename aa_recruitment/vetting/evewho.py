from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests
from django.core.cache import cache
from allianceauth.services.hooks import get_extension_logger

from aa_recruitment.models import FindingSeverity
from .constants import ESI_BASE_URL, HOSTILE_ALLIANCE_TERMS

logger = get_extension_logger(__name__)


class EveWhoAnalyzer:
    """Evaluates corporation history, membership duration, and hostile affiliations via ESI and EveWho."""

    def __init__(self, character_id: int):
        self.character_id = character_id
        self._raw_history: List[Dict[str, Any]] = []
        self._enriched_history: List[Dict[str, Any]] = []

    def fetch_corporation_history(self) -> List[Dict[str, Any]]:
        """Fetch corporation history from ESI (/corporationhistory/) with fallback to evewho.com."""
        if self._raw_history:
            return self._raw_history

        # 1. Primary: ESI
        esi_url = f"{ESI_BASE_URL}/characters/{self.character_id}/corporationhistory/"
        try:
            resp = requests.get(
                esi_url,
                headers={"User-Agent": "AllianceAuth-Recruitment/1.0"},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    self._raw_history = data
                    return self._raw_history
        except Exception as exc:
            logger.warning(
                f"ESI corporationhistory failed for char {self.character_id}: {exc}"
            )

        # 2. Fallback: EveWho.com API
        evewho_url = f"https://evewho.com/api/character/{self.character_id}"
        try:
            resp = requests.get(
                evewho_url,
                headers={"User-Agent": "AllianceAuth-Recruitment/1.0"},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                history = data.get("history", [])
                if isinstance(history, list) and history:
                    # Normalize evewho format to match ESI
                    normalized = []
                    for h in history:
                        s_date = h.get("start_date", "")
                        # convert "2021/05/16 10:53" to ISO
                        if s_date and "/" in s_date:
                            s_date = s_date.replace("/", "-")
                            if "T" not in s_date:
                                s_date = s_date.replace(" ", "T") + ":00Z"
                        normalized.append(
                            {
                                "corporation_id": h.get("corporation_id"),
                                "record_id": h.get("record_id"),
                                "start_date": s_date,
                            }
                        )
                    self._raw_history = normalized
                    return self._raw_history
        except Exception as exc:
            logger.warning(
                f"EveWho fallback failed for char {self.character_id}: {exc}"
            )

        return []

    def _resolve_bulk_names(self, ids: List[int]) -> Dict[int, str]:
        """Bulk resolve IDs to names via ESI /universe/names/."""
        if not ids:
            return {}
        try:
            resp = requests.post(
                f"{ESI_BASE_URL}/universe/names/",
                json=list(set(ids)),
                headers={"User-Agent": "AllianceAuth-Recruitment/1.0"},
                timeout=6,
            )
            if resp.status_code == 200:
                return {x["id"]: x["name"] for x in resp.json()}
        except Exception as exc:
            logger.warning(f"Failed to bulk resolve universe names: {exc}")
        return {}

    def _fetch_single_corp_detail(self, cid: int) -> Dict[str, Any]:
        """Fetch corp details (ticker, alliance_id) with 7-day Django cache."""
        cache_key = f"aa_recruitment_corp_{cid}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        # NPC corps (< 2,000,000) have no alliance
        if cid < 2000000:
            result = {"ticker": "", "alliance_id": None}
            cache.set(cache_key, result, timeout=86400 * 7)
            return result

        try:
            resp = requests.get(
                f"{ESI_BASE_URL}/corporations/{cid}/",
                headers={"User-Agent": "AllianceAuth-Recruitment/1.0"},
                timeout=4,
            )
            if resp.status_code == 200:
                d = resp.json()
                result = {
                    "ticker": d.get("ticker", ""),
                    "alliance_id": d.get("alliance_id"),
                }
                cache.set(cache_key, result, timeout=86400 * 7)
                return result
        except Exception:
            pass

        return {"ticker": "", "alliance_id": None}

    def get_history_list(self) -> List[Dict[str, Any]]:
        """Fetch and enrich the complete corporation membership history."""
        if self._enriched_history:
            return self._enriched_history

        raw = self.fetch_corporation_history()
        if not raw:
            return []

        distinct_cids = list({x["corporation_id"] for x in raw if x.get("corporation_id")})
        id_to_name = self._resolve_bulk_names(distinct_cids)

        # Concurrently fetch corp tickers and alliance IDs
        with ThreadPoolExecutor(max_workers=5) as executor:
            corp_details_list = list(executor.map(self._fetch_single_corp_detail, distinct_cids))
        corp_details = dict(zip(distinct_cids, corp_details_list))

        # Bulk resolve all discovered alliance names
        alliance_ids = list(
            {
                info["alliance_id"]
                for info in corp_details.values()
                if info.get("alliance_id")
            }
        )
        alliance_names = self._resolve_bulk_names(alliance_ids) if alliance_ids else {}

        now = datetime.now(timezone.utc)
        enriched = []

        # Sort raw newest to oldest if needed
        # In ESI, record 0 is the newest (current)
        for i, rec in enumerate(raw):
            cid = rec["corporation_id"]
            corp_name = id_to_name.get(cid, f"Corporation #{cid}")
            c_info = corp_details.get(cid, {})
            aid = c_info.get("alliance_id")
            aname = alliance_names.get(aid, "") if aid else ""
            ticker = c_info.get("ticker", "")

            # Parse start date
            s_str = rec.get("start_date", "")
            start_dt = None
            if s_str:
                try:
                    clean_s = s_str.replace("Z", "+00:00")
                    start_dt = datetime.fromisoformat(clean_s)
                except Exception:
                    pass

            # End date is start date of the newer record (rec[i-1])
            end_dt = None
            if i > 0:
                prev_s_str = raw[i - 1].get("start_date", "")
                if prev_s_str:
                    try:
                        clean_prev = prev_s_str.replace("Z", "+00:00")
                        end_dt = datetime.fromisoformat(clean_prev)
                    except Exception:
                        pass

            # Calculate duration
            days = 1
            dur_str = "-"
            if start_dt:
                eff_end = end_dt if end_dt else now
                delta = eff_end - start_dt
                days = max(1, delta.days)
                if days >= 365:
                    dur_str = f"{days // 365}y {(days % 365) // 30}m ({days}d)"
                elif days >= 30:
                    dur_str = f"{days // 30}m {days % 30}d"
                else:
                    dur_str = f"{days}d"

            # Check for hostile affiliations
            is_hostile = False
            c_low = corp_name.lower()
            a_low = aname.lower()
            for term in HOSTILE_ALLIANCE_TERMS:
                if term in c_low or term in a_low:
                    is_hostile = True
                    break

            is_npc = cid < 2000000

            enriched.append(
                {
                    "record_id": rec.get("record_id"),
                    "corporation_id": cid,
                    "corporation_name": corp_name,
                    "corporation_ticker": ticker,
                    "alliance_id": aid,
                    "alliance_name": aname,
                    "start_date": start_dt.strftime("%Y-%m-%d %H:%M") if start_dt else "-",
                    "end_date": end_dt.strftime("%Y-%m-%d %H:%M") if end_dt else "Present",
                    "duration_str": dur_str,
                    "duration_days": days,
                    "is_current": (i == 0),
                    "is_npc": is_npc,
                    "is_deleted": rec.get("is_deleted", False),
                    "is_hostile": is_hostile,
                    "evewho_url": f"https://evewho.com/corporation/{cid}",
                    "zkill_url": f"https://zkillboard.com/corporation/{cid}/",
                }
            )

        self._enriched_history = enriched
        return self._enriched_history

    def get_summary_dict(self) -> Dict[str, Any]:
        """Return summary metrics for corporation history."""
        history = self.get_history_list()
        player_corps = [h for h in history if not h.get("is_npc")]
        npc_corps = [h for h in history if h.get("is_npc")]

        avg_days = 0
        if player_corps:
            avg_days = int(sum(h.get("duration_days", 1) for h in player_corps) / len(player_corps))

        return {
            "character_id": self.character_id,
            "evewho_url": f"https://evewho.com/character/{self.character_id}",
            "total_corps": len(history),
            "player_corps_count": len(player_corps),
            "npc_corps_count": len(npc_corps),
            "avg_stay_days": avg_days,
            "history": history,
        }

    def analyze(self) -> List[Dict[str, Any]]:
        """Analyze corporation history and check against hostile alliance/corp lists."""
        findings: List[Dict[str, Any]] = []
        history = self.get_history_list()

        if not history:
            return findings

        current_entry = history[0]
        current_cname = current_entry.get("corporation_name", "")
        current_aname = current_entry.get("alliance_name", "")

        # 1. Check if CURRENTLY in known hostile
        if current_entry.get("is_hostile"):
            findings.append(
                {
                    "section": "evewho",
                    "severity": FindingSeverity.CRITICAL,
                    "title": "CURRENTLY in a known hostile entity",
                    "evidence": f"Currently in {current_cname} / {current_aname or 'No Alliance'}",
                    "recruiter_action": "Do not invite until candidate leaves the hostile corp/alliance.",
                }
            )

        # 2. Check past hostile history
        past_hostiles = []
        for entry in history[1:]:
            if entry.get("is_hostile"):
                disp = f"{entry.get('corporation_name')} ({entry.get('alliance_name') or 'No Alliance'})"
                if disp not in past_hostiles:
                    past_hostiles.append(disp)

        if past_hostiles:
            findings.append(
                {
                    "section": "evewho",
                    "severity": FindingSeverity.HIGH,
                    "title": "EVEWho history contains known hostile alliance affiliation",
                    "evidence": f"Past affiliation with: {', '.join(past_hostiles[:3])}",
                    "recruiter_action": "Inquire about circumstances of leaving and verify vouch/reputation.",
                }
            )

        # 3. Corporation hopping check (>10 distinct player corporations)
        player_corps = [h for h in history if not h.get("is_npc")]
        if len(player_corps) >= 8:
            findings.append(
                {
                    "section": "evewho",
                    "severity": FindingSeverity.LOW,
                    "title": "Frequent corporation hopping",
                    "evidence": (
                        f"Character has been in {len(player_corps)} distinct player corporations "
                        f"({len(history)} total records)."
                    ),
                    "recruiter_action": "Check reasons for frequent corp hopping.",
                }
            )

        # 4. Summary overview
        findings.append(
            {
                "section": "evewho",
                "severity": FindingSeverity.INFO,
                "title": "Corporation History Overview (EVEWho)",
                "evidence": (
                    f"Current: {current_cname} ({current_aname or 'No Alliance'}). "
                    f"Total history: {len(history)} corporations ({len(player_corps)} player corps)."
                ),
                "recruiter_action": "Review corporation timeline in the Corp History dossier tab.",
            }
        )

        return findings
