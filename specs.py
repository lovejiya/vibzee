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


# PATHS

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

# The panchang calendar already present in the project (reused as-is).
PANCHANG_PATH = DATA_DIR / "panchang_2026.json"
CULTURAL_METAPHORS_PATH = DATA_DIR / "cultural_metaphors.json"
RECENT_RUNS_PATH = DATA_DIR / "recent_runs.json"
LANDMARK_DB_PATH = DATA_DIR / "landmark_db.json"
STATIC_CALENDAR_PATH = DATA_DIR / "static_calendar.json"


# MODELS

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
    landmark_selection: Optional[dict] = None  # Chosen landmark + scoring metadata


class PreparedCandidate(BaseModel):
    id: str                             # unique: "wikidata_Q5471", "cultural_diya", etc.
    name: str                           # human-readable: "Ganges river", "earthen diya"
    domain: str = "PHOTOREALISTIC"      # PHOTOREALISTIC/MYTHOLOGICAL/ANIME/GHIBLI/ILLUSTRATED
    entity_type: str = ""               # from Wikidata P31: "river", "lamp", "deity"
    cultural: bool = False              # from cultural_metaphors.json?
    chain_sources: list[str] = []       # ["chain_2_wikidata", "chain_3_wikipedia"]
    selection_context: str = ""         # why this subject was offered
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


class BoundingBox(BaseModel):
    x: float          # left edge, 0.0–1.0
    y: float          # top edge, 0.0–1.0
    w: float          # width, 0.0–1.0
    h: float          # height, 0.0–1.0

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h

    def overlaps(self, other: "BoundingBox") -> bool:
        return not (self.right <= other.x or other.right <= self.x
                    or self.bottom <= other.y or other.bottom <= self.y)

    def overlap_area(self, other: "BoundingBox") -> float:
        dx = max(0, min(self.right, other.right) - max(self.x, other.x))
        dy = max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        return dx * dy


class ProtectedRegion(BaseModel):
    label: str = ""               # e.g. "deity_face", "dome_apex"
    box: BoundingBox
    rule: str = "no_overlap"      # "no_overlap" | "partial_ok"


class LayoutPlan(BaseModel):
    layout_id: str = ""
    quote_box: Optional[BoundingBox] = None
    photo_box: Optional[BoundingBox] = None
    protected_regions: list[ProtectedRegion] = []
    visual_weight_zone: str = ""  # human description: "lower-right", "upper-left"
    validation_passed: bool = False
    repair_applied: bool = False
    repair_reason: str = ""


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
    layout_plan: Optional[LayoutPlan] = None


# API ENDPOINTS + KEYS

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


# LOCATIONS (just coordinates + qid; everything else discovered)

LOCATIONS = {
    # Maharashtra
    "mumbai": {"lat": 19.0760, "lon": 72.8777, "name": "Mumbai", "state": "maharashtra"},
    "pune": {"lat": 18.5204, "lon": 73.8567, "name": "Pune", "state": "maharashtra"},
    "nashik": {"lat": 19.9975, "lon": 73.7898, "name": "Nashik", "state": "maharashtra"},
    "aurangabad": {"lat": 19.8762, "lon": 75.3433, "name": "Aurangabad", "state": "maharashtra"},
    "kolhapur": {"lat": 16.7050, "lon": 74.2433, "name": "Kolhapur", "state": "maharashtra"},
    "nagpur": {"lat": 21.1458, "lon": 79.0882, "name": "Nagpur", "state": "maharashtra"},
    # Rajasthan
    "jaipur": {"lat": 26.9124, "lon": 75.7873, "name": "Jaipur", "state": "rajasthan"},
    "udaipur": {"lat": 24.5854, "lon": 73.7125, "name": "Udaipur", "state": "rajasthan"},
    "jodhpur": {"lat": 26.2389, "lon": 73.0243, "name": "Jodhpur", "state": "rajasthan"},
    "jaisalmer": {"lat": 26.9157, "lon": 70.9083, "name": "Jaisalmer", "state": "rajasthan"},
    "pushkar": {"lat": 26.4898, "lon": 74.5511, "name": "Pushkar", "state": "rajasthan"},
    "bikaner": {"lat": 28.0229, "lon": 73.3119, "name": "Bikaner", "state": "rajasthan"},
    "chittorgarh": {"lat": 24.8887, "lon": 74.6269, "name": "Chittorgarh", "state": "rajasthan"},
    # Uttar Pradesh
    "varanasi": {"lat": 25.3176, "lon": 83.0068, "name": "Varanasi", "state": "uttar_pradesh"},
    "lucknow": {"lat": 26.8467, "lon": 80.9462, "name": "Lucknow", "state": "uttar_pradesh"},
    "agra": {"lat": 27.1767, "lon": 78.0081, "name": "Agra", "state": "uttar_pradesh"},
    "prayagraj": {"lat": 25.4358, "lon": 81.8463, "name": "Prayagraj", "state": "uttar_pradesh"},
    "mathura": {"lat": 27.4924, "lon": 77.6737, "name": "Mathura", "state": "uttar_pradesh"},
    "ayodhya": {"lat": 26.7922, "lon": 82.1998, "name": "Ayodhya", "state": "uttar_pradesh"},
    # Madhya Pradesh
    "bhopal": {"lat": 23.2599, "lon": 77.4126, "name": "Bhopal", "state": "madhya_pradesh"},
    "indore": {"lat": 22.7196, "lon": 75.8577, "name": "Indore", "state": "madhya_pradesh"},
    "ujjain": {"lat": 23.1765, "lon": 75.7885, "name": "Ujjain", "state": "madhya_pradesh"},
    "gwalior": {"lat": 26.2183, "lon": 78.1828, "name": "Gwalior", "state": "madhya_pradesh"},
    "jabalpur": {"lat": 23.1815, "lon": 79.9864, "name": "Jabalpur", "state": "madhya_pradesh"},
    "orchha": {"lat": 25.3520, "lon": 78.6408, "name": "Orchha", "state": "madhya_pradesh"},
    "khajuraho": {"lat": 24.8318, "lon": 79.9199, "name": "Khajuraho", "state": "madhya_pradesh"},
    # Bihar
    "patna": {"lat": 25.6093, "lon": 85.1376, "name": "Patna", "state": "bihar"},
    "bodh_gaya": {"lat": 24.6961, "lon": 84.9869, "name": "Bodh Gaya", "state": "bihar"},
    "rajgir": {"lat": 25.0286, "lon": 85.4258, "name": "Rajgir", "state": "bihar"},
    "vaishali": {"lat": 25.6841, "lon": 85.3119, "name": "Vaishali", "state": "bihar"},
    "gaya": {"lat": 24.7955, "lon": 84.9994, "name": "Gaya", "state": "bihar"},
    # Gujarat
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714, "name": "Ahmedabad", "state": "gujarat"},
    "vadodara": {"lat": 22.3072, "lon": 73.1812, "name": "Vadodara", "state": "gujarat"},
    "dwarka": {"lat": 22.2394, "lon": 68.9678, "name": "Dwarka", "state": "gujarat"},
    "somnath": {"lat": 20.8880, "lon": 70.4013, "name": "Somnath", "state": "gujarat"},
    "kutch_bhuj": {"lat": 23.2420, "lon": 69.6669, "name": "Kutch (Bhuj)", "state": "gujarat"},
    "junagadh": {"lat": 21.5222, "lon": 70.4579, "name": "Junagadh", "state": "gujarat"},
}


# LANDMARK SCORING CONSTANTS

LANDMARK_ADJACENT_TIMES = {
    "dawn": ["morning", "night"],
    "morning": ["dawn", "midday"],
    "midday": ["morning", "afternoon"],
    "afternoon": ["midday", "golden_hour"],
    "golden_hour": ["afternoon", "sunset"],
    "sunset": ["golden_hour", "twilight"],
    "twilight": ["sunset", "night"],
    "night": ["twilight", "dawn"],
}

LANDMARK_ENERGY_PREFERENCE = {
    "spiritual": "low", "love": "low", "friendship": "medium",
    "motivation": "high", "courage": "high", "solitude": "low",
    "nature": "low", "wisdom": "low", "gratitude": "medium",
    "celebration": "high",
}

LANDMARK_ENERGY_LEVELS = ["low", "medium", "high"]

LANDMARK_TYPE_AFFINITY = {
    "spiritual": {"temple": 10, "ghat": 8, "mosque": 9, "shrine": 9, "cave": 7, "garden": 4, "ruin": 5, "lake": 6},
    "love": {"garden": 10, "palace": 8, "lake": 9, "bridge": 7, "park": 7, "haveli": 7, "ghat": 5, "promenade": 8},
    "friendship": {"market": 9, "street": 10, "cafe": 9, "campus": 8, "park": 7, "ghat": 7, "garden": 6, "beach": 7},
    "motivation": {"fort": 10, "monument": 8, "stadium": 9, "campus": 7, "bridge": 8, "ruin": 7, "street": 6},
    "courage": {"fort": 10, "monument": 9, "ruin": 8, "bridge": 7, "ghat": 5},
    "solitude": {"ruin": 10, "lake": 9, "forest": 10, "cave": 8, "garden": 7, "ghat": 7, "temple": 6, "hill": 8},
    "nature": {"lake": 10, "forest": 10, "hill": 9, "garden": 9, "beach": 9, "park": 8, "ghat": 7, "ruin": 6},
    "wisdom": {"library": 10, "ruin": 10, "temple": 9, "museum": 7, "campus": 8, "garden": 7, "lake": 6},
    "gratitude": {"garden": 9, "temple": 8, "shrine": 7, "ghat": 7, "home": 8, "market": 5},
    "celebration": {"palace": 10, "market": 9, "haveli": 8, "ghat": 8, "street": 7, "stadium": 7, "fort": 6},
}

THEME_TO_LANDMARK_CATEGORY = {
    "spiritual": "spiritual", "devotion": "spiritual", "love": "love",
    "friendship": "friendship", "motivation": "motivation", "courage": "courage",
    "solitude": "solitude", "nature": "nature", "wisdom": "wisdom",
    "gratitude": "gratitude", "celebration": "celebration", "festival": "celebration",
    "family": "gratitude", "peace": "solitude", "self_worth": "motivation",
    "nostalgia": "wisdom", "good_morning": "gratitude", "good_night": "solitude",
    "birthday": "celebration", "general": "wisdom",
}

EMOTION_TO_LANDMARK_CATEGORY = {
    "hopeful": "motivation", "peaceful": "solitude", "determined": "courage",
    "devotional": "spiritual", "joyful": "celebration", "reflective": "wisdom",
    "melancholic": "solitude", "warm": "love", "grateful": "gratitude",
    "empowered": "motivation", "nostalgic": "wisdom", "loving": "love",
}

APP_TIME_TO_LANDMARK_TIME = {
    "pre-dawn": "night", "dawn": "dawn", "morning": "morning",
    "late-morning": "midday", "afternoon": "afternoon",
    "evening": "golden_hour", "dusk": "sunset", "night": "night",
}


# 5 DOMAIN PROFILES

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


# 8 LAYOUT PROFILES

LAYOUT_PROFILES = {
    "LT-V": {
        "corner": "left-top", "arrangement": "vertical",
        "anchor_x": "left", "anchor_y": "top",
        "quote_position": "top-left", "photo_position": "below-quote",
        "visual_weight": "lower-right",
        "gemini_guidance": "Main visual weight in lower-right. Upper-left should naturally have open sky, distant haze, or soft atmospheric elements.",
    },
    "RT-V": {
        "corner": "right-top", "arrangement": "vertical",
        "anchor_x": "right", "anchor_y": "top",
        "quote_position": "top-right", "photo_position": "below-quote",
        "visual_weight": "lower-left",
        "gemini_guidance": "Main visual weight in lower-left. Upper-right should naturally have open sky, cloud gradient, or distant mountains.",
    },
    "LB-V": {
        "corner": "left-bottom", "arrangement": "vertical",
        "anchor_x": "left", "anchor_y": "bottom",
        "quote_position": "bottom-left", "photo_position": "above-quote",
        "visual_weight": "upper-right",
        "gemini_guidance": "Main visual weight in upper-right. Lower-left should naturally have calm water, ground fog, or empty foreground.",
    },
    "RB-V": {
        "corner": "right-bottom", "arrangement": "vertical",
        "anchor_x": "right", "anchor_y": "bottom",
        "quote_position": "bottom-right", "photo_position": "above-quote",
        "visual_weight": "upper-left",
        "gemini_guidance": "Main visual weight in upper-left. Lower-right should naturally have distant landscape, fading fog, or still water.",
    },
    "LT-H": {
        "corner": "left-top", "arrangement": "horizontal",
        "anchor_x": "left", "anchor_y": "top",
        "quote_position": "top-left", "photo_position": "right-of-quote",
        "visual_weight": "lower-right",
        "gemini_guidance": "Main visual weight in lower-right and center. Upper-left should have wide open sky or soft cloud gradient.",
    },
    "RT-H": {
        "corner": "right-top", "arrangement": "horizontal",
        "anchor_x": "right", "anchor_y": "top",
        "quote_position": "top-right", "photo_position": "left-of-quote",
        "visual_weight": "lower-left",
        "gemini_guidance": "Main visual weight in lower-left and center. Upper-right should have wide open sky or atmospheric haze.",
    },
    "LB-H": {
        "corner": "left-bottom", "arrangement": "horizontal",
        "anchor_x": "left", "anchor_y": "bottom",
        "quote_position": "bottom-left", "photo_position": "right-of-quote",
        "visual_weight": "upper-right",
        "gemini_guidance": "Main visual weight in upper-right and center. Lower-left should have calm foreground, water surface, or ground mist.",
    },
    "RB-H": {
        "corner": "right-bottom", "arrangement": "horizontal",
        "anchor_x": "right", "anchor_y": "bottom",
        "quote_position": "bottom-right", "photo_position": "left-of-quote",
        "visual_weight": "upper-left",
        "gemini_guidance": "Main visual weight in upper-left and center. Lower-right should have distant background fading into atmosphere.",
    },
}

GUARDRAIL_POLICY_VERSION = "1.0"

SACRED_SUBJECT_TYPES = frozenset({
    "deity", "god", "goddess", "temple_spire", "dome", "minaret",
    "sacred_fire", "sacred_tree", "lingam", "cross", "crescent",
})


# 4 APPROACH TEMPLATES

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


# EMOTION CONCEPTS (for cultural fallback expansion)

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


# THEME HINTS (for thematic classification)

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


# LEXICONS & NLP DICTIONARIES

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


# SPARQL TEMPLATES

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


# MYTHOLOGY RELEVANCE SCORING (guides ranking of live SPARQL results)

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


# GEMINI SYSTEM PROMPT

GEMINI_SYSTEM_PROMPT = """
You are a creative Art Director and prompt designer for image generation (DALL-E 3).

You are provided with RAW COMPONENTS:
- A Quote (and its native language/script)
- Emotional Mood & Core Theme
- Ambient Environment (Weather, Time of Day lighting, Location/Landmark)
- Raw Visual Candidates & Cultural Symbols
- Pre-computed Layout Geometry (designated visual weight zone and calm photo corner)

Your job is NOT to mechanically copy pre-written text, but to IMAGINE, COMPOSE, and WRITE an original, high-detail image generation prompt (full_prompt) using your own visual storytelling and thoughts.

CREATIVE ART DIRECTION:
- Treat the candidates and location details as creative seeds. Envision vivid lighting, physical textures, color palette, camera perspective, and depth as a master photographer or painter would.
- Bring fresh, non-generic descriptions to life based on the quote's core emotion.
- Never name specific copyrighted characters (say "anime-style warrior", not "Naruto").
- Mythological figures (Hanuman, Surya, Agni, Krishna, Rama, etc.) ARE allowed with their traditional iconographic details.

FACE & FIGURE RULE:
- Do NOT render realistic close-up human faces.
- Human figures may appear as silhouettes, mid/long-distance forms, stylized figures, or viewed from behind.
- Exception: only if explicitly requesting a named mythological or anime figure may a stylized face appear — never photorealistic close-ups.

SUBJECT SELECTION:
- Choose the strongest main subject for the quote's meaning and emotion from any candidate source. You may select one supporting candidate that improves the scene.
- If the shortlist is weak, propose one concrete original subject based on the quote and setting. You may also pair one original subject with one shortlisted candidate if they express the same idea more clearly together.
- For an original subject, use the ID "original" and describe the subject in original_subject. Put the main subject ID first and explain why the original subject fits in reasoning.
- Quote imagery can be the main subject, a supporting motif, or part of the setting.
- Choose a deity only when a specific traditional association or story deepens the quote's meaning. Explain that connection in your reasoning.
- When user-supplied subjects are present, select only from those options and leave original_subject null.

PHOTO PLACEHOLDER & COMPOSITION:
- Follow the pre-computed layout geometry: place the scene's primary visual weight in the designated zone.
- Crucially, describe the calm corner naturally as part of the scene (e.g. soft atmospheric mist, open dawn sky gradient, peaceful water surface, or smooth stone wall) so a 2.5-inch square framed photo can float there beside the quote text without overlapping architectural spires, domes, deities, or silhouettes.

HOW TO WRITE THE IMAGE PROMPT (full_prompt):
Write a single, rich, cohesive paragraph containing:
1. SCENE & SUBJECT: Your original, evocative visualization of the subject, environment, lighting, colors, and textures.
2. TEXT INSTRUCTION: Render the exact quote in its ORIGINAL language and script within the quote zone, with clean, legible, high-contrast typography. In full_prompt, state whether the quote sits above, below, to the left, or to the right of the separate photo zone, following the selected layout.
   - If HINDI, render in clean Hindi Devanagari typography.
   - If ENGLISH, render in clean Latin typography.
   - NEVER translate the quote inside the image.
3. CALM PHOTO CORNER: In full_prompt, explicitly state where on the canvas to reserve the photo zone and whether it sits above, below, to the left, or to the right of the quote, following the selected layout. Describe it as a natural, uncluttered part of the scene and keep the entire zone free of text for the framed photo.
4. STYLE & AVOID: The selected visual domain style and negative constraints (e.g. no watermarks, no logos, no photorealistic close-up faces).
5. FORMAT: Always end with "4:5 portrait aspect ratio image."

SACRED SUBJECT REPORTING:
If your scene contains any deity, god/goddess figure, temple spire, dome, minaret, sacred fire, sacred tree, lingam, cross, or crescent, report each in "sacred_subjects" with its approximate normalized bounding box (x, y, w, h from 0.0 to 1.0) and type. This ensures text and photo overlays do not cover sacred elements.

RESPOND with JSON only:
{
    "selected_metaphor_ids": ["main_id"] or ["main_id", "supporting_id"],
    "original_subject": null or "a short description of the original subject",
    "selected_domain": "PHOTOREALISTIC|MYTHOLOGICAL|ANIME|ILLUSTRATED",
    "selected_approach": "1|2|3|4",
    "selected_details": ["D1", "D3"],
    "sacred_subjects": [{"type": "deity", "position": {"x": 0.4, "y": 0.3, "w": 0.2, "h": 0.3}}],
    "full_prompt": "the complete creative prompt as described above, including original scene description, exact quote typography in original script, calm photo corner, and style constraints",
    "reasoning": "2-3 sentences explaining your artistic choices and concept"
}
"""


# QUOTES (default pool + test quotes covering edge cases)

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
