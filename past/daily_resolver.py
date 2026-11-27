# daily_resolver.py
# Resolves the daily devotional context for Vibzee quote-to-image prompts.

import json
import os
from calendar import monthcalendar
from datetime import date, datetime, timedelta
import re
from typing import Dict, List, Optional

# Priority order: lowest number wins primary slot
PRIORITY_ORDER = {
    "navratri": 1, "festival_specific": 2, "jain_cycle": 3,
    "ramadan": 4, "christian_cycle": 5, "pitru_paksha": 6,
    "tithi": 7, "month": 8, "weekday": 9
}

# Tithi number mapping (1 to 15)
TITHI_NUMS = {
    "pratipada": 1, "dwitiya": 2, "tritiya": 3, "chaturthi": 4,
    "panchami": 5, "shashthi": 6, "shashti": 6, "saptami": 7,
    "ashtami": 8, "navami": 9, "dashami": 10, "ekadashi": 11,
    "dwadashi": 12, "trayodashi": 13, "chaturdashi": 14,
    "purnima": 15, "amavasya": 15
}

MONTH_ALIASES = {
    "shravana": "shravan", "ashvina": "ashwin",
    "ashwina": "ashwin", "kartika": "kartik"
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
RELEVANCE_RANK = {"high": 1, "medium": 2, "low": 3}


def amanta_month_on(day: date, intervals: list) -> Optional[str]:
    stamp = day.isoformat()
    return next((
        interval.get("month_key")
        for interval in intervals
        if isinstance(interval, dict) and (interval.get("start") or "") <= stamp <= (interval.get("end") or "")
    ), None)


class DailyResolver:
    """
    Combines static_calendar.json + deities.json + panchang output
    to resolve the complete devotional context for any given day.
    """

    def __init__(self, static_calendar_path: Optional[str] = None, deities_path: Optional[str] = None):
        base_dir = os.path.dirname(__file__)
        data_dir = os.path.join(base_dir, "data")

        # Fallback file discovery in data/ and base directory
        if not static_calendar_path:
            p1 = os.path.join(data_dir, "static_calendar.json")
            p2 = os.path.join(base_dir, "static_calendar.json")
            static_calendar_path = p1 if os.path.exists(p1) else p2

        if not deities_path:
            d1 = os.path.join(data_dir, "deities.json")
            d2 = os.path.join(base_dir, "deities.json")
            deities_path = d1 if os.path.exists(d1) else d2

        self.static_cal = self._load_json(static_calendar_path)
        self.deities = self._load_json(deities_path)
        self._relative_cache: Dict[int, List[dict]] = {}

    @staticmethod
    def _load_json(path: Optional[str]) -> dict:
        # Load json file safely, salvaging truncated files if unclosed
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                if text.endswith(","):
                    text = text[:-1]
                if not text.endswith("}"):
                    text += "\n}"
                data = json.loads(text)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    @staticmethod
    def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> Optional[date]:
        # Calculate nth weekday of a month (0=Mon, 6=Sun)
        cal = monthcalendar(year, month)
        days = [w[weekday] for w in cal if w[weekday] != 0]
        if n == -1 and days:
            return date(year, month, days[-1])
        if 1 <= n <= len(days):
            return date(year, month, days[n - 1])
        return None

    @staticmethod
    def compute_easter(year: int) -> date:
        # Anonymous Gregorian algorithm for Easter Sunday
        a = year % 19
        b, c = divmod(year, 100)
        d, e = divmod(b, 4)
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i, k = divmod(c, 4)
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month, day = divmod(h + l - 7 * m + 114, 31)
        return date(year, month, day + 1)

    @staticmethod
    def compute_advent_start(year: int) -> date:
        # 4th Sunday before Dec 25
        christmas = date(year, 12, 25)
        offset = (christmas.weekday() + 1) % 7
        days_back = 7 if offset == 0 else offset
        return christmas - timedelta(days=days_back + 21)

    def _tithi_to_number(self, tithi_str: str) -> int:
        # Extract tithi number from string
        cleaned = str(tithi_str or "").lower()
        for name, num in TITHI_NUMS.items():
            if name in cleaned:
                return num
        return 0

    @staticmethod
    def _date(value: Optional[str]) -> Optional[date]:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _records(value):
        return [item for item in (value if isinstance(value, list) else [value]) if isinstance(item, dict)]

    @staticmethod
    def _candidate(entry: dict, kind: str, source: str, theme: str, **defaults) -> dict:
        visual = entry.get("visual_description") or entry.get("visual_hint")
        candidate = dict(defaults)
        for key in ("deity", "color", "mood", "settings", "mumbai_locations", "worship_items"):
            if entry.get(key) is not None:
                candidate[key] = entry[key]
        candidate.update(
            type=kind, source=source, theme=theme,
            reason=entry.get("significance") or defaults.get("reason") or theme,
            deity_visual=visual or defaults.get("deity_visual", ""),
            devotee_visual=entry.get("devotee_visual") or visual or defaults.get("devotee_visual", ""),
        )
        return candidate

    def _calendar_events(self, day: date) -> List[dict]:
        events = []
        for key, stamp in (("fixed_dates", day.strftime("%m-%d")), ("year_specific_dates", day.isoformat())):
            entries = self.static_cal.get(key)
            if isinstance(entries, dict):
                events.extend(self._records(entries.get(stamp)))
            else:
                events.extend(item for item in self._records(entries) if item.get("date") == stamp)

        if day.year not in self._relative_cache:
            rules = self.static_cal.get("relative_dates")
            computed = []
            for rule in self._records(list(rules.values()) if isinstance(rules, dict) else rules):
                if rule.get("rule") != "nth_weekday_of":
                    continue
                try:
                    weekday = rule["weekday"]
                    if isinstance(weekday, str):
                        weekday = WEEKDAYS.index(weekday.strip().lower())
                    if 0 <= weekday < 7:
                        occurrence = self._nth_weekday_of_month(day.year, int(rule["month"]), weekday, int(rule.get("n", 1)))
                        computed.append({"date": occurrence, "data": rule})
                except (KeyError, TypeError, ValueError):
                    continue
            self._relative_cache[day.year] = computed
        events.extend(r["data"] for r in self._relative_cache[day.year] if r["date"] == day)
        return sorted(events, key=lambda e: RELEVANCE_RANK.get(str(e.get("mumbai_relevance")).lower(), 9))

    def _check_multi_day_sequences(self, day: date, month: str, paksha: str, tithi: str, events: List[dict]):
        matches, sequences, periods = [], [], []
        year = day.year
        date_key = f"date_{year}"
        stamp = day.isoformat()
        t_num = self._tithi_to_number(tithi)
        waxing = paksha == "shukla"
        # Undated editions can still use the current day's Amanta month and tithi.
        lunar_offsets = {
            "diwali_lakshmi_puja": (
                t_num - 15 if month == "ashwin" and paksha == "krishna" and 13 <= t_num <= 15
                else t_num if month == "kartik" and waxing and 1 <= t_num <= 2 else None
            ),
            "ganesh_chaturthi": t_num - 4 if month == "bhadrapada" and waxing and 4 <= t_num <= 14 else None,
            "pitru_paksha_start": (
                0 if month == "bhadrapada" and "purnima" in tithi.lower()
                else t_num if month == "bhadrapada" and paksha == "krishna" and 1 <= t_num <= 15 else None
            ),
            "sharad_navratri_start": t_num - 1 if month == "ashwin" and waxing and 1 <= t_num <= 10 else None,
            "chaitra_navratri_start": t_num - 1 if month == "chaitra" and waxing and 1 <= t_num <= 9 else None,
            "chhath_puja_sandhya_arghya": t_num - 6 if month == "kartik" and waxing and 5 <= t_num <= 7 else None,
        }
        cycles = {
            "navratri_sharad": ("navratri_cycle", "navratri", "Durga"),
            "diwali": ("diwali_cycle", "festival_specific", None),
            "ganpati_festival": ("ganpati_cycle", "festival_specific", "Ganesha"),
            "paryushana_jain": ("jain_paryushana_cycle", "jain_cycle", "Mahavira / Tirthankara"),
            "das_lakshana_jain": ("jain_das_lakshana_cycle", "jain_cycle", "Jina / Tirthankara"),
            "pitru_paksha": ("pitru_paksha_pattern", "pitru_paksha", "Pitru (ancestors)"),
            "ramadan": ("ramadan_pattern", "ramadan", None),
            "lent": ("christian_lent_pattern", "christian_cycle", "Jesus Christ"),
            "advent": ("christian_advent_pattern", "christian_cycle", "Jesus Christ"),
            "muktad_parsi": ("parsi_observances", "festival_specific", None),
            "mount_mary_novena": (None, "christian_cycle", "Mary"),
            "durga_puja_bengali": (None, "festival_specific", "Durga"),
            "navaratri_chaitra": (None, "festival_specific", "Durga"),
            "chhath_puja": (None, "festival_specific", "Surya"),
        }
        configured = self.static_cal.get("multi_day_sequences") or {}
        if isinstance(configured, list):
            configured = {item.get("name", ""): item for item in self._records(configured)}
        if self.deities.get("navratri_cycle") and "navratri_sharad" not in configured:
            configured = {**configured, "navratri_sharad": {
                "name": "Sharad Navratri", "religion": "hindu", "total_days": 9,
                "anchor_type": "dynamic_panchang", "anchor_panchang_event": "sharad_navratri_start",
                "period": "navratri",
            }}
        for key, seq in configured.items():
            if not isinstance(seq, dict):
                continue
            data_key, kind, deity = cycles.get(key, (None, "festival_specific", seq.get("deity")))
            data = self.deities.get(data_key)
            rows = {item.get("offset", index): item for index, item in enumerate(self._records(seq.get("days")))}
            first = min(rows, default=0)
            total = seq.get("total_days") or (max(rows, default=first) - first + 1)
            start = self._date((seq.get("anchor_dates") or {}).get(str(year)))
            end = self._date((seq.get("end_dates") or {}).get(str(year)))
            milestone_dates = {}
            exact = None

            if seq.get("anchor_type") == "fixed":
                start = self._date(f"{year}-{seq.get('anchor_date')}")
            elif seq.get("anchor_type") == "year_specific":
                start = self._date(seq.get("anchor_date"))
            elif seq.get("anchor_type") == "dynamic_panchang":
                exact = lunar_offsets.get(seq.get("anchor_panchang_event"))
            if start:
                for offset, row in rows.items():
                    when = self._date(row.get(date_key))
                    if when:
                        milestone_dates[when] = (offset, {})
                        total = max(total, (when - start).days - first + 1)

            if key in ("navratri_sharad", "diwali", "ganpati_festival"):
                dated = [(i, self._date(row.get(date_key)), row) for i, row in enumerate(self._records(data))]
                dated = [(i, when, row) for i, when, row in dated if when]
                if dated:
                    milestone_dates = {when: (row.get("offset", i + first), row) for i, when, row in dated}
                    start = next((when for when, (offset, _) in milestone_dates.items() if offset == 0), start)
                    if key == "ganpati_festival":
                        end = max(milestone_dates)
                elif key == "ganpati_festival" and start and end:
                    milestone_dates = {
                        end if offset == 9 else start + timedelta(days=offset): (offset, {})
                        for offset in rows
                    }
            elif key == "pitru_paksha":
                data = data or {}
                start = self._date(data.get(f"purnima_shraddha_{year}")) or start
                end = self._date((data.get("last_day") or {}).get(date_key))
            elif key == "muktad_parsi":
                data = (data or {}).get("muktad") or {}
                start = self._date(data.get(f"start_date_{year}")) or start
                end = self._date(data.get(f"end_date_{year}"))
            elif key == "lent":
                end = self.compute_easter(year)
                start = end - timedelta(days=46)
            elif key == "advent":
                start = self.compute_advent_start(year)
                end = date(year, 12, 24)
            elif key == "mount_mary_novena":
                feast = self._nth_weekday_of_month(year, 9, 6, 2)
                start = feast - timedelta(days=9)
            elif key == "ramadan" and start and start.year == year:
                for length in (29, 30):
                    candidates = (self.static_cal.get("year_specific_dates") or {}).get((start + timedelta(days=length)).isoformat())
                    if any(e.get("observance_id") == "eid_fitr" for e in self._records(candidates)):
                        total = length
                        break
                if any(e.get("observance_id") == "eid_fitr" for e in events):
                    continue

            if start and start.year != year:
                continue
            if start and end:
                total = (end - start).days + 1 - first
            delta = (day - start).days if start else exact
            if delta is None or not first <= delta < first + total:
                continue

            offset, rich = milestone_dates.get(day, (delta, {}))
            if key == "ganpati_festival" and milestone_dates and day not in milestone_dates:
                offset = None
            elif key == "ganpati_festival" and not start and delta >= 9:
                offset = 9 if delta == 10 else None
            if key == "pitru_paksha" and day == end:
                offset = max(rows, default=15)
            elif key == "pitru_paksha" and end and offset == max(rows, default=15):
                offset = None
            name = seq.get("name") or key
            day_number = delta - first + 1
            periods.append(seq.get("period") or key)
            item = rows.get(offset, {})
            if start and item.get(date_key) and item[date_key] != stamp:
                item = {}
            if not item and start:
                item = (seq.get("additional_milestones") or {}).get(stamp) or {}
            sequences.append({"id": key, "name": name, "day_number": day_number, "total_days": total,
                              "event_name": rich.get("event_name") or item.get("name")})
            if not (seq.get("religion") or seq.get("type") == "religious" or item.get("deity")):
                continue

            if key == "navratri_sharad":
                match = self._get_navratri_info(day_number, year)
                if match:
                    matches.append(dict(match, sequence=key))
                continue

            theme = item.get("name") or name
            mood = item.get("mood") or seq.get("overall_mood") or "festive"
            extras = {}
            if key in ("diwali", "ganpati_festival") and not rich:
                if item or not milestone_dates:
                    rich = next((row for i, row in enumerate(self._records(data))
                                 if row.get("offset", i + first) == offset), {})
                if key == "ganpati_festival" and not rich and not item:
                    rich = {"visual_description": seq.get("visual_hint")}
            elif kind == "jain_cycle":
                days = self._records(data)
                rich = days[day_number - 1] if day_number <= len(days) else {}
                theme = rich.get("name") or item.get("name") or theme
                extras = {"settings": ["derasar", "community_hall"], "color": "White",
                          "mumbai_locations": ["Walkeshwar, Ghatkopar and Mulund Jain temples"]}
            elif key == "pitru_paksha":
                rich = (data.get("last_day") or {}) if offset == max(rows, default=15) else {}
                rich = {"visual_description": data.get("daily_visual"), **rich}
                extras = {"mumbai_locations": [data.get("mumbai_location") or "Banganga Tank, Walkeshwar"],
                          "settings": ["riverbank", "home_shrine"],
                          "worship_items": ["black_sesame", "water", "kusha_grass", "rice_pinda"],
                          "restrictions": data.get("restrictions")}
            elif key == "muktad_parsi":
                rich = data
            elif key == "ramadan":
                data = data or {}
                daily = {label: scene.get("visual_description") for label, scene in (data.get("daily_pattern") or {}).items()
                         if isinstance(scene, dict) and scene.get("visual_description")}
                stage = {}
                if day_number == 27:
                    stage = data.get("night_27") or {}
                elif day_number > total - 10:
                    stage = data.get("last_10_nights") or {}
                rich = {**data, **stage}
                if daily.get("iftar"):
                    rich["devotee_visual"] = daily["iftar"]
                if not stage and daily.get("taraweeh"):
                    rich["visual_description"] = daily["taraweeh"]
                extras = {"daily_scenes": daily, "settings": ["mosque", "home"],
                          "date_status": (data.get(f"calendar_{year}") or {}).get("status")}
                theme = stage.get("name") or item.get("name") or ("Ramadan Last 10 Nights" if stage else "Ramadan Fasting")
                mood = "devotional"
            elif key == "lent":
                data = data or {}
                occasion = {0: "ash_wednesday", 39: "palm_sunday", 44: "good_friday", 46: "easter_sunday"}.get(delta)
                if day.weekday() == 4 and not occasion:
                    occasion = "friday_abstinence"
                    theme = "Lenten Friday"
                rich = {**data, **(data.get(occasion) or {})}
                if occasion and (data.get(occasion) or {}).get("visual_description"):
                    rich["devotee_visual"] = (data[occasion].get("devotee_visual") or data[occasion]["visual_description"])
                extras = {"settings": ["church"], "color": "White" if day == end else "Purple"}
                mood = "solemn" if delta in (0, 44) else "joyful" if day == end else "devotional"
            elif key == "advent":
                weeks = self._records(data)
                week = min(delta // 7, 3)
                rich = weeks[week] if week < len(weeks) else {}
                theme = f"Advent ({rich.get('theme', 'Preparation')})"
                extras = {"settings": ["church"], "color": rich.get("candle"),
                          "candles_lit": rich.get("candles_lit"),
                          "mumbai_locations": ["Mount Mary Basilica, Bandra", "Holy Name Cathedral, Colaba"]}
                mood = "devotional"

            merged = {"visual_hint": seq.get("visual_hint"), **item, **rich}
            if key not in ("ramadan", "advent", "muktad_parsi", "ganpati_festival"):
                theme = rich.get("name") or theme
            if key == "ganpati_festival" and (item or day in milestone_dates):
                theme = rich.get("event_name") or theme
            source = f"deities.{data_key}" if rich and data_key else f"static_calendar.{key}"
            matches.append(self._candidate(merged, kind, source, theme,
                                           deity=deity, mood=mood, sequence=key,
                                           **({"date_status": seq.get("date_status")} | extras)))
        return matches, sequences, periods

    def _get_navratri_info(self, day_number: int, year: int) -> Optional[dict]:
        # Day info from deities.json navratri_cycle or static_calendar
        cycle = self.deities.get("navratri_cycle", [])
        entry = next((
            item for index, item in enumerate(cycle or [], start=1)
            if isinstance(item, dict) and item.get("day", index) == day_number
        ), None)
        # The original unversioned deity scenes were written for the 2026 palette.
        scene_year = 2026
        source = "deities.navratri_cycle"
        if not entry:
            sequences = self.static_cal.get("multi_day_sequences")
            sequence = sequences.get("navratri_sharad") or {} if isinstance(sequences, dict) else {}
            entry = next((item for item in self._records(sequence.get("days")) if item.get("offset") == day_number - 1), None)
            scene_year = sequence.get("colors_year")
            source = "static_calendar.navratri_sharad"
        if not entry:
            return None
        devi = entry.get("devi", "Durga")
        color = entry.get(f"color_{year}")
        visual = entry.get(f"visual_description_{year}")
        devotee = entry.get(f"devotee_visual_{year}")
        if year == scene_year:
            color = color or entry.get("color")
            visual = visual or entry.get("visual_description") or entry.get("visual_hint")
            devotee = devotee or entry.get("devotee_visual")
        return {
            "type": "navratri", "source": source,
            "deity": f"Devi {devi}",
            "deity_visual": visual or f"{devi} above a brass lamp and flower offerings in a Mumbai mandap. {entry.get('iconography', '')}".strip(),
            "devotee_visual": devotee or f"A family raises a brass aarti lamp before {devi} at a flower-decked Navratri shrine in a Dadar courtyard.",
            "color": color, "theme": f"Navratri Day {day_number} ({devi})",
            "mood": entry.get("mood", "festive"),
            "settings": ["temple", "pandals", "home_shrine"],
            "mumbai_locations": ["Mahalaxmi Temple, Breach Candy", "Girgaon garba grounds"],
            "worship_items": entry.get("worship_items", ["flowers", "ghee_lamp"]),
            "reason": f"Sharad Navratri Day {day_number} celebrating {devi}"
        }

    def _get_tithi_deity(self, tithi: str, paksha: str) -> Optional[dict]:
        # Map tithi name and paksha to deities.json tithi entries
        t_low, p_low = tithi.lower(), paksha.lower()
        key = None
        if "chaturthi" in t_low:
            key = "chaturthi_shukla" if "shukla" in p_low or "shukla" in t_low else "chaturthi_krishna"
        elif "ekadashi" in t_low:
            key = "ekadashi"
        elif "purnima" in t_low:
            key = "purnima"
        elif "amavasya" in t_low:
            key = "amavasya"
        elif "ashtami" in t_low and ("shukla" in p_low or "shukla" in t_low):
            key = "ashtami_shukla"
        elif "navami" in t_low and ("shukla" in p_low or "shukla" in t_low):
            key = "navami_shukla"
        elif "trayodashi" in t_low:
            key = "trayodashi_shukla" if "shukla" in p_low or "shukla" in t_low else "trayodashi_krishna"

        if not key:
            return None
        tdata = (self.deities.get("tithi") or {}).get(key)
        if not tdata:
            return None
        deity = tdata.get("deity", "")
        return {
            "type": "tithi", "source": f"deities.tithi.{key}", "deity": deity,
            "deity_visual": tdata.get("visual_description", ""),
            "devotee_visual": tdata.get("devotee_visual", ""), "color": None,
            "theme": tdata.get("significance", key.replace("_", " ").title()),
            "mood": "devotional", "settings": ["temple", "home_shrine"],
            "mumbai_locations": [tdata["mumbai_note"]] if tdata.get("mumbai_note") else [],
            "worship_items": tdata.get("worship_items", []),
            "reason": f"Tithi {tithi} sacred to {deity}"
        }

    def _get_month_deity(self, month: str, paksha: str) -> Optional[dict]:
        # Look up month deity from deities.json month_deity
        if not month:
            return None
        norm_m = MONTH_ALIASES.get(month.lower().strip(), month.lower().strip())
        mdata = (self.deities.get("month_deity") or {}).get(norm_m)
        if not mdata:
            return None
        p_key = paksha.lower().strip()
        data = mdata.get(p_key) or mdata
        deity = data.get("primary_deity", "")
        return {
            "type": "month", "source": f"deities.month_deity.{norm_m}", "deity": deity,
            "deity_visual": data.get("visual_description", ""),
            "devotee_visual": data.get("devotee_visual") or data.get("visual_description", ""),
            "color": None, "theme": f"{norm_m.title()} Month Devotion", "mood": "devotional",
            "settings": ["temple", "home_shrine"],
            "mumbai_locations": [data["mumbai_note"]] if data.get("mumbai_note") else [],
            "worship_items": [], "reason": f"Month of {norm_m.title()} dedicated to {deity}"
        }

    def _get_weekday_deity(self, target_date: date) -> List[dict]:
        dname = WEEKDAYS[target_date.weekday()]
        day = ((self.deities.get("weekday") or {}).get(dname) or {})
        return [
            self._candidate(entry, "weekday", f"deities.weekday.{dname}.{religion}",
                            entry.get("aspect") or entry.get("deity") or dname.title(),
                            mood="devotional", mantra_reference=entry.get("mantra_reference"))
            for religion, entries in day.items()
            for entry in self._records(entries)
        ]

    @staticmethod
    def _event_id(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    def resolve(self, target_date: date, panchang_data: dict) -> dict:
        """Resolve Mumbai devotional context for the supplied civil date."""
        panchang_data = panchang_data or {}
        astro = panchang_data.get("astronomical_panchang") or {}
        intelligence = panchang_data.get("festival_intelligence") or {}
        tithi = panchang_data.get("tithi") or astro.get("tithi") or ""
        paksha = panchang_data.get("paksha")
        if isinstance(tithi, dict):
            paksha = paksha or tithi.get("paksha")
            tithi = tithi.get("udaya_tithi") or tithi.get("name") or ""
        tithi = str(tithi)
        paksha = str(paksha or tithi.partition(" ")[0]).strip().lower()
        month = panchang_data.get("lunar_month") or astro.get("lunar_month")
        if isinstance(month, dict):
            month = month.get("amanta") or month.get("regional")
        month = str(month or "").strip().lower()
        month = MONTH_ALIASES.get(month, month)

        year = target_date.year
        stamp = target_date.isoformat()
        intervals = (self.deities.get("meta") or {}).get(f"amanta_months_{year}") or []
        month = amanta_month_on(target_date, intervals) or month

        events = self._calendar_events(target_date)
        matches, sequences, periods = self._check_multi_day_sequences(target_date, month, paksha, tithi, events)
        active_keys = {item.get("sequence") for item in matches}
        observances = [row for row in self._records(self.deities.get(f"mumbai_observances_{year}")) if row.get("name")]
        dated_aliases = {
            self._event_id(alias)
            for row in observances
            for alias in [row["name"], *(row.get("aliases") or [])]
            if row.get("date") and row["date"] != stamp
        }
        dated_matches = {}
        for row in observances:
            if row.get("date") == stamp:
                key = row.get("observance_id") or self._event_id(row["name"])
                dated_matches[key] = row

        parsi = self.deities.get("parsi_observances") or {}
        for key, row in parsi.items():
            if isinstance(row, dict) and (row.get(f"date_{year}") == stamp or
                                         (key == "jamshedi_navroze" and target_date.strftime("%m-%d") == "03-21")):
                dated_matches[key] = dict(row, tradition="parsi")

        fixed_today = []
        for event in events:
            name = event.get("name") or event.get("title") or event.get("event")
            if not name:
                continue
            fixed_today.append(name)
            key = event.get("observance_id") or self._event_id(name)
            if event.get("sequence") in active_keys:
                dated_matches.pop(key, None)
                continue
            rich = dated_matches.pop(key, {})
            merged = {**event, **rich}
            if merged.get("religion") or merged.get("type") == "religious" or merged.get("deity"):
                matches.append(self._candidate(merged, "festival_specific", "deities.observance" if rich else "static_calendar",
                                               name, deity=rich.get("figure"), mood="festive",
                                               date_status=merged.get("date_status")))

        for row in dated_matches.values():
            if row.get("sequence") in active_keys:
                match = next(item for item in matches if item.get("sequence") == row["sequence"])
                match["deity"] = row.get("figure") or match.get("deity")
                match["deity_visual"] = row.get("visual_description") or match["deity_visual"]
                match["devotee_visual"] = row.get("devotee_visual") or match.get("devotee_visual") or match["deity_visual"]
                continue
            matches.append(self._candidate(row, "festival_specific", "deities.observance", row["name"],
                                           deity=row.get("figure"), mood="devotional", date_status=row.get("date_status")))

        festival = panchang_data.get("festival_name") or intelligence.get("active_festival")
        reported = panchang_data.get("all_events") or intelligence.get("all_events") or []
        if isinstance(reported, str):
            reported = [part.strip() for part in reported.split(",")]
        elif not isinstance(reported, (list, tuple)):
            reported = []
        festivals = [name for name in [festival, *reported] if isinstance(name, str) and name]
        known = {self._event_id(name) for name in fixed_today}
        for row in observances:
            if row.get("date") == stamp:
                known.update(self._event_id(alias) for alias in [row["name"], *(row.get("aliases") or [])])
        for match in matches:
            known.add(self._event_id(match["theme"]))
        if isinstance(festival, str) and festival:
            festival_id = self._event_id(festival)
            # The older Panchang also generates labels from sunrise tithi and solar month.
            # Use the curated civil-date matches for sequences with a date in this edition.
            sequence_names = (self.static_cal.get("meta") or {}).get("festival_sequence_aliases") or {}
            sequence = sequence_names.get(festival_id)
            covered = sequence in active_keys or (
                sequence and year == (self.static_cal.get("meta") or {}).get("year_specific_dates_for")
            )
            if festival_id not in known and festival_id not in dated_aliases and not covered:
                matches.append(self._candidate({}, "festival_specific", "panchang.festival", festival,
                                               deity=panchang_data.get("deity"),
                                               devotee_visual=f"At a neighborhood shrine in Mumbai, families gather for {festival}, carrying brass lamps and baskets of fresh flowers."))
            elif festival_id in dated_aliases or (covered and sequence not in active_keys):
                festivals = [label for label in festivals if self._event_id(label) != festival_id]
        festivals.extend(item["event_name"] for item in sequences
                         if item.get("event_name") and item["id"] in active_keys)
        festivals.extend(row["name"] for row in observances if row.get("date") == stamp)

        tithi_match = self._get_tithi_deity(tithi, paksha)
        month_match = self._get_month_deity(month, paksha)
        if tithi_match:
            matches.append(tithi_match)
        if month_match:
            matches.append(month_match)
        matches.extend(self._get_weekday_deity(target_date))
        if active_keys.intersection({"paryushana_jain", "das_lakshana_jain"}):
            periods.append("jain_festival")
        if month == "shravan":
            periods.append("shravan")
        is_somber = "pitru_paksha" in periods or any(
            match.get("mood") == "solemn" and match["theme"] in ("Good Friday", "Ashura", "Muharram (Ashura)")
            for match in matches
        )
        matches.sort(key=lambda match: PRIORITY_ORDER[match["type"]])
        if not matches:
            matches.append(self._candidate(
                {"visual_description": "Radiant morning sun casts warm light across a Mumbai balcony as a devotee greets the dawn with folded palms."},
                "weekday", "default", "Daily Devotion", deity="Surya", mood="devotional",
            ))
        defaults = {"deity": None, "deity_visual": "", "devotee_visual": "", "color": None,
                    "mood": "devotional", "settings": [], "mumbai_locations": [], "worship_items": []}
        return {
            "primary": {**defaults, **matches[0]},
            "secondary": [{**defaults, **match} for match in matches[1:]],
            "active_periods": list(dict.fromkeys(periods)),
            "active_sequences": sequences,
            "festivals_today": list(dict.fromkeys(festivals)),
            "fixed_events_today": list(dict.fromkeys(fixed_today)),
            "is_somber": is_somber,
            "is_fasting_day": "ramadan" in periods or bool(
                panchang_data.get("is_vrat_day") or panchang_data.get("vrats_and_observances")
            ),
        }


def get_daily_devotion(date_str: str, lat: float = 19.0760, lon: float = 72.8777) -> dict:
    """
    Convenience function: get devotional context for a date.
    Default coordinates: Mumbai (19.0760°N, 72.8777°E).
    """
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    try:
        from panchange_engine import get_coordinator
        panchang = get_coordinator().calculate_panchang(target_date=target_date, lat=lat, lon=lon)
        if "devotion" in panchang:
            return panchang["devotion"]
    except Exception:
        panchang = {}

    return DailyResolver().resolve(target_date, panchang)
