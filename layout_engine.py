"""
layout_engine.py — Deterministic geometry for the 8-layout system.

Calculates bounding boxes for quote and photo placement,
validates against cultural guardrails, and repairs violations.
"""
import json
from pathlib import Path

from specs import (
    BoundingBox, ProtectedRegion, LayoutPlan,
    LAYOUT_PROFILES, SACRED_SUBJECT_TYPES, GUARDRAIL_POLICY_VERSION,
)

_GUARDRAILS = None


def _load_guardrails() -> dict:
    global _GUARDRAILS
    if _GUARDRAILS is None:
        path = Path(__file__).parent / "data" / "layout_guardrails.json"
        _GUARDRAILS = json.loads(path.read_text(encoding="utf-8"))
    return _GUARDRAILS


def compute_layout(layout_id: str, photo_ratio: str = "1:1") -> LayoutPlan:
    """Build a LayoutPlan with deterministic quote/photo bounding boxes."""
    guardrails = _load_guardrails()
    geom = guardrails["layout_geometry"].get(layout_id)
    profile = LAYOUT_PROFILES.get(layout_id)

    if not geom or not profile:
        geom = guardrails["layout_geometry"]["RB-V"]
        profile = LAYOUT_PROFILES["RB-V"]
        layout_id = "RB-V"

    q = geom["quote"]
    p = geom["photo"]

    photo_w, photo_h = p["w"], p["h"]
    if photo_ratio == "2:3":
        photo_h = photo_w * 1.5
    elif photo_ratio == "9:16":
        photo_h = photo_w * (16 / 9)
    elif photo_ratio == "16:9":
        photo_h = photo_w * (9 / 16)
    elif photo_ratio == "4:3":
        photo_h = photo_w * (3 / 4)

    photo_h = min(photo_h, 0.40)

    return LayoutPlan(
        layout_id=layout_id,
        quote_box=BoundingBox(x=q["x"], y=q["y"], w=q["w"], h=q["h"]),
        photo_box=BoundingBox(x=p["x"], y=p["y"], w=photo_w, h=photo_h),
        visual_weight_zone=profile.get("visual_weight", ""),
    )


def detect_sacred_regions(gemini_selections: dict) -> list[ProtectedRegion]:
    """Extract protected regions from Gemini's creative plan output."""
    regions = []
    sacred_items = gemini_selections.get("sacred_subjects", [])
    for item in sacred_items:
        label = item.get("type", "unknown")
        pos = item.get("position", {})
        if not pos:
            continue
        box = BoundingBox(
            x=pos.get("x", 0.0), y=pos.get("y", 0.0),
            w=pos.get("w", 0.15), h=pos.get("h", 0.15),
        )
        rule = "no_overlap" if label in SACRED_SUBJECT_TYPES else "partial_ok"
        regions.append(ProtectedRegion(label=label, box=box, rule=rule))
    return regions


def validate_layout(plan: LayoutPlan) -> tuple[bool, list[str]]:
    """Check layout constraints. Returns (passed, list_of_violations)."""
    violations = []
    guardrails = _load_guardrails()
    limits = guardrails["overlap_limits"]

    if plan.quote_box and plan.photo_box:
        overlap = plan.quote_box.overlap_area(plan.photo_box)
        if overlap > limits["max_quote_photo_overlap_pct"]:
            violations.append(f"quote/photo overlap: {overlap:.3f}")

    if plan.quote_box:
        if plan.quote_box.right > 1.0 or plan.quote_box.bottom > 1.0:
            violations.append("quote_box exceeds canvas")
    if plan.photo_box:
        if plan.photo_box.right > 1.0 or plan.photo_box.bottom > 1.0:
            violations.append("photo_box exceeds canvas")

    for region in plan.protected_regions:
        if region.rule != "no_overlap":
            continue
        if plan.quote_box and plan.quote_box.overlap_area(region.box) > 0:
            violations.append(f"quote overlaps {region.label}")
        if plan.photo_box and plan.photo_box.overlap_area(region.box) > 0:
            violations.append(f"photo overlaps {region.label}")

    passed = len(violations) == 0
    return passed, violations


def repair_layout(plan: LayoutPlan, max_attempts: int = 3) -> LayoutPlan:
    """Shift boxes to fix violations. Bounded: gives up after max_attempts."""
    margin = _load_guardrails()["canvas"]["margin"]

    for attempt in range(max_attempts):
        passed, violations = validate_layout(plan)
        if passed:
            plan.validation_passed = True
            return plan

        for region in plan.protected_regions:
            if region.rule != "no_overlap":
                continue

            if plan.quote_box and plan.quote_box.overlaps(region.box):
                plan.quote_box = _shift_away(plan.quote_box, region.box, margin)
                plan.repair_applied = True
                plan.repair_reason = f"shifted quote from {region.label}"

            if plan.photo_box and plan.photo_box.overlaps(region.box):
                plan.photo_box = _shift_away(plan.photo_box, region.box, margin)
                plan.repair_applied = True
                plan.repair_reason = f"shifted photo from {region.label}"

        if plan.quote_box and plan.photo_box and plan.quote_box.overlaps(plan.photo_box):
            plan.photo_box = _shift_away(plan.photo_box, plan.quote_box, margin)
            plan.repair_applied = True
            plan.repair_reason = "resolved quote/photo overlap"

    plan.validation_passed, _ = validate_layout(plan)
    return plan


def _shift_away(box: BoundingBox, obstacle: BoundingBox, margin: float) -> BoundingBox:
    """Move box to clear the obstacle with minimal displacement."""
    cx_box = box.x + box.w / 2
    cx_obs = obstacle.x + obstacle.w / 2
    cy_box = box.y + box.h / 2
    cy_obs = obstacle.y + obstacle.h / 2

    dx = cx_box - cx_obs
    dy = cy_box - cy_obs

    if abs(dx) >= abs(dy):
        if dx >= 0:
            new_x = obstacle.right + margin
        else:
            new_x = obstacle.x - box.w - margin
        new_y = box.y
    else:
        new_x = box.x
        if dy >= 0:
            new_y = obstacle.bottom + margin
        else:
            new_y = obstacle.y - box.h - margin

    new_x = max(margin, min(new_x, 1.0 - box.w - margin))
    new_y = max(margin, min(new_y, 1.0 - box.h - margin))

    return BoundingBox(x=round(new_x, 3), y=round(new_y, 3), w=box.w, h=box.h)


def select_layout(context, recent_runs: list) -> str:
    """Pick a layout_id based on context and recency avoidance."""
    recent_layouts = {r.get("layout") for r in recent_runs[-4:]}
    arrangement = context.landmark_selection.get("landmark", {}).get("type", "") if context.landmark_selection else ""

    prefer_vertical = arrangement in ("temple", "fort", "monument", "minaret", "spire")

    candidates = []
    for lid, prof in LAYOUT_PROFILES.items():
        if lid in recent_layouts:
            continue
        if prefer_vertical and prof["arrangement"] != "vertical":
            continue
        candidates.append(lid)

    if not candidates:
        candidates = list(LAYOUT_PROFILES.keys())

    import random
    return random.choice(candidates)


def build_layout_context_for_gemini(plan: LayoutPlan) -> str:
    """Format layout geometry as text for the Gemini menu."""
    lines = [f"  Layout: {plan.layout_id}"]
    if plan.quote_box:
        q = plan.quote_box
        lines.append(f"  Quote zone: x={q.x:.2f} y={q.y:.2f} w={q.w:.2f} h={q.h:.2f}")
    if plan.photo_box:
        p = plan.photo_box
        lines.append(f"  Photo zone: x={p.x:.2f} y={p.y:.2f} w={p.w:.2f} h={p.h:.2f}")
    lines.append(f"  Visual weight: {plan.visual_weight_zone}")
    return "\n".join(lines)


def get_policy_version() -> str:
    return GUARDRAIL_POLICY_VERSION
