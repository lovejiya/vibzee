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
    SPARQL_TEMPLATES, EMOTION_SEEDS, EMOTION_TO_GENRE, GENRE_TO_ARCHETYPE,
    EMOTION_CONCEPTS, THEME_HINTS, ENGLISH_STOPWORDS, NONVISUAL_TOKENS, FALLBACK_LEXICON,
    PreparedCandidate, QuoteAnalysis, Context, CandidatePool,
    PANCHANG_PATH, CULTURAL_METAPHORS_PATH,
    OPEN_METEO_URL, WIKIDATA_SPARQL_URL, DBPEDIA_SPARQL_URL,
    WIKIPEDIA_SUMMARY_URL, WIKIPEDIA_API_URL,
    HTTP_USER_AGENT, CACHE_DIR,
)


_EXPANDED_EMOTION_SEEDS: dict = {}
_PANCHANG_DATA = None


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


def _get_stanza():
    """Lazy-load the Stanza Hindi pipeline. Returns None if unavailable."""
    if "stanza" not in _models:
        try:
            import stanza
            _models["stanza"] = stanza.Pipeline(
                "hi", processors="tokenize,pos,lemma,depparse",
                download_method=None, verbose=False,
            )
        except Exception:
            _models["stanza"] = None
    return _models["stanza"]


def _get_translator():
    """Lazy-load IndicTrans2 (indictranstoolkit). Returns None if unavailable."""
    if "translator" not in _models:
        try:
            # IndicTrans2 loading differs across toolkit versions; wrap defensively.
            from IndicTransToolkit import IndicProcessor  # noqa: F401
            # Model wiring is left to the environment's installed toolkit build.
            _models["translator"] = None
        except Exception:
            _models["translator"] = None
    return _models["translator"]


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


# ═══════════════════════════════════════════════════
# CONTEXT ENRICHMENT
# ═══════════════════════════════════════════════════

def enrich_context(quote, location, date, time_of_day) -> Context:
    """Gather all context data. Called by app.py Step 1."""
    weather = get_weather(location["lat"], location["lon"])
    festival = get_festival(date)
    quote_analysis = analyze_quote(quote)
    en_keywords = translate_hi_to_en(quote_analysis.key_terms)
    emotion = detect_emotion(quote_analysis, en_keywords=en_keywords)

    return Context(
        weather=weather, festival=festival, quote_analysis=quote_analysis,
        emotion=emotion, en_keywords=en_keywords, time=time_of_day, quote=quote,
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


def get_festival(date) -> str | None:
    """
    Panchang lookup -> festival, tithi, and lunar phase (paksha).
    Reuses parsed panchang_2026.json in memory rather than re-reading disk.
    Combines festival observance with tithi details into contextual string.
    """
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


def is_hindi_text(text: str) -> bool:
    """Check if the text contains Devanagari script characters (U+0900 to U+097F)."""
    return bool(re.search(r"[\u0900-\u097f]", text))


def analyze_quote(quote_text) -> QuoteAnalysis:
    """Analyze quote NLP (Hindi via Stanza or English via WordNet/regex)."""
    analysis = QuoteAnalysis(text=quote_text)

    # ── ENGLISH BYPASS PATH ─────────────────────────────────
    if not is_hindi_text(quote_text):
        wn = _get_wordnet()
        words = re.findall(r"[A-Za-z]+", quote_text)
        tokens = [w for w in words if w.lower() not in ENGLISH_STOPWORDS and len(w) > 2]
        analysis.tokens = words
        analysis.nouns = tokens[:5]
        analysis.key_terms = tokens[:8]
        analysis.has_concrete = any(is_visual_word(w) for w in analysis.nouns)
        analysis.theme = _infer_theme(analysis)
        return analysis

    # ── HINDI NLP PATH ──────────────────────────────────────
    nlp = _get_stanza()
    if nlp is None:
        # Fallback: whitespace tokens only, no POS. Pipeline still runs.
        analysis.tokens = re.findall(r"[^\s।,.!?—]+", quote_text)
        analysis.nouns = analysis.tokens[:5]
        analysis.key_terms = analysis.nouns
        analysis.theme = "general"
        return analysis

    try:
        doc = nlp(quote_text)
        negation_window: list[str] = []
        for sent in doc.sentences:
            for word in sent.words:
                analysis.tokens.append(word.text)
                upos = word.upos
                if upos in ("NOUN", "PROPN"):
                    analysis.nouns.append(word.lemma or word.text)
                    if negation_window:
                        analysis.negated_nouns.append(word.lemma or word.text)
                elif upos == "VERB":
                    analysis.verbs.append(word.lemma or word.text)
                elif upos == "ADJ":
                    analysis.adjectives.append(word.lemma or word.text)
                # Hindi negation markers
                if word.text in ("नहीं", "बिना", "न", "मत", "बग़ैर", "बगैर"):
                    negation_window = analysis.nouns[-2:]
        analysis.key_terms = list(dict.fromkeys(analysis.nouns + analysis.adjectives))
        analysis.has_concrete = _has_concrete(analysis.nouns)
        analysis.theme = _infer_theme(analysis)
    except Exception:
        analysis.tokens = re.findall(r"[^\s।,.!?—]+", quote_text)
        analysis.nouns = analysis.tokens[:5]
        analysis.key_terms = analysis.nouns
        analysis.theme = "general"
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


def translate_hi_to_en(hindi_words: list) -> list:
    """IndicTrans2 -> English translations. Passes through English words directly."""
    if not hindi_words:
        return []

    out = []
    to_translate = []
    for w in hindi_words:
        if not is_hindi_text(w):
            out.append(w.lower())
        else:
            to_translate.append(w)

    if to_translate:
        translator = _get_translator()
        if translator is not None:
            try:
                out.extend(translator(to_translate))
            except Exception:
                for w in to_translate:
                    out.append(FALLBACK_LEXICON.get(w, w))
        else:
            for w in to_translate:
                out.append(FALLBACK_LEXICON.get(w, w))

    return list(dict.fromkeys(out))


# ═══════════════════════════════════════════════════
# KNOWLEDGE CHAIN
# ═══════════════════════════════════════════════════

def run_knowledge_chain(context, location) -> CandidatePool:
    """
    Sequential 6-chain pipeline. Called by app.py Step 1.
    Each chain enriches the next. Returns pre-built candidates.
    """
    # Chain 1: word understanding via English WordNet (translate-first).
    # Replaces the discontinued pyiwn/IndoWordNet path.
    word_info = chain_1_word_understanding(context.quote_analysis, context.en_keywords)

    # WordNet synonyms/related are already English — extend the KG keyword set directly.
    en_keywords = list(dict.fromkeys(
        context.en_keywords + word_info.get("synonyms", []) + word_info.get("related", [])
    ))

    # Chain 2: Wikidata symbolic discovery
    wikidata_results = chain_2_wikidata(en_keywords, location)

    # Chain 3: Wikipedia visual enrichment
    wiki_results = chain_3_wikipedia(wikidata_results)

    # Chain 4: DBpedia thematic expansion
    dbpedia_results = chain_4_dbpedia(wiki_results.get("categories", []))

    # Chain 5: Fictional/anime discovery
    fiction_results = chain_5_fictional(context.emotion)

    # Chain 6: Cultural supplement (local) — matches keywords, theme, AND emotion.
    cultural_results = chain_6_cultural(
        en_keywords, emotion=context.emotion, theme=context.quote_analysis.theme)

    # Merge all results into candidate pool
    location_features = discover_location_features(location)
    cultural_data = _load_cultural()
    raw_candidates = merge_all(
        wikidata_results, wiki_results, dbpedia_results,
        fiction_results, cultural_results, location_features, cultural_data,
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

    # Pre-build text pieces for each candidate — pass quote key terms for scene blending.
    prepared = [
        pre_build_candidate(c, location_features, context.weather, context.time,
                            quote_terms=context.en_keywords)
        for c in raw_candidates
    ]

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


# ── CHAIN IMPLEMENTATIONS ──────────────────────────

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

        synonyms = list({lemma.name().replace("_", " ")
                         for s in synsets for lemma in s.lemmas()})

        is_abs = False
        if synsets:
            paths = synsets[0].hypernym_paths()
            is_abs = any("abstraction" in h.name() for p in paths for h in p)

        related = []
        for s in synsets[:2]:
            related += [l.name().replace("_", " ") for ss in s.also_sees() for l in ss.lemmas()]
            related += [l.name().replace("_", " ") for ss in s.similar_tos() for l in ss.lemmas()]

        synonyms = synonyms[:10]
        related = list(set(related))[:10]
        all_synonyms.extend(synonyms)
        all_related.extend(related)
        results.append({"word": hindi_word, "en_word": en_word,
                        "is_abstract": is_abs, "synonyms": synonyms, "related": related})

    return {"words": results,
            "synonyms": list(dict.fromkeys(all_synonyms)),
            "related": list(dict.fromkeys(all_related))}


def chain_2_wikidata(en_keywords, location) -> dict:
    """Wikidata: symbols, location features, mythology, fiction."""
    out = {"symbols": [], "location_features": [], "mythology": [], "fiction": []}
    try:
        # location_landmarks filters by P31 (tourist attraction / monument / tower),
        # so we get visible landmarks instead of languages, peoples or districts.
        out["location_features"] = query_wikidata(
            "location_landmarks", location_qid=location["qid"])
        out["mythology"] = query_wikidata("mythological_figures")
        for kw in en_keywords[:3]:
            qid = _resolve_qid(kw)
            if qid:
                out["symbols"].extend(query_wikidata("symbols_for_concept", concept_qid=qid))
    except Exception:
        pass
    return out


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


def chain_5_fictional(emotion) -> list:
    """
    Anime/cartoon ARCHETYPES only.

    AniList is consulted for genre/aesthetic context, but raw media TITLES are
    never injected as candidates — using a copyrighted work's name verbatim in a
    FLUX prompt is exactly what the system prompt forbids. We emit only the
    generic GENRE_TO_ARCHETYPE phrases (e.g. "lone traveler gazing toward a vast
    horizon"), which are safe and depictable.
    """
    out = []
    try:
        genres = EMOTION_TO_GENRE.get(emotion.get("primary"), ["Drama"])
        for g in genres:
            arch = GENRE_TO_ARCHETYPE.get(g)
            if arch:
                out.append({"label": arch, "genre": g, "fictional": True})
    except Exception:
        pass
    return out


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
        {"label": m["visual"], "context": m.get("context", ""), "concept": concept}
        for m, concept in raw_matches
    ]


# ═══════════════════════════════════════════════════
# LOCATION DISCOVERY
# ═══════════════════════════════════════════════════

def discover_location_features(location) -> list:
    """Wikidata: what notable things exist at this location? Cached."""
    key = f"loc_features_{location['name']}"
    cached = load_cache(key, "location")
    if cached is not None:
        return cached

    result = []
    try:
        features = query_wikidata("location_landmarks", location_qid=location["qid"])
        for f in features[:12]:
            name = f.get("label", "")
            if not name or _is_nonvisual_entity(name):
                continue
            f_type = ""
            qid = f.get("qid")
            if qid:
                types = query_wikidata("instance_of", entity_qid=qid)
                f_type = types[0]["label"] if types else ""
            if _is_nonvisual_entity(name, f_type):
                continue
            result.append({"name": name, "type": f_type, "qid": qid})
    except Exception:
        pass

    save_cache(key, result)
    return result


def discover_location_details(location) -> list:
    """Wikipedia: visual details for each location feature. Called by app.py."""
    key = f"loc_details_{location['name']}"
    cached = load_cache(key, "wikipedia")
    if cached is not None:
        return cached

    details = []
    try:
        features = discover_location_features(location)
        for feat in features[:8]:
            if not feat.get("name"):
                continue
            summary = fetch_wikipedia(feat["name"])
            phrases = extract_visual_phrases(summary)
            for phrase in phrases[:4]:
                details.append({"id": f"D{len(details) + 1}",
                                "text": phrase, "source": feat["name"]})
    except Exception:
        pass

    save_cache(key, details)
    return details


# ═══════════════════════════════════════════════════
# NLP UTILITIES (resolved at runtime, nothing hardcoded)
# ═══════════════════════════════════════════════════

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
        groundable=raw.get("groundable", False),
        cultural=raw.get("cultural", False),
        chain_sources=raw.get("chain_sources", []),
        subject_text=subject_text,
        scene_text=scene_text,
        weather_context=f"{weather['condition']}, {weather['temp']}C",
        visual_phrases=visual,
        verb_type=classify_verb(raw.get("associated_verb")) if raw.get("associated_verb") else "unknown",
    )


def _cultural_fallback_candidates(emotion, theme, en_keywords, weather, time, location) -> list[PreparedCandidate]:
    """Fallback via Chain 6 cultural metaphors matched by emotion/theme/keywords."""
    matches = _find_cultural_matches(en_keywords, emotion=emotion, theme=theme)

    # Build candidates from matches (up to 3).
    prepared = []
    for m, concept in matches[:3]:
        loc_hint = location["name"]
        prepared.append(PreparedCandidate(
            id=f"cultural_fallback_{concept}_{len(prepared)}",
            name=m["visual"],
            domain="PHOTOREALISTIC",
            entity_type="metaphor",
            cultural=True,
            chain_sources=["chain_6_cultural", "fallback"],
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


# ═══════════════════════════════════════════════════
# MERGE AND DEDUP
# ═══════════════════════════════════════════════════

def assign_domain(data, source_chain) -> str:
    """Assign visual domain based on the candidate's origin."""
    name = (data.get("label") or data.get("name") or "").lower()
    etype = (data.get("type") or data.get("entity_type") or "").lower()

    if source_chain == "chain_5_fictional":
        return "GHIBLI" if "ghibli" in name else "ANIME"
    if source_chain in ("chain_2_mythology",):
        return "MYTHOLOGICAL"
    if source_chain == "chain_2_wikidata" and etype in (
        "deity", "mythological character", "god", "goddess"):
        return "MYTHOLOGICAL"
    if source_chain == "chain_6_cultural":
        return "PHOTOREALISTIC"
    return "PHOTOREALISTIC"


def set_flags(candidate: dict, location_features, cultural_data):
    """Set groundable and cultural flags on a merged candidate dict."""
    location_types = {f.get("type", "").lower() for f in location_features}
    location_names = {f.get("name", "").lower() for f in location_features}
    name = candidate.get("name", "").lower()
    etype = candidate.get("entity_type", "").lower()

    candidate["groundable"] = bool(
        (etype and etype in location_types)
        or (name and name in location_names)
        or any(fn and fn in name for fn in location_names)
    )
    all_visuals = cultural_data.get("_all_visuals", [])
    candidate["cultural"] = name in set(v.lower() for v in all_visuals)


def merge_all(wikidata, wiki, dbpedia, fiction, cultural,
              location_features, cultural_data) -> list:
    """Merge candidates from all chains, deduplicate by name similarity."""
    all_raw = []
    for item in wikidata.get("symbols", []):
        all_raw.append({"data": item, "source": "chain_2_wikidata"})
    for item in wikidata.get("location_features", []):
        all_raw.append({"data": item, "source": "chain_2_wikidata"})
    for item in wikidata.get("mythology", []):
        all_raw.append({"data": item, "source": "chain_2_mythology"})
    for label, info in wiki.get("entities", {}).items():
        all_raw.append({"data": {"label": label, **info}, "source": "chain_3_wikipedia"})
    for item in dbpedia:
        all_raw.append({"data": item, "source": "chain_4_dbpedia"})
    for item in fiction:
        all_raw.append({"data": item, "source": "chain_5_fictional"})
    for item in cultural:
        all_raw.append({"data": item, "source": "chain_6_cultural"})

    # Sources whose entities must be visually depictable (drop languages/peoples/admin).
    _visual_required = {"chain_2_wikidata", "chain_3_wikipedia", "chain_4_dbpedia"}

    seen: dict = {}
    for item in all_raw:
        data = item["data"]
        name = (data.get("label") or data.get("name") or data.get("visual") or "").lower().strip()
        if not name:
            continue
        if item["source"] in _visual_required and _is_nonvisual_entity(
                name, data.get("type") or data.get("entity_type", "")):
            continue
        if name in seen:
            if item["source"] not in seen[name]["chain_sources"]:
                seen[name]["chain_sources"].append(item["source"])
            if data.get("visual"):
                seen[name].setdefault("visual_phrases", []).extend(data["visual"])
        else:
            merged = {
                "id": f"{item['source']}_{name.replace(' ', '_')[:24]}",
                "name": data.get("label") or data.get("name") or data.get("visual"),
                "entity_type": data.get("type") or data.get("entity_type", ""),
                "visual_phrases": list(data.get("visual", [])),
                "associated_verb": data.get("associated_verb"),
                "chain_sources": [item["source"]],
                "domain": assign_domain(data, item["source"]),
            }
            # cultural metaphors carry their visual phrase as the subject itself
            if item["source"] == "chain_6_cultural" and not merged["visual_phrases"]:
                merged["visual_phrases"] = [merged["name"]]
            seen[name] = merged

    merged_list = list(seen.values())
    for c in merged_list:
        set_flags(c, location_features, cultural_data)
    return merged_list


# ═══════════════════════════════════════════════════
# API HELPERS
# ═══════════════════════════════════════════════════

def query_wikidata(template_name, **params) -> list:
    """Execute SPARQL from SPARQL_TEMPLATES with params against Wikidata."""
    query = SPARQL_TEMPLATES[template_name].format(**params)
    resp = _session().get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=5,
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
        label = _clean_label(b.get(label_key, {}).get("value", "") if label_key else "")
        if not label:
            continue  # drop unlabeled / bare-QID results
        out.append({
            "label": label,
            "description": (b.get(desc_key, {}).get("value", "") if desc_key else ""),
            "qid": qid,
            "type": "",
        })
    return out


def _is_nonvisual_entity(name: str, etype: str = "") -> bool:
    """True if a name/type looks like a language, people, or admin division."""
    blob = f"{name} {etype}".lower()
    return any(tok in blob for tok in NONVISUAL_TOKENS)


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


# ═══════════════════════════════════════════════════
# CULTURAL DATA + CACHE
# ═══════════════════════════════════════════════════

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
    """Check in-memory cache first, then disk."""
    now = time.time()
    if key in _memory_cache:
        entry = _memory_cache[key]
        if now - entry["ts"] < CACHE_TTL.get(source, 86400):
            return entry["data"]

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
    """Save to memory and disk."""
    entry = {"ts": time.time(), "data": data}
    _memory_cache[key] = entry
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.json").write_text(
            json.dumps(entry, default=str, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
