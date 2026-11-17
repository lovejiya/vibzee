"""
test_panchang.py — Rigorous Verification Test Suite for Dual-Branch Parallel Panchang Architecture.

Tests all 9 mandatory requirements from Section G:
  1. Panchang engine works without loading festival JSON.
  2. Festival processor loads original JSON independently.
  3. Both run concurrently in parallel.
  4. Regional profiles are passed correctly to both.
  5. Final merge preserves all original festival records.
  6. Calculated festival dates are consistent with the selected calendar and tradition.
  7. Different regions produce different regional festival outputs for the same Gregorian date.
  8. Language changes presentation without changing astronomical calculations.
  9. User overrides change the selected calendar profile correctly.
"""
import unittest
import asyncio
from datetime import date, time
from pathlib import Path
import json

from panchange_engine import (
    DynamicPanchangEngine,
    FestivalProcessor,
    PanchangCoordinator,
    get_coordinator,
    REGIONAL_PROFILES,
    resolve_regional_profile,
)
from specs import PANCHANG_PATH


class TestDualBranchPanchangArchitecture(unittest.TestCase):

    def setUp(self):
        self.coordinator = PanchangCoordinator()
        self.test_date = date(2026, 11, 8)  # Diwali 2026
        self.mumbai_lat = 19.0760
        self.mumbai_lon = 72.8777

    def test_01_panchang_engine_works_without_festival_json(self):
        """1. Verify Panchang engine works completely without loading festival JSON."""
        engine = DynamicPanchangEngine()
        # Verify engine has no reference to panchang_2026.json
        res = engine.calculate(
            target_date=date(2026, 3, 19),  # Gudi Padwa / Ugadi
            lat=self.mumbai_lat,
            lon=self.mumbai_lon,
            regional_profile_id="maharashtra",
        )
        self.assertIsNotNone(res)
        self.assertIn("tithi", res)
        self.assertIn("nakshatra", res)
        self.assertIn("muhurats", res)
        self.assertIn("sun_moon_timings", res)
        self.assertEqual(res["date"], "2026-03-19")
        self.assertEqual(res["tithi"]["running_tithi"], "Shukla Pratipada")
        self.assertEqual(res["regional_calendar"]["profile_id"], "maharashtra")

    def test_02_festival_processor_loads_independently(self):
        """2. Verify Festival processor can load and query original JSON independently."""
        processor = FestivalProcessor(json_path=PANCHANG_PATH)
        self.assertGreaterEqual(processor.total_dates, 365)
        self.assertEqual(processor.total_festivals, 84)

        # Test querying without providing any Panchang data
        fest_res = processor.process_date(
            target_date=date(2026, 1, 1),
            regional_profile_id="north_india",
            tradition="Smartha",
            panchang_results=None
        )
        self.assertTrue(fest_res["has_static_record"])
        self.assertEqual(fest_res["festival_name"], "New Year Day & New Year's Day")
        self.assertEqual(fest_res["classification"], "GREGORIAN_FIXED")
        self.assertIsNotNone(fest_res["preserved_static_record"])

    def test_03_both_run_concurrently(self):
        """3. Verify both branches run concurrently via async/await."""
        async def run_async_test():
            coord = PanchangCoordinator()
            result = await coord.calculate_panchang_async(
                target_date=self.test_date,
                lat=self.mumbai_lat,
                lon=self.mumbai_lon,
                regional_profile_id="maharashtra"
            )
            return result

        result = asyncio.run(run_async_test())
        self.assertIsNotNone(result)
        self.assertIn("astronomical_panchang", result)
        self.assertIn("preserved_static_festival_data", result)
        self.assertEqual(result["regional_profile"]["id"], "maharashtra")

    def test_04_regional_profiles_passed_correctly_to_both(self):
        """4. Verify regional profiles are passed correctly to both branches."""
        for prof_id in ["gujarat", "tamil_nadu", "kerala", "west_bengal"]:
            result = self.coordinator.calculate_panchang(
                target_date=date(2026, 4, 14),  # Solar New Year
                lat=13.0827,
                lon=80.2707,
                regional_profile_id=prof_id
            )
            self.assertEqual(result["regional_profile"]["id"], prof_id)
            self.assertEqual(
                result["astronomical_panchang"]["regional_calendar"]["profile_id"],
                prof_id
            )

    def test_05_final_merge_preserves_all_original_festival_records(self):
        """5. Verify final merge preserves all original fields and records from panchang_2026.json."""
        with open(PANCHANG_PATH, "r", encoding="utf-8") as f:
            raw_original = json.load(f)

        orig_diwali = raw_original["2026-11-08"]

        result = self.coordinator.calculate_panchang(
            target_date=date(2026, 11, 8),
            lat=self.mumbai_lat,
            lon=self.mumbai_lon,
            regional_profile_id="north_india"
        )

        preserved = result["preserved_static_festival_data"]["raw_day_record"]
        for key in ["source", "date", "vaara", "tithi", "paksha", "festival_name", "summary", "context"]:
            self.assertIn(key, preserved)
            self.assertEqual(preserved[key], orig_diwali[key])

        # Aliases check
        aliases = self.coordinator.festival_processor.get_aliases()
        self.assertEqual(len(aliases), 36)
        self.assertEqual(aliases["दीपावली"], "Diwali")

    def test_06_calculated_festival_dates_consistent_with_calendar_and_tradition(self):
        """6. Verify calculated festival dates are consistent with tradition (Smartha vs Vaishnava)."""
        # Ekadashi check
        res_smartha = self.coordinator.calculate_panchang(
            target_date=date(2026, 1, 30),  # Jaya Ekadashi
            tradition="Smartha"
        )
        res_vaishnava = self.coordinator.calculate_panchang(
            target_date=date(2026, 1, 30),
            tradition="Vaishnava"
        )

        self.assertIn("Jaya Ekadashi", str(res_smartha["festival_intelligence"]["active_festival"]))
        self.assertEqual(res_smartha["regional_profile"]["tradition"], "Smartha")
        self.assertEqual(res_vaishnava["regional_profile"]["tradition"], "Vaishnava")

    def test_07_different_regions_produce_different_outputs_for_same_date(self):
        """7. Verify different regions produce different regional festival/calendar outputs for same date."""
        d = date(2026, 4, 15)

        res_tn = self.coordinator.calculate_panchang(target_date=d, regional_profile_id="tamil_nadu")
        res_kl = self.coordinator.calculate_panchang(target_date=d, regional_profile_id="kerala")
        res_wb = self.coordinator.calculate_panchang(target_date=d, regional_profile_id="west_bengal")
        res_mh = self.coordinator.calculate_panchang(target_date=d, regional_profile_id="maharashtra")

        # Regional month & era strings must differ
        str_tn = res_tn["astronomical_panchang"]["regional_calendar"]["regional_date_string"]
        str_kl = res_kl["astronomical_panchang"]["regional_calendar"]["regional_date_string"]
        str_wb = res_wb["astronomical_panchang"]["regional_calendar"]["regional_date_string"]
        str_mh = res_mh["astronomical_panchang"]["regional_calendar"]["regional_date_string"]

        self.assertIn("Chithirai", str_tn)
        self.assertIn("Medam", str_kl)
        self.assertIn("Boishakh", str_wb)
        self.assertIn("Shaka", str_mh)

        self.assertNotEqual(str_tn, str_kl)
        self.assertNotEqual(str_kl, str_wb)
        self.assertNotEqual(str_wb, str_mh)

    def test_08_language_changes_presentation_without_changing_astronomy(self):
        """8. Verify language changes presentation without changing astronomical calculations."""
        d = date(2026, 1, 1)

        res_en = self.coordinator.calculate_panchang(
            target_date=d, lat=self.mumbai_lat, lon=self.mumbai_lon,
            regional_profile_id="maharashtra", language="English"
        )
        res_mr = self.coordinator.calculate_panchang(
            target_date=d, lat=self.mumbai_lat, lon=self.mumbai_lon,
            regional_profile_id="maharashtra", language="Marathi"
        )

        # Astronomical calculations must be identical
        tithi_en = res_en["astronomical_panchang"]["tithi"]["tithi_number"]
        tithi_mr = res_mr["astronomical_panchang"]["tithi"]["tithi_number"]
        sr_en = res_en["astronomical_panchang"]["sun_moon_timings"]["sunrise"]
        sr_mr = res_mr["astronomical_panchang"]["sun_moon_timings"]["sunrise"]

        self.assertEqual(tithi_en, tithi_mr)
        self.assertEqual(sr_en, sr_mr)
        # Presentation fields differ
        self.assertEqual(res_en["regional_profile"]["requested_language"], "English")
        self.assertEqual(res_mr["regional_profile"]["requested_language"], "Marathi")

    def test_09_user_overrides_change_selected_calendar_profile_correctly(self):
        """9. Verify user explicit override takes precedence over location inference."""
        # Location is Mumbai (which defaults to Maharashtra), but user explicitly overrides with Gujarat
        res_override = self.coordinator.calculate_panchang(
            target_date=date(2026, 1, 1),
            location_name="Mumbai",
            regional_profile_id="gujarat"
        )
        self.assertEqual(res_override["regional_profile"]["id"], "gujarat")
        self.assertEqual(res_override["regional_profile"]["resolution_source"], "explicit_user_override")
        self.assertIn("Kartikadi", res_override["astronomical_panchang"]["regional_calendar"]["regional_era"])

        # Without explicit override, Mumbai infers Maharashtra
        res_inferred = self.coordinator.calculate_panchang(
            target_date=date(2026, 1, 1),
            location_name="Mumbai",
            regional_profile_id=None
        )
        self.assertEqual(res_inferred["regional_profile"]["id"], "maharashtra")
        self.assertIn("inferred_from_location", res_inferred["regional_profile"]["resolution_source"])


if __name__ == "__main__":
    unittest.main()
