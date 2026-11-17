"""
app.py — Vibzee Image Prompt Generator UI.
Built with Flask (zero external GUI setup needed). Run directly with: python3 app.py
"""
from datetime import datetime
import json
from flask import Flask, request, render_template_string, jsonify

from specs import LOCATIONS, QUOTES, MasterPrompt
from panchange_engine import REGIONAL_PROFILES, get_coordinator
import sources
import generator

app = Flask(__name__)


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


def run_pipeline(quote_input, location, date, time_of_day, photo_ratio, language="English", regional_profile: str = None):
    """Run the full generation pipeline and log the result."""
    translated_en_quote = ""
    if language.lower() not in ("english", "en"):
        translated_en_quote = generator.translate_quote_to_english(quote_input, language)

    ctx = sources.enrich_context(
        quote=quote_input,
        location=location,
        date=date,
        time_of_day=time_of_day,
        language=language,
        translated_en_quote=translated_en_quote,
        regional_profile=regional_profile,
    )
    candidates = sources.run_knowledge_chain(context=ctx, location=location)
    loc_details = sources.discover_location_details(location)

    prompt = generator.generate(
        candidates=candidates,
        context=ctx,
        location_details=loc_details,
        photo_ratio=photo_ratio,
        location=location,
    )

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

    return ctx, candidates, loc_details, prompt


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Vibzee Prompt Generator</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 24px; }
    .container { max-width: 760px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); padding: 28px 36px; }
    h1 { margin-top: 0; color: #0f172a; font-size: 24px; }
    .stage { border-left: 4px solid #6366f1; padding: 12px 18px; margin: 20px 0; background: #f1f5f9; border-radius: 0 8px 8px 0; }
    .stage h2 { margin: 0 0 10px 0; font-size: 16px; color: #4338ca; text-transform: uppercase; letter-spacing: 0.5px; }
    label { font-weight: 600; display: block; margin: 10px 0 4px; font-size: 14px; }
    select, input, textarea { width: 100%; padding: 8px 12px; border: 1px solid #cbd5e1; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
    button { background: #4f46e5; color: #fff; border: none; padding: 10px 18px; border-radius: 6px; font-size: 15px; font-weight: 600; cursor: pointer; margin-top: 14px; }
    button:hover { background: #4338ca; }
    .copy-btn { background: #10b981; float: right; margin-top: -6px; padding: 6px 12px; font-size: 13px; }
    .copy-btn:hover { background: #059669; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    pre { background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.5; }
    .badge { display: inline-block; background: #e0e7ff; color: #3730a3; padding: 3px 8px; border-radius: 4px; font-size: 12px; margin-right: 6px; }
    blockquote { border-left: 3px solid #cbd5e1; margin: 0; padding-left: 12px; color: #475569; font-style: italic; }
  </style>
  <script>
    function copyPrompt() {
      const code = document.getElementById("output-prompt").innerText;
      navigator.clipboard.writeText(code).then(() => {
        const btn = document.getElementById("copy-btn");
        btn.innerText = "✓ Copied!";
        setTimeout(() => btn.innerText = "Copy Prompt", 2000);
      });
    }
  </script>
</head>
<body>
<div class="container">
  <h1>✨ Vibzee Image Prompt Generator</h1>

  <!-- STAGE 1: INPUT -->
  <div class="stage">
    <h2>Stage 1: Input Variables</h2>
    <form method="POST" action="/">
      <div class="grid">
        <div>
          <label>Location</label>
          <select name="location_key">
            {% for key, val in locations.items() %}
              <option value="{{ key }}" {% if selected_loc == key %}selected{% endif %}>{{ val.name }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label>Photo Ratio</label>
          <select name="photo_ratio">
            {% for r in ["1:1", "2:3", "4:3", "9:16", "16:9"] %}
              <option value="{{ r }}" {% if selected_ratio == r %}selected{% endif %}>{{ r }}</option>
            {% endfor %}
          </select>
        </div>
      </div>

      <div class="grid" style="margin-top: 10px;">
        <div>
          <label>Date</label>
          <input type="date" name="date" value="{{ selected_date }}">
        </div>
        <div>
          <label>Time</label>
          <input type="time" name="time" value="{{ selected_time }}">
        </div>
      </div>

      <div style="margin-top: 10px;">
        <label>Quote Language</label>
        <select name="language">
          {% for lang in ["English", "Hindi", "Sanskrit", "Marathi", "Gujarati", "Bengali", "Tamil", "Telugu", "Kannada", "Punjabi", "Spanish", "French", "Japanese"] %}
            <option value="{{ lang }}" {% if selected_lang == lang %}selected{% endif %}>{{ lang }}</option>
          {% endfor %}
        </select>
      </div>

      <div style="margin-top: 10px;">
        <label>Regional Calendar Profile</label>
        <select name="regional_profile">
          <option value="" {% if not selected_profile %}selected{% endif %}>Auto (Inferred by Location/Language)</option>
          {% for pid, prof in regional_profiles.items() %}
            <option value="{{ pid }}" {% if selected_profile == pid %}selected{% endif %}>{{ prof.display_name }}</option>
          {% endfor %}
        </select>
      </div>

      <label>Choose Quote from Default Pool</label>
      <select name="preset_quote" onchange="document.getElementById('custom_quote').value = this.value">
        {% for q in quotes %}
          <option value="{{ q }}" {% if quote_input == q %}selected{% endif %}>{{ q }}</option>
        {% endfor %}
      </select>

      <label>Or Enter Custom Quote</label>
      <input type="text" id="custom_quote" name="custom_quote" value="{{ quote_input }}">

      <button type="submit">🚀 Generate Prompt</button>
    </form>
  </div>

  {% if prompt %}
  <!-- STAGE 2: PRINT CHOSEN VARIABLES -->
  <div class="stage">
    <h2>Stage 2: Variables Chosen</h2>
    <p>
      <span class="badge">Language: {{ selected_lang }}</span>
      <span class="badge">Location: {{ locations[selected_loc].name }}</span>
      <span class="badge">Ratio: {{ selected_ratio }}</span>
      <span class="badge">Date: {{ selected_date }}</span>
      <span class="badge">Time: {{ selected_time }} ({{ time_of_day }})</span>
    </p>
    <p><strong>Quote Selected:</strong></p>
    <blockquote>{{ quote_input }}</blockquote>
  </div>

  <!-- STAGE 3: INTERMEDIATE SELECTIONS -->
  <div class="stage">
    <h2>Stage 3: Context & Pipeline Decisions</h2>
    <p>
      <span class="badge">Domain: {{ prompt.visual_domain }}</span>
      <span class="badge">Layout: {{ prompt.layout_id }}</span>
      <span class="badge">Metaphor: {{ prompt.metaphor_used }}</span>
    </p>
    <p><strong>Weather:</strong> {{ ctx.weather.condition }}, {{ ctx.weather.temp }}°C | <strong>Festival:</strong> {{ ctx.festival or 'None' }}</p>
    {% if ctx.panchang_details %}
    <div style="margin: 10px 0; padding: 10px 14px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0; font-size: 0.9em; line-height: 1.5;">
      <p style="margin: 0 0 4px 0;"><strong>🗓 Regional Calendar:</strong> {{ ctx.panchang_details.astronomical_panchang.regional_calendar.regional_date_string }}</p>
      <p style="margin: 0 0 4px 0;"><strong>✨ Panchang:</strong> Tithi: {{ ctx.panchang_details.astronomical_panchang.tithi.udaya_tithi }} | Nakshatra: {{ ctx.panchang_details.astronomical_panchang.nakshatra.udaya_nakshatra }} | Yoga: {{ ctx.panchang_details.astronomical_panchang.yoga.yoga_name }} | Karana: {{ ctx.panchang_details.astronomical_panchang.karana.current_karana }}</p>
      <p style="margin: 0 0 4px 0;"><strong>☀️ Sun & Timings:</strong> Sunrise: {{ ctx.panchang_details.astronomical_panchang.sun_moon_timings.sunrise }} | Sunset: {{ ctx.panchang_details.astronomical_panchang.sun_moon_timings.sunset }} | Rahu Kaal: {{ ctx.panchang_details.astronomical_panchang.muhurats.rahu_kalam }} | Abhijit: {{ ctx.panchang_details.astronomical_panchang.muhurats.abhijit_muhurta }}</p>
      {% if ctx.panchang_details.festival_intelligence.active_festival %}
        <p style="margin: 0; color: #b45309;"><strong>🎉 Observance:</strong> {{ ctx.panchang_details.festival_intelligence.active_festival }} ({{ ctx.panchang_details.festival_intelligence.classification }})</p>
      {% endif %}
    </div>
    {% endif %}
    <p><strong>Reasoning:</strong> {{ prompt.gemini_selections.reasoning or 'N/A' }}</p>
  </div>

  <!-- STAGE 4: OUTPUT PROMPT (COPYPASTABLE) -->
  <div class="stage">
    <h2>Stage 4: Output Prompt (Copypastable)
      <button class="copy-btn" id="copy-btn" onclick="copyPrompt()">Copy Prompt</button>
    </h2>
    <pre id="output-prompt">{{ prompt.full_prompt }}</pre>
    <small style="color: #64748b;">Word count: {{ prompt.full_prompt.split()|length }} words</small>
  </div>
  {% endif %}
</div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    now = datetime.now()
    selected_loc = "mumbai"
    selected_ratio = "1:1"
    selected_lang = "English"
    selected_profile = ""
    selected_date = now.strftime("%Y-%m-%d")
    selected_time = now.strftime("%H:%M")
    quote_input = QUOTES[0]
    prompt = None
    ctx = None
    time_of_day = classify_time(now.hour)

    if request.method == "POST":
        selected_loc = request.form.get("location_key", "mumbai")
        selected_ratio = request.form.get("photo_ratio", "1:1")
        selected_lang = request.form.get("language", "English")
        selected_profile = request.form.get("regional_profile", "").strip()
        selected_date = request.form.get("date", selected_date)
        selected_time = request.form.get("time", selected_time)
        custom = request.form.get("custom_quote", "").strip()
        quote_input = custom if custom else request.form.get("preset_quote", QUOTES[0])

        location = LOCATIONS[selected_loc]
        try:
            dt = datetime.strptime(f"{selected_date} {selected_time}", "%Y-%m-%d %H:%M")
        except Exception:
            dt = datetime.now()
        time_of_day = classify_time(dt.hour)

        ctx, candidates, loc_details, prompt = run_pipeline(
            quote_input, location, dt, time_of_day, selected_ratio,
            language=selected_lang, regional_profile=selected_profile or None
        )

    return render_template_string(
        HTML_TEMPLATE,
        locations=LOCATIONS,
        quotes=QUOTES,
        regional_profiles=REGIONAL_PROFILES,
        selected_loc=selected_loc,
        selected_ratio=selected_ratio,
        selected_lang=selected_lang,
        selected_profile=selected_profile,
        selected_date=selected_date,
        selected_time=selected_time,
        quote_input=quote_input,
        time_of_day=time_of_day,
        prompt=prompt,
        ctx=ctx,
    )


@app.route("/api/panchang", methods=["GET"])
def api_panchang():
    """
    Direct JSON endpoint for querying dual-branch dynamic Panchang.
    Query parameters:
      - date: YYYY-MM-DD (defaults to today)
      - location: location key (e.g. mumbai, varanasi) or lat/lon
      - profile: regional profile id (e.g. maharashtra, gujarat, tamil_nadu)
      - language: language name (e.g. English, Hindi, Marathi)
      - tradition: Smartha or Vaishnava
    """
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    loc_key = request.args.get("location", "mumbai").lower()
    profile_id = request.args.get("profile")
    language = request.args.get("language", "English")
    tradition = request.args.get("tradition", "Smartha")

    loc = LOCATIONS.get(loc_key, LOCATIONS["mumbai"])
    try:
        lat = float(request.args.get("lat", loc["lat"]))
        lon = float(request.args.get("lon", loc["lon"]))
    except ValueError:
        lat, lon = loc["lat"], loc["lon"]

    try:
        target_d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        target_d = datetime.now().date()

    coord = get_coordinator()
    res = coord.calculate_panchang(
        target_date=target_d,
        lat=lat,
        lon=lon,
        location_name=loc.get("name"),
        regional_profile_id=profile_id,
        language=language,
        tradition=tradition,
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
