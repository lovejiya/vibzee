"""
cli.py — Interactive Command Line Interface for Vibzee.
"""
from datetime import datetime
import random
import sys

from specs import LOCATIONS, QUOTES
from panchange_engine import REGIONAL_PROFILES
from app import INDIA_TIMEZONE, run_pipeline, classify_time
from generator import PromptGenerationError
from logs.logger import build_run_log
import sources


def main():
    print("Vibzee Image Prompt Generator (Interactive CLI)")

    # Select quote from default pool, custom input, or random choice
    print("\nQuote Selection:\n1. Pick from default pool\n2. Enter custom quote\n3. Random quote")
    q_choice = input("Enter choice (1/2/3) [default: 1]: ").strip() or "1"
    if q_choice == "2":
        val = input("Enter your custom quote: ").strip()
        quote = val if val else QUOTES[0]
    elif q_choice == "3":
        quote = random.choice(QUOTES)
        print(f"Selected random quote: \"{quote}\"")
    else:
        for idx, q in enumerate(QUOTES, 1):
            print(f"  {idx}. {q}")
        q_idx = input(f"Choose quote number (1-{len(QUOTES)}) [default: 1]: ").strip()
        quote = QUOTES[int(q_idx) - 1] if q_idx.isdigit() and 1 <= int(q_idx) <= len(QUOTES) else QUOTES[0]

    # Select quote natural language
    print("\nQuote Language:")
    langs = ["English", "Hindi", "Sanskrit", "Marathi", "Gujarati", "Bengali", "Tamil", "Telugu", "Kannada", "Punjabi", "Spanish", "French", "Japanese", "Other"]
    for idx, l in enumerate(langs, 1):
        print(f"  {idx}. {l}")
    l_choice = input(f"Choose language (1-{len(langs)}) [default: 1 (English)]: ").strip()
    if l_choice.isdigit() and 1 <= int(l_choice) <= len(langs):
        sel_l = langs[int(l_choice) - 1]
        language = input("Enter language name: ").strip() or "English" if sel_l == "Other" else sel_l
    else:
        language = "English"

    # Select location from supported cities or enter custom
    print("\nLocation Selection:")
    loc_keys = list(LOCATIONS.keys())
    for idx, key in enumerate(loc_keys, 1):
        print(f"  {idx}. {LOCATIONS[key].get('name', key.title())} ({key})")
    print(f"  {len(loc_keys) + 1}. Custom location")
    default_idx = (loc_keys.index("mumbai") + 1) if "mumbai" in loc_keys else 1
    loc_choice = input(f"Choose location (1-{len(loc_keys) + 1}) [default: {default_idx}]: ").strip()
    if loc_choice == str(len(loc_keys) + 1):
        custom_loc = input("Enter custom location name: ").strip()
        location, is_custom_loc = (sources.resolve_location(custom_location=custom_loc), True) if custom_loc else (LOCATIONS["mumbai"], False)
    elif loc_choice.isdigit() and 1 <= int(loc_choice) <= len(loc_keys):
        location, is_custom_loc = LOCATIONS[loc_keys[int(loc_choice) - 1]], False
    else:
        location, is_custom_loc = LOCATIONS[loc_keys[default_idx - 1]], False

    # Select photo aspect ratio
    print("\nPhoto Aspect Ratio:")
    ratios = ["1:1", "2:3", "4:3", "9:16", "16:9"]
    for idx, r in enumerate(ratios, 1):
        print(f"  {idx}. {r}")
    r_choice = input(f"Choose ratio (1-{len(ratios)}) [default: 1 (1:1)]: ").strip()
    ratio = ratios[int(r_choice) - 1] if r_choice.isdigit() and 1 <= int(r_choice) <= len(ratios) else "1:1"

    # Select regional Vedic calendar profile
    print("\nRegional Calendar Profile:\n  0. Auto (Inferred by Location/Language)")
    prof_keys = list(REGIONAL_PROFILES.keys())
    for idx, k in enumerate(prof_keys, 1):
        print(f"  {idx}. {REGIONAL_PROFILES[k]['display_name']}")
    p_choice = input(f"Choose profile (0-{len(prof_keys)}) [default: 0 (Auto)]: ").strip()
    regional_profile = prof_keys[int(p_choice) - 1] if p_choice.isdigit() and 1 <= int(p_choice) <= len(prof_keys) else None

    # Resolve target date and time
    print("\nDate and Time:")
    now = datetime.now(INDIA_TIMEZONE)
    d_input = input(f"Enter Date (YYYY-MM-DD) [default: {now.strftime('%Y-%m-%d')}]: ").strip() or now.strftime("%Y-%m-%d")
    t_input = input(f"Enter Time (HH:MM 24-hr) [default: {now.strftime('%H:%M')}]: ").strip() or now.strftime("%H:%M")
    try:
        dt = datetime.strptime(f"{d_input} {t_input}", "%Y-%m-%d %H:%M")
    except Exception:
        dt = now
    time_of_day = classify_time(dt.hour)

    # Optional direct overrides for keywords and visual candidates
    print("\nOptional Direct Overrides:")
    kw_in = input("Enter own key words (comma-separated, or Enter to auto-extract): ").strip()
    custom_keywords = [k.strip() for k in kw_in.split(",") if k.strip()] if kw_in else None
    cand_in = input("Enter own visual candidates (comma-separated, or Enter for automatic search): ").strip()
    custom_candidates = [c.strip() for c in cand_in.split(",") if c.strip()] if cand_in else None

    # Choose output display mode
    print("\nOutput Display:\n1. Full details & pipeline log\n2. Prompt only (copy-ready)")
    quiet = (input("Enter choice (1/2) [default: 1]: ").strip() or "1") == "2"

    print(f"\nGenerating prompt for \"{quote}\" ({language}, {location['name']}, {ratio})...")

    while True:
        try:
            ctx, candidates, loc_details, prompt = run_pipeline(
                quote, location, dt, time_of_day, ratio,
                language=language, regional_profile=regional_profile,
                custom_keywords=custom_keywords,
                custom_candidates=custom_candidates,
            )
            break
        except PromptGenerationError as exc:
            print(f"\n{exc}", file=sys.stderr)
            if input("Press Enter to retry, or type anything to quit: ").strip():
                return

    # Display landmark selection details if present
    if ctx.landmark_selection:
        lm = ctx.landmark_selection
        print(f"\nLandmark: {lm['landmark']['name']} ({lm['landmark'].get('type', '')})")
        print(f"Score: {lm['score']} | Track: {lm['track']} | Category: {lm['category']}")

    # Display layout validation status
    if prompt.layout_plan:
        lp = prompt.layout_plan
        status = "Valid" if lp.validation_passed else "Failed"
        print(f"\nLayout: {lp.layout_id} | Weight: {lp.visual_weight_zone} | {status}")
        if lp.repair_applied:
            print(f"Repaired: {lp.repair_reason}")

    # Display final generated output
    if quiet:
        print("\nFINAL PROMPT:")
        print(prompt.full_prompt)
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
        print("\nOperation cancelled by user.")
        sys.exit(0)
