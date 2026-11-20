"""
generator.py — Builds the menu for Gemini, calls Gemini, parses the result.

Called by app.py. Does NOT gather data — that is sources.py's job.

Deviation from plan v14:
  The plan imports `google.generativeai`. This project's model is
  gemini-3.1-flash-lite, so we prefer the current unified SDK (`google.genai`)
  and fall back to `google.generativeai`. If neither SDK / no key is available,
  the rule-based fallback() produces a valid prompt (edge case 3).
"""
import json
import random
from datetime import datetime

from specs import (
    GEMINI_SYSTEM_PROMPT, GEMINI_MODEL, GEMINI_API_KEY,
    DOMAIN_PROFILES, LAYOUT_PROFILES, APPROACH_TEMPLATES,
    MasterPrompt, RECENT_RUNS_PATH, SACRED_SUBJECT_TYPES,
)
from layout_engine import (
    compute_layout, detect_sacred_regions, validate_layout,
    repair_layout, select_layout, build_layout_context_for_gemini,
)
from pathlib import Path


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
        sacred = detect_sacred_regions(selections)
        layout_plan.protected_regions = sacred
        passed, violations = validate_layout(layout_plan)
        if not passed:
            layout_plan = repair_layout(layout_plan)
        else:
            layout_plan.validation_passed = True

        prompt = build_master_prompt(selections, candidates, location_details, photo_ratio, layout_plan)
        prompt = verify_word_count(prompt)
    except Exception as exc:
        layout_plan.validation_passed = True
        prompt = fallback(candidates, context, location_details, photo_ratio, layout_plan)
        prompt.gemini_selections.setdefault("error", str(exc))

    save_recent(prompt)
    return prompt


def build_menu(candidates, context, location_details, photo_ratio, location, recent, layout_plan=None) -> str:
    """
    Format pre-built pieces into a structured menu for Gemini.

    Variety is enforced STRUCTURALLY, not just hinted: metaphors, domains and
    layouts used in recent runs are removed from the menu outright (as long as
    alternatives remain), so an identical metaphor+domain+layout combo cannot
    recur on consecutive runs of the same quote.
    """
    pool = _filter_recent_metaphors(candidates.pool, recent)
    domains = _filter_recent(list(DOMAIN_PROFILES), {r.get("domain") for r in recent[-4:]}, keep_min=2)
    layouts = _filter_recent(list(LAYOUT_PROFILES), {r.get("layout") for r in recent[-4:]}, keep_min=3)

    recent_avoid = "; ".join(
        f'{r.get("metaphor")}({r.get("domain")},{r.get("layout")})' for r in recent[-10:]
    ) if recent else "None"

    quote_native = [c for c in pool if c.quote_native]
    supplementary = [c for c in pool if not c.quote_native]

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
  Recent (avoid): {recent_avoid}
"""
    if layout_plan:
        menu += "\n=== LAYOUT GEOMETRY (pre-computed, do NOT change) ===\n"
        menu += build_layout_context_for_gemini(layout_plan) + "\n"
        menu += ("  Place the scene's visual weight in the " + layout_plan.visual_weight_zone + " zone.\n")
        menu += ("  SACRED SUBJECT RULE: If the scene includes a deity, temple spire, dome,\n"
                 "  sacred fire, or other sacred element, report its approximate position\n"
                 "  in the 'sacred_subjects' field so we can protect it from text overlay.\n")
    if quote_native:
        menu += "\n=== QUOTE-NATIVE VISUALS ===\n"
        menu += "These come from the quote's own words. They are the PRIMARY subject.\n"
        for c in quote_native:
            menu += f'\n[{c.id}] "{c.name}" [{c.domain}]\n'
            menu += f'  Subject text: "{c.subject_text}"\n'
            menu += f'  Scene text: "{c.scene_text}"\n'
            menu += f'  Visual phrases: {c.visual_phrases}\n'

    menu += "\n=== SUPPLEMENTARY CANDIDATES ===\n"
    if quote_native:
        menu += "These add atmosphere. Do NOT use as main subject if quote-native visuals exist.\n"
    else:
        menu += "Pick 1-2. Each has pre-written text — use ONLY these words.\n"
    for c in supplementary:
        menu += f"""
[{c.id}] "{c.name}" [{c.domain}]
  Groundable: {c.groundable} | Cultural: {c.cultural} | Chains: {c.chain_sources}
  Entity type: {c.entity_type}
  Subject text: "{c.subject_text}"
  Scene text: "{c.scene_text}"
  Weather: {c.weather_context}
  Visual phrases: {c.visual_phrases}
  Verb type: {c.verb_type}
"""

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
        raise RuntimeError("No LLM API key configured (VIBZEE_LLM_API_KEY).")

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
    subject_parts = [cand_by_id[cid].subject_text for cid in chosen_ids if cid in cand_by_id and cand_by_id[cid].subject_text]
    subject = ", blended with ".join(subject_parts)

    # Scene from first available metaphor
    scene = ""
    for cid in chosen_ids:
        if cid in cand_by_id and cand_by_id[cid].scene_text:
            scene = cand_by_id[cid].scene_text
            break
    if not scene and candidates.pool:
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
        metaphor_used=str(chosen_ids),
        full_prompt=selections.get("full_prompt", "").strip(),
        gemini_selections=selections,
        layout_plan=layout_plan,
    )


def verify_word_count(prompt: MasterPrompt) -> MasterPrompt:
    """No-op — word count limit removed (DALL-E 3 via ChatGPT handles long prompts)."""
    return prompt


def fallback(candidates, context, location_details, photo_ratio, layout_plan=None) -> MasterPrompt:
    """Rule-based fallback when Gemini is down. Picks diverse candidates & styles."""
    pool = candidates.pool if candidates.pool else []
    recent = load_recent()
    filtered_pool = _filter_recent_metaphors(pool, recent) if pool else []
    candidate_pool = filtered_pool or pool
    candidate = random.choice(candidate_pool) if candidate_pool else None

    details = random.sample(location_details, min(3, len(location_details))) if location_details else []
    detail_text = ", ".join(d["text"] for d in details)

    available_domains = _filter_recent(list(DOMAIN_PROFILES), {r.get("domain") for r in recent[-4:]}, keep_min=2)
    domain = candidate.domain if (candidate and candidate.domain in DOMAIN_PROFILES) else random.choice(available_domains)
    layout = layout_plan.layout_id if layout_plan else random.choice(
        _filter_recent(list(LAYOUT_PROFILES), {r.get("layout") for r in recent[-4:]}, keep_min=3))
    approach = str(random.randint(1, 4))

    subject = candidate.subject_text if candidate else ""
    scene = candidate.scene_text if candidate else ""

    # Inject landmark visual description into scene if available
    lm_sel = context.landmark_selection if hasattr(context, "landmark_selection") else None
    if lm_sel:
        lm_vis = lm_sel["landmark"].get("visual_description", "")
        if lm_vis:
            scene = f"{lm_vis}, {scene}" if scene else lm_vis

    parts = [
        f"{photo_ratio} portrait image, high resolution.",
        f"{subject}." if subject else "",
        f"{scene}." if scene else "",
        f"{detail_text}." if detail_text else "",
        f"{DOMAIN_PROFILES[domain]['style_text']}.",
        f"No text, no watermarks. {DOMAIN_PROFILES[domain]['avoid_text']}",
    ]
    full_prompt = " ".join(p for p in parts if p)

    return MasterPrompt(
        image_type_format="4:5 portrait image, high resolution",
        subject=subject,
        scene=scene,
        style=DOMAIN_PROFILES[domain]["style_text"],
        composition=LAYOUT_PROFILES[layout]["gemini_guidance"],
        empty_space=APPROACH_TEMPLATES.get(approach, APPROACH_TEMPLATES["1"])["gemini_guidance"],
        details=detail_text,
        avoid=DOMAIN_PROFILES[domain]["avoid_text"],
        quote_used=candidates.quote,
        full_prompt=full_prompt,
        layout_id=layout,
        visual_domain=domain,
        photo_approach=approach,
        photo_ratio=photo_ratio,
        metaphor_used=candidate.name if candidate else "",
        gemini_selections={"fallback": True, "reasoning": "Gemini unavailable"},
        layout_plan=layout_plan,
    )


# ── helpers ─────────────────────────────────────────

def _filter_recent_metaphors(pool, recent, lookback=6):
    """Drop candidates whose id was used in recent runs, unless nothing would remain."""
    used = " ".join(str(r.get("metaphor", "")) for r in recent[-lookback:])
    fresh = [c for c in pool if c.id not in used]
    return fresh if fresh else pool


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
