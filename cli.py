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


def prompt_location() -> str:
    print("\n--- Step 3: Select Location ---")
    loc_keys = list(LOCATIONS.keys())
    for idx, key in enumerate(loc_keys, 1):
        name = LOCATIONS[key].get("name", key.title())
        print(f"  {idx}. {name} ({key})")

    default_idx = 1
    if "mumbai" in loc_keys:
        default_idx = loc_keys.index("mumbai") + 1

    choice = input(f"Choose location (1-{len(loc_keys)}) [default: {default_idx}]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(loc_keys):
        return loc_keys[int(choice) - 1]
    return loc_keys[default_idx - 1]


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
    location_key = prompt_location()
    location = LOCATIONS[location_key]
    ratio = prompt_ratio()
    regional_profile = prompt_regional_profile()
    dt = prompt_datetime()
    time_of_day = classify_time(dt.hour)
    quiet = prompt_view_mode()

    print("\n" + "=" * 55)
    print(f"🚀 Generating Prompt...")
    print(f"Quote:    \"{quote}\"")
    print(f"Language: {language} | Location: {location['name']} | Ratio: {ratio}")
    print(f"Regional Profile: {regional_profile or 'Auto (Inferred)'}")
    print(f"Date:     {dt.strftime('%Y-%m-%d')} | Time: {dt.strftime('%H:%M')} ({time_of_day})")
    print("=" * 55 + "\n")

    ctx, candidates, loc_details, prompt = run_pipeline(
        quote, location, dt, time_of_day, ratio,
        language=language, regional_profile=regional_profile
    )

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
