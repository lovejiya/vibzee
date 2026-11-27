"""
app.py — Vibzee Image Prompt Generator UI.
Built with Flask (zero external GUI setup needed). Run directly with: python3 app.py
"""
from datetime import datetime, timedelta, timezone
import json
import math
from flask import Flask, Response, jsonify, render_template_string, request, stream_with_context

from specs import APPROACH_TEMPLATES, LOCATIONS, QUOTES
from panchange_engine import REGIONAL_PROFILES, get_coordinator
import sources
import generator

app = Flask(__name__)
STAGES = {
    "context": "Context", "shortlist": "Shortlist", "gemini": "Gemini response",
    "layout": "Layout checks", "final": "Final prompt",
}
STREAM_TYPE = "application/x-ndjson"
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), "IST")


def classify_time(hour: int) -> str:
    if hour < 5:
        return "pre-dawn"
    if hour < 7:
        return "dawn"
    if hour < 9:
        return "morning"
    if hour < 12:
        return "late-morning"
    if hour < 16:
        return "afternoon"
    if hour < 18:
        return "evening"
    if hour < 20:
        return "dusk"
    return "night"


def run_pipeline(
    quote_input, location, date, time_of_day, photo_ratio,
    language="English", regional_profile: str = None,
    custom_keywords: list[str] = None, custom_candidates: list[str] = None
):
    """Run the full generation pipeline and log the result."""
    results = dict(pipeline_stages(
        quote_input, location, date, time_of_day, photo_ratio, language,
        regional_profile, custom_keywords, custom_candidates,
    ))
    candidates, loc_details, _ = results["shortlist"]
    return results["context"], candidates, loc_details, results["final"]


def pipeline_stages(
    quote_input, location, date, time_of_day, photo_ratio,
    language, regional_profile, custom_keywords, custom_candidates,
):
    translated_en_quote = ""
    if not custom_keywords and language.lower() not in ("english", "en"):
        translated_en_quote = generator.translate_quote_to_english(quote_input, language)

    ctx = sources.enrich_context(
        quote=quote_input,
        location=location,
        date=date,
        time_of_day=time_of_day,
        language=language,
        translated_en_quote=translated_en_quote,
        regional_profile=regional_profile,
        custom_keywords=custom_keywords,
    )
    yield "context", ctx

    # Landmark selection — runs after context enrichment so we have theme + emotion
    lm_sel = sources.select_landmark(
        location=location,
        theme=ctx.quote_analysis.theme,
        emotion=ctx.emotion,
        time_of_day=time_of_day,
        situation_keywords=ctx.en_keywords,
    )
    ctx.landmark_selection = lm_sel

    candidates = sources.run_knowledge_chain(
        context=ctx,
        location=location,
        custom_candidates=custom_candidates,
    )
    loc_details = sources.discover_location_details(location, landmark_selection=lm_sel)
    yield "shortlist", (candidates, loc_details, lm_sel)

    for stage, value in generator.generation_stages(candidates, ctx, loc_details, photo_ratio, location):
        if stage == "final":
            prompt = value
        else:
            yield stage, value

    try:
        from logs.logger import get_next_run_id, record_run_log, build_run_log
        run_id = get_next_run_id()
        log_body = build_run_log(
            quote_input, location, photo_ratio, time_of_day,
            ctx, candidates, loc_details, prompt,
        )
        record_run_log(run_id, date, log_body)
    except Exception:
        pass

    yield "final", prompt


HTML_TEMPLATE = r"""
{%- macro facts(items) %}
  <dl class="facts">
    {% for label, value in items if value is defined and value is not none and value != '' %}
      <div><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
    {% endfor %}
  </dl>
{% endmacro -%}

{% macro badge(kind, id, selected) %}
  <span class="selection" data-choice="{{ kind }}" data-id="{{ id }}"{% if id not in selected %} hidden{% endif %}>Selected</span>
{% endmacro -%}

{% macro subjects(options, chosen) %}
  <ul class="options">
    {% for option in options %}
      <li class="option">
        <strong>{{ option.name }}</strong>{{ badge(0, option.id, chosen) }}
        {% if option.selection_context %}<small>{{ option.selection_context }}</small>{% endif %}
        {% if option.chain_sources %}<small>{{ option.chain_sources|join(', ')|replace('_', ' ') }}</small>{% endif %}
      </li>
    {% endfor %}
  </ul>
{% endmacro -%}

{% macro box(area) %}
  {% if area %}x {{ '%.2f'|format(area.x) }} · y {{ '%.2f'|format(area.y) }} · w {{ '%.2f'|format(area.w) }} · h {{ '%.2f'|format(area.h) }}{% endif %}
{% endmacro -%}

{% macro content(stage, results, inputs) %}
  {% set gemini = results.get('gemini', {}) %}
  {% set chosen = gemini.get('selected_metaphor_ids') %}
  {% set chosen = chosen if chosen is sequence and chosen is not string and chosen is not mapping else [] %}
  {% set chosen_details = gemini.get('selected_details') %}
  {% set chosen_details = chosen_details if chosen_details is sequence and chosen_details is not string and chosen_details is not mapping else [] %}

  {% if stage == 'context' %}
    {% set ctx = results.context %}
    {% set calendar = ctx.panchang_details or {} %}
    {% set profile = calendar.regional_profile or {} %}
    <blockquote>{{ inputs.quote_input }}</blockquote>
    {{ facts([
      ('Location', inputs.active_location_name), ('Date', inputs.selected_date),
      ('Time', inputs.selected_time ~ ' · ' ~ inputs.time_of_day|capitalize),
      ('Photo ratio', inputs.selected_ratio), ('Language', inputs.selected_lang),
      ('Regional profile', profile.display_name|default(inputs.profile_label, true)),
      ('Overrides active', ([('Location' if inputs.is_custom_loc else ''), ('Keywords' if inputs.is_custom_kw else ''), ('Subjects' if inputs.is_custom_cand else '')]|reject('equalto', '')|join(', ')))
    ]) }}
    <details>
      <summary>Quote analysis, weather and Panchang</summary>
      {{ facts([
        ('Analyzed text', ctx.quote_analysis.text if ctx.quote_analysis.text != ctx.quote else ''),
        ('Keywords', ctx.en_keywords|join(', ')), ('Theme', ctx.quote_analysis.theme),
        ('Emotion', ctx.emotion.primary), ('Sentiment', ctx.emotion.sentiment),
        ('Negated nouns', ctx.quote_analysis.negated_nouns|join(', ')),
        ('Visual imagery', ctx.visual_imagery|map(attribute='english')|join(', ')),
        ('Weather', ctx.weather.condition), ('Temperature', ctx.weather.temp ~ '°C' if ctx.weather.temp is defined and ctx.weather.temp is not none else ''),
        ('Humidity', ctx.weather.humidity ~ '%' if ctx.weather.humidity is defined and ctx.weather.humidity is not none else ''),
        ('Festival or tithi', ctx.festival or 'None')
      ]) }}
      {% if calendar %}
        {% set astro = calendar.astronomical_panchang or {} %}
        {% set intelligence = calendar.festival_intelligence or {} %}
        {% set resolved = intelligence.resolved_observance or {} %}
        {{ facts([
          ('Regional date', (astro.regional_calendar or {}).regional_date_string),
          ('Amanta month at sunrise', (astro.lunar_month or {}).amanta),
          ('Tithi at sunrise', (astro.tithi or {}).udaya_tithi),
          ('Tithi at ' ~ astro.evaluated_at ~ ' IST', (astro.tithi or {}).running_tithi),
          ('Nakshatra at sunrise', (astro.nakshatra or {}).udaya_nakshatra),
          ('Nakshatra at selected time', (astro.nakshatra or {}).running_nakshatra),
          ('Yoga', (astro.yoga or {}).yoga_name), ('Karana', (astro.karana or {}).current_karana),
          ('Sunrise', (astro.sun_moon_timings or {}).sunrise), ('Sunset', (astro.sun_moon_timings or {}).sunset),
          ('Rahu Kaal', (astro.muhurats or {}).rahu_kalam), ('Abhijit', (astro.muhurats or {}).abhijit_muhurta),
          ('Resolved observance', resolved.name),
          ('Observance date status', resolved.date_status|default('', true)|replace('_', ' ')),
          ('2026 reference observance', intelligence.active_festival),
          ('2026 reference classification', intelligence.classification if intelligence.active_festival else '')
        ]) }}
      {% else %}<p class="muted">Panchang details unavailable.</p>{% endif %}
    </details>

  {% elif stage == 'shortlist' %}
    {% set candidates, details, landmark = results.shortlist %}
    <div class="shortlist-grid">
      <div class="group">
        <h3>Top 5 landmarks</h3>
        {% if landmark %}
          {% set ranks = landmark.top_5|default(landmark.top_3) %}
          <p class="muted">Weighted selection from the top {{ [ranks|length, 3]|min }}.</p>
          <table aria-label="Ranked landmarks">
            <thead><tr><th scope="col">Rank</th><th scope="col">Landmark</th><th scope="col">Score</th></tr></thead>
            <tbody>
              {% for option in ranks %}
                {% set selected = option.selected|default(option.name == landmark.landmark.name) %}
                <tr{% if selected %} class="selected"{% endif %}>
                  <td>{{ loop.index }}</td><td>{{ option.name }} {% if selected %}<span class="selection">Selected</span>{% endif %}</td><td>{{ option.score }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
          <details>
            <summary>Landmark details</summary>
            {{ facts([('Type', landmark.landmark.type), ('Track', landmark.track), ('Category', landmark.category),
              ('Contrast probability', '%.0f%%'|format(landmark.contrast_probability * 100) if landmark.contrast_probability is defined else ''),
              ('Visual description', landmark.landmark.visual_description)]) }}
          </details>
        {% else %}<p class="muted">No ranked landmarks for this run.</p>{% endif %}
      </div>
      <div class="group">
        <h3>Subjects offered <small>{{ candidates.pool|length }}</small></h3>
        <p class="muted">{{ 'User-supplied subjects' if inputs.is_custom_cand else 'In the order sent to Gemini' }}</p>
        {{ subjects(candidates.pool[:5], chosen) }}
        {% if candidates.pool|length > 5 %}
          <details><summary>Show all {{ candidates.pool|length }} subjects</summary>{{ subjects(candidates.pool[5:], chosen) }}</details>
        {% endif %}
      </div>
    </div>
    {% if details %}
      <details>
        <summary>Location details offered <span class="muted">{{ details|length }}</span></summary>
        <ul class="options">
          {% for detail in details %}
            <li class="option"><strong>{{ detail.id }} · {{ detail.source }}</strong>{{ badge(1, detail.id, chosen_details) }}<small>{{ detail.text }}</small></li>
          {% endfor %}
        </ul>
      </details>
    {% endif %}

  {% elif stage == 'gemini' %}
    {% set names = {'original': gemini.original_subject} %}
    {% for candidate in results.shortlist[0].pool %}{% set _ = names.update({candidate.id: candidate.name}) %}{% endfor %}
    {% set main = chosen[0] if chosen and chosen[0] is string else '' %}
    {% set supporting = chosen[1] if chosen|length > 1 and chosen[1] is string else '' %}
    {% set approach = gemini.selected_approach|default('1')|string %}
    {{ facts([
      ('Main subject', names.get(main, main)), ('Supporting subject', names.get(supporting, supporting)),
      ('Original subject', gemini.original_subject),
      ('Style', gemini.selected_domain|default('PHOTOREALISTIC')|capitalize),
      ('Photo approach', inputs.approaches.get(approach, inputs.approaches['1']).name|capitalize)
    ]) }}
    {% if gemini.reasoning %}<blockquote>{{ gemini.reasoning }}</blockquote>{% endif %}
    <details><summary>View response JSON</summary><pre>{{ gemini|tojson(indent=2) }}</pre></details>

  {% elif stage == 'layout' %}
    {% set plan = results.layout %}
    {{ facts([('Layout', plan.layout_id), ('Validation', 'Valid' if plan.validation_passed else 'Failed'),
      ('Visual weight', plan.visual_weight_zone), ('Repair', plan.repair_reason if plan.repair_applied else '')]) }}
    <details>
      <summary>Quote, photo and protected regions</summary>
      {{ facts([('Quote area', box(plan.quote_box)), ('Photo area', box(plan.photo_box))]) }}
      {% if plan.protected_regions %}
        <ul class="options">{% for region in plan.protected_regions %}<li class="option">{{ region.label|replace('_', ' ') }} · {{ region.rule|replace('_', ' ') }}<small>{{ box(region.box) }}</small></li>{% endfor %}</ul>
      {% else %}<p class="muted">No protected regions.</p>{% endif %}
    </details>

  {% elif stage == 'final' %}
    {% set prompt = results.final.full_prompt %}
    <pre id="output-prompt" tabindex="0">{{ prompt }}</pre>
    <div class="prompt-actions"><small>{{ prompt.split()|length }} words</small><button type="button" id="copy-btn">Copy prompt</button></div>
    <p id="copy-feedback" class="muted" role="status"></p>
  {% endif %}
{% endmacro -%}
{% macro select_field(name, label, options, selected, attribute='', auto=false) %}
  <label>{{ label }}
    <select name="{{ name }}">
      {% if auto %}<option value=""{% if not selected %} selected{% endif %}>Auto</option>{% endif %}
      {% for option in options %}
        {% set key, value = (option, option) if option is string else option %}
        <option value="{{ key }}"{% if key == selected %} selected{% endif %}>{{ value[attribute] if attribute else value }}</option>
      {% endfor %}
    </select>
  </label>
{% endmacro %}
{%- if fragment is defined -%}
  {{ content(fragment, results, inputs) }}
{%- else -%}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vibzee Prompt Generator</title>
  <style>
    :root {
      color-scheme: dark;
      --page: #141318;
      --panel: #1d1c23;
      --field: #17161c;
      --line: #44404e;
      --text: #f4f0f5;
      --muted: #b9b1c2;
      --accent: #d1b5f6;
      --selected: #342943;
      --error: #ffb9bb;
      --gutter: clamp(.625rem, 2.6vw, 2rem);
      --space: clamp(.625rem, 1.6vh, 1.1rem);
      --gap: clamp(.6rem, 1.25vh, .85rem);
      --rail: clamp(1.5rem, 2.4vw, 2rem);
      font: 15px/1.5 system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body { margin: 0; background: var(--page); color: var(--text); overflow-wrap: anywhere; }
    main { width: min(100% - 2 * var(--gutter), 96rem); margin: 0 auto; padding: var(--space) 0 calc(2.5 * var(--space)); }
    h1, h2, h3, p { margin: 0; }
    .masthead, .stage-heading, .prompt-actions, .run-error {
      display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .65rem;
    }
    .masthead { margin-bottom: var(--space); }
    h1 { font-size: 1.5rem; font-weight: 550; line-height: 1.25; }
    h1 strong { font-size: 1.8rem; letter-spacing: -.035em; }
    h1 span { margin-left: .55rem; padding-left: .75rem; border-left: 1px solid var(--line); }
    .panel { min-width: 0; border: 1px solid var(--line); border-radius: .65rem; background: var(--panel); }
    form { padding: var(--space); }
    .form-grid, .quote-grid, .shortlist-grid { display: grid; gap: var(--gap); }
    .form-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr)); align-items: end; }
    .quote-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr) auto; margin-top: var(--gap); align-items: end; }
    .overrides-grid { margin-top: var(--gap); align-items: start; }
    label { display: grid; gap: .3rem; min-width: 0; font-weight: 600; }
    input, select, textarea, button { font: inherit; }
    input, select, textarea {
      display: block; width: 100%; min-width: 0; min-height: 2.6rem; padding: .48rem .6rem;
      border: 1px solid #615969; border-radius: .4rem; background: var(--field); color: var(--text);
    }
    textarea { resize: vertical; }
    button {
      min-height: 2.6rem; padding: .48rem .95rem; border: 1px solid transparent; border-radius: .4rem;
      background: var(--accent); color: #201827; font-weight: 700; cursor: pointer;
    }
    button:hover:not(:disabled) { background: #e2cdfb; }
    button:disabled { opacity: .65; cursor: progress; }
    :is(button, input, select, textarea, summary, pre):focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
    details { margin-top: .7rem; }
    summary { width: fit-content; color: var(--accent); font-weight: 600; cursor: pointer; }
    .run-error { margin-top: .8rem; color: var(--error); }
    #run-status, .stage-status { color: var(--muted); font-size: .86rem; }
    .timeline { display: grid; gap: var(--gap); margin: var(--space) 0 0; padding: 0 0 0 var(--rail); list-style: none; }
    .stage { position: relative; padding: var(--gap) clamp(.65rem, 1.55vw, 1rem); }
    .stage:not(:last-child)::before {
      position: absolute; top: 1rem; bottom: calc(-1rem - var(--gap)); left: calc(.625rem - var(--rail));
      width: 1px; background: var(--line); content: '';
    }
    .marker {
      position: absolute; top: .85rem; left: calc(-1 * var(--rail)); width: 1.25rem; height: 1.25rem; display: grid; place-items: center;
      border: 1px solid var(--line); border-radius: 50%; background: var(--page); font-size: .8rem; font-weight: 750;
    }
    .stage[data-state="complete"] .marker { background: var(--accent); color: var(--page); border-color: var(--accent); }
    .stage[data-state="complete"] .marker::before { content: '✓'; }
    .stage[data-state="active"] { border-color: var(--accent); }
    .stage[data-state="active"] :is(.marker, .stage-status) { border-color: var(--accent); color: var(--accent); }
    .stage[data-state="active"] .marker::before { content: '•'; }
    .stage[data-state="failed"] :is(.marker, .stage-status) { border-color: var(--error); color: var(--error); }
    .stage[data-state="failed"] .marker::before { content: '!'; }
    .stage h2 { font-size: 1.2rem; }
    .stage-content:not(:empty) { margin-top: .65rem; }
    .facts { display: flex; flex-wrap: wrap; gap: .5rem 1.2rem; margin: .6rem 0 0; }
    .facts div { min-width: 0; }
    dt, small, .muted { color: var(--muted); font-size: .86rem; }
    dd { margin: 0; }
    blockquote, pre { margin: .5rem 0 0; padding: .65rem .8rem; border-radius: .4rem; background: var(--field); }
    .shortlist-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); }
    .group { min-width: 0; padding: .7rem .8rem; border: 1px solid var(--line); border-radius: .45rem; }
    h3 { font-size: 1rem; }
    table { width: 100%; margin-top: .4rem; border-collapse: collapse; }
    th, td { padding: .35rem .45rem; border-bottom: 1px solid var(--line); text-align: left; }
    th:first-child, td:first-child, th:last-child, td:last-child { width: 1%; white-space: nowrap; }
    th:last-child, td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
    .options { margin: .35rem 0 0; padding: 0; list-style: none; }
    .option { padding: .35rem .45rem; border-bottom: 1px solid var(--line); }
    .option small { display: block; }
    .selected, .option:has(.selection:not([hidden])) { background: var(--selected); }
    .selection { display: inline-block; margin-left: .3rem; padding: .02rem .4rem; border-radius: .3rem; color: var(--accent); font-size: .8rem; font-weight: 700; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; }
    #output-prompt { font: inherit; }
    .prompt-actions { margin-top: .65rem; }
    @media (max-width: 40rem) {
      .quote-grid { grid-template-columns: minmax(0, 1fr); }
      h1 span { font-size: 1.05rem; }
    }
    @media (pointer: coarse) {
      input, select, textarea, button { font-size: 16px; min-height: 2.95rem; }
    }
  </style>
  <script>
    document.addEventListener('DOMContentLoaded', () => {
      const form = document.querySelector('#prompt-form');
      const timeline = document.querySelector('.timeline');
      const rows = [...timeline.children];
      const status = document.querySelector('#run-status');
      const runError = document.querySelector('#run-error');
      const generate = document.querySelector('#generate');
      const retry = document.querySelector('#retry');
      const streamType = 'application/x-ndjson';

      form.elements.preset_quote.addEventListener('change', (event) => {
        form.elements.custom_quote.value = event.target.value;
      });
      timeline.addEventListener('click', async (event) => {
        if (event.target.id !== 'copy-btn') return;
        const prompt = document.querySelector('#output-prompt');
        const feedback = document.querySelector('#copy-feedback');
        try {
          await navigator.clipboard.writeText(prompt.textContent);
          feedback.textContent = 'Prompt copied.';
        } catch {
          prompt.focus();
          const range = document.createRange();
          range.selectNodeContents(prompt);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          feedback.textContent = 'Prompt selected. Use your device’s copy shortcut.';
        }
      });

      if (!window.fetch || !window.ReadableStream || !window.TextDecoderStream) return;
      function setState(row, state) {
        row.dataset.state = state;
        row.querySelector('.stage-status').textContent = state[0].toUpperCase() + state.slice(1);
        if (state === 'active') row.setAttribute('aria-current', 'step');
        else row.removeAttribute('aria-current');
      }

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (generate.disabled) return;
        const body = new URLSearchParams(new FormData(form));
        generate.disabled = retry.disabled = true;
        runError.hidden = true;
        rows.forEach((row) => {
          setState(row, 'waiting');
          row.querySelector('.stage-content').replaceChildren();
        });
        let active = rows[0];
        setState(active, 'active');
        status.textContent = 'Running · Context';

        let reader;
        let pending = '';
        const interrupted = 'The run was interrupted. Please retry.';
        try {
          const response = await fetch(form.action, {method: form.method, headers: {Accept: streamType}, body});
          if (!response.headers.get('content-type')?.startsWith(streamType) || !response.body) throw new Error(interrupted);
          reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          while (active) {
            const {value, done} = await reader.read();
            if (done) throw new Error(interrupted);
            const lines = (pending + value).split('\n');
            pending = lines.pop();
            for (const line of lines) {
              if (!line) continue;
              const update = JSON.parse(line);
              if (update.stage === 'start') continue;
              if (update.stage === 'error') throw new Error(update.message);
              if (update.stage !== active.id) throw new Error(interrupted);
              active.querySelector('.stage-content').innerHTML = update.html;
              if (update.selected) {
                for (const badge of timeline.querySelectorAll('[data-choice]')) {
                  const ids = update.selected[badge.dataset.choice];
                  badge.hidden = !Array.isArray(ids) || !ids.includes(badge.dataset.id);
                }
              }
              setState(active, 'complete');
              active = active.nextElementSibling;
              if (!active) break;
              setState(active, 'active');
              status.textContent = `Running · ${active.querySelector('h2').textContent}`;
            }
          }
          status.textContent = 'Complete';
        } catch (error) {
          if (active) setState(active, 'failed');
          status.textContent = 'Run failed';
          runError.hidden = false;
          document.querySelector('#error-message').textContent = error.constructor === Error ? error.message : interrupted;
        } finally {
          if (reader) reader.cancel().catch(() => {});
          generate.disabled = retry.disabled = false;
        }
      });
    });
  </script>
</head>
<body>
  <main>
    <header class="masthead">
      <h1><strong>Vibzee</strong> <span>Prompt Generator</span></h1>
      <p id="run-status" role="status">{{ 'Run failed' if error else 'Complete' if results else 'Ready' }}</p>
    </header>

    <form id="prompt-form" class="panel" method="post" action="/">
      <div class="form-grid">
        {{ select_field('location_key', 'Location', locations.items(), inputs.selected_loc, 'name') }}
        {{ select_field('photo_ratio', 'Photo ratio', ['1:1', '2:3', '4:3', '9:16', '16:9'], inputs.selected_ratio) }}
        <label>Date <input type="date" name="date" value="{{ inputs.selected_date }}"></label>
        <label>Time <input type="time" name="time" value="{{ inputs.selected_time }}"></label>
        {{ select_field('language', 'Quote language', ['English', 'Hindi', 'Sanskrit', 'Marathi', 'Gujarati', 'Bengali', 'Tamil', 'Telugu', 'Kannada', 'Punjabi', 'Spanish', 'French', 'Japanese'], inputs.selected_lang) }}
        {{ select_field('regional_profile', 'Regional profile', regional_profiles.items(), inputs.selected_profile, 'display_name', auto=true) }}
      </div>
      <div class="quote-grid">
        {{ select_field('preset_quote', 'Preset quote', quotes, inputs.quote_input) }}
        <label>Custom quote <input type="text" id="custom_quote" name="custom_quote" value="{{ inputs.quote_input }}"></label>
        <button id="generate" type="submit">Generate prompt</button>
      </div>
      <details class="overrides"{% if inputs.custom_location or inputs.custom_keywords or inputs.custom_candidates %} open{% endif %}>
        <summary>Overrides</summary>
        <div class="form-grid overrides-grid">
          <label>Custom location <input type="text" name="custom_location" value="{{ inputs.custom_location }}" placeholder="e.g. Jaipur"></label>
          <label>Custom keywords <input type="text" name="custom_keywords" value="{{ inputs.custom_keywords }}" placeholder="Comma-separated keywords"></label>
          <label>Custom subjects <textarea name="custom_candidates" rows="2" placeholder="Separate subjects with commas or new lines">{{ inputs.custom_candidates }}</textarea></label>
        </div>
      </details>
      <div class="run-error" id="run-error"{% if not error %} hidden{% endif %}>
        <span id="error-message" role="alert">{{ error or '' }}</span>
        <button id="retry" type="submit">Retry</button>
      </div>
    </form>

    <ol class="timeline" aria-label="Generation stages">
      {% for stage, title in stages.items() %}
        {% set state = 'complete' if stage in results else 'failed' if stage == failed_stage else 'waiting' %}
        <li class="panel stage" id="{{ stage }}" data-state="{{ state }}">
          <span class="marker" aria-hidden="true"></span>
          <div class="stage-heading"><h2>{{ title }}</h2><span class="stage-status">{{ state|capitalize }}</span></div>
          <div class="stage-content">{{ content(stage, results, inputs) if stage in results else '' }}</div>
        </li>
      {% endfor %}
    </ol>
  </main>
</body>
</html>
{%- endif %}
"""


@app.route("/", methods=["GET", "POST"])
def index():
    now = datetime.now(INDIA_TIMEZONE)
    selected_loc = "mumbai"
    selected_ratio = "1:1"
    selected_lang = "English"
    selected_profile = ""
    selected_date = now.strftime("%Y-%m-%d")
    selected_time = now.strftime("%H:%M")
    quote_input = QUOTES[0]
    results = {}
    time_of_day = classify_time(now.hour)

    custom_location = ""
    custom_keywords = ""
    custom_candidates = ""
    is_custom_loc = False
    is_custom_kw = False
    is_custom_cand = False
    active_location_name = LOCATIONS.get(selected_loc, {}).get("name", "Mumbai")

    if request.method == "POST":
        selected_loc = request.form.get("location_key", "mumbai")
        selected_ratio = request.form.get("photo_ratio", "1:1")
        selected_lang = request.form.get("language", "English")
        selected_profile = request.form.get("regional_profile", "").strip()
        selected_date = request.form.get("date", selected_date)
        selected_time = request.form.get("time", selected_time)
        custom = request.form.get("custom_quote", "").strip()
        quote_input = custom if custom else request.form.get("preset_quote", QUOTES[0])

        custom_location = request.form.get("custom_location", "").strip()
        custom_keywords = request.form.get("custom_keywords", "").strip()
        custom_candidates = request.form.get("custom_candidates", "").strip()

        # Resolve location (direct override if provided)
        if custom_location:
            location = sources.resolve_location(selected_loc, custom_location)
            is_custom_loc = True
            active_location_name = location.get("name", custom_location)
        else:
            location = LOCATIONS.get(selected_loc, LOCATIONS["mumbai"])
            active_location_name = location["name"]

        # Parse custom keywords (direct override if provided)
        parsed_keywords = None
        if custom_keywords:
            parsed_keywords = [k.strip() for k in custom_keywords.split(",") if k.strip()]
            if parsed_keywords:
                is_custom_kw = True

        # Parse custom candidates (direct override if provided)
        parsed_candidates = None
        if custom_candidates:
            lines = [l.strip() for l in custom_candidates.replace("\r", "").split("\n") if l.strip()]
            cand_list = []
            for line in lines:
                for item in line.split(","):
                    val = item.strip()
                    if val:
                        cand_list.append(val)
            if cand_list:
                parsed_candidates = cand_list
                is_custom_cand = True
        try:
            dt = datetime.strptime(f"{selected_date} {selected_time}", "%Y-%m-%d %H:%M")
            time_of_day = classify_time(dt.hour)
        except ValueError:
            results["error"] = ("Enter a valid date and time, then retry.", 400)

    inputs = dict(
        selected_loc=selected_loc,
        selected_ratio=selected_ratio,
        selected_lang=selected_lang,
        selected_profile=selected_profile,
        selected_date=selected_date,
        selected_time=selected_time,
        quote_input=quote_input,
        time_of_day=time_of_day,
        custom_location=custom_location,
        custom_keywords=custom_keywords,
        custom_candidates=custom_candidates,
        is_custom_loc=is_custom_loc,
        is_custom_kw=is_custom_kw,
        is_custom_cand=is_custom_cand,
        active_location_name=active_location_name,
        profile_label=REGIONAL_PROFILES.get(selected_profile, {}).get("display_name", "Auto"),
        approaches=APPROACH_TEMPLATES,
    )

    if request.method == "POST" and "error" not in results:
        def updates():
            try:
                yield from pipeline_stages(
                    quote_input, location, dt, time_of_day, selected_ratio, selected_lang,
                    selected_profile or None, parsed_keywords, parsed_candidates,
                )
            except generator.PromptGenerationError as exc:
                yield "error", (str(exc), 503)
            except Exception:
                app.logger.exception("Prompt pipeline failed")
                yield "error", ("Something went wrong while generating the prompt. Please retry.", 500)

        if request.headers.get("Accept") == STREAM_TYPE:
            def stream():
                yield '{"stage":"start"}\n'
                template = app.jinja_env.from_string(HTML_TEMPLATE)
                for stage, value in updates():
                    results[stage] = value
                    if stage == "error":
                        yield json.dumps({"stage": stage, "message": value[0]}) + "\n"
                        break
                    html = template.render(fragment=stage, results=results, inputs=inputs).strip()
                    event = {"stage": stage, "html": html}
                    if stage == "gemini":
                        event["selected"] = [value.get("selected_metaphor_ids"), value.get("selected_details")]
                    yield json.dumps(event, ensure_ascii=False) + "\n"

            return Response(stream_with_context(stream()), mimetype=STREAM_TYPE, headers={"Cache-Control": "no-store"})

        results.update(updates())

    error, status = results.get("error", (None, 200))
    if error and request.headers.get("Accept") == STREAM_TYPE:
        return Response(json.dumps({"stage": "error", "message": error}) + "\n", status, mimetype=STREAM_TYPE)
    return render_template_string(
        HTML_TEMPLATE, locations=LOCATIONS, quotes=QUOTES, regional_profiles=REGIONAL_PROFILES,
        stages=STAGES, inputs=inputs, results=results, error=error,
        failed_stage=next((stage for stage in STAGES if stage not in results), "final") if error else None,
    ), status


@app.route("/api/panchang", methods=["GET"])
def api_panchang():
    """
    Direct JSON endpoint for querying dual-branch dynamic Panchang.
    Query parameters:
      - date: YYYY-MM-DD (defaults to today)
      - time: local time in HH:MM IST (defaults to noon)
      - location: location key (e.g. mumbai, varanasi), or give lat and lon
      - profile: regional profile id (e.g. maharashtra, gujarat, tamil_nadu)
      - language: language name (e.g. English, Hindi, Marathi)
      - tradition: Smartha or Vaishnava
    """
    date_str = request.args.get("date", datetime.now(INDIA_TIMEZONE).strftime("%Y-%m-%d"))
    time_str = request.args.get("time", "12:00")
    loc_key = request.args.get("location", "mumbai").lower()
    profile_id = request.args.get("profile")
    language = request.args.get("language", "English")
    tradition = request.args.get("tradition", "Smartha")

    coordinates_given = "lat" in request.args or "lon" in request.args
    location_name = None
    if not coordinates_given:
        loc = LOCATIONS.get(loc_key)
        if not loc:
            return jsonify(error="Unknown location key. Supply a supported location or both latitude and longitude."), 400
        lat, lon = loc["lat"], loc["lon"]
        location_name = loc["name"]
    else:
        try:
            lat, lon = float(request.args["lat"]), float(request.args["lon"])
        except (KeyError, ValueError):
            return jsonify(error="Supply numeric lat and lon together."), 400
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify(error="Latitude must be between -90 and 90 and longitude between -180 and 180."), 400
    try:
        target = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        if target.date() == datetime.max.date():
            raise ValueError("Date exceeds supported calculation range.")
    except ValueError:
        return jsonify(error="Enter a valid date (YYYY-MM-DD) and time (HH:MM)."), 400

    coord = get_coordinator()
    res = coord.calculate_panchang(
        target_date=target.date(),
        lat=lat,
        lon=lon,
        location_name=location_name,
        regional_profile_id=profile_id,
        language=language,
        tradition=tradition,
        eval_time=target.time(),
    )
    return jsonify(res)


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("🚀 Vibzee UI running!")
    print("👉 On this machine:        http://127.0.0.1:5001")
    print("👉 On same Wi-Fi network:  http://<YOUR-IP>:5001")
    print("   (Find your IP with: ipconfig getifaddr en0)")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=5001, debug=False)
