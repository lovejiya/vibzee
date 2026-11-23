"""
sources.py — All external data gathering.

Weather, NLP, translation, knowledge-graph queries, Wikipedia extraction.
Nothing hardcoded about the world — everything discovered at runtime.

Design note (graceful degradation):
  The plan loads Stanza / pyiwn / IndicTrans2 at import. Those are heavy (~1GB)
  and may not be installed in every environment. Here they are LAZY-loaded, and
  every chain and NLP utility degrades gracefully if a model or API is missing —
  consistent with the plan's "skip on failure" philosophy (edge cases 1, 2, 10).
  Install the models (see README) to enable the full Hindi NLP path.
"""
import json
import re
import time
from pathlib import Path

import requests

from specs import (
    LOCATIONS, SPARQL_TEMPLATES, EMOTION_SEEDS,
    EMOTION_CONCEPTS, THEME_HINTS, ENGLISH_STOPWORDS, NONVISUAL_TOKENS,
    THEME_MYTHOLOGY_KEYWORDS, FESTIVAL_MYTHOLOGY_KEYWORDS, THEME_TO_EPIC,
    PreparedCandidate, QuoteAnalysis, Context, CandidatePool,
    PANCHANG_PATH, CULTURAL_METAPHORS_PATH, LANDMARK_DB_PATH, RECENT_RUNS_PATH,
    OPEN_METEO_URL, WIKIDATA_SPARQL_URL, DBPEDIA_SPARQL_URL,
    WIKIPEDIA_SUMMARY_URL, WIKIPEDIA_API_URL,
    HTTP_USER_AGENT, CACHE_DIR,
    LANDMARK_ADJACENT_TIMES, LANDMARK_ENERGY_PREFERENCE, LANDMARK_ENERGY_LEVELS,
    LANDMARK_TYPE_AFFINITY, THEME_TO_LANDMARK_CATEGORY, EMOTION_TO_LANDMARK_CATEGORY,
    APP_TIME_TO_LANDMARK_TIME,
)


_EXPANDED_EMOTION_SEEDS: dict = {}
_PANCHANG_DATA = None
_LANDMARK_DB = None


# LANDMARK SELECTION ENGINE

def _load_landmark_db() -> dict:
    global _LANDMARK_DB
    if _LANDMARK_DB is None:
        _LANDMARK_DB = json.loads(LANDMARK_DB_PATH.read_text(encoding="utf-8"))
    return _LANDMARK_DB


# Locate city and its landmarks in the database
def _find_city_in_db(location: dict) -> tuple[str, str, list] | None:
    db = _load_landmark_db()
    loc_name = (location.get("name") or "").lower().strip()
    state_hint = (location.get("state") or "").lower().strip()

    loc_key = ""
    for k, v in LOCATIONS.items():
        if v.get("name", "").lower() == loc_name:
            loc_key = k.lower()
            break

    # Direct match by state hint
    if state_hint and state_hint in db:
        for city_key, landmarks in db[state_hint].items():
            city_clean = city_key.lower().replace("_", " ")
            if city_key.lower() in (loc_name, loc_key) or city_clean == loc_name:
                return state_hint, city_key, landmarks

    # Search all states
    for state, cities in db.items():
        for city_key, landmarks in cities.items():
            city_clean = city_key.lower().replace("_", " ")
            if city_key.lower() in (loc_name, loc_key) or city_clean == loc_name or loc_name in city_clean or city_clean in loc_name:
                return state, city_key, landmarks

    return None


# Determine expected vs unexpected track based on recent run history
def _pick_track(recent_runs: list, quote_category: str) -> tuple[str, float]:
    import random as _rnd
    same_cat = [r for r in recent_runs if r.get("quote_category") == quote_category]
    last_3 = same_cat[-3:]

    base = 0.30
    if len(last_3) >= 3 and all(r.get("track") == "expected" for r in last_3):
        base = 0.60
    elif last_3 and last_3[-1].get("track") == "unexpected":
        base = 0.15

    track = "unexpected" if _rnd.random() < base else "expected"
    return track, base


# Score an individual landmark based on affinity, timing, and energy
def _score_landmark(landmark: dict, quote_category: str, time_of_day: str,
                    situation_keywords: list, times_used: int, track: str) -> float:
    score = 0.0
    aff_dict = landmark.get(f"{track}_affinity", landmark.get("expected_affinity", {}))
    score += aff_dict.get(quote_category, 0.2) * 40

    best = landmark.get("best_time", [])
    if time_of_day in best:
        score += 20
    elif any(t in best for t in LANDMARK_ADJACENT_TIMES.get(time_of_day, [])):
        score += 10
    elif not best:
        score += 5
    else:
        score += 2

    if situation_keywords:
        overlap = set(k.lower() for k in situation_keywords) & set(
            k.lower() for k in landmark.get("setting_keywords", []))
        score += min(len(overlap) * 6, 15)

    type_scores = LANDMARK_TYPE_AFFINITY.get(quote_category, {})
    score += type_scores.get(landmark.get("type", ""), 2)

    pref = LANDMARK_ENERGY_PREFERENCE.get(quote_category, "medium")
    actual = landmark.get("energy", "medium")
    if track == "unexpected":
        score += 8 if actual != pref else 3
    else:
        pref_idx = LANDMARK_ENERGY_LEVELS.index(pref) if pref in LANDMARK_ENERGY_LEVELS else 1
        actual_idx = LANDMARK_ENERGY_LEVELS.index(actual) if actual in LANDMARK_ENERGY_LEVELS else 1
        score += [10, 5, 1][abs(actual_idx - pref_idx)]

    score -= times_used * 12
    return round(score, 2)


# Pick best landmark for location and quote category
def select_landmark(location: dict, theme: str, emotion: str, time_of_day: str,
                    situation_keywords: list = None) -> dict | None:
    """Pick the best landmark for a quote from the curated DB. Returns None if city not in DB."""
    import random as _rnd
    from datetime import datetime

    result = _find_city_in_db(location)
    if not result:
        return None

    state, city, landmarks = result
    emotion_primary = emotion.get("primary", "") if isinstance(emotion, dict) else str(emotion)
    category = THEME_TO_LANDMARK_CATEGORY.get(theme) or EMOTION_TO_LANDMARK_CATEGORY.get(emotion_primary) or "wisdom"
    landmark_time = APP_TIME_TO_LANDMARK_TIME.get(time_of_day, "morning")
    keywords = situation_keywords or []

    # Load recent landmark runs to determine usage and contrast track
    recent_runs = []
    try:
        if RECENT_RUNS_PATH.exists():
            data = json.loads(RECENT_RUNS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                recent_runs = [r for r in data if r.get("landmark_chosen")]
    except Exception:
        pass

    usage_counts = {}
    for r in [r for r in recent_runs if r.get("landmark_state") == state and r.get("landmark_city") == city][-30:]:
        lm_name = r.get("landmark_chosen")
        if lm_name:
            usage_counts[lm_name] = usage_counts.get(lm_name, 0) + 1

    track, contrast_prob = _pick_track(recent_runs, category)

    scored = []
    for lm in landmarks:
        used = usage_counts.get(lm["name"], 0)
        s = _score_landmark(lm, category, landmark_time, keywords, used, track)
        scored.append((s, lm))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_3 = scored[:3]
    if not top_3:
        return None

    weights = [max(s, 1.0) for s, _ in top_3]
    chosen_score, chosen_lm = _rnd.choices(top_3, weights=weights, k=1)[0]

    # Save landmark run history for contrast tracking
    try:
        data = json.loads(RECENT_RUNS_PATH.read_text(encoding="utf-8")) if RECENT_RUNS_PATH.exists() else []
        if not isinstance(data, list):
            data = []
        data.append({
            "timestamp": datetime.now().isoformat(),
            "landmark_state": state,
            "landmark_city": city,
            "quote_category": category,
            "landmark_chosen": chosen_lm["name"],
            "landmark_type": chosen_lm.get("type", ""),
            "landmark_score": chosen_score,
            "track": track,
            "contrast_probability": contrast_prob,
            "top_3_considered": [{"name": lm["name"], "score": s} for s, lm in top_3],
        })
        RECENT_RUNS_PATH.write_text(json.dumps(data[-200:], indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass

    return {
        "landmark": chosen_lm,
        "score": chosen_score,
        "track": track,
        "contrast_probability": contrast_prob,
        "category": category,
        "state": state,
        "city": city,
        "top_3": [{"name": lm["name"], "score": s, "type": lm.get("type", "")} for s, lm in top_3],
    }


def _get_expanded_emotion_seeds() -> dict:
    """Precompute and cache WordNet expanded emotion seeds once in memory."""
    global _EXPANDED_EMOTION_SEEDS
    if not _EXPANDED_EMOTION_SEEDS:
        wn = _get_wordnet()
        for emotion, seeds in EMOTION_SEEDS.items():
            expanded = set(seeds)
            if wn is not None:
                for seed in seeds:
                    for syn in wn.synsets(seed)[:3]:
                        expanded.update(l.name().replace("_", " ") for l in syn.lemmas())
            _EXPANDED_EMOTION_SEEDS[emotion] = expanded
    return _EXPANDED_EMOTION_SEEDS


_models: dict = {}



def _get_wordnet():
    """Lazy-load NLTK WordNet. Returns None if unavailable."""
    if "wordnet" not in _models:
        try:
            from nltk.corpus import wordnet
            wordnet.synsets("test")  # force data check
            _models["wordnet"] = wordnet
        except Exception:
            _models["wordnet"] = None
    return _models["wordnet"]


def _session() -> requests.Session:
    if "session" not in _models:
        s = requests.Session()
        s.headers.update({"User-Agent": HTTP_USER_AGENT, "Accept": "application/json"})
        _models["session"] = s
    return _models["session"]


# LOCATION RESOLVER

def resolve_location(location_key: str = "mumbai", custom_location: str = None) -> dict:
    """
    Resolve location: returns predefined location from LOCATIONS or constructs
    a dynamic location object for a custom user location, overriding predefined values.
    """
    if custom_location and custom_location.strip():
        name = custom_location.strip()
        for k, v in LOCATIONS.items():
            if name.lower() in (k.lower(), v.get("name", "").lower()):
                return v
        return {
            "name": name,
            "lat": 20.5937,
            "lon": 78.9629,
            "custom": True,
        }
    return LOCATIONS.get(location_key, LOCATIONS.get("mumbai", {"name": "Mumbai", "lat": 19.0760, "lon": 72.8777}))


# CONTEXT ENRICHMENT

def enrich_context(
    quote, location, date, time_of_day,
    language: str = "English", translated_en_quote: str = "",
    regional_profile: str = None, custom_keywords: list[str] = None
) -> Context:
    """Gather all context data. Called by app.py Step 1.
    If custom_keywords is provided, overrides subsequent NLP analysis and translation.
    """
    weather = get_weather(location["lat"], location["lon"])
    panchang_data = get_full_panchang(date, location=location, regional_profile=regional_profile, language=language)
    festival = None
    if panchang_data:
        fest_name = panchang_data.get("festival_intelligence", {}).get("active_festival")
        t_dict = panchang_data.get("astronomical_panchang", {}).get("tithi", {})
        udaya_t = t_dict.get("udaya_tithi")
        p_name = t_dict.get("paksha")
        t_str = f"{udaya_t} ({p_name} Paksha)" if udaya_t and p_name else (udaya_t or "")
        if fest_name and t_str:
            festival = f"{fest_name} [{t_str}]"
        elif fest_name:
            festival = fest_name
        elif t_str:
            festival = t_str
    else:
        festival = get_festival(date, location=location, regional_profile=regional_profile, language=language)

    if custom_keywords:
        # Override subsequent NLP extraction & translation functions directly
        clean_kws = [k.strip() for k in custom_keywords if k.strip()]
        quote_analysis = QuoteAnalysis(
            text=quote,
            nouns=clean_kws,
            key_terms=clean_kws,
            has_concrete=True,
        )
        quote_analysis.theme = _infer_theme(quote_analysis)
        en_keywords = clean_kws
        emotion = detect_emotion(quote_analysis, en_keywords=en_keywords)
        visual_imagery = [{"hindi": k, "english": k} for k in dict.fromkeys(clean_kws)]
    else:
        analysis_quote = translated_en_quote if translated_en_quote else quote
        quote_analysis = analyze_quote(analysis_quote)
        en_keywords = translate_hi_to_en(quote_analysis.key_terms)
        emotion = detect_emotion(quote_analysis, en_keywords=en_keywords)
        visual_imagery = extract_visual_imagery(quote_analysis, en_keywords)

    return Context(
        weather=weather, festival=festival, quote_analysis=quote_analysis,
        emotion=emotion, en_keywords=en_keywords, time=time_of_day, quote=quote,
        visual_imagery=visual_imagery,
        visual_richness_score=len(visual_imagery),
        panchang_details=panchang_data,
    )


def get_weather(lat, lon) -> dict:
    """Open-Meteo API -> {condition, temp, humidity}. No key required."""
    try:
        resp = _session().get(
            OPEN_METEO_URL,
            params={
                "latitude": lat, "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code",
            },
            timeout=3,
        )
        cur = resp.json().get("current", {})
        code = cur.get("weather_code", 0)

        # Inline weather interpretation
        if code == 0:
            condition = "clear sky"
        elif code in (1, 2, 3):
            condition = "partly cloudy"
        elif code in (45, 48):
            condition = "mist"
        elif 51 <= code <= 67:
            condition = "drizzle"
        elif 71 <= code <= 77:
            condition = "snow"
        elif 80 <= code <= 82:
            condition = "rain showers"
        elif 95 <= code <= 99:
            condition = "thunderstorm"
        else:
            condition = "overcast"

        return {
            "condition": condition,
            "temp": round(cur.get("temperature_2m", 0)),
            "humidity": cur.get("relative_humidity_2m", 0),
        }
    except Exception:
        return {"condition": "clear", "temp": 20, "humidity": 60}


def get_full_panchang(target_date, location=None, regional_profile=None, language="English") -> dict | None:
    """
    Execute the dual-branch parallel Panchang coordinator.
    Returns unified Panchang JSON with astronomical calculations, regional calendar,
    and preserved festival records.
    """
    try:
        from panchange_engine import get_coordinator
        coord = get_coordinator()
        d = target_date.date() if hasattr(target_date, "date") else target_date
        lat = location.get("lat", 19.0760) if location else 19.0760
        lon = location.get("lon", 72.8777) if location else 72.8777
        loc_name = location.get("name") if location else None
        return coord.calculate_panchang(
            target_date=d,
            lat=lat,
            lon=lon,
            location_name=loc_name,
            regional_profile_id=regional_profile,
            language=language,
        )
    except Exception:
        return None


def get_festival(date, location=None, regional_profile=None, language="English") -> str | None:
    """
    Panchang lookup -> festival, tithi, and lunar phase (paksha).
    Executes the dual-engine coordinator while preserving exact fallback compatibility
    with panchang_2026.json.
    """
    try:
        from panchange_engine import get_coordinator
        coord = get_coordinator()
        d = date.date() if hasattr(date, "date") else date
        lat = location.get("lat", 19.0760) if location else 19.0760
        lon = location.get("lon", 72.8777) if location else 72.8777
        loc_name = location.get("name") if location else None
        res_str = coord.get_festival_string(
            target_date=d,
            lat=lat,
            lon=lon,
            location_name=loc_name,
            regional_profile_id=regional_profile,
            language=language,
        )
        if res_str:
            return res_str
    except Exception:
        pass

    # Direct fallback to preserved panchang_2026.json in memory
    global _PANCHANG_DATA
    if _PANCHANG_DATA is None:
        try:
            _PANCHANG_DATA = json.loads(PANCHANG_PATH.read_text(encoding="utf-8"))
        except Exception:
            _PANCHANG_DATA = {}

    day = _PANCHANG_DATA.get(date.strftime("%Y-%m-%d"), {})
    fest = day.get("festival_name")
    tithi = day.get("tithi")
    paksha = day.get("paksha")

    tithi_info = f"{tithi} ({paksha} Paksha)" if tithi and paksha else (tithi or "")

    if fest and tithi_info:
        return f"{fest} [{tithi_info}]"
    if fest:
        return fest
    if tithi_info:
        return tithi_info
    return None




_KNOWN_VISUAL = {
    "rangoli", "diya", "diwali", "holi", "lamp", "candle", "flame", "color",
    "festival", "garland", "incense", "mandala", "kolam", "mehendi", "bindi",
    "firework", "lantern", "wreath", "petal", "offering",
}


def extract_visual_imagery(quote_analysis, en_keywords) -> list[dict]:
    """Extract the quote's own concrete visual words (English input)."""
    visuals = []
    seen = set()
    for w in en_keywords:
        w_lower = w.lower()
        if w_lower in seen or w_lower in ENGLISH_STOPWORDS:
            continue
        if is_visual_word(w_lower) or w_lower in _KNOWN_VISUAL:
            visuals.append({"hindi": w, "english": w_lower})
            seen.add(w_lower)
    return visuals


def build_quote_native_candidates(visual_imagery, weather, time_of_day) -> list[PreparedCandidate]:
    """Create first-class candidates from the quote's own visual words."""
    candidates = []
    weather_ctx = f"{weather.get('condition', '')}, {weather.get('temp', '')}C"
    for v in visual_imagery:
        candidates.append(PreparedCandidate(
            id=f"quote_native_{v['english']}",
            name=v["english"],
            domain="PHOTOREALISTIC",
            entity_type="quote_visual",
            cultural=False,
            chain_sources=["quote_native"],
            selection_context="Imagery supplied by the quote or keyword override.",
            subject_text=v["english"],
            scene_text=f"{v['english']} in {time_of_day} light",
            weather_context=weather_ctx,
            visual_phrases=[v["english"]],
            quote_native=True,
        ))
    return candidates


def analyze_quote(quote_text) -> QuoteAnalysis:
    """Analyze quote NLP (English input assumed)."""
    analysis = QuoteAnalysis(text=quote_text)
    words = re.findall(r"[A-Za-z]+", quote_text)
    tokens = [w for w in words if w.lower() not in ENGLISH_STOPWORDS and len(w) > 2]
    analysis.tokens = words
    analysis.nouns = tokens[:5]
    analysis.key_terms = tokens[:8]
    analysis.has_concrete = any(is_visual_word(w) for w in analysis.nouns)
    analysis.theme = _infer_theme(analysis)
    return analysis


def detect_emotion(quote_analysis, en_keywords: list = None) -> dict:
    """
    Seed-word overlap + simple sentiment -> primary emotion.
    Uses pre-expanded emotion seed cache for instant O(1) matching.
    """
    terms = set(t.lower() for t in quote_analysis.key_terms)
    if en_keywords is not None:
        terms |= set(k.lower() for k in en_keywords)
    else:
        terms |= set(t.lower() for t in translate_hi_to_en(quote_analysis.key_terms))

    expanded_seeds = _get_expanded_emotion_seeds()
    best_emotion, best_score = "hopeful", 0

    for emotion, expanded in expanded_seeds.items():
        score = sum(1 for t in terms if any(t in e or e in t for e in expanded))
        if score > best_score:
            best_emotion, best_score = emotion, score

    # crude sentiment: positive emotions -> high, melancholic -> low
    sentiment = {
        "hopeful": 0.7, "peaceful": 0.6, "determined": 0.6, "devotional": 0.65,
        "joyful": 0.8, "reflective": 0.5, "melancholic": 0.2,
        "warm": 0.75, "grateful": 0.7, "empowered": 0.7,
        "nostalgic": 0.4, "loving": 0.8,
    }.get(best_emotion, 0.5)
    return {"primary": best_emotion, "sentiment": sentiment, "score": best_score}


def translate_hi_to_en(words: list) -> list:
    """Lowercase passthrough (English-only input assumed)."""
    if not words:
        return []
    return list(dict.fromkeys(w.lower() for w in words))


# KNOWLEDGE CHAIN

def run_knowledge_chain(context, location, custom_candidates: list[str] = None) -> CandidatePool:
    """
    Use the knowledge chains to build a shortlist of visual candidates.
    Custom candidates replace automatic discovery.
    """
    if custom_candidates:
        prepared = []
        loc_name = location.get("name", "India")
        w_cond = context.weather.get("condition", "clear sky") if context.weather else "clear sky"
        w_temp = context.weather.get("temp", 20) if context.weather else 20
        weather_ctx = f"{w_cond}, {w_temp}C"

        for idx, item in enumerate(custom_candidates):
            item_str = item.strip()
            if not item_str:
                continue
            cand_id = f"custom_candidate_{idx + 1}"
            scene_text = f"Set against the authentic atmospheric backdrop of {loc_name} during {context.time}, with {w_cond} and natural ambient lighting."
            prepared.append(
                PreparedCandidate(
                    id=cand_id,
                    name=item_str,
                    domain="PHOTOREALISTIC",
                    entity_type="custom_user_candidate",
                    cultural=True,
                    chain_sources=["user_override"],
                    selection_context="Subject supplied by the user.",
                    subject_text=item_str,
                    scene_text=scene_text,
                    weather_context=weather_ctx,
                    visual_phrases=[item_str],
                    verb_type="physical",
                    quote_native=True,
                )
            )

        if not prepared:
            prepared = _cultural_fallback_candidates(
                context.emotion, context.quote_analysis.theme,
                context.en_keywords, context.weather, context.time, location,
            )

        return CandidatePool(
            pool=prepared,
            emotion=context.emotion,
            theme=context.quote_analysis.theme,
            negated=context.quote_analysis.negated_nouns,
            quote=context.quote,
        )

    # Chain 1: word understanding via English WordNet (translate-first).
    # Replaces the discontinued pyiwn/IndoWordNet path.
    word_info = chain_1_word_understanding(context.quote_analysis, context.en_keywords)

    expanded = list(dict.fromkeys(word_info["synonyms"] + word_info["related"]))
    expanded = [term for term in expanded if term not in context.en_keywords]
    en_keywords = context.en_keywords + expanded

    wikidata_results = chain_2_wikidata(
        context.en_keywords, location,
        emotion=context.emotion,
        theme=context.quote_analysis.theme,
        festival=context.festival or "",
        quote=context.quote_analysis.text,
        expanded_keywords=expanded,
    )
    wiki_results = chain_3_wikipedia(wikidata_results)
    dbpedia_results = chain_4_dbpedia(wiki_results["categories"])

    # Chain 6: Cultural supplement (local) — matches keywords, theme, AND emotion.
    cultural_results = chain_6_cultural(
        en_keywords, emotion=context.emotion, theme=context.quote_analysis.theme)

    # Merge all results into candidate pool
    # Landmark-based location features: use the chosen landmark if available
    lm_sel = context.landmark_selection
    if lm_sel:
        lm = lm_sel["landmark"]
        location_features = [{"name": lm["name"], "type": lm.get("type", ""), "qid": None}]
    else:
        location_features = [{"name": location.get("name", ""), "type": "location", "qid": None}]
    cultural_data = _load_cultural()
    raw_candidates = merge_all(
        wikidata_results, wiki_results, dbpedia_results,
        cultural_results, location_features, cultural_data,
    )

    # Persist newly discovered visual metaphors from live chains (Wikidata, Wikipedia, DBpedia)
    # into cultural_metaphors.json so it dynamically updates on every run.
    new_to_save = []
    for c in raw_candidates:
        if c.get("domain") in ("PHOTOREALISTIC", "MYTHOLOGICAL") and c.get("visual_phrases"):
            for vp in c.get("visual_phrases", [])[:2]:
                if len(vp.split()) >= 2:  # Must be a descriptive phrase
                    new_to_save.append({
                        "concept": context.quote_analysis.theme or "general",
                        "visual": vp,
                        "context": f"{c.get('name', '')} in {location['name']}",
                    })
    if new_to_save:
        save_discovered_cultural_metaphors(new_to_save)

    quote_candidates = build_quote_native_candidates(
        context.visual_imagery[:2], context.weather, context.time,
    )
    by_name = {c.name.casefold(): c for c in quote_candidates}
    source_counts = {}
    for raw in raw_candidates:
        name = raw["name"].strip().casefold()
        source = raw["chain_sources"][0]
        if source_counts.get(source, 0) >= 2:
            continue

        candidate = pre_build_candidate(
            raw, location_features, context.weather, context.time,
            quote_terms=context.en_keywords,
        )
        existing = by_name.get(name)
        if existing:
            candidate.quote_native = True
            candidate.chain_sources = existing.chain_sources + candidate.chain_sources
        by_name[name] = candidate
        source_counts[source] = source_counts.get(source, 0) + 1

    prepared = list(by_name.values())

    # Always guarantee at least one candidate (edge case 1: no nouns / all APIs down).
    # Route through Chain 6 cultural metaphors matched by emotion, not hardcoded location.
    if not prepared:
        prepared = _cultural_fallback_candidates(
            context.emotion, context.quote_analysis.theme,
            context.en_keywords, context.weather, context.time, location,
        )

    return CandidatePool(
        pool=prepared,
        emotion=context.emotion,
        theme=context.quote_analysis.theme,
        negated=context.quote_analysis.negated_nouns,
        quote=context.quote,
    )


# CHAIN IMPLEMENTATIONS

def chain_1_word_understanding(quote_analysis, en_keywords) -> dict:
    """
    Word understanding via English WordNet, using translated keywords.

    Replaces the discontinued pyiwn/IndoWordNet path. English WordNet (~150k
    words) gives synonyms, hypernym-based abstract/concrete classification, and
    related concepts (also_sees + similar_tos). Cultural nuance stays in Chain 6.
    """
    wn = _get_wordnet()
    results, all_related, all_synonyms = [], [], []

    # Pair each Hindi key term with its translation; fall back to translating here.
    en_terms = en_keywords or translate_hi_to_en(quote_analysis.key_terms)
    pairs = list(zip(quote_analysis.key_terms, en_terms))
    # Also cover any English keywords without a Hindi pairing.
    for extra in en_terms[len(quote_analysis.key_terms):]:
        pairs.append(("", extra))

    if wn is None:
        # Graceful fallback: no WordNet -> keywords only, treat as abstract.
        for hi, en in pairs:
            results.append({"word": hi, "en_word": en, "is_abstract": True,
                            "synonyms": [], "related": []})
        return {"words": results, "synonyms": [], "related": []}

    for hindi_word, en_word in pairs:
        if not en_word:
            continue
        synsets = wn.synsets(en_word, pos=wn.NOUN)

        synonyms = list(dict.fromkeys(
            lemma.name().replace("_", " ") for s in synsets for lemma in s.lemmas()
        ))

        is_abs = False
        if synsets:
            paths = synsets[0].hypernym_paths()
            is_abs = any("abstraction" in h.name() for p in paths for h in p)

        related = []
        for s in synsets[:2]:
            related += [l.name().replace("_", " ") for ss in s.also_sees() for l in ss.lemmas()]
            related += [l.name().replace("_", " ") for ss in s.similar_tos() for l in ss.lemmas()]

        synonyms = synonyms[:10]
        related = list(dict.fromkeys(related))[:10]
        all_synonyms.extend(synonyms)
        all_related.extend(related)
        results.append({"word": hindi_word, "en_word": en_word,
                        "is_abstract": is_abs, "synonyms": synonyms, "related": related})

    return {"words": results,
            "synonyms": list(dict.fromkeys(all_synonyms)),
            "related": list(dict.fromkeys(all_related))}


def chain_2_wikidata(en_keywords, location, emotion="", theme="", festival="",
                    *, quote="", expanded_keywords=()) -> dict:
    """Find relevant mythological figures and symbols."""
    out = {"symbols": [], "location_features": [], "mythology": []}
    deities = []

    try:
        cached_deities = load_cache("mythology_deities", "wikidata")
        if cached_deities is None:
            cached_deities = query_wikidata("mythology_deities")
            save_cache("mythology_deities", cached_deities)
        deities.extend(cached_deities)
    except Exception:
        pass

    if theme in THEME_TO_EPIC:
        try:
            deities.extend(query_wikidata("epic_characters", work_qid=THEME_TO_EPIC[theme]))
        except Exception:
            pass

    out["mythology"] = _score_mythology_relevance(deities, theme, emotion, festival, quote)

    # Try up to three original terms, then one WordNet term if more options are needed.
    symbols = {}
    for keyword in list(en_keywords[:3]) + list(expanded_keywords[:1]):
        if len(symbols) >= 2:
            break
        qid = _resolve_qid(keyword)
        if not qid:
            continue
        try:
            for item in query_wikidata("symbols_for_concept", concept_qid=qid):
                label = item["label"].strip().casefold()
                entity = f"{label} {item.get('type') or ''}".lower()
                if label and not any(token in entity for token in NONVISUAL_TOKENS):
                    symbols.setdefault(label, {**item, "selection_context": f"Symbol for {keyword}."})
        except Exception:
            continue
    out["symbols"] = list(symbols.values())[:2]
    return out


def _score_mythology_relevance(deities, theme, emotion, festival, quote) -> list:
    """Rank candidates with an identifiable connection to the quote."""
    quote_tokens = re.findall(r"[a-z]+", quote.lower())
    quote_text = " " + " ".join(quote_tokens) + " "
    quote_words = {word for word in quote_tokens if len(word) > 2} - ENGLISH_STOPWORDS
    theme_words = set(THEME_MYTHOLOGY_KEYWORDS.get(theme, [])) if theme != "general" else set()
    festival_words = next(
        (set(words) for name, words in FESTIVAL_MYTHOLOGY_KEYWORDS.items() if name in festival.lower()),
        set(),
    )
    primary = emotion.get("primary", "") if isinstance(emotion, dict) else str(emotion)
    mood_words = set(EMOTION_CONCEPTS.get(primary, []))

    scored = []
    for deity in deities:
        name = " ".join(re.findall(r"[a-z]+", deity["label"].lower()))
        description = deity.get("description", "")
        words = set(re.findall(r"[a-z]+", description.lower()))
        named = bool(name) and f" {name} " in quote_text
        quote_matches = quote_words & words
        theme_matches = theme_words & (words | {name})
        if not (named or quote_matches or theme_matches):
            continue

        festival_match = bool(festival_words & (words | {name}))
        score = (named, len(quote_matches), len(theme_matches), festival_match, bool(words & mood_words))
        reason = "Named in the quote." if named else f"Matches {', '.join(sorted(quote_matches | theme_matches))}."
        scored.append((score, {**deity, "selection_context": f"{reason} {description}".strip()}))

    results = {}
    for _, deity in sorted(scored, key=lambda item: item[0], reverse=True):
        results.setdefault(deity["label"].strip().casefold(), deity)
    return list(results.values())[:2]


def chain_3_wikipedia(wikidata_results) -> dict:
    """Wikipedia: visual phrases + categories for each entity."""
    out: dict = {"entities": {}, "categories": []}
    try:
        entities = (wikidata_results.get("symbols", [])
                    + wikidata_results.get("location_features", [])
                    + wikidata_results.get("mythology", []))
        for entity in entities[:10]:
            label = entity.get("label")
            if not label:
                continue
            summary = fetch_wikipedia(label)
            visual = extract_visual_phrases(summary)
            cats = get_wiki_categories(label)
            out["entities"][label] = {"visual": visual, "categories": cats,
                                      "entity_type": entity.get("type", "")}
            out["categories"].extend(cats)
    except Exception:
        pass
    return out


def chain_4_dbpedia(categories) -> list:
    """DBpedia: explore category graph (1 hop, max 5 cats, max 10 items)."""
    try:
        return explore_dbpedia_categories(categories, max_hops=1, max_cats=5, max_items=10)
    except Exception:
        return []


def _find_cultural_matches(en_keywords: list, emotion: dict = None, theme: str = None) -> list[tuple[dict, str]]:
    """
    Consolidated 3-pass cultural matching helper.
    Returns list of (metaphor_dict, concept_str) tuples.
    """
    cultural = _load_cultural()
    matches = []
    seen_visuals = set()
    kws = [k.lower() for k in en_keywords]

    def _add(m, concept):
        if m["visual"] not in seen_visuals:
            seen_visuals.add(m["visual"])
            matches.append((m, concept))

    # Pass 1: keyword matches
    for concept, metaphors in cultural.items():
        if concept.startswith("_"):
            continue
        if concept in kws or any(k in concept or concept in k for k in kws):
            for m in metaphors:
                _add(m, concept)

    # Pass 2: theme match
    if theme:
        theme_lower = theme.lower()
        for concept, metaphors in cultural.items():
            if concept.startswith("_"):
                continue
            if concept == theme_lower or theme_lower in concept or concept in theme_lower:
                for m in metaphors:
                    _add(m, concept)

    # Pass 3: emotion-based expansion (fallback only — prevents bias when
    # Pass 1/2 already found quote-relevant metaphors).
    if emotion and len(matches) < 3:
        primary = (emotion.get("primary") or "hopeful").lower()
        for concept_name in EMOTION_CONCEPTS.get(primary, ["hope"]):
            for m in cultural.get(concept_name, []):
                _add(m, concept_name)

    return matches


def chain_6_cultural(en_keywords, emotion=None, theme=None) -> list:
    """Cultural supplement: Indian-specific metaphors from cultural_metaphors.json."""
    raw_matches = _find_cultural_matches(en_keywords, emotion=emotion, theme=theme)
    return [
        {
            "label": m["visual"],
            "selection_context": f"Metaphor for {concept}. {m.get('context', '')}".strip(),
        }
        for m, concept in raw_matches
    ]


# LOCATION DETAILS (landmark-based)

def discover_location_details(location, landmark_selection=None) -> list:
    """Build location details from the chosen landmark's visual_description."""
    details = []

    if landmark_selection:
        lm = landmark_selection["landmark"]
        vis_desc = lm.get("visual_description", "")
        known_for = lm.get("known_for", "")
        lm_name = lm.get("name", "")

        if vis_desc:
            details.append({"id": "D1", "text": vis_desc, "source": lm_name})
        if known_for:
            details.append({"id": "D2", "text": known_for, "source": lm_name})

        # Add setting keywords as atmospheric context
        kws = lm.get("setting_keywords", [])
        if kws:
            details.append({
                "id": "D3",
                "text": f"atmospheric elements: {', '.join(kws[:6])}",
                "source": lm_name,
            })

    if not details:
        loc_name = location.get("name", "the location")
        details = [
            {"id": "D1", "text": f"characteristic architecture and natural atmosphere of {loc_name}", "source": loc_name},
            {"id": "D2", "text": f"distinctive ambient scenery and textures of {loc_name}", "source": loc_name},
        ]

    return details


# NLP UTILITIES (resolved at runtime, nothing hardcoded)

def is_visual_word(word, pos="NOUN") -> bool:
    """WordNet concreteness check -> is this photographable?"""
    wn = _get_wordnet()
    if wn is None:
        return True  # permissive fallback
    try:
        synsets = wn.synsets(word)
        for syn in synsets[:3]:
            lex = syn.lexname()  # e.g. "noun.artifact", "noun.cognition"
            if lex and lex.split(".")[-1] in (
                "artifact", "object", "animal", "plant", "body", "food",
                "location", "substance", "natural_object", "shape", "person",
            ):
                return True
        return False
    except Exception:
        return True


def classify_verb(verb) -> str:
    """WordNet lexname -> physical/mental/stative."""
    wn = _get_wordnet()
    if wn is None or not verb:
        return "unknown"
    try:
        for syn in wn.synsets(verb, pos="v")[:3]:
            lex = (syn.lexname() or "").split(".")[-1]
            if lex in ("motion", "contact", "creation", "consumption", "competition"):
                return "physical"
            if lex in ("cognition", "emotion", "perception", "communication"):
                return "mental"
            if lex in ("stative", "possession"):
                return "stative"
        return "unknown"
    except Exception:
        return "unknown"


def extract_visual_phrases(wiki_text) -> list:
    """Stanza/regex on wiki text -> (adj+noun) pairs where is_visual_word=True."""
    if not wiki_text:
        return []
    phrases: list[str] = []
    nlp = _get_stanza_en()
    if nlp is not None:
        try:
            doc = nlp(wiki_text)
            for sent in doc.sentences:
                words = sent.words
                for i, w in enumerate(words):
                    if w.upos == "NOUN" and is_visual_word(w.lemma or w.text):
                        adj = ""
                        if i > 0 and words[i - 1].upos == "ADJ":
                            adj = words[i - 1].text + " "
                        phrases.append((adj + (w.text)).strip())
            return list(dict.fromkeys(phrases))[:8]
        except Exception:
            pass
    # Regex fallback: capitalized or adjective-noun bigrams that look visual.
    for m in re.findall(r"\b([a-z]+)\s+([a-z]+)\b", wiki_text.lower()):
        adj, noun = m
        if is_visual_word(noun):
            phrases.append(f"{adj} {noun}")
    return list(dict.fromkeys(phrases))[:8]


def _get_stanza_en():
    """Lazy English Stanza pipeline for wiki-text phrase extraction."""
    if "stanza_en" not in _models:
        try:
            import stanza
            _models["stanza_en"] = stanza.Pipeline(
                "en", processors="tokenize,pos,lemma",
                download_method=None, verbose=False,
            )
        except Exception:
            _models["stanza_en"] = None
    return _models["stanza_en"]


def pre_build_candidate(raw, location_features, weather, time,
                        quote_terms=None) -> PreparedCandidate:
    """Assemble subject_text, scene_text from discovered data. No templates."""
    visual = raw.get("visual_phrases", [])
    subject_text = " ".join(visual[:4]) if visual else raw.get("name", "")
    loc_names = ", ".join(f["name"] for f in location_features[:3] if f.get("name"))
    # Blend quote key terms into scene alongside location+weather.
    quote_hint = ""
    if quote_terms:
        quote_hint = ", ".join(quote_terms[:2])
    scene_parts = [x for x in (quote_hint, loc_names, f"{weather['condition']} {time}") if x]
    scene_text = ", ".join(scene_parts)

    return PreparedCandidate(
        id=raw.get("id", raw.get("name", "unknown")),
        name=raw.get("name", ""),
        domain=raw.get("domain", "PHOTOREALISTIC"),
        entity_type=raw.get("entity_type", ""),
        cultural=raw.get("cultural", False),
        chain_sources=raw.get("chain_sources", []),
        selection_context=raw.get("selection_context", ""),
        subject_text=subject_text,
        scene_text=scene_text,
        weather_context=f"{weather['condition']}, {weather['temp']}C",
        visual_phrases=visual,
        verb_type=classify_verb(raw.get("associated_verb")) if raw.get("associated_verb") else "unknown",
    )


def _cultural_fallback_candidates(emotion, theme, en_keywords, weather, time, location) -> list[PreparedCandidate]:
    """Fallback via Chain 6 cultural metaphors matched by emotion/theme/keywords."""
    matches = _find_cultural_matches(en_keywords, emotion=emotion, theme=theme)

    # Keep the same limit as the cultural route.
    prepared = []
    for m, concept in matches[:2]:
        loc_hint = location["name"]
        prepared.append(PreparedCandidate(
            id=f"cultural_fallback_{concept}_{len(prepared)}",
            name=m["visual"],
            domain="PHOTOREALISTIC",
            entity_type="metaphor",
            cultural=True,
            chain_sources=["chain_6_cultural", "fallback"],
            selection_context=f"Metaphor for {concept}.",
            subject_text=m["visual"],
            scene_text=f"{m.get('context', concept)}, {weather['condition']} {time} near {loc_hint}",
            weather_context=f"{weather['condition']}, {weather['temp']}C",
            visual_phrases=[m["visual"]],
        ))

    # Ultimate fallback: first available cultural visual.
    if not prepared:
        cultural = _load_cultural()
        all_v = cultural.get("_all_visuals", [])
        visual = all_v[0] if all_v else "earthen diya lamp with flickering flame"
        prepared.append(PreparedCandidate(
            id="cultural_fallback_generic",
            name=visual,
            domain="PHOTOREALISTIC",
            entity_type="metaphor",
            cultural=True,
            chain_sources=["chain_6_cultural", "fallback"],
            subject_text=visual,
            scene_text=f"{weather['condition']} {time} near {location['name']}",
            weather_context=f"{weather['condition']}, {weather['temp']}C",
            visual_phrases=[visual],
        ))

    return prepared


# MERGE AND DEDUP

# Merge candidates from all chains and assign domains
def merge_all(wikidata, wiki, dbpedia, cultural,
              location_features, cultural_data) -> list:
    """Merge candidates from all chains, assign domains, and set cultural flags."""
    live_raw = []
    for item in wikidata.get("mythology", []):
        live_raw.append({"data": item, "source": "chain_2_mythology"})
    for item in wikidata.get("symbols", []):
        live_raw.append({"data": item, "source": "chain_2_wikidata"})
    for item in wikidata.get("location_features", []):
        live_raw.append({"data": item, "source": "chain_2_wikidata"})
    for label, info in wiki.get("entities", {}).items():
        live_raw.append({"data": {"label": label, **info}, "source": "chain_3_wikipedia"})
    for item in dbpedia:
        live_raw.append({"data": item, "source": "chain_4_dbpedia"})
    for item in cultural:
        live_raw.append({"data": item, "source": "chain_6_cultural"})

    _visual_required = {"chain_2_wikidata", "chain_3_wikipedia", "chain_4_dbpedia"}
    seen: dict = {}

    for item in live_raw:
        data = item["data"]
        name = (data.get("label") or data.get("name") or data.get("visual") or "").lower().strip()
        etype = (data.get("type") or data.get("entity_type") or "").lower()
        if not name:
            continue
        # Skip non-visual entities like administrative regions or languages
        if item["source"] in _visual_required and any(tok in f"{name} {etype}" for tok in NONVISUAL_TOKENS):
            continue

        if name in seen:
            if item["source"] not in seen[name]["chain_sources"]:
                seen[name]["chain_sources"].append(item["source"])
            if data.get("visual"):
                seen[name].setdefault("visual_phrases", []).extend(data["visual"])
        elif item["source"] != "chain_3_wikipedia":
            # Assign visual domain based on origin
            if item["source"] == "chain_2_mythology" or (item["source"] == "chain_2_wikidata" and etype in ("deity", "mythological character", "god", "goddess")):
                domain = "MYTHOLOGICAL"
            else:
                domain = "PHOTOREALISTIC"

            merged = {
                "id": f"{item['source']}_{name.replace(' ', '_')[:24]}",
                "name": data.get("label") or data.get("name") or data.get("visual"),
                "entity_type": data.get("type") or data.get("entity_type", ""),
                "visual_phrases": list(data.get("visual", [])),
                "associated_verb": data.get("associated_verb"),
                "chain_sources": [item["source"]],
                "selection_context": (
                    data.get("selection_context") or data.get("description")
                    or data.get("entity_type", "")
                ),
                "domain": domain,
            }
            if item["source"] == "chain_6_cultural" and not merged["visual_phrases"]:
                merged["visual_phrases"] = [merged["name"]]
            seen[name] = merged

    # Set cultural flag
    all_visuals = set(v.lower() for v in cultural_data.get("_all_visuals", []))

    merged_list = list(seen.values())
    for c in merged_list:
        c_name = c.get("name", "").lower()
        c["cultural"] = c_name in all_visuals

    return merged_list


# API HELPERS

_NON_LATIN_LABEL_MAP = {
    "Q11378": "Shiva", "Q11380": "Vishnu", "Q42891": "Krishna",
    "Q132127": "Kali",
}


def query_wikidata(template_name, **params) -> list:
    """Execute SPARQL from SPARQL_TEMPLATES with params against Wikidata."""
    query = SPARQL_TEMPLATES[template_name].format(**params)
    timeout = 15 if "mythology" in template_name or "epic" in template_name else 5
    resp = _session().get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    bindings = resp.json().get("results", {}).get("bindings", [])
    out = []
    for b in bindings:
        label_key = next((k for k in b if k.endswith("Label")), None)
        desc_key = next((k for k in b if k.endswith("Description")), None)
        var_key = next((k for k in b if not k.endswith("Label")
                        and not k.endswith("Description")), None)
        uri = b.get(var_key, {}).get("value", "") if var_key else ""
        qid = uri.rsplit("/", 1)[-1] if uri.startswith("http") else ""
        raw_label = (b.get(label_key, {}).get("value", "") if label_key else "").strip()
        label = "" if re.fullmatch(r"Q\d+", raw_label) else raw_label
        if qid in _NON_LATIN_LABEL_MAP:
            label = _NON_LATIN_LABEL_MAP[qid]
        if not label:
            continue
        out.append({
            "label": label,
            "description": (b.get(desc_key, {}).get("value", "") if desc_key else ""),
            "qid": qid,
            "type": "",
        })
    return out


def _batch_type_lookup(qids: list) -> dict:
    """Batch P31 lookup: returns {entity_qid: type_label} for up to 50 entities."""
    entity_values = " ".join(f"wd:{q}" for q in qids)
    query = SPARQL_TEMPLATES["batch_instance_of"].format(entity_values=entity_values)
    resp = _session().get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=8,
    )
    resp.raise_for_status()
    type_map = {}
    for b in resp.json().get("results", {}).get("bindings", []):
        entity_uri = b.get("entity", {}).get("value", "")
        entity_qid = entity_uri.rsplit("/", 1)[-1] if entity_uri.startswith("http") else ""
        type_label = b.get("typeLabel", {}).get("value", "")
        if entity_qid and type_label and not re.fullmatch(r"Q\d+", type_label):
            type_map.setdefault(entity_qid, type_label)
    return type_map


def _resolve_qid(keyword) -> str | None:
    """Resolve an English keyword to a Wikidata QID via the search API."""
    try:
        resp = _session().get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbsearchentities", "search": keyword,
                    "language": "en", "format": "json", "limit": 1},
            timeout=5,
        )
        hits = resp.json().get("search", [])
        return hits[0]["id"] if hits else None
    except Exception:
        return None


def fetch_wikipedia(title) -> str:
    """Wikipedia REST API -> summary text."""
    try:
        url = WIKIPEDIA_SUMMARY_URL.format(title=requests.utils.quote(title))
        resp = _session().get(url, timeout=5)
        if resp.status_code != 200:
            return ""
        return resp.json().get("extract", "")
    except Exception:
        return ""


def get_wiki_categories(title) -> list:
    """Wikipedia API -> article categories."""
    try:
        resp = _session().get(
            WIKIPEDIA_API_URL,
            params={"action": "query", "prop": "categories", "titles": title,
                    "format": "json", "cllimit": 10},
            timeout=5,
        )
        pages = resp.json().get("query", {}).get("pages", {})
        cats = []
        for page in pages.values():
            for c in page.get("categories", []):
                cats.append(c["title"].replace("Category:", ""))
        return cats
    except Exception:
        return []


def explore_dbpedia_categories(categories, max_hops, max_cats, max_items) -> list:
    """DBpedia SPARQL -> category graph walk (1 hop)."""
    out = []
    for cat in categories[:max_cats]:
        cat_res = cat.replace(" ", "_")
        query = f"""
            SELECT ?item ?label WHERE {{
              ?item <http://purl.org/dc/terms/subject>
                    <http://dbpedia.org/resource/Category:{cat_res}> .
              ?item rdfs:label ?label .
              FILTER(lang(?label) = "en")
            }} LIMIT {max_items}
        """
        try:
            resp = _session().get(
                DBPEDIA_SPARQL_URL,
                params={"query": query, "format": "application/sparql-results+json"},
                timeout=3,
            )
            for b in resp.json().get("results", {}).get("bindings", []):
                out.append({"label": b.get("label", {}).get("value", ""),
                            "entity_type": cat})
        except Exception:
            continue
    return out


def _infer_theme(analysis: QuoteAnalysis) -> str:
    terms = set(translate_hi_to_en(analysis.key_terms))
    for theme, hints in THEME_HINTS.items():
        if any(any(h in t or t in h for h in hints) for t in terms):
            return theme
    return "general"


def _has_concrete(nouns) -> bool:
    en = translate_hi_to_en(nouns)
    return any(is_visual_word(w) for w in en)


# CULTURAL DATA + CACHE

def _load_cultural() -> dict:
    try:
        data = json.loads(CULTURAL_METAPHORS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"_all_visuals": []}
    all_visuals = []
    for concept, metaphors in data.items():
        if concept.startswith("_"):
            continue
        for m in metaphors:
            if isinstance(m, dict) and m.get("visual"):
                all_visuals.append(m["visual"])
    data["_all_visuals"] = all_visuals
    return data


def save_discovered_cultural_metaphors(new_entries: list[dict]):
    """
    Persist newly discovered visual metaphors from runtime chains (Wikidata, Wikipedia, DBpedia)
    into cultural_metaphors.json so they are permanently cached and serve as future offline fallback.
    """
    if not new_entries:
        return

    try:
        data = {}
        if CULTURAL_METAPHORS_PATH.exists():
            try:
                data = json.loads(CULTURAL_METAPHORS_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        # Collect existing visual phrases across the dictionary for fast deduplication
        existing_visuals = set()
        for concept, metaphors in data.items():
            if concept.startswith("_"):
                continue
            for m in metaphors:
                if isinstance(m, dict) and m.get("visual"):
                    existing_visuals.add(m["visual"].strip().lower())

        added_count = 0
        for entry in new_entries:
            concept = (entry.get("concept") or "general").strip().lower()
            visual = (entry.get("visual") or "").strip()
            context_desc = (entry.get("context") or f"symbolic visual for {concept}").strip()

            if not visual or visual.lower() in existing_visuals:
                continue

            target_list = data.setdefault(concept, [])
            target_list.append({"visual": visual, "context": context_desc})
            existing_visuals.add(visual.lower())
            added_count += 1

        if added_count > 0:
            # Atomic write to prevent file corruption
            temp_path = CULTURAL_METAPHORS_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(CULTURAL_METAPHORS_PATH)
    except Exception:
        pass



CACHE_TTL = {
    "wikidata": 30 * 86400,
    "wikipedia": 14 * 86400,
    "dbpedia": 30 * 86400,
    "anilist": 7 * 86400,
    "location": 30 * 86400,
    "general": 86400,
}

_memory_cache: dict = {}


def load_cache(key: str, source: str = "general"):
    """Check in-memory cache, then Upstash Redis, then disk."""
    now = time.time()
    if key in _memory_cache:
        entry = _memory_cache[key]
        if now - entry["ts"] < CACHE_TTL.get(source, 86400):
            return entry["data"]

    # Check Upstash Redis cloud cache
    try:
        from logs.logger import cloud_load_cache
        cloud_val = cloud_load_cache(key)
        if cloud_val is not None:
            _memory_cache[key] = {"ts": now, "data": cloud_val}
            return cloud_val
    except Exception:
        pass

    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        try:
            entry = json.loads(cache_path.read_text(encoding="utf-8"))
            if now - entry["ts"] < CACHE_TTL.get(source, 86400):
                _memory_cache[key] = entry
                return entry["data"]
        except Exception:
            pass
    return None


def save_cache(key: str, data):
    """Save to memory, Upstash Redis, and disk."""
    now = time.time()
    entry = {"ts": now, "data": data}
    _memory_cache[key] = entry

    # Save to Upstash Redis cloud cache
    try:
        from logs.logger import cloud_save_cache
        cloud_save_cache(key, data, ttl_seconds=CACHE_TTL.get("general", 86400))
    except Exception:
        pass

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps(entry, default=str, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
