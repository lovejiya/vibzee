"""
app.py — Vibzee Image Prompt Generator UI.
Built with Flask (zero external GUI setup needed). Run directly with: python3 app.py
"""
from datetime import datetime
import html
import json
import random
import webbrowser
from flask import Flask, request, render_template_string

from specs import LOCATIONS, QUOTES, MasterPrompt
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
      <span class="badge">Location: {{ locations[selected_loc].name }}</span>
      <span class="badge">Ratio: {{ selected_ratio }}</span>
      <span class="badge">Time of Day: {{ time_of_day }}</span>
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
    selected_loc = "mumbai"
    selected_ratio = "1:1"
    quote_input = QUOTES[0]
    prompt = None
    ctx = None
    time_of_day = classify_time(datetime.now().hour)

    if request.method == "POST":
        selected_loc = request.form.get("location_key", "mumbai")
        selected_ratio = request.form.get("photo_ratio", "1:1")
        custom = request.form.get("custom_quote", "").strip()
        quote_input = custom if custom else request.form.get("preset_quote", QUOTES[0])

        location = LOCATIONS[selected_loc]
        date = datetime.now()
        time_of_day = classify_time(date.hour)

        ctx = sources.enrich_context(
            quote=quote_input, location=location, date=date, time_of_day=time_of_day
        )
        candidates = sources.run_knowledge_chain(context=ctx, location=location)
        loc_details = sources.discover_location_details(location)

        prompt = generator.generate(
            candidates=candidates,
            context=ctx,
            location_details=loc_details,
            photo_ratio=selected_ratio,
            location=location,
        )

    return render_template_string(
        HTML_TEMPLATE,
        locations=LOCATIONS,
        quotes=QUOTES,
        selected_loc=selected_loc,
        selected_ratio=selected_ratio,
        quote_input=quote_input,
        time_of_day=time_of_day,
        prompt=prompt,
        ctx=ctx,
    )


if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("🚀 Vibzee UI running!")
    print("👉 On this machine:        http://127.0.0.1:5001")
    print("👉 On same Wi-Fi network:  http://<YOUR-IP>:5001")
    print("   (Find your IP with: ipconfig getifaddr en0)")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=5001, debug=False)
