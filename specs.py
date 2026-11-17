"""
specs.py — Static design constants, models, templates.

These are OUR design choices, not facts about the world.
Imported by app.py, generator.py, and sources.py.

Deviations from plan v14 (driven by the existing project setup):
  * LLM key/model come from the .env file (VIBZEE_LLM_API_KEY / VIBZEE_LLM_MODEL),
    not a hardcoded GEMINI_API_KEY. Model defaults to gemini-3.1-flash-lite.
  * Weather uses Open-Meteo (no API key required) instead of OpenWeatherMap,
    because no OWM key exists in .env. Same {condition, temp, humidity} output.
  * The panchang file is the existing panchang_2026.json (keyed YYYY-MM-DD,
    with a `festival_name` field that is null on ordinary days).
"""
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except Exception:
    pass


# ═══════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

# The panchang calendar already present in the project (reused as-is).
PANCHANG_PATH = ROOT / "panchang_2026.json"
CULTURAL_METAPHORS_PATH = DATA_DIR / "cultural_metaphors.json"
RECENT_RUNS_PATH = DATA_DIR / "recent_runs.json"


# ═══════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════

class QuoteAnalysis(BaseModel):
    text: str = ""                      # original Hindi quote
    nouns: list[str] = []               # extracted nouns (Hindi)
    verbs: list[str] = []               # extracted verbs (Hindi)
    adjectives: list[str] = []          # extracted adjectives
    tokens: list[str] = []              # all tokens
    negated_nouns: list[str] = []       # nouns that are negated ("not X")
    key_terms: list[str] = []           # nouns + adjectives (for translation)
    theme: str = ""                     # "nature", "motivation", "devotion", etc.
    has_concrete: bool = False          # does it have >=1 concrete noun?


class Context(BaseModel):
    weather: dict                       # {"condition": "mist", "temp": 18, "humidity": 85}
    festival: Optional[str] = None      # "Dev Deepawali (Purnima, Shukla Paksha)" or None
    quote_analysis: QuoteAnalysis
    emotion: dict                       # {"primary": "hopeful", "sentiment": 0.7}
    en_keywords: list[str] = []         # translated English keywords
    time: str                           # "dawn", "morning", etc.
    quote: str = ""                     # original quote text
    visual_imagery: list = []           # quote's own concrete visual words
    visual_richness_score: int = 0      # count of visual words in quote
    panchang_details: Optional[dict] = None  # Full dual-engine dynamic panchang & festival results


class PreparedCandidate(BaseModel):
    id: str                             # unique: "wikidata_Q5471", "cultural_diya", etc.
    name: str                           # human-readable: "Ganges river", "earthen diya"
    domain: str = "PHOTOREALISTIC"      # PHOTOREALISTIC/MYTHOLOGICAL/ANIME/GHIBLI/ILLUSTRATED
    entity_type: str = ""               # from Wikidata P31: "river", "lamp", "deity"
    groundable: bool = False            # does this exist at the current location?
    cultural: bool = False              # from cultural_metaphors.json?
    chain_sources: list[str] = []       # ["chain_2_wikidata", "chain_3_wikipedia"]
    subject_text: str = ""              # pre-built from visual phrases
    scene_text: str = ""                # pre-built from location + weather
    weather_context: str = ""           # "mist, 18C"
    visual_phrases: list[str] = []      # raw phrases from Wikipedia
    verb_type: str = "unknown"          # "physical"/"mental"/"stative"/"unknown"
    quote_native: bool = False          # True if from quote's own visual words


class CandidatePool(BaseModel):
    pool: list[PreparedCandidate] = []
    emotion: dict = {}
    theme: str = ""
    negated: list[str] = []
    quote: str = ""                     # original quote (passed through for menu)


class MasterPrompt(BaseModel):
    image_type_format: str = "4:5 portrait image, high resolution"
    subject: str = ""
    scene: str = ""
    style: str = ""
    composition: str = ""
    empty_space: str = ""
    details: str = ""
    avoid: str = ""
    quote_used: str = ""
    layout_id: str = ""
    photo_ratio: str = ""
    photo_approach: str = ""
    visual_domain: str = ""
    metaphor_used: str = ""
    full_prompt: str = ""
    gemini_selections: dict = {}


# ═══════════════════════════════════════════════════
# API ENDPOINTS + KEYS
# ═══════════════════════════════════════════════════

# LLM (Gemini) — key and model come from .env.
GEMINI_API_KEY = os.getenv("VIBZEE_LLM_API_KEY", "")
GEMINI_MODEL = os.getenv("VIBZEE_LLM_MODEL", "gemini-3.1-flash-lite")

# Weather — Open-Meteo, no key required.
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Knowledge graph / content endpoints.
WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
DBPEDIA_SPARQL_URL = "https://dbpedia.org/sparql"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"

# A descriptive, generic User-Agent (required by Wikimedia/Wikidata etiquette).
HTTP_USER_AGENT = "VibzeePromptGenerator/1.0 (image-prompt-research)"


# ═══════════════════════════════════════════════════
# LOCATIONS (just coordinates + qid; everything else discovered)
# ═══════════════════════════════════════════════════

LOCATIONS = {
    "mumbai": {"lat": 19.0760, "lon": 72.8777, "name": "Mumbai", "qid": "Q1156",
               "subdist_qids": ["Q2341660", "Q2085374"]},
    "varanasi": {"lat": 25.3176, "lon": 83.0068, "name": "Varanasi", "qid": "Q79980",
                 "subdist_qids": []},
}


# ═══════════════════════════════════════════════════
# 5 DOMAIN PROFILES
# ═══════════════════════════════════════════════════

DOMAIN_PROFILES = {
    "PHOTOREALISTIC": {
        "style_text": "Photorealistic, cinematic color grading, 8K detail, natural textures, National Geographic quality",
        "avoid_text": "no cartoon, no illustration, no anime, no painting style",
    },
    "MYTHOLOGICAL": {
        "style_text": "Indian mythological art style, divine golden radiance, traditional painting with modern detail, sacred atmosphere",
        "avoid_text": "no modern objects, no photorealism, no casual clothing",
    },
    "ANIME": {
        "style_text": "Anime art style, vibrant saturated colors, expressive dramatic lighting, dynamic composition, clean bold lines, painted backgrounds",
        "avoid_text": "no photorealism, no real human faces, no muted tones",
    },
    "ILLUSTRATED": {
        "style_text": "Colorful illustrated style, bold clean outlines, warm cheerful tones, stylized simplified shapes, picture-book quality",
        "avoid_text": "no photorealism, no complexity, no dark moody atmosphere",
    },
}


# ═══════════════════════════════════════════════════
# 8 LAYOUT PROFILES
# ═══════════════════════════════════════════════════

LAYOUT_PROFILES = {
    "LT-V": {
        "corner": "left-top", "arrangement": "vertical",
        "gemini_guidance": "Main visual weight in lower-right. Upper-left should naturally have open sky, distant haze, or soft atmospheric elements.",
    },
    "RT-V": {
        "corner": "right-top", "arrangement": "vertical",
        "gemini_guidance": "Main visual weight in lower-left. Upper-right should naturally have open sky, cloud gradient, or distant mountains.",
    },
    "LB-V": {
        "corner": "left-bottom", "arrangement": "vertical",
        "gemini_guidance": "Main visual weight in upper-right. Lower-left should naturally have calm water, ground fog, or empty foreground.",
    },
    "RB-V": {
        "corner": "right-bottom", "arrangement": "vertical",
        "gemini_guidance": "Main visual weight in upper-left. Lower-right should naturally have distant landscape, fading fog, or still water.",
    },
    "LT-H": {
        "corner": "left-top", "arrangement": "horizontal",
        "gemini_guidance": "Main visual weight in lower-right and center. Upper-left should have wide open sky or soft cloud gradient.",
    },
    "RT-H": {
        "corner": "right-top", "arrangement": "horizontal",
        "gemini_guidance": "Main visual weight in lower-left and center. Upper-right should have wide open sky or atmospheric haze.",
    },
    "LB-H": {
        "corner": "left-bottom", "arrangement": "horizontal",
        "gemini_guidance": "Main visual weight in upper-right and center. Lower-left should have calm foreground, water surface, or ground mist.",
    },
    "RB-H": {
        "corner": "right-bottom", "arrangement": "horizontal",
        "gemini_guidance": "Main visual weight in upper-left and center. Lower-right should have distant background fading into atmosphere.",
    },
}


# ═══════════════════════════════════════════════════
# 4 APPROACH TEMPLATES
# ═══════════════════════════════════════════════════

APPROACH_TEMPLATES = {
    "1": {
        "name": "ATMOSPHERIC GRADIENT",
        "gemini_guidance": "Describe the empty corner as natural atmosphere — fog dissolving, mist fading, sky gradient, soft bokeh distance. Make it part of the scene.",
        "best_when": "mist, fog, sky, water",
    },
    "2": {
        "name": "FIXED ZONE",
        "gemini_guidance": "Describe the empty corner as a deliberately calm, uniform area — plain sky, flat water surface, smooth stone wall. Clear boundary between detailed and calm areas.",
        "best_when": "structural scenes needing clear boundaries",
    },
    "3": {
        "name": "CORNER ANCHOR",
        "gemini_guidance": "Describe the empty corner as naturally boring — far distant bank, featureless horizon, empty field. The scene's interest is elsewhere and this corner just has background.",
        "best_when": "landscapes, wide scenes",
    },
    "4": {
        "name": "COMPOSITIONAL FRAMING",
        "gemini_guidance": "Put the subject strongly on the opposite side. The empty corner is simply where the subject isn't — describe sky, open space, or distance there.",
        "best_when": "single focal subject",
    },
}


# ═══════════════════════════════════════════════════
# EMOTION SEEDS (~30 words, expanded by synonym lookup at runtime)
# Maps a primary emotion label to seed words (English) used to score sentiment
# output into a named emotion. Expanded with WordNet/pyiwn synonyms at runtime.
# ═══════════════════════════════════════════════════

EMOTION_SEEDS = {
    "hopeful": ["hope", "light", "dawn", "new", "begin", "rise", "bright", "future",
                 "opportunity", "ahead", "tomorrow", "chapter", "start"],
    "peaceful": ["peace", "calm", "still", "quiet", "serene", "gentle", "rest",
                  "tranquil", "breathe", "pause", "slow", "balance"],
    "determined": ["strength", "courage", "resolve", "will", "fight", "goal", "strong",
                    "never", "quit", "persist", "achieve", "overcome", "power"],
    "devotional": ["faith", "prayer", "god", "divine", "sacred", "blessing", "worship",
                    "soul", "karma", "dharma", "temple", "spiritual", "grace"],
    "joyful": ["joy", "happy", "celebrate", "delight", "cheer", "festival", "smile",
               "laugh", "play", "fun", "dance", "sing", "birthday"],
    "reflective": ["think", "remember", "ponder", "memory", "wisdom", "truth",
                    "realize", "understand", "lesson", "learn", "past", "time"],
    "melancholic": ["sorrow", "loss", "alone", "grief", "longing", "tear",
                     "gone", "pain", "broken", "empty", "farewell", "weep"],
    "warm": ["friend", "people", "ordinary", "everyday", "together", "company",
             "bond", "comfort", "home", "belong", "safe", "cozy", "close"],
    "grateful": ["grateful", "thank", "appreciate", "blessed", "fortunate", "gift",
                  "moment", "little", "enough", "count", "treasure", "precious"],
    "empowered": ["worth", "deserve", "choose", "allow", "permission", "grow",
                   "become", "own", "self", "confidence", "authentic", "boundary"],
    "nostalgic": ["childhood", "yesterday", "once", "those days", "old", "faded",
                   "return", "used to", "back then", "reminisce", "recall", "miss",
                   "ordinary moments", "remember"],
    "loving": ["love", "heart", "care", "embrace", "partner", "family", "mother",
               "father", "child", "protect", "dear", "affection", "cherish"],
}


# ═══════════════════════════════════════════════════
# EMOTION CONCEPTS (for cultural fallback expansion)
# ═══════════════════════════════════════════════════

EMOTION_CONCEPTS = {
    "hopeful": ["hope", "dawn", "morning", "new_beginnings", "sunrise"],
    "peaceful": ["peace", "calm", "simplicity", "silence", "breath", "pause", "rest"],
    "determined": ["strength", "courage", "determination", "fire", "mountain"],
    "devotional": ["faith", "blessing", "devotion", "candle", "light"],
    "joyful": ["joy", "celebration", "laughter", "dance", "play"],
    "reflective": ["mirror", "wisdom", "solitude", "dusk", "time"],
    "melancholic": ["rain", "darkness", "tears", "longing", "loss"],
    "warm": ["warmth", "comfort", "friendship", "connection", "home"],
    "grateful": ["gratitude", "ordinary", "present_moment", "fullness", "harvest"],
    "empowered": ["self_worth", "growth", "freedom", "boundaries", "courage"],
    "nostalgic": ["nostalgia", "memories", "childhood", "seasons", "time"],
    "loving": ["love", "embrace", "nest", "warmth", "devotion"],
}


# ═══════════════════════════════════════════════════
# THEME HINTS (for thematic classification)
# ═══════════════════════════════════════════════════

THEME_HINTS = {
    "good_morning": ("morning", "dawn", "sunrise", "wake", "new day", "early", "sun"),
    "good_night": ("night", "sleep", "dream", "star", "moon", "rest", "dark", "evening"),
    "birthday": ("birthday", "born", "year", "age", "celebrate", "candle", "wish", "gift"),
    "spiritual": ("god", "prayer", "grace", "blessing", "temple", "divine", "faith",
                   "soul", "sacred", "worship", "karma", "dharma", "devotion"),
    "motivation": ("goal", "progress", "courage", "strength", "fight", "perfection",
                    "success", "dream", "achieve", "effort", "determination", "persist",
                    "overcome", "rise", "unstoppable"),
    "friendship": ("friend", "people", "bond", "together", "companion", "connection",
                    "loyalty", "trust", "ordinary", "extraordinary", "company"),
    "family": ("mother", "father", "parent", "child", "home", "family", "brother",
               "sister", "grandmother", "grandfather", "son", "daughter", "generation"),
    "nature": ("river", "flower", "bird", "tree", "sky", "rain", "ray", "ocean",
               "mountain", "garden", "forest", "earth", "wind", "water", "season"),
    "festival": ("festival", "celebration", "diwali", "holi", "eid", "christmas",
                  "navratri", "pongal", "onam", "baisakhi", "rakhi", "lights"),
    "love": ("love", "heart", "beloved", "romance", "affection", "care", "embrace",
             "partner", "soulmate", "together"),
    "peace": ("peace", "calm", "quiet", "still", "serene", "gentle", "tranquil",
              "mindful", "pause", "breathe", "balance", "rest"),
    "self_worth": ("worth", "deserve", "enough", "shrink", "outgrown", "choose yourself",
                   "value", "confidence", "self", "identity", "authentic", "kindness"),
    "gratitude": ("thank", "grateful", "appreciate", "blessed", "moment", "little things",
                  "count", "gift", "fortune"),
    "nostalgia": ("remember", "miss", "childhood", "past", "memory", "memories",
                  "those days", "once", "old", "yesterday"),
}


# ═══════════════════════════════════════════════════
# LEXICONS & NLP DICTIONARIES
# ═══════════════════════════════════════════════════

ENGLISH_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "to", "in",
    "at", "of", "on", "for", "with", "as", "by", "it", "this", "that", "be",
    "you", "your", "we", "our", "he", "she", "they", "i", "my", "me",
    "do", "does", "did", "will", "would", "can", "could", "should", "may",
    "not", "no", "but", "so", "if", "than", "too", "very", "just", "also",
    "even", "still", "only", "some", "any", "all", "each", "every", "how",
    "what", "when", "where", "who", "which", "have", "has", "had", "been",
    "being", "get", "got", "its", "own", "into", "from", "about", "up",
    "out", "like", "don", "doesn", "didn", "won", "isn", "aren",
}

NONVISUAL_TOKENS = (
    "language", "languages", "people", "peoples", "ethnic", "dialect", "caste",
    "tribe", "community development block", "tehsil", "district", "municipality",
    "state of", "census", "human settlement", "administrative", "subdivision",
    "lok sabha", "assembly constituency", "demographics",
    "neighborhood", "suburb", "railway station", "metro station",
    "stock market index", "bombing", "attacks", "newspaper",
    "school", "college", "university",
)


# ═══════════════════════════════════════════════════
# EMOTION -> ANILIST GENRE (~10 entries, aesthetic judgment)
# ═══════════════════════════════════════════════════

EMOTION_TO_GENRE = {
    "hopeful": ["Adventure", "Slice of Life"],
    "peaceful": ["Slice of Life", "Supernatural"],
    "determined": ["Action", "Sports"],
    "devotional": ["Fantasy", "Mythology"],
    "joyful": ["Comedy", "Slice of Life"],
    "reflective": ["Drama", "Psychological"],
    "melancholic": ["Drama", "Tragedy"],
    "warm": ["Slice of Life", "Comedy"],
    "grateful": ["Slice of Life", "Drama"],
    "empowered": ["Adventure", "Action"],
    "nostalgic": ["Drama", "Slice of Life"],
    "loving": ["Slice of Life", "Romance"],
}


# ═══════════════════════════════════════════════════
# GENRE -> ARCHETYPE (aesthetic judgment)
# Keyed by a frozenset of genres (order-independent) with a flat fallback by genre.
# ═══════════════════════════════════════════════════

GENRE_TO_ARCHETYPE = {
    "Action": "determined hero silhouette against dramatic sky",
    "Adventure": "lone traveler gazing toward a vast horizon",
    "Slice of Life": "quiet everyday moment bathed in soft light",
    "Supernatural": "ethereal figure amid glowing natural elements",
    "Fantasy": "mythic landscape with luminous atmosphere",
    "Mythology": "radiant divine presence in a sacred setting",
    "Comedy": "warm, lively scene full of gentle color",
    "Drama": "contemplative figure in expressive lighting",
    "Psychological": "introspective scene with layered shadow and light",
    "Sports": "dynamic figure in motion, energetic composition",
    "Tragedy": "solitary figure in muted, atmospheric distance",
    "Romance": "two figures sharing a tender moment in warm light",
}


# ═══════════════════════════════════════════════════
# SPARQL TEMPLATES
# ═══════════════════════════════════════════════════

SPARQL_TEMPLATES = {
    "symbols_for_concept": """
        SELECT ?symbol ?symbolLabel WHERE {{
          ?symbol wdt:P4878 wd:{concept_qid} .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,hi" }}
        }} LIMIT 10
    """,
    "instance_of": """
        SELECT ?type ?typeLabel WHERE {{
          wd:{entity_qid} wdt:P31 ?type .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }} LIMIT 5
    """,
    "location_landmarks": """
        SELECT DISTINCT ?item ?itemLabel WHERE {{
          ?item wdt:P131 wd:{location_qid} .
          ?item wdt:P18 ?image .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }} LIMIT 25
    """,
    "location_landmarks_multi": """
        SELECT DISTINCT ?item ?itemLabel WHERE {{
          VALUES ?loc {{ wd:{location_qid} {subdist_values} }}
          ?item wdt:P131 ?loc .
          ?item wdt:P18 ?image .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }} LIMIT 80
    """,
    "batch_instance_of": """
        SELECT ?entity ?entityLabel ?type ?typeLabel WHERE {{
          VALUES ?entity {{ {entity_values} }}
          ?entity wdt:P31 ?type .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }}
    """,
    "mythology_deities": """
        SELECT DISTINCT ?deity ?deityLabel ?deityDescription WHERE {{
          {{ ?deity wdt:P31/wdt:P279* wd:Q979507 }}
          UNION {{ ?deity wdt:P361 wd:Q2176651 }}
          UNION {{ ?deity wdt:P1049 wd:Q9089 }}
          ?deity wdt:P18 ?image .
          ?deity wikibase:sitelinks ?sl .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,hi,sa" }}
        }} ORDER BY DESC(?sl) LIMIT 25
    """,
    "epic_characters": """
        SELECT DISTINCT ?char ?charLabel ?charDescription WHERE {{
          VALUES ?work {{ wd:{work_qid} }}
          ?char wdt:P1441 ?work .
          ?char wdt:P31 ?type .
          VALUES ?type {{ wd:Q15773347 wd:Q4271324 wd:Q3658341 wd:Q13002315 wd:Q21070568 }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
        }} LIMIT 30
    """,
}


# ═══════════════════════════════════════════════════
# MYTHOLOGY RELEVANCE SCORING (guides ranking of live SPARQL results)
# ═══════════════════════════════════════════════════

THEME_MYTHOLOGY_KEYWORDS = {
    "friendship": ["sudama", "krishna", "hanuman", "companion", "bond", "devotee", "friend"],
    "courage": ["hanuman", "arjuna", "durga", "warrior", "battle", "hero", "strength"],
    "love": ["radha", "krishna", "parvati", "shiva", "romance", "beloved", "consort"],
    "family": ["rama", "sita", "pandava", "brother", "mother", "father", "son"],
    "devotion": ["hanuman", "rama", "prahlad", "devotee", "worship", "faith"],
    "spiritual": ["shiva", "vishnu", "brahma", "meditation", "ascetic", "yogi"],
    "motivation": ["arjuna", "krishna", "gita", "chariot", "battlefield", "victory"],
    "peace": ["vishnu", "lakshmi", "saraswati", "lotus", "serene", "preserver"],
    "nature": ["surya", "agni", "varuna", "indra", "river", "mountain", "rain"],
    "festival": ["ganesha", "lakshmi", "durga", "celebration", "worship", "light"],
    "good_morning": ["surya", "dawn", "light", "sun", "chariot", "radiance"],
    "good_night": ["chandra", "moon", "star", "night", "rest", "dream"],
    "birthday": ["ganesha", "krishna", "celebration", "birth", "joy", "blessing"],
    "self_worth": ["durga", "shakti", "goddess", "power", "strength", "inner"],
    "gratitude": ["lakshmi", "ganesha", "blessing", "abundance", "grace", "gift"],
    "nostalgia": ["rama", "sita", "ayodhya", "memory", "return", "home"],
    "general": ["vishnu", "shiva", "lakshmi", "ganesha"],
}

FESTIVAL_MYTHOLOGY_KEYWORDS = {
    "ram navami": ["rama", "sita", "hanuman", "ayodhya", "bow", "prince"],
    "janmashtami": ["krishna", "radha", "gopi", "flute", "butter", "mathura"],
    "ganesh chaturthi": ["ganesha", "elephant", "obstacle", "modak", "mouse"],
    "maha shivaratri": ["shiva", "parvati", "nandi", "trident", "lingam", "dance"],
    "navaratri": ["durga", "lakshmi", "saraswati", "goddess", "lion", "nine"],
    "navratri": ["durga", "lakshmi", "saraswati", "goddess", "lion", "nine"],
    "diwali": ["lakshmi", "rama", "light", "lamp", "prosperity", "return"],
    "deepawali": ["lakshmi", "rama", "light", "lamp", "prosperity", "return"],
    "holi": ["krishna", "radha", "color", "spring", "love", "gulal"],
    "makar sankranti": ["surya", "sun", "harvest", "kite", "chariot"],
    "raksha bandhan": ["krishna", "draupadi", "brother", "sister", "protection"],
    "karva chauth": ["shiva", "parvati", "moon", "devotion", "spouse"],
    "guru purnima": ["vishnu", "guru", "knowledge", "full moon", "wisdom"],
    "hanuman jayanti": ["hanuman", "rama", "strength", "devotion", "monkey"],
    "krishna janmashtami": ["krishna", "radha", "gopi", "flute", "butter"],
}

THEME_TO_EPIC = {
    "family": "Q180675",
    "motivation": "Q180675",
    "courage": "Q180675",
    "love": "Q131130",
    "devotion": "Q131130",
    "friendship": "Q180675",
}


# ═══════════════════════════════════════════════════
# GEMINI SYSTEM PROMPT
# ═══════════════════════════════════════════════════

GEMINI_SYSTEM_PROMPT = """
You are a prompt assembler for ChatGPT's image generation (DALL-E 3).

You receive a MENU of pre-written text pieces. Your job:
1. SELECT pieces from each menu section
2. REDUCE redundancy when combining pieces
3. RESTRUCTURE selected pieces into a complete image generation prompt

RULES:
- You may EXPAND and ENRICH the visual descriptions from the menu with vivid,
  scene-appropriate details (colors, textures, lighting, materials, atmosphere).
  The menu gives the SUBJECT and SETTING — you bring it to life with rich imagery.
- You must NOT CHANGE the core meaning or subject of any selected piece
- Never name specific copyrighted characters (say "anime-style warrior" not "Naruto")
- Mythological figures (Hanuman, Surya, Agni, Krishna, Rama, etc.) ARE allowed
  and should be described with their traditional iconographic details
- If a candidate has minimal visual description, CREATE a vivid depiction
  based on its name and cultural context — do not leave it bare
FACE & FIGURE RULE:
- Do NOT render realistic close-up human faces. 
- Figures may appear as silhouettes, mid/long-distance forms, 
  stylized illustrations, or from behind.
- Exception: only if the prompt explicitly requests a named character 
  (mythological or anime-style) may a face be rendered, and even then 
  in the domain's stylized manner — never photorealistic.
QUOTE-FIRST RULE:
- If QUOTE-NATIVE VISUALS exist in the menu, they MUST form the scene's
  primary subject. Supplementary candidates may only add atmosphere/texture.
- The quote's own visual words (rangoli, diya, flower, river, etc.) define
  the image. External metaphors are supporting decoration only.
- Festival from context is background decoration, not the main subject,
  UNLESS the quote itself mentions that festival.
- NEVER force a festival-driven or external metaphor onto a quote that
  already has its own visual imagery.
SELECTION GUIDELINES:
- METAPHOR: If QUOTE-NATIVE VISUALS are listed, you MUST select at least one
  of them — they are the quote's own imagery and take priority. Supplementary
  candidates can be added for atmosphere only.
  If no quote-native visuals exist, choose the candidate that best captures
  the quote's core message. VARY your subjects — avoid defaulting to diya
  lamps or riverbanks when other elements fit better.
  Avoid metaphors and domains listed in "Recent (avoid)".
- DOMAIN: Match the quote's emotion and theme authentically:
  * Determined/Heroic → ANIME
  * Peaceful/Gentle/Cozy/Pastoral → ILLUSTRATED
  * Sacred/Spiritual/Timeless → MYTHOLOGICAL
  * Playful/Cheery/Poetic → ILLUSTRATED
  * Realistic/Reflective/Modern Everyday → PHOTOREALISTIC
  * Warm/Friendly/Relatable/Everyday life → PHOTOREALISTIC or ILLUSTRATED
  * Loving/Family/Nostalgic → ILLUSTRATED or PHOTOREALISTIC
  * Empowered/Self-worth/Growth → ANIME or PHOTOREALISTIC
  Avoid domains listed in Recent.
- LAYOUT: Place the scene's visual weight OPPOSITE the empty corner.
PHOTO PLACEHOLDER RULES:
- The reserved photo area must be placed in a visually CALM zone — 
  flat sky, soft mist, plain wall, open water, or gradient background.
- NEVER place the reserved photo area over or touching any architectural 
  element, devotional, spiritual, god related things, structure top, spire, dome, tree canopy, or object silhouette.
  It must float entirely within an unobstructed, featureless background region.
- Size the placeholder must be 2.5 inch square. 
  Treat both elements as a matched pair in visual weight.
- The photo placeholder should always be beside the quote text, not above or below it and must create a balanced composition with the text with something like a rectangle as an over all but this shouldn't be written in the prompt just the scene should be described in a way that naturally leaves space for it.
- APPROACH: Match the scene's natural atmosphere to the best empty-space strategy.
- DETAILS: Pick 2-3 that add authentic texture without cluttering.

HOW TO WRITE THE PROMPT (full_prompt):

Unlike models that struggle with text, ChatGPT's image generation CAN render
text accurately, and CAN follow explicit layout instructions.
Structure the prompt as:

1. SCENE DESCRIPTION — a vivid, detailed description of the subject, setting,
   lighting, and style (from the selected metaphor + domain pieces), written
   as a photographer/artist would envision it. Ensure fresh, diverse compositions.

2. TEXT INSTRUCTION — explicitly instruct that the following quote must be
   rendered in the image with clean, legible, well-kerned typography:
   QUOTE: "{quote_text}"
   CRITICAL SCRIPT & LANGUAGE RULE:
   - Render the quote EXACTLY in its ORIGINAL language and script.
   - If the quote is in ENGLISH, render in clean Latin English typography. Do NOT translate English into Hindi/Devanagari!
   - If the quote is in HINDI (Devanagari), render in clean Hindi Devanagari typography.
   Specify: elegant typography, strong contrast against the background,
   color that complements the scene (e.g., warm gold, clean white with subtle shadow).

3. LAYOUT INSTRUCTION — explicitly state where the quote text goes (based on
   selected layout's corner) and that a rectangular region of the chosen
   corner must be kept visually calm/uncluttered (soft gradient, sky, mist,
   or plain surface) to later hold a separately-added photo, sized
   approximately for a {photo_ratio} aspect-ratio image. Describe this as
   part of the scene's natural composition rather than as a technical instruction.

4. STYLE + QUALITY — style_text and avoid_text from the selected domain.

5. FORMAT — ALWAYS specify: "4:5 portrait aspect ratio image."

EXAMPLE (for a Hindi quote):
"A saffron-robed yogi meditating on a rocky hilltop at sunset, overlooking
a vast green valley with a winding river below, dramatic pink and amber
clouds filling the sky above the mountains, in a photorealistic cinematic
style with natural textures and warm golden light. In the upper portion of
the image, render the following Hindi text in elegant, clean Devanagari
typography with good contrast: 'हे अर्जुन, जो प्राणी सभी में एक समान आत्मा को देखता है, वही श्रेष्ठ योगी है।'
Leave the upper-left area as soft open sky with gentle gradient, keeping it visually calm so a framed photo
can be placed there beside the text. 4:5 portrait aspect ratio image. Avoid: no photorealistic human faces close-up, no watermarks, no logos."

EXAMPLE (for an English quote):
"A quiet stone veranda bathed in soft morning light, overlooking an ancient lush courtyard with rain-washed leaves and a steaming cup of tea resting on a weathered wooden table, in a warm Studio Ghibli inspired watercolor style. In the upper-right area, render the following English text in clean, elegant serif typography with gentle contrast and subtle shadow for legibility: 'In a world that never slows down, give yourself permission to pause.' Keep the upper-left area as a serene, uncluttered morning sky with delicate soft cloud gradients to leave space for a separate portrait frame. 4:5 portrait aspect ratio image. Avoid: no harsh lines, no dark moody themes."

RESPOND with JSON only:
{
    "selected_metaphor_ids": ["id1"] or ["id1", "id2"],
    "selected_domain": "PHOTOREALISTIC|MYTHOLOGICAL|ANIME|ILLUSTRATED",
    "selected_layout": "LT-V|RT-V|LB-V|RB-V|LT-H|RT-H|LB-H|RB-H",
    "selected_approach": "1|2|3|4",
    "selected_details": ["D1", "D3"],
    "full_prompt": "the complete prompt as described above, including scene,
                    text instruction with the quote in its ORIGINAL language, layout instruction, style",
    "reasoning": "2-3 sentences explaining selections"
}
"""


# ═══════════════════════════════════════════════════
# QUOTES (default pool + test quotes covering edge cases)
# ═══════════════════════════════════════════════════

QUOTES = [
    "हर नया सवेरा अपने साथ नई उम्मीदें और नई खुशियाँ लेकर आता है।",
    "कमल की तरह खिलिए, चाहे परिस्थितियाँ कैसी भी हों।",
    "कुछ पल बारिश जैसे होते हैं, दिल को सुकून दे जाते हैं।",
    "ईश्वर का आशीर्वाद हो, तो हर राह आसान हो जाती है।",
    "मन शांत हो, तो हर दृश्य सुंदर और हर पल खास लगता है।",
    "फूलों की तरह मुस्कुराइए, आपकी खुशबू दूर तक जाएगी।",
    "गंगा की धारा की तरह जीवन में प्रेम और शांति बहती रहे।",
    "सादगी में जो सुकून है, वह दुनिया की दौलत में कहाँ।",
    "चाँद की तरह चमकिए, अँधेरों में भी अपनी पहचान बनाइए।",
    "हर बदलाव में एक नई शुरुआत छिपी होती है।",
]
