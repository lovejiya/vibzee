"""
logger.py — Dedicated logging utility for Vibzee.

Lives inside the logs/ folder. It runs the pipeline (or inspects existing pipeline data),
captures all important function and API outputs (emotion, weather, panchang/tithi,
knowledge graphs, Gemini selections, and final prompt), and saves them to run logs
with an auto-incrementing run number and timestamp.
"""
import io
import re
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so it can import app, sources, specs, generator cleanly
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from specs import LOCATIONS, QUOTES, MasterPrompt
import sources
import generator
import app

LOGS_DIR = Path(__file__).resolve().parent


class LoggerWriter:
    """Tees output to both terminal stdout and an in-memory buffer."""
    def __init__(self, original_stdout):
        self.terminal = original_stdout
        self.buffer = io.StringIO()

    def write(self, message):
        self.terminal.write(message)
        self.buffer.write(message)

    def flush(self):
        self.terminal.flush()

    def get_log(self) -> str:
        return self.buffer.getvalue()


def _get_next_run_id() -> int:
    """Determine the next incremental run number from all_runs.log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    all_runs_file = LOGS_DIR / "all_runs.log"
    if not all_runs_file.exists():
        return 1

    try:
        content = all_runs_file.read_text(encoding="utf-8")
        matches = re.findall(r"RUN #(\d+)", content)
        if matches:
            return max(int(m) for m in matches) + 1
    except Exception:
        pass
    return 1


def _save_run_log(run_id: int, timestamp: datetime, content: str):
    """Save execution log into the single cumulative logs/all_runs.log file."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    header = f"RUN #{run_id:04d} | DATE & TIME: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
    divider = "#" * 70 + "\n"
    full_entry = f"{divider}{header}{divider}\n{content}\n\n"

    # Append strictly to the single master log file
    with open(LOGS_DIR / "all_runs.log", "a", encoding="utf-8") as f:
        f.write(full_entry)


def log_run(quote: str = None, photo_ratio: str = "1:1", location_key: str = "mumbai") -> MasterPrompt:
    """
    Executes the Vibzee pipeline while extracting and printing the outputs of all
    important functions (weather API, panchang, emotion NLP, knowledge graphs,
    Gemini selection, final prompt) and persists everything to a log file.
    """
    run_id = _get_next_run_id()
    start_time = datetime.now()

    logger = LoggerWriter(sys.stdout)
    sys.stdout = logger

    try:
        location = LOCATIONS[location_key]
        quote = quote or random.choice(QUOTES)
        date = start_time
        time_of_day = app.classify_time(date.hour)

        print(f"RUN ID: #{run_id:04d} | TIMESTAMP: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 60)

        # ── STAGE 1: CONTEXT ENRICHMENT & API OUTPUTS ──────
        print("=" * 60)
        print("STAGE 1: CONTEXT ENRICHMENT & API OUTPUTS")
        print("=" * 60)
        print(f"[Quote Input]\n  Hindi: \"{quote}\"")

        context = sources.enrich_context(
            quote=quote, location=location, date=date, time_of_day=time_of_day)

        print(f"  Key Terms: {context.quote_analysis.key_terms}")
        print(f"  Theme: {context.quote_analysis.theme}")
        print(f"  Translated Keywords: {context.en_keywords}")
        print()
        print(f"[API: Open-Meteo Weather]\n  Location: {location['name']} (Lat {location['lat']}, Lon {location['lon']})")
        print(f"  Condition: {context.weather.get('condition')}")
        print(f"  Temperature: {context.weather.get('temp')}°C | Humidity: {context.weather.get('humidity')}%")
        print()
        print(f"[Panchang Calendar Context]\n  Date: {date.strftime('%Y-%m-%d')}")
        print(f"  Festival & Lunar Tithi: {context.festival or 'None'}")
        print()
        print(f"[Emotion Detection (NLP + WordNet)]\n  Primary Emotion: {context.emotion.get('primary')}")
        print(f"  Sentiment: {context.emotion.get('sentiment')} | Score: {context.emotion.get('score')}")
        print()

        # ── STAGE 2: KNOWLEDGE GRAPH & DISCOVERY API OUTPUTS ──────
        print("=" * 60)
        print("STAGE 2: KNOWLEDGE GRAPH & DISCOVERY API OUTPUTS")
        print("=" * 60)
        candidates = sources.run_knowledge_chain(context=context, location=location)
        location_details = sources.discover_location_details(location)

        print(f"[Knowledge Chain & Metaphors Summary]")
        print(f"  Total Candidates Prepared: {len(candidates.pool)}")
        cultural_candidates = [c for c in candidates.pool if c.cultural]
        print(f"  Cultural Metaphor Matches: {len(cultural_candidates)}")
        for c in cultural_candidates[:3]:
            print(f"    - \"{c.name}\" ({c.scene_text})")
        if candidates.pool:
            sample = candidates.pool[0]
            print(f"  Sample Candidate: [{sample.id}] \"{sample.name}\" ({sample.domain})")
            print(f"    Subject: \"{sample.subject_text}\"")
            print(f"    Scene: \"{sample.scene_text}\"")
        print(f"  Location Details Discovered: {len(location_details)}")
        for d in location_details[:3]:
            print(f"    - [{d['id']}] {d['text']} (from {d['source']})")
        print()

        # ── STAGE 3: GEMINI LLM API OUTPUT & FINAL SELECTIONS ──────
        print("=" * 60)
        print("STAGE 3: GEMINI LLM API OUTPUT & FINAL SELECTIONS")
        print("=" * 60)
        prompt = generator.generate(
            candidates=candidates,
            context=context,
            location_details=location_details,
            photo_ratio=photo_ratio,
            location=location,
        )

        selections = prompt.gemini_selections
        print(f"[API: Google Gemini ({generator.GEMINI_MODEL})]")
        print(f"  Selected Metaphor IDs: {selections.get('selected_metaphor_ids', prompt.metaphor_used)}")
        print(f"  Selected Visual Domain: {prompt.visual_domain}")
        print(f"  Selected Layout: {prompt.layout_id}")
        print(f"  Selected Approach: {prompt.photo_approach}")
        print(f"  Selected Details: {selections.get('selected_details', [])}")
        print()
        print(f"[Gemini Reasoning]\n  {selections.get('reasoning', 'N/A')}")
        print()

        # ── STAGE 4: FINAL MASTER PROMPT ──────
        print("=" * 60)
        print("STAGE 4: FINAL MASTER PROMPT")
        print("=" * 60)
        print("FLUX PROMPT:")
        print("-" * 40)
        print(prompt.full_prompt)
        print()
        print(f"Layout: {prompt.layout_id}")
        print(f"Domain: {prompt.visual_domain}")
        print(f"Photo approach: {prompt.photo_approach}")
        print(f"Metaphor: {prompt.metaphor_used}")
        print(f"Word count: {len(prompt.full_prompt.split())}")
        print("=" * 60)

        output_log = logger.get_log()
        _save_run_log(run_id, start_time, output_log)
        print(f"\n[Log Saved] Run #{run_id:04d} appended to logs/all_runs.log\n")

        return prompt

    finally:
        sys.stdout = logger.terminal


if __name__ == "__main__":
    print("Vibzee Logging Runner")
    print("-" * 40)

    user_input = input("Enter quote (or number 1-10, or Enter for random): ").strip()

    if user_input.isdigit() and 1 <= int(user_input) <= len(QUOTES):
        quote = QUOTES[int(user_input) - 1]
    elif user_input:
        quote = user_input
    else:
        quote = None

    ratio = input("Photo ratio (1:1 / 2:3 / 4:3) [default 1:1]: ").strip() or "1:1"

    log_run(quote=quote, photo_ratio=ratio)
