"""
generator.py — Builds the menu for Gemini, calls Gemini, parses the result.

Called by app.py after source discovery.
"""
import json
from datetime import datetime
from pathlib import Path

from specs import (
    GEMINI_SYSTEM_PROMPT, GEMINI_MODEL, GEMINI_API_KEY,
    DOMAIN_PROFILES, LAYOUT_PROFILES, APPROACH_TEMPLATES,
    MasterPrompt, RECENT_RUNS_PATH,
)
from layout_engine import (
    compute_layout, detect_sacred_regions, validate_layout,
    repair_layout, select_layout, build_layout_context_for_gemini,
)


class PromptGenerationError(RuntimeError):
    """Gemini could not return a usable image prompt."""


def generate(candidates, context, location_details, photo_ratio, location) -> MasterPrompt:
    """
    Main generation function. Called by app.py Step 2.

    1. Compute deterministic layout geometry
    2. Build menu of pre-written pieces (with layout context)
    3. Call Gemini to select + restructure
    4. Detect sacred regions from Gemini output, validate & repair
    5. Save to recency
    6. Return MasterPrompt
    """
    recent = load_recent()

    layout_id = select_layout(context, recent)
    layout_plan = compute_layout(layout_id, photo_ratio)

    menu = build_menu(candidates, context, location_details, photo_ratio, location, recent, layout_plan)

    try:
        selections = call_gemini(menu)
        full_prompt = selections.get("full_prompt") if isinstance(selections, dict) else None
        if not isinstance(full_prompt, str) or not full_prompt.strip():
            raise PromptGenerationError("Gemini returned an empty or invalid prompt.")

        sacred = detect_sacred_regions(selections)
        layout_plan.protected_regions = sacred
        passed, _ = validate_layout(layout_plan)
        if not passed:
            layout_plan = repair_layout(layout_plan)
        else:
            layout_plan.validation_passed = True

        prompt = build_master_prompt(selections, candidates, location_details, photo_ratio, layout_plan)
    except PromptGenerationError:
        raise
    except Exception as exc:
        raise PromptGenerationError("Gemini couldn’t generate a usable prompt.") from exc

    save_recent(prompt)
    return prompt


def build_menu(candidates, context, location_details, photo_ratio, location, recent, layout_plan=None) -> str:
    """Format the shortlist and scene context for Gemini."""
    domains = _filter_recent(list(DOMAIN_PROFILES), {r.get("domain") for r in recent[-4:]}, keep_min=2)
    layouts = _filter_recent(list(LAYOUT_PROFILES), {r.get("layout") for r in recent[-4:]}, keep_min=3)

    recent_avoid = "; ".join(
        f'{r.get("metaphor")}({r.get("domain")},{r.get("layout")})' for r in recent[-10:]
    ) if recent else "None"

    # Landmark context for Gemini
    lm_sel = context.landmark_selection
    lm_context = ""
    if lm_sel:
        lm = lm_sel["landmark"]
        lm_context = f"""  Landmark: {lm['name']} ({lm.get('type', '')})
  Landmark visual: {lm.get('visual_description', '')}
  Landmark track: {lm_sel['track']} (category: {lm_sel['category']})"""

    menu = f"""CONTEXT:
  Quote: "{candidates.quote}"
  Emotion: {context.emotion.get('primary')}
  Theme: {candidates.theme}
  Negated: {candidates.negated}
  Weather: {context.weather.get('condition')}, {context.weather.get('temp')}C
  Time: {context.time}
  Festival: {context.festival or "None"}
  Photo ratio: {photo_ratio}
  Location: {location['name']}
{lm_context}
  Recent choices (prefer variety when options fit equally well): {recent_avoid}
"""
    if layout_plan:
        menu += "\n=== LAYOUT GEOMETRY (pre-computed, do NOT change) ===\n"
        menu += build_layout_context_for_gemini(layout_plan) + "\n"
        menu += ("  Place the scene's visual weight in the " + layout_plan.visual_weight_zone + " zone.\n")
        menu += ("  SACRED SUBJECT RULE: If the scene includes a deity, temple spire, dome,\n"
                 "  sacred fire, or other sacred element, report its approximate position\n"
                 "  in the 'sacred_subjects' field so we can protect it from text overlay.\n")
    menu += "\n=== SUBJECT CANDIDATES ===\n"
    for candidate in candidates.pool:
        sources = ", ".join(candidate.chain_sources)
        reason = candidate.selection_context
        details = ", ".join(candidate.visual_phrases[:3])
        menu += f"[{candidate.id}] {candidate.name} ({sources})"
        if reason:
            menu += f" | {reason}"
        if details:
            menu += f" | Visual details: {details}"
        menu += "\n"

    menu += "\n=== DOMAINS ===\nPick 1. Use its style_text and avoid_text.\n"
    for name in domains:
        prof = DOMAIN_PROFILES[name]
        menu += f'[{name}] style: "{prof["style_text"]}" | avoid: "{prof["avoid_text"]}"\n'

    if layout_plan:
        sel_prof = LAYOUT_PROFILES.get(layout_plan.layout_id, {})
        menu += (f'\n=== SELECTED LAYOUT ===\n'
                 f'[{layout_plan.layout_id}] ({sel_prof.get("corner", "")}, {sel_prof.get("arrangement", "")}): '
                 f'{sel_prof.get("gemini_guidance", "")}\n')
    else:
        menu += ("\n=== LAYOUTS ===\nPick 1. Use this to guide WHERE to place scene "
                 "elements — do NOT put this text in the prompt.\n")
        for name in layouts:
            prof = LAYOUT_PROFILES[name]
            menu += f'[{name}] ({prof["corner"]}, {prof["arrangement"]}): {prof["gemini_guidance"]}\n'

    menu += ("\n=== APPROACHES ===\nPick 1. Use this to guide HOW the empty corner "
             "is described — do NOT put this text in the prompt.\n")
    for num, appr in APPROACH_TEMPLATES.items():
        menu += f'[{num}] {appr["name"]}: {appr["gemini_guidance"]} (best: {appr["best_when"]})\n'

    menu += "\n=== LOCATION DETAILS ===\nPick 2-3.\n"
    for d in location_details:
        menu += f'[{d["id"]}] "{d["text"]}" (from {d["source"]})\n'

    return menu


def call_gemini(menu: str) -> dict:
    """Call Gemini with system prompt + menu. Returns parsed JSON."""
    if not GEMINI_API_KEY:
        raise PromptGenerationError("Gemini is unavailable. Set VIBZEE_LLM_API_KEY before retrying.")

    # Prefer the current unified SDK.
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=menu,
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.85,
            ),
        )
        return json.loads(response.text)
    except ImportError:
        pass

    # Fall back to the legacy SDK named in the plan.
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        GEMINI_MODEL, system_instruction=GEMINI_SYSTEM_PROMPT)
    response = model.generate_content(
        menu,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.85,
        },
    )
    return json.loads(response.text)


def translate_quote_to_english(quote: str, language: str) -> str:
    """Translate quote to English using Gemini if language is not English."""
    if not quote or language.lower() in ("english", "en"):
        return quote

    if not GEMINI_API_KEY:
        return quote

    prompt = f"Translate the following {language} quote into a clear, natural English sentence. Return only the translated English quote text, nothing else:\n\n{quote}"

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        text = resp.text.strip().strip('"\'')
        return text if text else quote
    except Exception:
        pass

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        m = genai.GenerativeModel(GEMINI_MODEL)
        resp = m.generate_content(prompt)
        text = resp.text.strip().strip('"\'')
        return text if text else quote
    except Exception:
        return quote


def build_master_prompt(selections, candidates, location_details, photo_ratio, layout_plan=None) -> MasterPrompt:
    """Build MasterPrompt from Gemini's selections."""
    domain = selections.get("selected_domain", "PHOTOREALISTIC")
    layout = layout_plan.layout_id if layout_plan else selections.get("selected_layout", "RB-V")
    approach = str(selections.get("selected_approach", "1"))

    # Subject from selected metaphor ids
    cand_by_id = {c.id: c for c in candidates.pool}
    chosen_ids = selections.get("selected_metaphor_ids", [])
    subjects = {cid: c.name or c.subject_text for cid, c in cand_by_id.items()}
    if "original" in chosen_ids:
        original = selections.get("original_subject")
        if (
            not isinstance(original, str) or not original.strip()
            or chosen_ids.count("original") != 1 or len(chosen_ids) > 2
            or any(cid != "original" and cid not in cand_by_id for cid in chosen_ids)
            or any("user_override" in c.chain_sources for c in candidates.pool)
        ):
            raise PromptGenerationError("Gemini returned an invalid original subject.")
        subjects["original"] = original.strip()
    subject = ", blended with ".join(subjects[cid] for cid in chosen_ids if subjects.get(cid))

    # Scene from first available metaphor
    scene = ""
    for cid in chosen_ids:
        if cid in cand_by_id and cand_by_id[cid].scene_text:
            scene = cand_by_id[cid].scene_text
            break
    if not scene and candidates.pool and "original" not in chosen_ids:
        scene = candidates.pool[0].scene_text

    # Location details
    details_map = {d["id"]: d["text"] for d in location_details}
    details = ", ".join(details_map[c] for c in selections.get("selected_details", []) if c in details_map)

    empty_space = APPROACH_TEMPLATES.get(approach, APPROACH_TEMPLATES["1"])["gemini_guidance"]

    return MasterPrompt(
        image_type_format="4:5 portrait image, high resolution",
        subject=subject,
        scene=scene,
        style=DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["PHOTOREALISTIC"])["style_text"],
        composition=LAYOUT_PROFILES.get(layout, LAYOUT_PROFILES["RB-V"])["gemini_guidance"],
        empty_space=empty_space,
        details=details,
        avoid=DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["PHOTOREALISTIC"])["avoid_text"],
        quote_used=candidates.quote,
        layout_id=layout,
        photo_ratio=photo_ratio,
        photo_approach=approach,
        visual_domain=domain,
        metaphor_used=str([subjects[cid] if cid == "original" else cid for cid in chosen_ids]),
        full_prompt=selections.get("full_prompt", "").strip(),
        gemini_selections=selections,
        layout_plan=layout_plan,
    )


def _filter_recent(options, used, keep_min):
    """Remove recently-used options, but always leave at least `keep_min`."""
    fresh = [o for o in options if o not in used]
    return fresh if len(fresh) >= keep_min else options


def load_recent() -> list:
    try:
        from logs.logger import cloud_load_recent
        cloud_data = cloud_load_recent()
        if cloud_data:
            return cloud_data
    except Exception:
        pass

    path = Path(RECENT_RUNS_PATH)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_recent(prompt: MasterPrompt):
    entry = {
        "date": str(datetime.now()),
        "metaphor": prompt.metaphor_used,
        "domain": prompt.visual_domain,
        "layout": prompt.layout_id,
        "approach": prompt.photo_approach,
    }

    try:
        from logs.logger import cloud_save_recent
        cloud_save_recent(entry)
    except Exception:
        pass

    recent = load_recent()
    recent.append(entry)
    recent = recent[-30:]
    try:
        Path(RECENT_RUNS_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(RECENT_RUNS_PATH).write_text(
            json.dumps(recent, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
