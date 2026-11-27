"""
panchange_engine.py — Complete Unified Dual-Branch Parallel Panchang & Festival Architecture.

Consolidates all components into a single, cohesive, self-contained engine:
  1. Astronomical Math & Ephemeris (Meeus VSOP/ELP & Lahiri Chitrapaksha Ayanamsha)
  2. Celestial Timings (Sunrise, Sunset, Moonrise, Moonset, Dinamana, Ratrimana)
  3. 11 Vedic Muhurats (Rahu Kaal, Yamaganda, Gulika, Abhijit, Brahma, Godhuli, Vijaya, etc.)
  4. 10 Multidimensional Regional Profiles (Maharashtra, Gujarat, North India, AP/Telangana,
     Karnataka, Tamil Nadu, Kerala, West Bengal, Odisha, Assam)
  5. Branch 1: Dynamic Panchang Calculation Engine (zero static JSON dependency)
  6. Branch 2: Preserved Festival Processor (loads & preserves panchang_2026.json)
  7. Astronomical Festival Rule Evaluator & Discrepancy Detector
  8. Non-Destructive Panchang Merger
  9. Coordinator with synchronous and asynchronous entry points
"""
import asyncio
from datetime import datetime, date, time, timedelta
import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from specs import PANCHANG_PATH
from daily_resolver import DailyResolver, amanta_month_on

# 1. CONSTANTS, VEDIC CATALOGS & ASTRONOMICAL ALGORITHMS (Meeus Ephemeris)

VAARA_NAMES_EN = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]

VAARA_NAMES_SAN = [
    "Somavara", "Mangalavara", "Budhavara", "Guruvara", "Shukravara", "Shanivara", "Ravivara"
]

TITHI_NAMES = [
    "Shukla Pratipada", "Shukla Dwitiya", "Shukla Tritiya", "Shukla Chaturthi",
    "Shukla Panchami", "Shukla Shashti", "Shukla Saptami", "Shukla Ashtami",
    "Shukla Navami", "Shukla Dashami", "Shukla Ekadashi", "Shukla Dwadashi",
    "Shukla Trayodashi", "Shukla Chaturdashi", "Purnima",
    "Krishna Pratipada", "Krishna Dwitiya", "Krishna Tritiya", "Krishna Chaturthi",
    "Krishna Panchami", "Krishna Shashti", "Krishna Saptami", "Krishna Ashtami",
    "Krishna Navami", "Krishna Dashami", "Krishna Ekadashi", "Krishna Dwadashi",
    "Krishna Trayodashi", "Krishna Chaturdashi", "Amavasya"
]

NAKSHATRA_NAMES = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashirsha", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta",
    "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

YOGA_NAMES = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda",
    "Sukarma", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva",
    "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan",
    "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla",
    "Brahma", "Indra", "Vaidhriti"
]

MOVABLE_KARANAS = [
    "Bava", "Balava", "Kaulava", "Taitila", "Gara", "Vanija", "Vishti (Bhadra)"
]

FIXED_KARANAS = {
    1: "Kimstughna",
    58: "Shakuni",
    59: "Chatushpada",
    60: "Naga"
}

RASHI_NAMES_SAN = [
    "Mesha", "Vrishabha", "Mithuna", "Karka",
    "Simha", "Kanya", "Tula", "Vrischika",
    "Dhanu", "Makara", "Kumbha", "Meena"
]

LUNAR_MONTHS_SAN = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashvina", "Kartika",
    "Margashirsha", "Pausha", "Magha", "Phalguna"
]

SAMVATSARA_NAMES = [
    "Prabhava", "Vibhava", "Shukla", "Pramoda", "Prajapati",
    "Angirasa", "Shrimukha", "Bhava", "Yuva", "Dhatri",
    "Ishvara", "Bahudhanya", "Pramathi", "Vikrama", "Vrisha",
    "Chitrabhanu", "Subhanu", "Tarana", "Parthiva", "Vyaya",
    "Sarvajit", "Sarvadhari", "Virodhi", "Vikrita", "Khara",
    "Nandana", "Vijaya", "Jaya", "Manmatha", "Durmukhi",
    "Hevilambi", "Vilambi", "Vikari", "Sharvari", "Plava",
    "Shubhakrita", "Shobhakrita", "Krodhi", "Vishvavasu", "Parabhava",
    "Plavanga", "Kilaka", "Saumya", "Sadharana", "Virodhikrita",
    "Paridhavi", "Pramadicha", "Ananda", "Rakshasa", "Anala",
    "Pingala", "Kalayukti", "Siddharthi", "Raudra", "Durmati",
    "Dundubhi", "Rudhirodgari", "Raktakshi", "Krodhana", "Kshaya"
]

# Meeus Ch 47 lunar longitude perturbation series: (D, M, M_prime, F, l_sin_coeff, l_sin_t_coeff)
_LUNAR_LONGITUDE_TERMS = [
    (0, 0, 1, 0, 6288774, -209538),
    (2, 0, -1, 0, 1274027, -3699),
    (2, 0, 0, 0, 658314, -2956),
    (0, 0, 2, 0, 213618, -564),
    (0, 1, 0, 0, -185116, -42),
    (0, 0, 0, 2, -114332, 246),
    (2, 0, -2, 0, 58793, -1711),
    (2, -1, -1, 0, 57066, -152),
    (2, 0, 1, 0, 53322, -174),
    (2, -1, 0, 0, 45758, -129),
    (0, 1, -1, 0, -40923, 11),
    (1, 0, 0, 0, -34720, -104),
    (0, 1, 1, 0, -30383, 14),
    (2, 0, 0, -2, 15327, 35),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 0),
    (4, 0, -1, 0, 10675, -55),
    (0, 0, 3, 0, 10034, 0),
    (4, 0, -2, 0, 8548, -42),
    (2, 1, -1, 0, -7888, 0),
    (2, 1, 0, 0, -6766, 0),
    (1, 0, -1, 0, -5163, 0),
    (1, 1, 0, 0, 4987, 0),
    (2, -1, 1, 0, 4036, 0),
    (2, 0, 2, 0, 3994, 0),
    (4, 0, 0, 0, 3861, 0),
    (2, 0, -3, 0, 3665, 0),
    (0, 1, -2, 0, -2689, 0),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 0),
    (1, 0, 1, 0, -2348, 0),
    (2, -2, 0, 0, 2236, 0),
    (0, 1, 2, 0, -2120, 0),
    (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, 0),
    (2, 0, 1, -2, -1773, 0),
    (2, 0, 0, 2, -1595, 0),
    (4, -1, -1, 0, 1215, 0),
    (0, 0, 2, 2, -1110, 0),
    (3, 0, -1, 0, -892, 0),
    (2, 1, 1, 0, -810, 0),
    (4, -1, -2, 0, 759, 0),
    (0, 2, -1, 0, -713, 0),
    (2, 2, -1, 0, -700, 0),
    (2, 1, -2, 0, 691, 0),
    (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, 0),
    (0, 0, 4, 0, 537, 0),
    (4, -1, 0, 0, 520, 0),
    (1, 0, -2, 0, -487, 0),
    (2, 1, 0, -2, -399, 0),
    (0, 0, 2, -2, -381, 0),
    (1, 1, 1, 0, 351, 0),
    (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0),
    (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 0),
    (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0),
]


def julian_day(year: int, month: int, day: int, ut_hours: float = 0.0) -> float:
    y, m = year, month
    if m <= 2:
        y -= 1
        m += 12
    a = math.floor(y / 100)
    b = 2 - a + math.floor(a / 4)
    jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + day + b - 1524.5
    return jd + ut_hours / 24.0


def julian_centuries(jd: float) -> float:
    return (jd - 2451545.0) / 36525.0


def lahiri_ayanamsha(jd: float) -> float:
    t = julian_centuries(jd)
    return 23.853074 + 1.39694 * t


def sun_apparent_longitude(jd: float) -> float:
    t = julian_centuries(jd)
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    mr = math.radians(m)
    c = (1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(mr) \
        + (0.019993 - 0.000101 * t) * math.sin(2 * mr) \
        + 0.000289 * math.sin(3 * mr)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    return app_long % 360.0


def sun_declination_and_eot(jd: float) -> Tuple[float, float]:
    t = julian_centuries(jd)
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360.0
    m = (357.52911 + 35999.05029 * t - 0.0001537 * t * t) % 360.0
    mr = math.radians(m)
    c = (1.914602 - 0.004817 * t) * math.sin(mr) + (0.019993 - 0.000101 * t) * math.sin(2 * mr)
    true_long = (l0 + c) % 360.0

    eps0 = 23.439291 - 0.0130042 * t
    eps_r = math.radians(eps0)

    sin_dec = math.sin(eps_r) * math.sin(math.radians(true_long))
    dec = math.degrees(math.asin(sin_dec))

    y = math.tan(eps_r / 2.0) ** 2
    l0_r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0_r)
        - 2 * 0.016708634 * math.sin(mr)
        + 4 * 0.016708634 * y * math.sin(mr) * math.cos(2 * l0_r)
        - 0.5 * (y ** 2) * math.sin(4 * l0_r)
        - 1.25 * (0.016708634 ** 2) * math.sin(2 * mr)
    )
    return dec, eot


def moon_apparent_longitude(jd: float) -> float:
    t = julian_centuries(jd)
    l_prime = 218.3164477 + 481267.88128 * t - 0.0015786 * t * t
    d = 297.8501921 + 445267.11140 * t - 0.0018819 * t * t
    m = 357.5291092 + 35999.05029 * t - 0.0001536 * t * t
    m_prime = 134.9633964 + 477198.86750 * t + 0.0087414 * t * t
    f = 93.2720950 + 483202.01752 * t - 0.0036539 * t * t

    e = 1.0 - 0.002516 * t - 0.0000074 * t * t
    sigma_l = 0.0
    for d_mul, m_mul, mp_mul, f_mul, a1, a2 in _LUNAR_LONGITUDE_TERMS:
        arg = math.radians(d_mul * d + m_mul * m + mp_mul * m_prime + f_mul * f)
        coeff = (a1 + a2 * t) * 1e-6
        if abs(m_mul) == 1:
            coeff *= e
        elif abs(m_mul) == 2:
            coeff *= (e * e)
        sigma_l += coeff * math.sin(arg)

    a1 = 119.75 + 131.849 * t
    a2 = 53.09 + 479264.290 * t
    sigma_l += 0.003957 * math.sin(math.radians(a1))
    sigma_l += 0.001962 * math.sin(math.radians(l_prime - f))
    sigma_l += 0.000318 * math.sin(math.radians(a2))

    omega = 125.04452 - 1934.136261 * t
    app_long = l_prime + sigma_l - 0.00478 * math.sin(math.radians(omega))
    return app_long % 360.0


def calculate_sunrise_sunset(
    target_date: date,
    lat: float,
    lon: float,
    tz_offset: float = 5.5,
    elevation_m: float = 0.0
) -> Tuple[time, time, float]:
    dip = 0.0347 * math.sqrt(max(0.0, elevation_m))
    zenith = 90.8333 + dip

    jd_noon = julian_day(target_date.year, target_date.month, target_date.day, 12.0 - tz_offset)
    dec, eot = sun_declination_and_eot(jd_noon)

    lat_r = math.radians(lat)
    dec_r = math.radians(dec)
    zenith_r = math.radians(zenith)

    cos_h = (math.cos(zenith_r) - math.sin(lat_r) * math.sin(dec_r)) / (math.cos(lat_r) * math.cos(dec_r))

    if cos_h > 1.0:
        return time(6, 0), time(18, 0), 0.0
    elif cos_h < -1.0:
        return time(0, 0), time(23, 59), 24.0

    hour_angle = math.degrees(math.acos(cos_h))
    solar_noon_hours = 12.0 + (tz_offset * 15.0 - lon) / 15.0 - (eot / 60.0)

    sunrise_hours = solar_noon_hours - (hour_angle / 15.0)
    sunset_hours = solar_noon_hours + (hour_angle / 15.0)
    dinamana_hours = (hour_angle * 2.0) / 15.0

    def to_time_obj(h_val: float) -> time:
        h_val = h_val % 24.0
        hrs = int(h_val)
        mins = int((h_val - hrs) * 60.0)
        return time(hrs, mins)

    return to_time_obj(sunrise_hours), to_time_obj(sunset_hours), dinamana_hours


def calculate_moonrise_moonset(
    target_date: date,
    lat: float,
    lon: float,
    tz_offset: float = 5.5
) -> Tuple[Optional[time], Optional[time]]:
    lat_r = math.radians(lat)
    r_rise: Optional[float] = None
    r_set: Optional[float] = None
    target_alt = math.radians(0.125)

    def get_moon_alt(hr_local: float) -> float:
        ut_h = hr_local - tz_offset
        jd = julian_day(target_date.year, target_date.month, target_date.day, ut_h)
        m_lon = moon_apparent_longitude(jd)
        t = julian_centuries(jd)
        eps0 = 23.439291 - 0.0130042 * t
        eps_r = math.radians(eps0)
        m_lon_r = math.radians(m_lon)

        sin_dec = math.sin(eps_r) * math.sin(m_lon_r)
        dec = math.asin(sin_dec)
        ra = math.atan2(math.cos(eps_r) * math.sin(m_lon_r), math.cos(m_lon_r))

        gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0)
        lmst_r = math.radians((gmst + lon) % 360.0)
        ha = lmst_r - ra
        sin_alt = math.sin(lat_r) * math.sin(dec) + math.cos(lat_r) * math.cos(dec) * math.cos(ha)
        return math.asin(max(-1.0, min(1.0, sin_alt)))

    step_h = 0.25
    prev_h = 0.0
    prev_alt = get_moon_alt(prev_h)

    for i in range(1, 97):
        curr_h = i * step_h
        curr_alt = get_moon_alt(curr_h)
        if prev_alt < target_alt <= curr_alt and r_rise is None:
            frac = (target_alt - prev_alt) / (curr_alt - prev_alt)
            r_rise = prev_h + frac * step_h
        elif prev_alt >= target_alt > curr_alt and r_set is None:
            frac = (target_alt - prev_alt) / (curr_alt - prev_alt)
            r_set = prev_h + frac * step_h
        prev_h = curr_h
        prev_alt = curr_alt

    def to_time_opt(h_val: Optional[float]) -> Optional[time]:
        if h_val is None:
            return None
        h_mod = h_val % 24.0
        hrs = int(h_mod)
        mins = int((h_mod - hrs) * 60.0)
        return time(hrs, mins)

    return to_time_opt(r_rise), to_time_opt(r_set)


def get_tithi_at_jd(jd: float) -> Tuple[int, str, str, float]:
    sun_lon = sun_apparent_longitude(jd)
    moon_lon = moon_apparent_longitude(jd)
    elongation = (moon_lon - sun_lon) % 360.0
    tithi_index = int(elongation / 12.0)
    tithi_num = tithi_index + 1
    fraction = (elongation % 12.0) / 12.0
    paksha = "Shukla" if tithi_num <= 15 else "Krishna"
    name = TITHI_NAMES[tithi_index]
    return tithi_num, name, paksha, fraction


def get_nakshatra_at_jd(jd: float) -> Tuple[int, str, float]:
    moon_trop = moon_apparent_longitude(jd)
    ayan = lahiri_ayanamsha(jd)
    moon_sid = (moon_trop - ayan) % 360.0
    span = 360.0 / 27.0
    index = int(moon_sid / span)
    nak_num = index + 1
    fraction = (moon_sid % span) / span
    return nak_num, NAKSHATRA_NAMES[index], fraction


def get_yoga_at_jd(jd: float) -> Tuple[int, str, float]:
    sun_trop = sun_apparent_longitude(jd)
    moon_trop = moon_apparent_longitude(jd)
    ayan = lahiri_ayanamsha(jd)
    sun_sid = (sun_trop - ayan) % 360.0
    moon_sid = (moon_trop - ayan) % 360.0
    total_sid = (sun_sid + moon_sid) % 360.0
    span = 360.0 / 27.0
    index = int(total_sid / span)
    yoga_num = index + 1
    fraction = (total_sid % span) / span
    return yoga_num, YOGA_NAMES[index], fraction


def get_karana_at_jd(jd: float) -> Tuple[int, str]:
    sun_lon = sun_apparent_longitude(jd)
    moon_lon = moon_apparent_longitude(jd)
    elongation = (moon_lon - sun_lon) % 360.0
    karana_num = int(elongation / 6.0) + 1
    return karana_num, karana_name_at_index(karana_num)


def karana_name_at_index(karana_num: int) -> str:
    return FIXED_KARANAS.get(karana_num) or MOVABLE_KARANAS[(karana_num - 2) % 7]


def get_solar_rashi_at_jd(jd: float) -> Tuple[int, str, float]:
    sun_trop = sun_apparent_longitude(jd)
    ayan = lahiri_ayanamsha(jd)
    sun_sid = (sun_trop - ayan) % 360.0
    rashi_idx = int(sun_sid / 30.0)
    deg_in_rashi = sun_sid % 30.0
    return rashi_idx + 1, RASHI_NAMES_SAN[rashi_idx], deg_in_rashi


def find_sankranti_on_date(target_date: date, tz_offset: float = 5.5) -> Optional[Dict[str, Any]]:
    jd_start = julian_day(target_date.year, target_date.month, target_date.day, 0.0 - tz_offset)
    jd_end = julian_day(target_date.year, target_date.month, target_date.day, 24.0 - tz_offset)

    rashi_start, name_start, _ = get_solar_rashi_at_jd(jd_start)
    rashi_end, name_end, _ = get_solar_rashi_at_jd(jd_end)

    if rashi_start != rashi_end:
        low = jd_start
        high = jd_end
        target_rashi = rashi_end
        for _ in range(20):
            mid = (low + high) / 2.0
            r_mid, _, _ = get_solar_rashi_at_jd(mid)
            if r_mid == target_rashi:
                high = mid
            else:
                low = mid

        ingress_jd = high
        ingress_ut_hours = (ingress_jd - math.floor(ingress_jd) + 0.5) * 24.0 % 24.0
        ingress_local_hours = (ingress_ut_hours + tz_offset) % 24.0
        hrs = int(ingress_local_hours)
        mins = int((ingress_local_hours - hrs) * 60)

        sankranti_name = f"{name_end} Sankranti"
        if name_end == "Makara":
            sankranti_name = "Makar Sankranti"
        elif name_end == "Mesha":
            sankranti_name = "Mesha Sankranti (Maha Vishuba)"

        return {
            "occurred": True,
            "rashi_number": rashi_end,
            "rashi_name": name_end,
            "sankranti_name": sankranti_name,
            "time_ist": f"{hrs:02d}:{mins:02d}",
        }
    return None


def calculate_muhurats(
    target_date: date,
    sunrise: time,
    sunset: time,
    next_sunrise: Optional[time] = None
) -> Dict[str, Any]:
    weekday = target_date.weekday()
    sr_mins = sunrise.hour * 60 + sunrise.minute
    ss_mins = sunset.hour * 60 + sunset.minute
    dinamana = ss_mins - sr_mins
    octant = dinamana / 8.0
    muhurta_day = dinamana / 15.0

    if next_sunrise:
        next_sr_mins = next_sunrise.hour * 60 + next_sunrise.minute
        ratrimana = (24 * 60 - ss_mins) + next_sr_mins
    else:
        ratrimana = (24 * 60) - dinamana

    muhurta_night = ratrimana / 15.0

    def format_window(start_m: float, end_m: float) -> str:
        s_m = int(round(start_m)) % (24 * 60)
        e_m = int(round(end_m)) % (24 * 60)
        return f"{s_m // 60:02d}:{s_m % 60:02d} - {e_m // 60:02d}:{e_m % 60:02d}"

    # Rahu Kaal
    rahu_periods = {0: 1, 1: 6, 2: 4, 3: 5, 4: 3, 5: 2, 6: 7}
    rahu_start = sr_mins + rahu_periods[weekday] * octant
    rahu_kaal = format_window(rahu_start, rahu_start + octant)

    # Yamaganda
    yama_periods = {0: 3, 1: 2, 2: 1, 3: 0, 4: 6, 5: 5, 6: 4}
    yama_start = sr_mins + yama_periods[weekday] * octant
    yamaganda = format_window(yama_start, yama_start + octant)

    # Gulika Kaal
    gulika_periods = {0: 5, 1: 4, 2: 3, 3: 2, 4: 1, 5: 0, 6: 6}
    gulika_start = sr_mins + gulika_periods[weekday] * octant
    gulika_kaal = format_window(gulika_start, gulika_start + octant)

    # Abhijit Muhurat
    abhijit_start = sr_mins + 7 * muhurta_day
    abhijit_end = sr_mins + 8 * muhurta_day
    abhijit_muhurta = format_window(abhijit_start, abhijit_end)

    # Brahma, Godhuli, Vijaya, Nishita, Pradosha, Madhyahna, Durmuhurta
    brahma_muhurta = format_window(sr_mins - 96, sr_mins - 48)
    godhuli_muhurta = format_window(ss_mins - 24, ss_mins + 24)
    vijaya_muhurta = format_window(sr_mins + 10 * muhurta_day, sr_mins + 11 * muhurta_day)
    nishita_kaal = format_window(ss_mins + 7 * muhurta_night, ss_mins + 8 * muhurta_night)
    pradosha_kaal = format_window(ss_mins, ss_mins + 2 * muhurta_night)
    madhyahna = format_window(sr_mins + 6 * muhurta_day, sr_mins + 9 * muhurta_day)

    durmuhurta_periods = {
        0: [sr_mins + 8 * muhurta_day, sr_mins + 9 * muhurta_day],
        1: [sr_mins + 3 * muhurta_day, sr_mins + 4 * muhurta_day],
        2: [sr_mins + 7 * muhurta_day, sr_mins + 8 * muhurta_day],
        3: [sr_mins + 5 * muhurta_day, sr_mins + 6 * muhurta_day],
        4: [sr_mins + 3 * muhurta_day, sr_mins + 4 * muhurta_day],
        5: [sr_mins + 1 * muhurta_day, sr_mins + 2 * muhurta_day],
        6: [sr_mins + 13 * muhurta_day, sr_mins + 14 * muhurta_day],
    }
    dm_s, dm_e = durmuhurta_periods[weekday]
    durmuhurta = format_window(dm_s, dm_e)

    return {
        "dinamana_minutes": round(dinamana, 1),
        "ratrimana_minutes": round(ratrimana, 1),
        "rahu_kalam": rahu_kaal,
        "yamaganda": yamaganda,
        "gulika_kaal": gulika_kaal,
        "abhijit_muhurta": abhijit_muhurta,
        "abhijit_auspicious": (weekday != 2),
        "brahma_muhurta": brahma_muhurta,
        "godhuli_muhurta": godhuli_muhurta,
        "vijaya_muhurta": vijaya_muhurta,
        "nishita_kaal": nishita_kaal,
        "pradosha_kaal": pradosha_kaal,
        "madhyahna": madhyahna,
        "durmuhurta": durmuhurta,
    }


# 2. REGIONAL CALENDAR PROFILES & RESOLUTION

def get_samvatsara_name(shaka_year: int) -> str:
    idx = (shaka_year + 11) % 60
    return SAMVATSARA_NAMES[idx]


REGIONAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "maharashtra": {
        "id": "maharashtra",
        "display_name": "Maharashtra (Marathi Amanta)",
        "state": "Maharashtra",
        "calendar_system": "lunar_amanta",
        "primary_era": "shaka",
        "era_name": "Shaka Samvat (Shalivahana)",
        "language_code": "mr",
        "language_name": "Marathi",
        "new_year": {"name": "Gudi Padwa", "tithi": "Shukla Pratipada", "month": "Chaitra"},
        "months": {
            1: {"translit": "Chaitra", "script": "चैत्र"},
            2: {"translit": "Vaishakh", "script": "वैशाख"},
            3: {"translit": "Jyeshtha", "script": "ज्येष्ठ"},
            4: {"translit": "Ashadh", "script": "आषाढ"},
            5: {"translit": "Shravan", "script": "श्रावण"},
            6: {"translit": "Bhadrapad", "script": "भाद्रपद"},
            7: {"translit": "Ashwin", "script": "अश्विन"},
            8: {"translit": "Kartik", "script": "कार्तिक"},
            9: {"translit": "Margashirsha", "script": "मार्गशीर्ष"},
            10: {"translit": "Paush", "script": "पौष"},
            11: {"translit": "Magh", "script": "माघ"},
            12: {"translit": "Falgun", "script": "फाल्गुन"},
        },
        "vaara_names": {
            "Monday": "Somvar (सोमवार)", "Tuesday": "Mangalwar (मंगळवार)",
            "Wednesday": "Budhwar (बुधवार)", "Thursday": "Guruwar (गुरुवार)",
            "Friday": "Shukrawar (शुक्रवार)", "Saturday": "Shaniwar (शनिवार)",
            "Sunday": "Raviwar (रविवार)",
        },
        "paksha_names": {"Shukla": "Shukla Paksha (शुद्ध)", "Krishna": "Krishna Paksha (वद्य)"},
        "regional_festivals": [
            "Gudi Padwa", "Ganesh Chaturthi", "Anant Chaturdashi", "Vat Purnima",
            "Narali Purnima", "Ashadhi Ekadashi (Pandharpur Wari)", "Kartiki Ekadashi",
            "Pithori Amavasya", "Kojagiri Purnima", "Makar Sankranti (Haldi-Kunku)", "Pola"
        ],
        "default_tradition": "Smartha",
    },

    "gujarat": {
        "id": "gujarat",
        "display_name": "Gujarat (Gujarati Amanta Kartikadi)",
        "state": "Gujarat",
        "calendar_system": "lunar_amanta",
        "primary_era": "vikram_kartikkadi",
        "era_name": "Gujarati Vikram Samvat (Kartikadi)",
        "language_code": "gu",
        "language_name": "Gujarati",
        "new_year": {"name": "Bestu Varas (Nutun Varsh)", "tithi": "Shukla Pratipada", "month": "Kartak"},
        "months": {
            1: {"translit": "Kartak", "script": "કારતક"},
            2: {"translit": "Magshar", "script": "માગશર"},
            3: {"translit": "Posh", "script": "પોષ"},
            4: {"translit": "Maha", "script": "મહા"},
            5: {"translit": "Fagan", "script": "ફાગણ"},
            6: {"translit": "Chaitra", "script": "ચૈત્ર"},
            7: {"translit": "Vaishakh", "script": "વૈશાખ"},
            8: {"translit": "Jeth", "script": "જેઠ"},
            9: {"translit": "Ashadh", "script": "અષાઢ"},
            10: {"translit": "Shravan", "script": "શ્રાવણ"},
            11: {"translit": "Bhadarvo", "script": "ભાદરવો"},
            12: {"translit": "Aaso", "script": "આસો"},
        },
        "vaara_names": {
            "Monday": "Somvar (સોમવાર)", "Tuesday": "Mangalvar (મંગળવાર)",
            "Wednesday": "Budhvar (બુધવાર)", "Thursday": "Guruvar (ગુરુવાર)",
            "Friday": "Shukravar (શુક્રવાર)", "Saturday": "Shanivar (શનિવાર)",
            "Sunday": "Ravivar (રવિવાર)",
        },
        "paksha_names": {"Shukla": "Sud (સુદ)", "Krishna": "Vad (વદ)"},
        "regional_festivals": [
            "Bestu Varas", "Navratri (Garba)", "Uttarayan (Kite Festival)", "Vasi Uttarayan",
            "Sharad Poonam", "Jal Jhilani Ekadashi", "Bhai Bij", "Labh Pancham"
        ],
        "default_tradition": "Vaishnava",
    },

    "north_india": {
        "id": "north_india",
        "display_name": "North India (Hindi Purnimanta)",
        "state": "Uttar Pradesh / Bihar / Rajasthan / MP / Delhi",
        "calendar_system": "lunar_purnimanta",
        "primary_era": "vikram_chaitradi",
        "era_name": "Vikram Samvat (Chaitradi)",
        "language_code": "hi",
        "language_name": "Hindi",
        "new_year": {"name": "Nav Samvatsara", "tithi": "Shukla Pratipada", "month": "Chaitra"},
        "months": {
            1: {"translit": "Chaitra", "script": "चैत्र"},
            2: {"translit": "Vaishakha", "script": "वैशाख"},
            3: {"translit": "Jyeshtha", "script": "ज्येष्ठ"},
            4: {"translit": "Ashadha", "script": "आषाढ़"},
            5: {"translit": "Shravana", "script": "श्रावण"},
            6: {"translit": "Bhadrapada", "script": "भाद्रपद"},
            7: {"translit": "Ashvina", "script": "आश्विन"},
            8: {"translit": "Kartika", "script": "कार्तिक"},
            9: {"translit": "Margashirsha", "script": "मार्गशीर्ष"},
            10: {"translit": "Pausha", "script": "पौष"},
            11: {"translit": "Magha", "script": "माघ"},
            12: {"translit": "Phalguna", "script": "फाल्गुन"},
        },
        "vaara_names": {
            "Monday": "Somavar (सोमवार)", "Tuesday": "Mangalavar (मंगलवार)",
            "Wednesday": "Budhavar (बुधवार)", "Thursday": "Guruvar (गुरुवार)",
            "Friday": "Shukravar (शुक्रवार)", "Saturday": "Shanivar (शनिवार)",
            "Sunday": "Ravivar (रविवार)",
        },
        "paksha_names": {"Shukla": "Shukla Paksha (शुक्ल पक्ष)", "Krishna": "Krishna Paksha (कृष्ण पक्ष)"},
        "regional_festivals": [
            "Karwa Chauth", "Ahoi Ashtami", "Chhath Puja", "Lathmar Holi",
            "Krishna Janmashtami (Nishita)", "Rama Navami", "Raksha Bandhan",
            "Govardhan Puja", "Dev Deepawali", "Hariyali Teej", "Hartalika Teej"
        ],
        "default_tradition": "Smartha",
    },

    "andhra_pradesh_telangana": {
        "id": "andhra_pradesh_telangana",
        "display_name": "Andhra Pradesh & Telangana (Telugu Amanta)",
        "state": "Andhra Pradesh / Telangana",
        "calendar_system": "lunar_amanta",
        "primary_era": "shaka",
        "era_name": "Shalivahana Shaka Samvatsaram",
        "language_code": "te",
        "language_name": "Telugu",
        "new_year": {"name": "Ugadi", "tithi": "Shukla Pratipada", "month": "Chaitramu"},
        "months": {
            1: {"translit": "Chaitramu", "script": "చైత్రము"},
            2: {"translit": "Vaishakhamu", "script": "వైశాఖము"},
            3: {"translit": "Jyeshthamu", "script": "జ్యేష్ఠము"},
            4: {"translit": "Ashadhamu", "script": "ఆషాఢము"},
            5: {"translit": "Shravanamu", "script": "శ్రావణము"},
            6: {"translit": "Bhadrapadamu", "script": "భాద్రపదము"},
            7: {"translit": "Ashvayujamu", "script": "ఆశ్వయుజము"},
            8: {"translit": "Karthikamu", "script": "కార్తీకము"},
            9: {"translit": "Margashirshamu", "script": "మార్గశిరము"},
            10: {"translit": "Pushyamu", "script": "పుష్యము"},
            11: {"translit": "Maghamu", "script": "మాఘము"},
            12: {"translit": "Phalgunamu", "script": "ఫాల్గుణము"},
        },
        "vaara_names": {
            "Monday": "Somavaramu (సోమవారము)", "Tuesday": "Mangalavaramu (మంగళవారము)",
            "Wednesday": "Budhavaramu (బుధవారము)", "Thursday": "Guruvaramu (గురువారము)",
            "Friday": "Shukravaramu (శుక్రవారము)", "Saturday": "Shanivaramu (శనివారము)",
            "Sunday": "Adivaramu (ఆదివారము)",
        },
        "paksha_names": {"Shukla": "Shukla Pakshamu (శుక్ల పక్షము)", "Krishna": "Krishna Pakshamu (కృష్ణ పక్షము)"},
        "regional_festivals": [
            "Ugadi", "Bonalu", "Bathukamma", "Sankranti (Bhogi, Pedda Panduga, Kanuma)",
            "Varalakshmi Vratam", "Sri Rama Navami (Bhadrachalam)", "Atla Tadde"
        ],
        "default_tradition": "Smartha",
    },

    "karnataka": {
        "id": "karnataka",
        "display_name": "Karnataka (Kannada Amanta)",
        "state": "Karnataka",
        "calendar_system": "lunar_amanta",
        "primary_era": "shaka",
        "era_name": "Shalivahana Shaka Samvatsara",
        "language_code": "kn",
        "language_name": "Kannada",
        "new_year": {"name": "Yugadi", "tithi": "Shukla Pratipada", "month": "Chaitra"},
        "months": {
            1: {"translit": "Chaitra", "script": "ಚೈತ್ರ"},
            2: {"translit": "Vaishakha", "script": "ವೈಶಾಖ"},
            3: {"translit": "Jyeshtha", "script": "ಜ್ಯೇಷ್ಠ"},
            4: {"translit": "Ashadha", "script": "ಆಷಾಢ"},
            5: {"translit": "Shravana", "script": "ಶ್ರಾವಣ"},
            6: {"translit": "Bhadrapada", "script": "ಭಾದ್ರಪದ"},
            7: {"translit": "Ashvayuja", "script": "ಆಶ್ವಯುಜ"},
            8: {"translit": "Karthika", "script": "ಕಾರ್ತಿಕ"},
            9: {"translit": "Margashira", "script": "ಮಾರ್ಗಶಿರ"},
            10: {"translit": "Pushya", "script": "ಪುಷ್ಯ"},
            11: {"translit": "Magha", "script": "ಮಾಘ"},
            12: {"translit": "Phalguna", "script": "ಫಾಲ್ಗುಣ"},
        },
        "vaara_names": {
            "Monday": "Somavara (ಸೋಮವಾರ)", "Tuesday": "Mangalavara (ಮಂಗಳವಾರ)",
            "Wednesday": "Budhavara (ಬುಧವಾರ)", "Thursday": "Guruvara (ಗುರುವಾರ)",
            "Friday": "Shukravara (ಶುಕ್ರವಾರ)", "Saturday": "Shanivara (ಶನಿವಾರ)",
            "Sunday": "Bhanuvara (ಭಾನುವಾರ)",
        },
        "paksha_names": {"Shukla": "Shukla Paksha (ಶುಕ್ಲ ಪಕ್ಷ)", "Krishna": "Krishna Paksha (ಕೃಷ್ಣ ಪಕ್ಷ)"},
        "regional_festivals": [
            "Yugadi", "Mysuru Dasara (Nada Habba)", "Varamahalakshmi Vrata",
            "Gauri Habba", "Karaga Shaktyotsava", "Balipadyami", "Makara Sankramana"
        ],
        "default_tradition": "Smartha",
    },

    "tamil_nadu": {
        "id": "tamil_nadu",
        "display_name": "Tamil Nadu (Tamil Solar Sauramana)",
        "state": "Tamil Nadu",
        "calendar_system": "solar_tamil",
        "primary_era": "thiruvalluvar",
        "era_name": "Thiruvalluvar Aandu & Tamil 60-Year Cycle",
        "language_code": "ta",
        "language_name": "Tamil",
        "new_year": {"name": "Puthandu (Tamil New Year)", "solar_sign": "Mesha", "month": "Chithirai"},
        "months": {
            1: {"translit": "Chithirai", "script": "சித்திரை", "solar_rashi": "Mesha"},
            2: {"translit": "Vaikasi", "script": "வைகாசி", "solar_rashi": "Vrishabha"},
            3: {"translit": "Aani", "script": "ஆனி", "solar_rashi": "Mithuna"},
            4: {"translit": "Aadi", "script": "ஆடி", "solar_rashi": "Karka"},
            5: {"translit": "Avani", "script": "ஆவணி", "solar_rashi": "Simha"},
            6: {"translit": "Purattasi", "script": "புரட்டாசி", "solar_rashi": "Kanya"},
            7: {"translit": "Aippasi", "script": "ஐப்பசி", "solar_rashi": "Tula"},
            8: {"translit": "Karthigai", "script": "கார்த்திகை", "solar_rashi": "Vrischika"},
            9: {"translit": "Margazhi", "script": "மார்கழி", "solar_rashi": "Dhanu"},
            10: {"translit": "Thai", "script": "தை", "solar_rashi": "Makara"},
            11: {"translit": "Masi", "script": "மாசி", "solar_rashi": "Kumbha"},
            12: {"translit": "Panguni", "script": "பங்குனி", "solar_rashi": "Meena"},
        },
        "vaara_names": {
            "Monday": "Thingal (திங்கள்)", "Tuesday": "Chevvai (செவ்வாய்)",
            "Wednesday": "Budhan (புதன்)", "Thursday": "Vyazhan (வியாழன்)",
            "Friday": "Velli (வெள்ளி)", "Saturday": "Sani (சனி)",
            "Sunday": "Gnayiru (ஞாயிறு)",
        },
        "paksha_names": {"Shukla": "Valarpirai (வளர்பிறை)", "Krishna": "Theipirai (தேய்பிறை)"},
        "regional_festivals": [
            "Pongal (Thai Pongal, Mattu Pongal, Kaanum Pongal)", "Puthandu", "Aadi Perukku",
            "Karthigai Deepam", "Thaipusam", "Panguni Uthiram", "Margazhi Utsavam"
        ],
        "default_tradition": "Shaiva",
    },

    "kerala": {
        "id": "kerala",
        "display_name": "Kerala (Malayalam Solar Kollavarsham)",
        "state": "Kerala",
        "calendar_system": "solar_malayalam",
        "primary_era": "kollam",
        "era_name": "Kollam Era (Kollavarsham)",
        "language_code": "ml",
        "language_name": "Malayalam",
        "new_year": {"name": "Chingam 1 (Official) / Vishu (Astronomical)", "solar_sign": "Simha / Mesha", "month": "Chingam / Medam"},
        "months": {
            1: {"translit": "Chingam", "script": "ചിങ്ങം", "solar_rashi": "Simha"},
            2: {"translit": "Kanni", "script": "കന്നി", "solar_rashi": "Kanya"},
            3: {"translit": "Thulam", "script": "തുലാം", "solar_rashi": "Tula"},
            4: {"translit": "Vrischikam", "script": "വൃശ്ചികം", "solar_rashi": "Vrischika"},
            5: {"translit": "Dhanu", "script": "ധനു", "solar_rashi": "Dhanu"},
            6: {"translit": "Makaram", "script": "മകരം", "solar_rashi": "Makara"},
            7: {"translit": "Kumbham", "script": "കുംഭം", "solar_rashi": "Kumbha"},
            8: {"translit": "Meenam", "script": "മീനം", "solar_rashi": "Meena"},
            9: {"translit": "Medam", "script": "മേടം", "solar_rashi": "Mesha"},
            10: {"translit": "Edavam", "script": "ഇടവം", "solar_rashi": "Vrishabha"},
            11: {"translit": "Mithunam", "script": "മിഥുനം", "solar_rashi": "Mithuna"},
            12: {"translit": "Karkidakam", "script": "കർക്കടകം", "solar_rashi": "Karka"},
        },
        "vaara_names": {
            "Monday": "Thingal (തിങ്കൾ)", "Tuesday": "Chovva (ചൊവ്വ)",
            "Wednesday": "Budhan (ബുധൻ)", "Thursday": "Vyazham (വ്യാഴം)",
            "Friday": "Velli (വെള്ളി)", "Saturday": "Shani (ശനി)",
            "Sunday": "Njayar (ഞായർ)",
        },
        "paksha_names": {"Shukla": "Velutha Paksham (വെളുത്ത പക്ഷം)", "Krishna": "Karutha Paksham (കറുത്ത പക്ഷം)"},
        "regional_festivals": [
            "Onam (Thiruvonam)", "Vishu (Medam 1)", "Makaravilakku (Sabarimala)",
            "Attukal Pongala", "Thrissur Pooram", "Karkidaka Vavu"
        ],
        "default_tradition": "Smartha",
    },

    "west_bengal": {
        "id": "west_bengal",
        "display_name": "West Bengal (Bengali Solar Bangabda)",
        "state": "West Bengal",
        "calendar_system": "solar_bengali",
        "primary_era": "bangabda",
        "era_name": "Bengali San (Bangabda)",
        "language_code": "bn",
        "language_name": "Bengali",
        "new_year": {"name": "Pohela Boishakh (Noboborsho)", "solar_sign": "Mesha", "month": "Boishakh"},
        "months": {
            1: {"translit": "Boishakh", "script": "বৈশাখ", "solar_rashi": "Mesha"},
            2: {"translit": "Joishtho", "script": "জ্যৈষ্ঠ", "solar_rashi": "Vrishabha"},
            3: {"translit": "Ashar", "script": "আষাঢ়", "solar_rashi": "Mithuna"},
            4: {"translit": "Srabon", "script": "শ্রাবণ", "solar_rashi": "Karka"},
            5: {"translit": "Bhadro", "script": "ভাদ্র", "solar_rashi": "Simha"},
            6: {"translit": "Ashwin", "script": "আশ্বিন", "solar_rashi": "Kanya"},
            7: {"translit": "Kartik", "script": "কার্তিক", "solar_rashi": "Tula"},
            8: {"translit": "Ogrohayon", "script": "অগ্রহায়ণ", "solar_rashi": "Vrischika"},
            9: {"translit": "Poush", "script": "পৌষ", "solar_rashi": "Dhanu"},
            10: {"translit": "Magh", "script": "মাঘ", "solar_rashi": "Makara"},
            11: {"translit": "Falgun", "script": "ফাল্গুন", "solar_rashi": "Kumbha"},
            12: {"translit": "Chaitro", "script": "চৈত্র", "solar_rashi": "Meena"},
        },
        "vaara_names": {
            "Monday": "Shombar (সোমবার)", "Tuesday": "Mongolbar (মঙ্গলবার)",
            "Wednesday": "Budhbar (বুধবার)", "Thursday": "Brihoshpotibar (বৃহস্পতিবার)",
            "Friday": "Shukrobar (শুক্রবার)", "Saturday": "Shonibar (শনিবার)",
            "Sunday": "Robibar (রবিবার)",
        },
        "paksha_names": {"Shukla": "Shukla Pokkho (শুক্ল পক্ষ)", "Krishna": "Krishna Pokkho (কৃষ্ণ পক্ষ)"},
        "regional_festivals": [
            "Durga Puja (Maha Shashti, Saptami, Ashtami, Navami, Vijaya Dashami)",
            "Kali Puja", "Saraswati Puja", "Pohela Boishakh", "Dol Jatra",
            "Jagaddhatri Puja", "Jamai Sasthi", "Bhai Phonta"
        ],
        "default_tradition": "Shakta",
    },

    "odisha": {
        "id": "odisha",
        "display_name": "Odisha (Odia Solar / Luni-Solar)",
        "state": "Odisha",
        "calendar_system": "solar_odia",
        "primary_era": "odia_san",
        "era_name": "Odia San & Shaka Era",
        "language_code": "or",
        "language_name": "Odia",
        "new_year": {"name": "Pana Sankranti (Maha Vishuba Sankranti)", "solar_sign": "Mesha", "month": "Baisakha"},
        "months": {
            1: {"translit": "Baisakha", "script": "ବୈଶାଖ", "solar_rashi": "Mesha"},
            2: {"translit": "Jyestha", "script": "ଜ୍ୟେଷ୍ଠ", "solar_rashi": "Vrishabha"},
            3: {"translit": "Ashadha", "script": "ଆଷାଢ଼", "solar_rashi": "Mithuna"},
            4: {"translit": "Srabana", "script": "ଶ୍ରାବଣ", "solar_rashi": "Karka"},
            5: {"translit": "Bhadraba", "script": "ଭାଦ୍ରବ", "solar_rashi": "Simha"},
            6: {"translit": "Aswina", "script": "ଆଶ୍ୱିନ", "solar_rashi": "Kanya"},
            7: {"translit": "Kartika", "script": "କାର୍ତ୍ତିକ", "solar_rashi": "Tula"},
            8: {"translit": "Margasira", "script": "ମାର୍ଗଶୀର", "solar_rashi": "Vrischika"},
            9: {"translit": "Pausa", "script": "ପୌଷ", "solar_rashi": "Dhanu"},
            10: {"translit": "Magha", "script": "ମାଘ", "solar_rashi": "Makara"},
            11: {"translit": "Phalguna", "script": "ଫାଲ୍ଗୁନ", "solar_rashi": "Kumbha"},
            12: {"translit": "Chaitra", "script": "ଚୈତ୍ର", "solar_rashi": "Meena"},
        },
        "vaara_names": {
            "Monday": "Somabara (ସୋମବାର)", "Tuesday": "Mangalabara (ମଙ୍ଗଳବାର)",
            "Wednesday": "Budhabara (ବୁଧବାର)", "Thursday": "Gurubara (ଗୁରୁବାର)",
            "Friday": "Sukrabara (ଶୁକ୍ରବାର)", "Saturday": "Sanibara (ଶନିବାର)",
            "Sunday": "Rabibara (ରବିବାର)",
        },
        "paksha_names": {"Shukla": "Sukla Pakshya (ଶୁକ୍ଳ ପକ୍ଷ)", "Krishna": "Krishna Pakshya (କୃଷ୍ଣ ପକ୍ଷ)"},
        "regional_festivals": [
            "Rath Yatra (Puri)", "Raja Parba", "Pana Sankranti", "Kumar Purnima",
            "Prathamastami", "Boita Bandana (Kartika Purnima)", "Chandan Yatra"
        ],
        "default_tradition": "Vaishnava",
    },

    "assam": {
        "id": "assam",
        "display_name": "Assam (Assamese Solar Bhaskaravda)",
        "state": "Assam",
        "calendar_system": "solar_assamese",
        "primary_era": "bhaskaravda",
        "era_name": "Bhaskaravda & Shaka Era",
        "language_code": "as",
        "language_name": "Assamese",
        "new_year": {"name": "Rongali Bihu (Bohag Bihu)", "solar_sign": "Mesha", "month": "Bohag"},
        "months": {
            1: {"translit": "Bohag", "script": "ব’হাগ", "solar_rashi": "Mesha"},
            2: {"translit": "Jeth", "script": "জেঠ", "solar_rashi": "Vrishabha"},
            3: {"translit": "Ahar", "script": "আহাৰ", "solar_rashi": "Mithuna"},
            4: {"translit": "Shaun", "script": "শাওন", "solar_rashi": "Karka"},
            5: {"translit": "Bhado", "script": "ভাদ", "solar_rashi": "Simha"},
            6: {"translit": "Ahin", "script": "আহিন", "solar_rashi": "Kanya"},
            7: {"translit": "Kati", "script": "কাতি", "solar_rashi": "Tula"},
            8: {"translit": "Aghon", "script": "আঘোণ", "solar_rashi": "Vrischika"},
            9: {"translit": "Puh", "script": "পুহ", "solar_rashi": "Dhanu"},
            10: {"translit": "Magh", "script": "মাঘ", "solar_rashi": "Makara"},
            11: {"translit": "Fagun", "script": "ফাগুন", "solar_rashi": "Kumbha"},
            12: {"translit": "Chot", "script": "চ’ত", "solar_rashi": "Meena"},
        },
        "vaara_names": {
            "Monday": "Xombar (সোমবাৰ)", "Tuesday": "Mongolbar (মঙ্গলবাৰ)",
            "Wednesday": "Budhbar (বুধবাৰ)", "Thursday": "Brihospotibar (বৃহস্পতিবাৰ)",
            "Friday": "Xukrobar (শুক্ৰবাৰ)", "Saturday": "Xonibar (শনিবাৰ)",
            "Sunday": "Deobar (দেওবাৰ)",
        },
        "paksha_names": {"Shukla": "Xukla Pokhyo (শুক্ল পক্ষ)", "Krishna": "Krixno Pokhyo (কৃষ্ণ পক্ষ)"},
        "regional_festivals": [
            "Rongali Bihu (Bohag Bihu)", "Kati Bihu (Kongali Bihu)", "Magh Bihu (Bhogali Bihu)",
            "Ambubachi Mela (Kamakhya)", "Me-Dam-Me-Phi"
        ],
        "default_tradition": "Shakta",
    }
}

LOCATION_TO_PROFILE_MAP = {
    "mumbai": "maharashtra", "pune": "maharashtra", "nagpur": "maharashtra",
    "ahmedabad": "gujarat", "surat": "gujarat", "vadodara": "gujarat",
    "varanasi": "north_india", "delhi": "north_india", "lucknow": "north_india",
    "jaipur": "north_india", "patna": "north_india",
    "hyderabad": "andhra_pradesh_telangana", "vijayawada": "andhra_pradesh_telangana",
    "bengaluru": "karnataka", "mysuru": "karnataka",
    "chennai": "tamil_nadu", "madurai": "tamil_nadu",
    "kochi": "kerala", "thiruvananthapuram": "kerala",
    "kolkata": "west_bengal", "bhubaneswar": "odisha", "puri": "odisha",
    "guwahati": "assam",
}

LANGUAGE_TO_PROFILE_MAP = {
    "marathi": "maharashtra", "gujarati": "gujarat", "hindi": "north_india",
    "telugu": "andhra_pradesh_telangana", "kannada": "karnataka", "tamil": "tamil_nadu",
    "malayalam": "kerala", "bengali": "west_bengal", "odia": "odisha", "assamese": "assam",
}


def resolve_regional_profile(
    explicit_profile: Optional[str] = None,
    location_name: Optional[str] = None,
    language_name: Optional[str] = None,
    default_profile: str = "north_india"
) -> Dict[str, Any]:
    if explicit_profile:
        key = explicit_profile.strip().lower().replace(" ", "_").replace("-", "_")
        if key in REGIONAL_PROFILES:
            profile = dict(REGIONAL_PROFILES[key])
            profile["resolution_source"] = "explicit_user_override"
            return profile

    if location_name:
        loc_clean = location_name.strip().lower()
        for loc_key, prof_key in LOCATION_TO_PROFILE_MAP.items():
            if loc_key in loc_clean:
                profile = dict(REGIONAL_PROFILES[prof_key])
                profile["resolution_source"] = f"inferred_from_location:{loc_key}"
                return profile

    if language_name:
        lang_clean = language_name.strip().lower()
        for lang_key, prof_key in LANGUAGE_TO_PROFILE_MAP.items():
            if lang_key in lang_clean:
                profile = dict(REGIONAL_PROFILES[prof_key])
                profile["resolution_source"] = f"inferred_from_language:{lang_key}"
                return profile

    profile = dict(REGIONAL_PROFILES[default_profile])
    profile["resolution_source"] = "system_default"
    return profile


# 3. BRANCH 1: DYNAMIC PANCHANG CALCULATION ENGINE

def is_mumbai_location(lat: float, lon: float) -> bool:
    return 18.89 <= lat <= 19.31 and 72.75 <= lon <= 73.00


class DynamicPanchangEngine:
    """Calculate astronomy and format the requested regional calendar."""

    def __init__(self, calendar_metadata: Optional[dict] = None):
        self.calendar_metadata = calendar_metadata or {}

    def calculate(
        self,
        target_date: date,
        lat: float,
        lon: float,
        tz_offset: float = 5.5,
        elevation_m: float = 0.0,
        regional_profile_id: Optional[str] = None,
        location_name: Optional[str] = None,
        language_name: Optional[str] = None,
        eval_time: Optional[time] = None,
    ) -> Dict[str, Any]:
        profile = resolve_regional_profile(
            explicit_profile=regional_profile_id,
            location_name=location_name,
            language_name=language_name,
        )

        sunrise, sunset, dinamana_hrs = calculate_sunrise_sunset(
            target_date, lat, lon, tz_offset, elevation_m
        )

        next_date = target_date + timedelta(days=1)
        next_sunrise, _, _ = calculate_sunrise_sunset(
            next_date, lat, lon, tz_offset, elevation_m
        )

        moonrise, moonset = calculate_moonrise_moonset(target_date, lat, lon, tz_offset)

        weekday_idx = target_date.weekday()
        vaara_en = VAARA_NAMES_EN[weekday_idx]
        vaara_san = VAARA_NAMES_SAN[weekday_idx]
        vaara_reg = profile.get("vaara_names", {}).get(vaara_en, vaara_san)

        sr_ut_hours = (sunrise.hour + sunrise.minute / 60.0) - tz_offset
        jd_sunrise = julian_day(target_date.year, target_date.month, target_date.day, sr_ut_hours)

        if eval_time:
            ev_ut_hours = (eval_time.hour + eval_time.minute / 60.0) - tz_offset
            jd_eval = julian_day(target_date.year, target_date.month, target_date.day, ev_ut_hours)
        else:
            jd_eval = julian_day(target_date.year, target_date.month, target_date.day, 12.0 - tz_offset)

        udaya_tithi_num, udaya_tithi_name, udaya_paksha, udaya_tithi_frac = get_tithi_at_jd(jd_sunrise)
        _, running_tithi_name, running_paksha, _ = get_tithi_at_jd(jd_eval)

        rem_tithi_hrs = (1.0 - udaya_tithi_frac) * 24.0
        tithi_end_time_h = (sunrise.hour + sunrise.minute / 60.0) + rem_tithi_hrs
        tithi_end_h = int(tithi_end_time_h) % 24
        tithi_end_m = int((tithi_end_time_h - int(tithi_end_time_h)) * 60)
        tithi_end_str = f"{tithi_end_h:02d}:{tithi_end_m:02d}"

        udaya_nak_num, udaya_nak_name, udaya_nak_frac = get_nakshatra_at_jd(jd_sunrise)
        _, running_nak_name, _ = get_nakshatra_at_jd(jd_eval)

        rem_nak_hrs = (1.0 - udaya_nak_frac) * 24.2
        nak_end_time_h = (sunrise.hour + sunrise.minute / 60.0) + rem_nak_hrs
        nak_end_h = int(nak_end_time_h) % 24
        nak_end_m = int((nak_end_time_h - int(nak_end_time_h)) * 60)
        nak_end_str = f"{nak_end_h:02d}:{nak_end_m:02d}"

        yoga_num, yoga_name, _ = get_yoga_at_jd(jd_eval)
        karana_num, karana_name = get_karana_at_jd(jd_eval)
        next_karana_name = karana_name_at_index(karana_num % 60 + 1)

        rashi_num, solar_rashi_san, deg_in_rashi = get_solar_rashi_at_jd(jd_eval)
        sankranti_info = find_sankranti_on_date(target_date, tz_offset)

        amanta_month_idx = (rashi_num % 12) + 1
        month_source = "solar_rashi_estimate"
        chaitra_start = date(target_date.year, 3, 19)
        intervals = self.calendar_metadata.get(f"amanta_months_{target_date.year}") or []
        if intervals and is_mumbai_location(lat, lon):
            civil_month = amanta_month_on(target_date, intervals)
            if civil_month:
                # The civil observance can start later than sunrise on a new-moon day.
                if udaya_tithi_name == "Amavasya":
                    civil_month = amanta_month_on(target_date - timedelta(days=1), intervals) or civil_month
                lookup_key = {"shravan": "shravana", "ashwin": "ashvina", "kartik": "kartika"}.get(civil_month, civil_month)
                amanta_month_idx = LUNAR_MONTHS_SAN.index(lookup_key.capitalize()) + 1
                month_source = "mumbai_civil_calendar"
            chaitra = next((row.get("start") for row in intervals
                            if isinstance(row, dict) and row.get("month_key") == "chaitra"), None)
            if chaitra:
                chaitra_start = date.fromisoformat(chaitra)

        amanta_month_san = LUNAR_MONTHS_SAN[amanta_month_idx - 1]

        if udaya_paksha == "Krishna":
            purnimanta_month_idx = (amanta_month_idx % 12) + 1
        else:
            purnimanta_month_idx = amanta_month_idx
        purnimanta_month_san = LUNAR_MONTHS_SAN[purnimanta_month_idx - 1]

        cal_sys = profile.get("calendar_system", "lunar_amanta")
        g_year = target_date.year

        is_post_chaitra = target_date >= chaitra_start
        is_post_bestu = (target_date >= date(g_year, 11, 10))
        is_post_mesha = (target_date >= date(g_year, 4, 14))
        is_post_chingam = (target_date >= date(g_year, 8, 17))

        shaka_year = (g_year - 78) if is_post_chaitra else (g_year - 79)
        vikram_chaitradi = (g_year + 57) if is_post_chaitra else (g_year + 56)
        vikram_kartikkadi = (g_year + 57) if is_post_bestu else (g_year + 56)
        kollam_year = (g_year - 824) if is_post_chingam else (g_year - 825)
        bangabda_year = (g_year - 593) if is_post_mesha else (g_year - 594)
        thiruvalluvar_year = g_year + 31
        samvatsara_name = get_samvatsara_name(shaka_year)

        regional_months_dict = profile.get("months", {})
        regional_month_name = ""
        regional_month_script = ""
        regional_era_str = ""
        regional_date_str = ""

        if cal_sys == "lunar_purnimanta":
            m_info = regional_months_dict.get(purnimanta_month_idx, {})
            regional_month_name = m_info.get("translit", purnimanta_month_san)
            regional_month_script = m_info.get("script", regional_month_name)
            regional_era_str = f"{vikram_chaitradi} Vikram Samvat"
            paksha_disp = profile.get("paksha_names", {}).get(udaya_paksha, udaya_paksha)
            regional_date_str = f"{regional_month_name} {paksha_disp} {udaya_tithi_name.split()[-1]}, {regional_era_str}"

        elif cal_sys == "lunar_amanta":
            if profile["id"] == "gujarat":
                guj_month_idx = ((amanta_month_idx + 4) % 12) or 12
                m_info = regional_months_dict.get(guj_month_idx, {})
                regional_era_str = f"{vikram_kartikkadi} Vikram Samvat (Kartikadi)"
            else:
                m_info = regional_months_dict.get(amanta_month_idx, {})
                regional_era_str = f"{shaka_year} {profile.get('era_name', 'Shaka Samvat')} ({samvatsara_name} Samvatsara)"

            regional_month_name = m_info.get("translit", amanta_month_san)
            regional_month_script = m_info.get("script", regional_month_name)
            paksha_disp = profile.get("paksha_names", {}).get(udaya_paksha, udaya_paksha)
            regional_date_str = f"{regional_month_name} {paksha_disp} {udaya_tithi_name.split()[-1]}, {regional_era_str}"

        elif cal_sys.startswith("solar_"):
            if profile["id"] == "kerala":
                mal_month_idx = ((rashi_num - 5) % 12) + 1
                m_info = regional_months_dict.get(mal_month_idx, {})
                regional_era_str = f"{kollam_year} Kollavarsham"
            elif profile["id"] == "tamil_nadu":
                m_info = regional_months_dict.get(rashi_num, {})
                regional_era_str = f"{samvatsara_name} Varusham, {thiruvalluvar_year} Thiruvalluvar Aandu"
            elif profile["id"] == "west_bengal":
                m_info = regional_months_dict.get(rashi_num, {})
                regional_era_str = f"{bangabda_year} Bangabda"
            elif profile["id"] == "assam":
                m_info = regional_months_dict.get(rashi_num, {})
                regional_era_str = f"{bangabda_year} Bhaskaravda"
            else:
                m_info = regional_months_dict.get(rashi_num, {})
                regional_era_str = f"{shaka_year} Shaka Era"

            regional_month_name = m_info.get("translit", solar_rashi_san)
            regional_month_script = m_info.get("script", regional_month_name)
            solar_day_num = int(deg_in_rashi) + 1
            regional_date_str = f"{solar_day_num} {regional_month_name} ({regional_month_script}), {regional_era_str}"

        muhurats = calculate_muhurats(
            target_date=target_date,
            sunrise=sunrise,
            sunset=sunset,
            next_sunrise=next_sunrise,
        )

        return {
            "source": "Dynamic Vedic Ephemeris Engine (Meeus/Lahiri)",
            "calculation_methodology": "Drik Siddhanta (Astronomical Sidereal)",
            "date": target_date.isoformat(),
            "evaluated_at": (eval_time or time(12)).strftime("%H:%M"),
            "vaara": {
                "english": vaara_en,
                "sanskrit": vaara_san,
                "regional": vaara_reg,
            },
            "tithi": {
                "udaya_tithi": udaya_tithi_name,
                "running_tithi": running_tithi_name,
                "running_paksha": running_paksha,
                "tithi_number": udaya_tithi_num,
                "paksha": udaya_paksha,
                "paksha_regional": profile.get("paksha_names", {}).get(udaya_paksha, udaya_paksha),
                "fraction_elapsed": round(udaya_tithi_frac, 3),
                "approx_end_time": tithi_end_str,
            },
            "nakshatra": {
                "udaya_nakshatra": udaya_nak_name,
                "running_nakshatra": running_nak_name,
                "nakshatra_number": udaya_nak_num,
                "fraction_elapsed": round(udaya_nak_frac, 3),
                "approx_end_time": nak_end_str,
            },
            "yoga": {"yoga_name": yoga_name, "yoga_number": yoga_num},
            "karana": {"current_karana": karana_name, "karana_number": karana_num, "next_karana": next_karana_name},
            "solar_position": {
                "rashi_sanskrit": solar_rashi_san,
                "rashi_number": rashi_num,
                "degree_in_rashi": round(deg_in_rashi, 2),
                "sankranti_today": sankranti_info,
            },
            "lunar_month": {
                "amanta": amanta_month_san, "purnimanta": purnimanta_month_san,
                "is_adhika_masa": False, "source": month_source,
            },
            "regional_calendar": {
                "profile_id": profile["id"],
                "profile_display": profile["display_name"],
                "calendar_system": cal_sys,
                "regional_month": regional_month_name,
                "regional_month_script": regional_month_script,
                "regional_era": regional_era_str,
                "regional_date_string": regional_date_str,
                "samvatsara_name": samvatsara_name,
                "eras": {
                    "shaka_samvat": shaka_year,
                    "vikram_chaitradi": vikram_chaitradi,
                    "vikram_kartikkadi": vikram_kartikkadi,
                    "kollam_era": kollam_year,
                    "bangabda": bangabda_year,
                    "thiruvalluvar_aandu": thiruvalluvar_year,
                }
            },
            "sun_moon_timings": {
                "sunrise": sunrise.strftime("%H:%M"),
                "sunset": sunset.strftime("%H:%M"),
                "moonrise": moonrise.strftime("%H:%M") if moonrise else "No Moonrise",
                "moonset": moonset.strftime("%H:%M") if moonset else "No Moonset",
                "dinamana_hours": round(dinamana_hrs, 2),
            },
            "muhurats": muhurats,
        }


# 4. ASTRONOMICAL FESTIVAL RULE EVALUATOR

class FestivalRuleEvaluator:
    @staticmethod
    def evaluate_festival_rules(
        target_date: date,
        panchang: Dict[str, Any],
        tradition: str = "Smartha",
        regional_profile_id: str = "north_india"
    ) -> List[Dict[str, Any]]:
        calculated_events = []
        tithi_info = panchang.get("tithi", {})
        udaya_tithi = tithi_info.get("udaya_tithi", "")
        running_tithi = tithi_info.get("running_tithi", udaya_tithi)
        paksha = tithi_info.get("paksha", "")
        lunar_m = panchang.get("lunar_month", {})
        amanta_m = lunar_m.get("amanta", "")
        purnimanta_m = lunar_m.get("purnimanta", "")
        nakshatra_info = panchang.get("nakshatra", {})
        nakshatra_name = nakshatra_info.get("udaya_nakshatra", "")
        solar_info = panchang.get("solar_position", {})
        sankranti = solar_info.get("sankranti_today")

        def tithi_matches(target_name: str) -> bool:
            return (target_name in udaya_tithi) or (target_name in running_tithi)

        # 1. Makar Sankranti
        if (sankranti and sankranti.get("rashi_name") == "Makara") or (target_date.month == 1 and target_date.day == 14):
            calculated_events.append({
                "rule_name": "Makar Sankranti",
                "festival_name": "Makar Sankranti / Pongal",
                "tradition": "Universal",
                "astronomical_trigger": "Sun ingress into sidereal Makara Rashi",
                "notes": "Marks Uttarayana, the northward journey of the Sun."
            })

        # 2. Mesha Sankranti / Solar New Years
        if (sankranti and sankranti.get("rashi_name") == "Mesha") or (target_date.month == 4 and target_date.day in (14, 15)):
            calculated_events.append({
                "rule_name": "Solar New Year",
                "festival_name": "Baisakhi / Solar New Year",
                "tradition": "Solar",
                "astronomical_trigger": "Mesha Sankranti (Sun ingress into Aries)",
                "notes": "Commences regional solar years across TN, Kerala, Bengal, Odisha, and Assam."
            })

        # 3. Chaitra Navratri / Gudi Padwa / Ugadi
        if amanta_m == "Chaitra" and tithi_matches("Shukla Pratipada"):
            calculated_events.append({
                "rule_name": "Chaitra Shukla Pratipada",
                "festival_name": "Chaitra Navratri Begins (Ugadi / Gudi Padwa)",
                "tradition": "Universal Luni-Solar",
                "astronomical_trigger": "Shukla Pratipada of Chaitra",
                "notes": "Vedic New Year in Maharashtra (Gudi Padwa), Karnataka/AP/Telangana (Ugadi)."
            })

        # 4. Rama Navami
        if amanta_m == "Chaitra" and tithi_matches("Shukla Navami"):
            calculated_events.append({
                "rule_name": "Rama Navami",
                "festival_name": "Rama Navami",
                "tradition": "Universal",
                "astronomical_trigger": "Chaitra Shukla Navami with Madhyahna observance",
                "notes": "Celebration of Lord Rama's birth during Madhyahna."
            })

        # 5. Akshaya Tritiya
        if amanta_m == "Vaishakha" and tithi_matches("Shukla Tritiya"):
            calculated_events.append({
                "rule_name": "Akshaya Tritiya",
                "festival_name": "Akshaya Tritiya",
                "tradition": "Universal",
                "astronomical_trigger": "Vaishakha Shukla Tritiya at sunrise",
                "notes": "Auspicious day of eternal wealth and spiritual merit."
            })

        # 6. Maha Shivratri
        if (purnimanta_m == "Phalguna" or amanta_m == "Magha") and tithi_matches("Krishna Chaturdashi"):
            calculated_events.append({
                "rule_name": "Maha Shivratri",
                "festival_name": "Maha Shivratri",
                "tradition": "Shaiva / Smartha",
                "astronomical_trigger": "Krishna Chaturdashi spanning Nishita Kaal (midnight)",
                "notes": "Great Night of Lord Shiva with all-night vigil (Jagaran)."
            })

        # 7. Holika Dahan & Holi
        if (purnimanta_m == "Phalguna" or amanta_m == "Phalguna") and tithi_matches("Purnima"):
            calculated_events.append({
                "rule_name": "Holika Dahan",
                "festival_name": "Holika Dahan / Chhoti Holi",
                "tradition": "Universal",
                "astronomical_trigger": "Phalguna Purnima prevailing at Pradosha",
                "notes": "Sacred bonfire dispelling negative forces."
            })
        if (purnimanta_m == "Chaitra" or amanta_m == "Phalguna") and tithi_matches("Krishna Pratipada") and target_date.month in (3, 4):
            calculated_events.append({
                "rule_name": "Holi Dhulandi",
                "festival_name": "Holi (Dhulandi)",
                "tradition": "Universal",
                "astronomical_trigger": "Krishna Pratipada immediately following Phalguna Purnima",
                "notes": "Grand festival of colors, joy, and unity."
            })

        # 8. Krishna Janmashtami
        if (purnimanta_m == "Bhadrapada" or amanta_m == "Shravana") and tithi_matches("Krishna Ashtami"):
            is_vaishnava = (tradition.lower() == "vaishnava")
            calculated_events.append({
                "rule_name": "Krishna Janmashtami",
                "festival_name": "Krishna Janmashtami",
                "tradition": "Vaishnava" if is_vaishnava else "Smartha",
                "astronomical_trigger": "Bhadrapada Krishna Ashtami with Nishita Kaal",
                "notes": "Midnight celebration of Lord Krishna's divine birth."
            })

        # 9. Ganesh Chaturthi
        if amanta_m == "Bhadrapada" and tithi_matches("Shukla Chaturthi"):
            calculated_events.append({
                "rule_name": "Ganesh Chaturthi",
                "festival_name": "Ganesh Chaturthi (Vinayaka Chavithi)",
                "tradition": "Universal",
                "astronomical_trigger": "Bhadrapada Shukla Chaturthi spanning Madhyahna",
                "notes": "10-day grand festival of Lord Ganesha culminating in Anant Chaturdashi."
            })

        # 10. Sharad Navratri to Dussehra
        if amanta_m == "Ashvina" and tithi_matches("Shukla Pratipada"):
            calculated_events.append({
                "rule_name": "Sharad Navratri Begins",
                "festival_name": "Sharad Navratri Begins (Ghatasthapana)",
                "tradition": "Shakta / Universal",
                "astronomical_trigger": "Ashwin Shukla Pratipada at sunrise",
                "notes": "Nine nights dedicated to Goddess Durga."
            })
        if amanta_m == "Ashvina" and tithi_matches("Shukla Ashtami"):
            calculated_events.append({
                "rule_name": "Maha Ashtami",
                "festival_name": "Maha Ashtami (Durga Ashtami)",
                "tradition": "Shakta",
                "astronomical_trigger": "Ashwin Shukla Ashtami with Sandhi Puja transition",
                "notes": "Peak day of Durga Puja and Kumari Puja."
            })
        if amanta_m == "Ashvina" and tithi_matches("Shukla Dashami"):
            calculated_events.append({
                "rule_name": "Vijayadashami",
                "festival_name": "Dussehra (Vijayadashami)",
                "tradition": "Universal",
                "astronomical_trigger": "Ashwin Shukla Dashami (Aparahna Kaal)",
                "notes": "Victory of Rama over Ravana and Durga over Mahishasura."
            })

        # 11. Karwa Chauth
        if (purnimanta_m == "Kartika" or amanta_m == "Ashvina") and tithi_matches("Krishna Chaturthi"):
            calculated_events.append({
                "rule_name": "Karwa Chauth",
                "festival_name": "Karwa Chauth",
                "tradition": "North India Regional Vrat",
                "astronomical_trigger": "Krishna Chaturthi with Moonrise sighting",
                "notes": "Maternal and spousal fast broken upon sighting the Moon."
            })

        # 12. Diwali
        if amanta_m in ("Ashvina", "Kartika"):
            if tithi_matches("Krishna Trayodashi"):
                calculated_events.append({
                    "rule_name": "Dhanteras",
                    "festival_name": "Dhanteras (Dhantrayodashi)",
                    "tradition": "Universal",
                    "astronomical_trigger": "Kartik Krishna Trayodashi at Pradosha",
                    "notes": "Advent of Lord Dhanvantari and welcoming Goddess Lakshmi."
                })
            elif tithi_matches("Krishna Chaturdashi"):
                calculated_events.append({
                    "rule_name": "Narak Chaturdashi",
                    "festival_name": "Narak Chaturdashi (Choti Diwali)",
                    "tradition": "Universal",
                    "astronomical_trigger": "Kartik Krishna Chaturdashi with dawn snan",
                    "notes": "Vanquishing of demon Narakasura by Lord Krishna."
                })
            elif tithi_matches("Amavasya"):
                calculated_events.append({
                    "rule_name": "Diwali Lakshmi Puja",
                    "festival_name": "Diwali (Deepawali / Lakshmi Puja)",
                    "tradition": "Universal",
                    "astronomical_trigger": "Kartik Amavasya prevailing at Pradosha Kaal",
                    "notes": "Festival of Lights and grand Lakshmi-Ganesha Puja."
                })

        # 13. Govardhan Puja & Bhai Dooj
        if amanta_m == "Kartika" and tithi_matches("Shukla Pratipada"):
            calculated_events.append({
                "rule_name": "Govardhan Puja",
                "festival_name": "Govardhan Puja (Annakut)",
                "tradition": "Universal / Gujarat Bestu Varas",
                "astronomical_trigger": "Kartik Shukla Pratipada at sunrise",
                "notes": "Gujarati New Year (Bestu Varas) and Annakut mountain offering."
            })
        if amanta_m == "Kartika" and tithi_matches("Shukla Dwitiya"):
            calculated_events.append({
                "rule_name": "Bhai Dooj",
                "festival_name": "Bhai Dooj (Yama Dwitiya)",
                "tradition": "Universal",
                "astronomical_trigger": "Kartik Shukla Dwitiya (Aparahna Kaal)",
                "notes": "Celebration of sibling bond between brothers and sisters."
            })

        # 14. Chhath Puja
        if amanta_m == "Kartika" and tithi_matches("Shukla Shashti"):
            calculated_events.append({
                "rule_name": "Chhath Sandhya Arghya",
                "festival_name": "Chhath Puja (Surya Shashthi Sandhya Arghya)",
                "tradition": "North India / Bihar / UP",
                "astronomical_trigger": "Kartik Shukla Shashthi with Sunset Arghya to Surya Dev",
                "notes": "Ancient Vedic sun worship standing in holy waters."
            })
        if amanta_m == "Kartika" and tithi_matches("Shukla Saptami"):
            calculated_events.append({
                "rule_name": "Chhath Usha Arghya",
                "festival_name": "Chhath Puja (Usha Arghya)",
                "tradition": "North India / Bihar / UP",
                "astronomical_trigger": "Kartik Shukla Saptami with Sunrise Arghya",
                "notes": "Dawn conclusion of the 36-hour Chhath fast."
            })

        # 15. Ekadashi Vrats
        if "Ekadashi" in udaya_tithi:
            calculated_events.append({
                "rule_name": f"{amanta_m} {paksha} Ekadashi",
                "festival_name": f"{amanta_m} {paksha} Ekadashi",
                "tradition": tradition,
                "astronomical_trigger": f"Udaya Ekadashi in {amanta_m} {paksha} Paksha",
                "notes": "Sacred day of fasting and meditation dedicated to Lord Vishnu."
            })

        return calculated_events

    @staticmethod
    def compare_and_flag_discrepancies(
        static_entry: Optional[Dict[str, Any]],
        calculated_events: List[Dict[str, Any]],
        target_date: date,
        regional_profile_id: str
    ) -> Dict[str, Any]:
        static_fest_name = static_entry.get("festival_name") if static_entry else None
        calc_fest_names = [e["festival_name"] for e in calculated_events]

        if not static_fest_name and not calculated_events:
            return {
                "has_discrepancy": False,
                "status": "NO_FESTIVAL",
                "documentation": "Ordinary day with no major static or calculated festival observance."
            }

        match_found = False
        if static_fest_name:
            norm_s = static_fest_name.lower()
            for c_name in calc_fest_names:
                norm_c = c_name.lower()
                s_words = set(w for w in norm_s.replace("/", " ").replace("(", " ").replace(")", " ").split() if len(w) > 3)
                c_words = set(w for w in norm_c.replace("/", " ").replace("(", " ").replace(")", " ").split() if len(w) > 3)
                if s_words.intersection(c_words):
                    match_found = True
                    break

        if match_found or (static_fest_name and not calculated_events):
            return {
                "has_discrepancy": False,
                "status": "CONCORDANT",
                "source_static_json": static_entry.get("source", "Shastra-Samvat Local Panchang") if static_entry else None,
                "source_calculated_rule": "Dynamic Vedic Ephemeris (Drik Siddhanta)",
                "static_festival": static_fest_name,
                "calculated_festivals": calc_fest_names,
                "documentation": "Static reference dataset and calculated astronomical rules are concordant."
            }

        return {
            "has_discrepancy": True,
            "status": "VARIATION_DETECTED",
            "source_static_json": static_entry.get("source", "Shastra-Samvat Local Panchang") if static_entry else "Not recorded in static dataset",
            "source_calculated_rule": "Dynamic Vedic Ephemeris (Drik Siddhanta)",
            "static_festival": static_fest_name,
            "calculated_festivals": calc_fest_names,
            "regional_profile": regional_profile_id,
            "documentation": (
                f"On {target_date.strftime('%Y-%m-%d')}, static reference records: '{static_fest_name or 'None'}' "
                f"while astronomical calculation indicates: {', '.join(calc_fest_names) or 'None'}. "
                "Both records are preserved. In Hindu calendar traditions, observance dates may shift by 1 day "
                "depending on Udaya Tithi vs Nishita/Pradosha Kaal or Smartha vs Vaishnava parampara."
            )
        }


# 5. BRANCH 2: PRESERVED FESTIVAL AND REGIONAL OBSERVANCE PROCESSOR

CAT_GREGORIAN_FIXED = "GREGORIAN_FIXED"
CAT_ISLAMIC_LUNAR = "ISLAMIC_LUNAR"
CAT_SOLAR_TRANSIT = "SOLAR_TRANSIT"
CAT_HINDU_LUNAR = "HINDU_LUNAR"
CAT_REGIONAL_OBSERVANCE = "REGIONAL_OBSERVANCE"


class FestivalProcessor:
    """
    Branch 2: Preserved Festival and Regional Observance Processor.
    Loads and operates on panchang_2026.json while respecting regional filters.
    """

    def __init__(self, json_path: Path = PANCHANG_PATH):
        self.json_path = json_path
        self._raw_data: Dict[str, Any] = {}
        self._festival_aliases: Dict[str, str] = {}
        self._date_index: Dict[str, Dict[str, Any]] = {}
        self._load_reference_json()

    def _load_reference_json(self) -> None:
        if not self.json_path.exists():
            return
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                self._raw_data = json.load(f)
            self._festival_aliases = self._raw_data.get("_festival_aliases", {})
            for k, v in self._raw_data.items():
                if not k.startswith("_"):
                    self._date_index[k] = v
        except Exception:
            pass

    @property
    def total_dates(self) -> int:
        return len(self._date_index)

    @property
    def total_festivals(self) -> int:
        return sum(1 for v in self._date_index.values() if v.get("festival_name"))

    def get_aliases(self) -> Dict[str, str]:
        return dict(self._festival_aliases)

    def classify_festival(self, festival_name: Optional[str]) -> str:
        if not festival_name:
            return "NONE"
        name_lower = festival_name.lower()

        gregorian_keywords = [
            "new year", "republic day", "valentine", "women", "good friday",
            "easter", "earth day", "workers", "may day", "mother", "environment",
            "father", "yoga day", "independence day", "teachers", "gandhi jayanti",
            "halloween", "children", "christmas"
        ]
        if any(kw in name_lower for kw in gregorian_keywords):
            return CAT_GREGORIAN_FIXED

        islamic_keywords = ["shab-e-barat", "eid", "bakrid", "muharram", "mawlid", "milad"]
        if any(kw in name_lower for kw in islamic_keywords):
            return CAT_ISLAMIC_LUNAR

        solar_keywords = ["sankranti", "pongal", "baisakhi", "solar new year"]
        if any(kw in name_lower for kw in solar_keywords):
            return CAT_SOLAR_TRANSIT

        regional_keywords = [
            "gudi padwa", "ugadi", "chath", "chhath", "karwa chauth", "ahoi",
            "vat purnima", "vat savitri", "bonalu", "bathukamma", "bihu", "onam",
            "vishu", "durga puja", "rath yatra"
        ]
        if any(kw in name_lower for kw in regional_keywords):
            return CAT_REGIONAL_OBSERVANCE

        return CAT_HINDU_LUNAR

    def get_regional_affinity(self, festival_name: Optional[str]) -> List[str]:
        if not festival_name:
            return ["all"]
        name_lower = festival_name.lower()
        affinities = []

        if "gudi padwa" in name_lower or "ganesh" in name_lower or "vat purnima" in name_lower:
            affinities.append("maharashtra")
        if "ugadi" in name_lower:
            affinities.extend(["andhra_pradesh_telangana", "karnataka"])
        if "pongal" in name_lower or "puthandu" in name_lower:
            affinities.append("tamil_nadu")
        if "vishu" in name_lower or "onam" in name_lower:
            affinities.append("kerala")
        if "durga" in name_lower or "kali puja" in name_lower or "pohela" in name_lower:
            affinities.append("west_bengal")
        if "chhath" in name_lower or "karwa chauth" in name_lower or "ahoi" in name_lower:
            affinities.append("north_india")
        if "bestu varas" in name_lower or "navratri" in name_lower or "uttarayan" in name_lower:
            affinities.append("gujarat")
        if "rath yatra" in name_lower or "pana sankranti" in name_lower:
            affinities.append("odisha")
        if "bihu" in name_lower:
            affinities.append("assam")

        if not affinities or any(w in name_lower for w in ["diwali", "holi", "shivratri", "janmashtami", "ram navami", "republic", "independence"]):
            affinities.append("pan_indian")
        return affinities

    def process_date(
        self,
        target_date: date,
        regional_profile_id: str = "north_india",
        tradition: str = "Smartha",
        panchang_results: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        date_str = target_date.strftime("%Y-%m-%d")
        static_entry = self._date_index.get(date_str)
        preserved_static_data = dict(static_entry) if static_entry else None

        fest_name = static_entry.get("festival_name") if static_entry else None
        all_events = static_entry.get("all_events", []) if static_entry else []
        context_str = static_entry.get("context", "") if static_entry else ""
        summary_str = static_entry.get("summary", "") if static_entry else ""

        classification = self.classify_festival(fest_name)
        regional_affinities = self.get_regional_affinity(fest_name)
        is_regionally_relevant = (
            "pan_indian" in regional_affinities
            or regional_profile_id in regional_affinities
            or "all" in regional_affinities
        )

        result: Dict[str, Any] = {
            "target_date": date_str,
            "has_static_record": (static_entry is not None),
            "preserved_static_record": preserved_static_data,
            "festival_name": fest_name,
            "all_events": all_events,
            "context": context_str,
            "summary": summary_str,
            "classification": classification,
            "regional_affinities": regional_affinities,
            "is_regionally_relevant": is_regionally_relevant,
            "tradition_evaluated": tradition,
        }

        if panchang_results is not None:
            calc_events = FestivalRuleEvaluator.evaluate_festival_rules(
                target_date=target_date,
                panchang=panchang_results,
                tradition=tradition,
                regional_profile_id=regional_profile_id,
            )
            discrepancy_report = FestivalRuleEvaluator.compare_and_flag_discrepancies(
                static_entry=static_entry,
                calculated_events=calc_events,
                target_date=target_date,
                regional_profile_id=regional_profile_id,
            )
            result["calculated_astronomical_festivals"] = calc_events
            result["discrepancy_report"] = discrepancy_report
        else:
            result["calculated_astronomical_festivals"] = []
            result["discrepancy_report"] = {
                "has_discrepancy": False,
                "status": "ASTRONOMICAL_EVALUATION_SKIPPED",
                "documentation": "Panchang results not supplied; static reference preserved directly."
            }

        return result


# 6. NON-DESTRUCTIVE MERGER & VALIDATION

class PanchangMerger:
    @staticmethod
    def merge(
        panchang_data: Dict[str, Any],
        festival_data: Dict[str, Any],
        profile: Dict[str, Any],
        tradition: str = "Smartha",
        language: str = "English"
    ) -> Dict[str, Any]:
        target_date = panchang_data.get("date", "")
        static_record = festival_data.get("preserved_static_record") or {}

        vrats = []
        udaya_tithi = panchang_data.get("tithi", {}).get("udaya_tithi", "")
        paksha = panchang_data.get("tithi", {}).get("paksha", "")

        if "Ekadashi" in udaya_tithi:
            vrats.append(f"{udaya_tithi} Vrat ({tradition})")
        if "Trayodashi" in udaya_tithi:
            vrats.append(f"Pradosha Vrat ({paksha} Paksha)")
        if "Purnima" in udaya_tithi:
            vrats.append("Purnima Vrat & Satyanarayan Puja")
        if "Amavasya" in udaya_tithi:
            vrats.append("Amavasya Pitru Tarpan")
        if "Chaturthi" in udaya_tithi and paksha == "Krishna":
            vrats.append("Sankashti Chaturthi Vrat (Moonrise worship)")

        profile_festivals = profile.get("regional_festivals", [])
        for rf in profile_festivals:
            if "vrat" in rf.lower() or "habba" in rf.lower():
                if rf in str(festival_data.get("festival_name", "")) or any(rf in str(c.get("festival_name", "")) for c in festival_data.get("calculated_astronomical_festivals", [])):
                    vrats.append(rf)

        original_context = festival_data.get("context", "")
        reg_cal = panchang_data.get("regional_calendar", {})
        reg_date_str = reg_cal.get("regional_date_string", "")

        fest_name = festival_data.get("festival_name")
        vaara_name = panchang_data.get("vaara", {}).get("regional") or panchang_data.get("vaara", {}).get("english")
        sunrise_str = panchang_data.get("sun_moon_timings", {}).get("sunrise", "")

        observance_part = f" — Observance: {fest_name}" if fest_name else ""
        combined_summary = (
            f"Auspicious {udaya_tithi} ({vaara_name}) [{reg_date_str}]"
            f"{observance_part} — Sunrise at {sunrise_str}"
        )

        return {
            "source": "Vibzee Dual-Engine Parallel Panchang System",
            "date": target_date,
            "regional_profile": {
                "id": profile.get("id"),
                "display_name": profile.get("display_name"),
                "calendar_system": profile.get("calendar_system"),
                "state": profile.get("state"),
                "primary_era": profile.get("primary_era"),
                "language_name": profile.get("language_name"),
                "language_code": profile.get("language_code"),
                "requested_language": language,
                "tradition": tradition,
                "resolution_source": profile.get("resolution_source", "inferred"),
            },
            "astronomical_panchang": panchang_data,
            "preserved_static_festival_data": {
                "original_source": static_record.get("source", "panchang_2026.json"),
                "festival_name": static_record.get("festival_name"),
                "all_events": static_record.get("all_events"),
                "original_summary": static_record.get("summary"),
                "original_context": static_record.get("context"),
                "raw_day_record": static_record,
            },
            "festival_intelligence": {
                "active_festival": fest_name,
                "all_events": festival_data.get("all_events", []),
                "classification": festival_data.get("classification"),
                "regional_affinities": festival_data.get("regional_affinities", []),
                "is_regionally_relevant": festival_data.get("is_regionally_relevant", True),
                "calculated_astronomical_festivals": festival_data.get("calculated_astronomical_festivals", []),
                "discrepancy_report": festival_data.get("discrepancy_report", {}),
            },
            "vrats_and_observances": list(set(vrats)),
            "summary": combined_summary,
            "context": original_context,
        }


# 7. COORDINATOR & CONVENIENCE API

class PanchangCoordinator:
    """Combine astronomy, festival evidence and local devotional context."""

    def __init__(self):
        self.daily_resolver = DailyResolver()
        self.engine = DynamicPanchangEngine(self.daily_resolver.deities.get("meta"))
        self.festival_processor = FestivalProcessor()
        self.merger = PanchangMerger()

    async def calculate_panchang_async(
        self,
        target_date: date,
        lat: float = 19.0760,
        lon: float = 72.8777,
        location_name: Optional[str] = None,
        regional_profile_id: Optional[str] = None,
        language: str = "English",
        tradition: str = "Smartha",
        eval_time: Optional[time] = None,
        elevation_m: float = 0.0,
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self.calculate_panchang, target_date, lat, lon, location_name,
            regional_profile_id, language, tradition, eval_time, elevation_m,
        )

    def calculate_panchang(
        self,
        target_date: date,
        lat: float = 19.0760,
        lon: float = 72.8777,
        location_name: Optional[str] = None,
        regional_profile_id: Optional[str] = None,
        language: str = "English",
        tradition: str = "Smartha",
        eval_time: Optional[time] = None,
        elevation_m: float = 0.0,
    ) -> Dict[str, Any]:
        in_mumbai = is_mumbai_location(lat, lon)
        if in_mumbai and not location_name:
            location_name = "Mumbai"
        profile = resolve_regional_profile(
            explicit_profile=regional_profile_id,
            location_name=location_name,
            language_name=language,
        )
        panchang = self.engine.calculate(
            target_date, lat, lon, elevation_m=elevation_m,
            regional_profile_id=profile["id"], location_name=location_name,
            language_name=language, eval_time=eval_time,
        )
        festivals = self.festival_processor.process_date(
            target_date, profile["id"], tradition, panchang_results=panchang,
        )
        result = self.merger.merge(panchang, festivals, profile, tradition, language)
        if in_mumbai:
            devotion = self.daily_resolver.resolve(target_date, result)
            result["devotion"] = devotion
            primary = devotion["primary"]
            if primary["type"] not in ("weekday", "month", "tithi"):
                result["festival_intelligence"]["resolved_observance"] = {
                    "name": primary["theme"],
                    "source": primary["source"],
                    "date_status": primary.get("date_status"),
                }
        return result

    def get_festival_string(
        self,
        target_date: date,
        lat: float = 19.0760,
        lon: float = 72.8777,
        location_name: Optional[str] = None,
        regional_profile_id: Optional[str] = None,
        language: str = "English",
        tradition: str = "Smartha",
    ) -> Optional[str]:
        res = self.calculate_panchang(
            target_date=target_date,
            lat=lat,
            lon=lon,
            location_name=location_name,
            regional_profile_id=regional_profile_id,
            language=language,
            tradition=tradition,
        )

        intelligence = res["festival_intelligence"]
        fest = (intelligence.get("resolved_observance") or {}).get("name") or intelligence["active_festival"]
        tithi_dict = res["astronomical_panchang"]["tithi"]
        udaya_tithi = tithi_dict.get("udaya_tithi")
        paksha = tithi_dict.get("paksha")

        tithi_info = f"{udaya_tithi} ({paksha} Paksha)" if udaya_tithi and paksha else (udaya_tithi or "")

        if fest and tithi_info:
            return f"{fest} [{tithi_info}]"
        if fest:
            return fest
        if tithi_info:
            return tithi_info
        return None


# Global singleton instance
_GLOBAL_COORDINATOR: Optional[PanchangCoordinator] = None


def get_coordinator() -> PanchangCoordinator:
    global _GLOBAL_COORDINATOR
    if _GLOBAL_COORDINATOR is None:
        _GLOBAL_COORDINATOR = PanchangCoordinator()
    return _GLOBAL_COORDINATOR


def calculate_panchang(*args, **kwargs) -> Dict[str, Any]:
    return get_coordinator().calculate_panchang(*args, **kwargs)


async def calculate_panchang_async(*args, **kwargs) -> Dict[str, Any]:
    return await get_coordinator().calculate_panchang_async(*args, **kwargs)


def get_festival_string(*args, **kwargs) -> Optional[str]:
    return get_coordinator().get_festival_string(*args, **kwargs)
