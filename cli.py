"""
cli.py — Interactive Command Line Interface for Vibzee.

Usage:
    python3 cli.py
Prompts the user interactively step-by-step for Quote, Location, Ratio, and Output format.
"""
from datetime import datetime
import random
import sys

from specs import LOCATIONS, QUOTES
from panchange_engine import REGIONAL_PROFILES
from app import run_pipeline, classify_time
from logs.logger import build_run_log
import sources


def prompt_quote() -> str:
    print("\n--- Step 1: Select Quote ---")
    print("1. Pick from default pool")
    print("2. Enter custom quote")
    print("3. Random quote")
    choice = input("Enter choice (1/2/3) [default: 1]: ").strip() or "1"

    if choice == "2":
        val = input("Enter your custom quote: ").strip()
        if val:
            return val
        print("Empty input. Falling back to default quote.")
        return QUOTES[0]
    elif choice == "3":
        chosen = random.choice(QUOTES)
        print(f"Selected random quote: \"{chosen}\"")
        return chosen
    else:
        print("\nDefault pool quotes:")
        for idx, q in enumerate(QUOTES, 1):
            print(f"  {idx}. {q}")
        q_idx = input(f"Choose quote number (1-{len(QUOTES)}) [default: 1]: ").strip()
        if q_idx.isdigit() and 1 <= int(q_idx) <= len(QUOTES):
            return QUOTES[int(q_idx) - 1]
        return QUOTES[0]


def prompt_language() -> str:
    print("\n--- Step 2: Select Quote Language ---")
    langs = ["English", "Hindi", "Sanskrit", "Marathi", "Gujarati", "Bengali", "Tamil", "Telugu", "Kannada", "Punjabi", "Spanish", "French", "Japanese", "Other"]
    for idx, l in enumerate(langs, 1):
        print(f"  {idx}. {l}")
    choice = input(f"Choose language (1-{len(langs)}) [default: 1 (English)]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(langs):
        sel = langs[int(choice) - 1]
        if sel == "Other":
            custom = input("Enter language name: ").strip()
            return custom if custom else "English"
        return sel
    return "English"


def prompt_location():
    print("\n--- Step 3: Select Location ---")
    loc_keys = list(LOCATIONS.keys())
    for idx, key in enumerate(loc_keys, 1):
        name = LOCATIONS[key].get("name", key.title())
        print(f"  {idx}. {name} ({key})")
    print(f"  {len(loc_keys) + 1}. Custom location (enter own city/place)")

    default_idx = 1
    if "mumbai" in loc_keys:
        default_idx = loc_keys.index("mumbai") + 1

    choice = input(f"Choose location (1-{len(loc_keys) + 1}) [default: {default_idx}]: ").strip()
    if choice == str(len(loc_keys) + 1):
        custom = input("Enter custom location name (e.g. Jaipur, Ladakh, Kyoto): ").strip()
        if custom:
            return sources.resolve_location(custom_location=custom), True
    if choice.isdigit() and 1 <= int(choice) <= len(loc_keys):
        k = loc_keys[int(choice) - 1]
        return LOCATIONS[k], False
    return LOCATIONS[loc_keys[default_idx - 1]], False


def prompt_custom_overrides():
    print("\n--- Optional: Direct Overrides (bypasses search/extraction steps) ---")
    kw_in = input("Enter own key words (comma-separated, or press Enter to auto-extract): ").strip()
    keywords = [k.strip() for k in kw_in.split(",") if k.strip()] if kw_in else None

    cand_in = input("Enter own visual candidates/subjects (comma-separated, or press Enter for 6-chain search): ").strip()
    candidates = [c.strip() for c in cand_in.split(",") if c.strip()] if cand_in else None

    return keywords, candidates


def prompt_ratio() -> str:
    print("\n--- Step 4: Select Photo Aspect Ratio ---")
    ratios = ["1:1", "2:3", "4:3", "9:16", "16:9"]
    for idx, r in enumerate(ratios, 1):
        print(f"  {idx}. {r}")
    choice = input(f"Choose ratio (1-{len(ratios)}) [default: 1 (1:1)]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(ratios):
        return ratios[int(choice) - 1]
    return "1:1"


def prompt_regional_profile() -> str | None:
    print("\n--- Step 5: Select Regional Calendar Profile ---")
    print("  0. Auto (Inferred by Location/Language)")
    prof_keys = list(REGIONAL_PROFILES.keys())
    for idx, k in enumerate(prof_keys, 1):
        print(f"  {idx}. {REGIONAL_PROFILES[k]['display_name']}")
    choice = input(f"Choose profile (0-{len(prof_keys)}) [default: 0 (Auto)]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(prof_keys):
        return prof_keys[int(choice) - 1]
    return None


def prompt_datetime():
    print("\n--- Step 5: Date & Time ---")
    now = datetime.now()
    cur_date = now.strftime("%Y-%m-%d")
    cur_time = now.strftime("%H:%M")

    d_input = input(f"Enter Date (YYYY-MM-DD) [default: current ({cur_date})]: ").strip()
    selected_date = d_input if d_input else cur_date

    t_input = input(f"Enter Time (HH:MM 24-hr) [default: current ({cur_time})]: ").strip()
    selected_time = t_input if t_input else cur_time

    try:
        dt = datetime.strptime(f"{selected_date} {selected_time}", "%Y-%m-%d %H:%M")
    except Exception:
        print("Invalid format, using current date & time.")
        dt = now
    return dt


def prompt_view_mode() -> bool:
    print("\n--- Step 6: Output Display ---")
    print("1. Full details & pipeline log")
    print("2. Prompt only (copy-ready)")
    choice = input("Enter choice (1/2) [default: 1]: ").strip() or "1"
    return choice == "2"


def main():
    print("=" * 55)
    print("✨ Vibzee Image Prompt Generator (Interactive CLI)")
    print("=" * 55)

    quote = prompt_quote()
    language = prompt_language()
    location, is_custom_loc = prompt_location()
    ratio = prompt_ratio()
    regional_profile = prompt_regional_profile()
    dt = prompt_datetime()
    time_of_day = classify_time(dt.hour)
    custom_keywords, custom_candidates = prompt_custom_overrides()
    quiet = prompt_view_mode()

    print("\n" + "=" * 55)
    print(f"🚀 Generating Prompt...")
    print(f"Quote:    \"{quote}\"")
    print(f"Language: {language} | Location: {location['name']}{' (Override)' if is_custom_loc else ''} | Ratio: {ratio}")
    if custom_keywords:
        print(f"Custom Keywords (Override): {custom_keywords}")
    if custom_candidates:
        print(f"Custom Candidates (Override): {custom_candidates}")
    print(f"Regional Profile: {regional_profile or 'Auto (Inferred)'}")
    print(f"Date:     {dt.strftime('%Y-%m-%d')} | Time: {dt.strftime('%H:%M')} ({time_of_day})")
    print("=" * 55)

    ctx, candidates, loc_details, prompt = run_pipeline(
        quote, location, dt, time_of_day, ratio,
        language=language, regional_profile=regional_profile,
        custom_keywords=custom_keywords,
        custom_candidates=custom_candidates,
    )

    # Show landmark selection
    if ctx.landmark_selection:
        lm = ctx.landmark_selection
        print(f"\n📍 Landmark: {lm['landmark']['name']} ({lm['landmark'].get('type', '')})")
        print(f"   Score: {lm['score']} | Track: {lm['track']} | Category: {lm['category']}")
        print(f"   Top 3: {', '.join(t['name'] + ' (' + str(t['score']) + ')' for t in lm['top_3'])}")

    # Show layout plan
    if prompt.layout_plan:
        lp = prompt.layout_plan
        status = "✓ Valid" if lp.validation_passed else "✗ Failed"
        print(f"\n📐 Layout: {lp.layout_id} | Weight: {lp.visual_weight_zone} | {status}")
        if lp.repair_applied:
            print(f"   Repaired: {lp.repair_reason}")
        if lp.protected_regions:
            print(f"   Protected: {len(lp.protected_regions)} sacred region(s)")

    if quiet:
        print("\n" + "=" * 60)
        print("FLUX PROMPT (COPYPASTABLE):")
        print("=" * 60)
        print(prompt.full_prompt)
        print("=" * 60)
    else:
        log = build_run_log(
            quote, location, ratio, time_of_day,
            ctx, candidates, loc_details, prompt,
        )
        print(log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        sys.exit(0)
