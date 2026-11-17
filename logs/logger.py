"""
logger.py — Dedicated logging & cloud sync utility for Vibzee.

Provides unified support for:
1. Local disk logging & caching (when running on your computer)
2. Upstash Redis cloud logging, caching, & recent runs (zero extra libraries needed; uses requests)
3. Pulling remote Vercel logs/recent runs directly into your local machine
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests

LOGS_DIR = Path(__file__).resolve().parent
ALL_RUNS_FILE = LOGS_DIR / "all_runs.log"

# Upstash REST credentials from environment
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")


# ─────────────────────────────────────────────────────────────
# 1. UPSTASH REST CLIENT (Lightweight, No extra pip dependencies)
# ─────────────────────────────────────────────────────────────

def _redis_cmd(*args) -> any:
    """Execute any Redis command via Upstash REST API using plain requests."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    try:
        url = f"{UPSTASH_URL}/" + "/".join(str(a) for a in args)
        headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
        resp = requests.get(url, headers=headers, timeout=3)
        if resp.status_code == 200:
            return resp.json().get("result")
    except Exception:
        pass
    return None


def _redis_post(cmd: list) -> any:
    """Execute Redis command with JSON payload via POST (for complex/large values)."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {UPSTASH_TOKEN}",
            "Content-Type": "application/json",
        }
        resp = requests.post(f"{UPSTASH_URL}", headers=headers, json=cmd, timeout=3)
        if resp.status_code == 200:
            return resp.json().get("result")
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────
# 2. LOGGING (Local File + Upstash Cloud)
# ─────────────────────────────────────────────────────────────


def get_next_run_id() -> int:
    """Determine the next incremental run number (checks local file first, then Redis)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if ALL_RUNS_FILE.exists():
        try:
            content = ALL_RUNS_FILE.read_text(encoding="utf-8")
            matches = re.findall(r"RUN #(\d+)", content)
            if matches:
                return max(int(m) for m in matches) + 1
        except Exception:
            pass

    # If local file is empty/on cloud, check Redis
    cloud_len = _redis_cmd("llen", "vibzee:all_runs")
    if cloud_len and isinstance(cloud_len, int):
        return cloud_len + 1
    return 1


def record_run_log(run_id: int, timestamp: datetime, content: str):
    """
    Saves execution log:
    - Locally to logs/all_runs.log (if local filesystem is writable)
    - Remotely to Upstash Redis (key: 'vibzee:all_runs') so Vercel logs are captured
    """
    header = f"RUN #{run_id:04d} | DATE & TIME: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
    divider = "#" * 70 + "\n"
    full_entry = f"{divider}{header}{divider}\n{content}\n\n"

    # 1. Local disk write
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(ALL_RUNS_FILE, "a", encoding="utf-8") as f:
            f.write(full_entry)
    except Exception:
        pass

    # 2. Upstash Cloud write (accessible from both Vercel & local)
    _redis_post(["rpush", "vibzee:all_runs", full_entry])


# ─────────────────────────────────────────────────────────────
# 3. LOG BODY BUILDER
# ─────────────────────────────────────────────────────────────

def build_run_log(quote, location, ratio, time_of_day, ctx, candidates, loc_details, prompt):
    """Build a comprehensive log capturing every pipeline stage."""
    sep = "=" * 60
    sub = "-" * 40

    qa = ctx.quote_analysis
    lines = [
        sep,
        "STAGE 1: CONTEXT ENRICHMENT",
        sep,
        "[Quote Input]",
        f'  Text: "{quote}"',
        f"  Key Terms: {qa.key_terms}",
        f"  Nouns: {qa.nouns}",
        f"  Theme: {qa.theme}",
        f"  Has Concrete Nouns: {qa.has_concrete}",
        f"  Translated Keywords: {ctx.en_keywords}",
        "",
        "[Weather — Open-Meteo]",
        f"  Location: {location['name']} (Lat {location['lat']}, Lon {location['lon']})",
        f"  Condition: {ctx.weather.get('condition')}",
        f"  Temperature: {ctx.weather.get('temp')}°C | Humidity: {ctx.weather.get('humidity')}%",
        "",
        "[Panchang]",
        f"  Festival/Tithi: {ctx.festival or 'None'}",
        *(
            [
                f"  Regional Calendar: {ctx.panchang_details.get('astronomical_panchang', {}).get('regional_calendar', {}).get('regional_date_string', '')}",
                f"  Sunrise: {ctx.panchang_details.get('astronomical_panchang', {}).get('sun_moon_timings', {}).get('sunrise', '')} | Sunset: {ctx.panchang_details.get('astronomical_panchang', {}).get('sun_moon_timings', {}).get('sunset', '')} | Rahu Kaal: {ctx.panchang_details.get('astronomical_panchang', {}).get('muhurats', {}).get('rahu_kalam', '')}",
            ]
            if getattr(ctx, "panchang_details", None)
            else []
        ),
        "",
        "[Emotion Detection]",
        f"  Primary: {ctx.emotion.get('primary')}",
        f"  Sentiment: {ctx.emotion.get('sentiment')} | Score: {ctx.emotion.get('score')}",
        "",
        "[Visual Imagery from Quote]",
        f"  Richness Score: {ctx.visual_richness_score}",
        f"  Items: {ctx.visual_imagery}",
        "",
        sep,
        "STAGE 2: KNOWLEDGE CHAIN & CANDIDATES",
        sep,
        f"Total Candidates: {len(candidates.pool)}",
        f"Quote-Native: {sum(1 for c in candidates.pool if c.quote_native)}",
        "",
    ]
    for c in candidates.pool:
        lines.append(
            f'  [{c.id}] "{c.name}" domain={c.domain} '
            f"groundable={c.groundable} cultural={c.cultural} "
            f"chains={c.chain_sources}"
        )
        lines.append(f'    subject: "{c.subject_text}"')
        lines.append(f'    scene: "{c.scene_text}"')
        lines.append(f"    visual_phrases: {c.visual_phrases}")

    lines += [
        "",
        f"[Location Details Discovered: {len(loc_details)}]",
    ]
    for d in loc_details:
        lines.append(f'  [{d["id"]}] "{d["text"]}" (from {d["source"]})')

    sel = prompt.gemini_selections
    lines += [
        "",
        sep,
        "STAGE 3: GEMINI LLM SELECTIONS",
        sep,
        f"Selected Metaphor IDs: {sel.get('selected_metaphor_ids', 'N/A')}",
        f"Selected Domain: {sel.get('selected_domain', 'N/A')}",
        f"Selected Layout: {sel.get('selected_layout', 'N/A')}",
        f"Selected Approach: {sel.get('selected_approach', 'N/A')}",
        f"Selected Details: {sel.get('selected_details', 'N/A')}",
        f"Fallback Used: {sel.get('fallback', False)}",
        f"Error: {sel.get('error', 'None')}",
        "",
        "[Reasoning]",
        f"  {sel.get('reasoning', 'N/A')}",
    ]

    word_count = len(prompt.full_prompt.split())
    lines += [
        "",
        sep,
        "STAGE 4: FINAL PROMPT",
        sep,
        f"Domain: {prompt.visual_domain}",
        f"Layout: {prompt.layout_id} | Approach: {prompt.photo_approach}",
        f"Ratio: {ratio} | Metaphor: {prompt.metaphor_used}",
        f"Word Count: {word_count}",
        "",
        "[Subject]",
        f"  {prompt.subject}",
        "[Scene]",
        f"  {prompt.scene}",
        "[Style]",
        f"  {prompt.style}",
        "[Composition]",
        f"  {prompt.composition}",
        "[Empty Space]",
        f"  {prompt.empty_space}",
        "[Details]",
        f"  {prompt.details}",
        "[Avoid]",
        f"  {prompt.avoid}",
        "",
        sub,
        "DALL-E PROMPT:",
        sub,
        prompt.full_prompt,
        sep,
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 4. RECENT RUNS (Shared across Vercel & Local)
# ─────────────────────────────────────────────────────────────

def cloud_load_recent() -> list:
    """Load recent runs from Upstash Redis, or fallback to empty list."""
    res = _redis_cmd("get", "vibzee:recent_runs")
    if res:
        try:
            return json.loads(res)
        except Exception:
            pass
    return []


def cloud_save_recent(entry: dict):
    """Append a recent run to Upstash Redis (keeps last 30 runs)."""
    recent = cloud_load_recent()
    recent.append(entry)
    recent = recent[-30:]
    _redis_post(["set", "vibzee:recent_runs", json.dumps(recent, ensure_ascii=False)])


# ─────────────────────────────────────────────────────────────
# 4. CACHE (Shared across Vercel & Local)
# ─────────────────────────────────────────────────────────────

def cloud_load_cache(key: str):
    """Fetch cached data from Upstash Redis."""
    res = _redis_cmd("get", f"vibzee:cache:{key}")
    if res:
        try:
            return json.loads(res)
        except Exception:
            pass
    return None


def cloud_save_cache(key: str, data, ttl_seconds: int = 86400):
    """Save cached data into Upstash Redis with expiration TTL."""
    payload = json.dumps(data, default=str, ensure_ascii=False)
    _redis_post(["setex", f"vibzee:cache:{key}", ttl_seconds, payload])


# ─────────────────────────────────────────────────────────────
# 5. SYNC COMMAND: Pull all Vercel logs into your local file
# ─────────────────────────────────────────────────────────────

def pull_logs_from_cloud():
    """
    Downloads all run logs stored in Upstash Redis and writes them to
    your local logs/all_runs.log file.
    """
    logs = _redis_post(["lrange", "vibzee:all_runs", 0, -1])
    if not logs or not isinstance(logs, list):
        print("No remote logs found in Upstash Redis.")
        return

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALL_RUNS_FILE, "w", encoding="utf-8") as f:
        for entry in logs:
            f.write(entry)
    print(f"✓ Successfully synced {len(logs)} run logs into: {ALL_RUNS_FILE}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Vibzee Logger & Cloud Sync")
    parser.add_argument("--sync", action="store_true", help="Pull logs from Upstash Redis to local file")
    args = parser.parse_args()

    if args.sync:
        pull_logs_from_cloud()
    else:
        print("Vibzee Logger loaded. Run with --sync to pull logs from Vercel/Upstash.")
