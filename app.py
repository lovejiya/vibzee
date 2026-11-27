import json
from datetime import date, datetime, timedelta, timezone

from flask import Flask, Response, render_template, request, stream_with_context

import context
import generator
from daily_god import get_daily_deities
from landmark import LOCATION_KEY, LOCATION_NAME, rank_landmarks


app = Flask(__name__)
INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30), 'IST')
STREAM_TYPE = 'application/x-ndjson'
STAGES = {
    'context': 'Context', 'shortlist': 'Shortlist', 'gemini': 'Gemini response',
    'layout': 'Layout', 'final': 'Final prompt',
}
LANGUAGES = (
    'English', 'Hindi', 'Sanskrit', 'Marathi', 'Gujarati', 'Bengali', 'Tamil',
    'Telugu', 'Kannada', 'Punjabi', 'Spanish', 'French', 'Japanese',
)
QUOTES = (
    'हर नया सवेरा अपने साथ नई उम्मीदें और नई खुशियाँ लेकर आता है।',
    'कमल की तरह खिलिए, चाहे परिस्थितियाँ कैसी भी हों।',
    'कुछ पल बारिश जैसे होते हैं, दिल को सुकून दे जाते हैं।',
    'ईश्वर का आशीर्वाद हो, तो हर राह आसान हो जाती है।',
    'मन शांत हो, तो हर दृश्य सुंदर और हर पल खास लगता है।',
    'फूलों की तरह मुस्कुराइए, आपकी खुशबू दूर तक जाएगी।',
    'गंगा की धारा की तरह जीवन में प्रेम और शांति बहती रहे।',
    'सादगी में जो सुकून है, वह दुनिया की दौलत में कहाँ।',
    'चाँद की तरह चमकिए, अँधेरों में भी अपनी पहचान बनाइए।',
    'हर बदलाव में एक नई शुरुआत छिपी होती है।',
)
LIGHTING_PERIODS = (
    (5, 'pre-dawn'), (7, 'dawn'), (9, 'morning'), (12, 'late-morning'),
    (16, 'afternoon'), (18, 'evening'), (20, 'dusk'), (24, 'night'),
)


# Read the same form fields from either interface, validate the location, language, date,
# and time, then return normalized inputs with the matching lighting period.
def parse_inputs(fields):
    quote = fields.get('custom_quote', '').strip() or fields.get('preset_quote', '').strip()
    if not quote:
        raise ValueError('Choose a preset or enter a quote.')
    if fields.get('location_key') != LOCATION_KEY:
        raise ValueError('Choose Mumbai as the location.')
    language = fields.get('language')
    if language not in LANGUAGES:
        raise ValueError('Choose a supported quote language.')
    try:
        selected = datetime.strptime(f'{fields.get("date")} {fields.get("time")}', '%Y-%m-%d %H:%M')
    except ValueError as exc:
        raise ValueError('Enter a valid date and time, then retry.') from exc

    return {
        'quote': quote, 'language': language, 'location_key': LOCATION_KEY, 'location': LOCATION_NAME,
        'date': selected.date().isoformat(), 'time': selected.strftime('%H:%M'),
        'time_of_day': next(label for cutoff, label in LIGHTING_PERIODS if selected.hour < cutoff),
    }


# Run translation, quote analysis, landmark ranking, weekday lookup, and prompt composition.
# Yield trace inputs and outputs for the CLI and five result stages for the browser.
# Attach a failure to its stage so both interfaces keep all earlier results on screen.
def pipeline_stages(inputs):
    stage = 'context'
    try:
        yield 'trace', ('Translation', 'Input', {'quote': inputs['quote'], 'language': inputs['language']})
        english = generator.translate_quote_to_english(inputs['quote'], inputs['language'])
        yield 'trace', ('Translation', 'Output', {
            'english_quote': english, 'used_gemini': inputs['language'] != 'English',
        })

        yield 'trace', ('spaCy keyword extraction', 'Input', english)
        direct_keywords = context.extract_keywords(english)
        yield 'trace', ('spaCy keyword extraction', 'Output', direct_keywords)

        yield 'trace', ('GoEmotions classification', 'Input', english)
        emotions = context.detect_emotions(english)
        yield 'trace', ('GoEmotions classification', 'Output', emotions)

        yield 'trace', ('ConceptNet expansion', 'Input', direct_keywords)
        expansions, graph_status = context.expand_keywords(direct_keywords)
        keywords = list(dict.fromkeys(direct_keywords + [edge['keyword'] for edge in expansions]))
        yield 'trace', ('ConceptNet expansion', 'Output', {
            'status': graph_status, 'edges': expansions, 'combined_keywords': keywords,
        })
        quote_context = {
            'english_quote': english, 'direct_keywords': direct_keywords, 'emotions': emotions,
            'expansions': expansions, 'keywords': keywords, 'graph_status': graph_status,
        }
        yield 'context', quote_context

        stage = 'shortlist'
        ranking_inputs = {
            'location_key': inputs['location_key'], 'time_of_day': inputs['time_of_day'],
            'keywords': direct_keywords, 'expansions': expansions, 'emotions': emotions,
        }
        yield 'trace', ('Mumbai landmark ranking', 'Input', ranking_inputs)
        ranked = rank_landmarks(**ranking_inputs)
        shortlist = {'landmarks': ranked[:3]}
        yield 'trace', ('Mumbai landmark ranking', 'Output', {
            'top_three_ids': [item['id'] for item in shortlist['landmarks']], 'ranked': ranked,
        })

        yield 'trace', ('Weekday deities', 'Input', inputs['date'])
        weekday, deities = get_daily_deities(date.fromisoformat(inputs['date']))
        shortlist.update(weekday=weekday, deities=deities)
        yield 'trace', ('Weekday deities', 'Output', {'weekday': weekday, 'deities': deities})
        yield 'shortlist', shortlist

        stage = 'gemini'
        menu, schema = generator.build_scene_request(inputs, quote_context, shortlist)
        yield 'trace', ('Gemini scene composition', 'Input', {
            'model': generator.GEMINI_MODEL, 'system_instruction': generator.SCENE_INSTRUCTIONS,
            'contents': menu, 'response_schema': schema,
        })
        response = generator.call_gemini(menu, generator.SCENE_INSTRUCTIONS, response_schema=schema)
        yield 'trace', ('Gemini scene composition', 'Output', response)
        scene = generator.parse_scene(response, shortlist)
        subject_names = {item['id']: item['name'] for item in deities}
        background_names = {item['id']: item['name'] for item in shortlist['landmarks']}
        subject_names['original_subject'] = scene['original_subject']
        background_names['original_background'] = scene['original_background']
        yield 'gemini', {
            **scene, 'chosen_subjects': [subject_names[item] for item in scene['selected_subject_ids']],
            'chosen_backgrounds': [background_names[item] for item in scene['selected_background_ids']],
        }

        stage = 'layout'
        layout_id = scene['selected_layout_id']
        layout = {'id': layout_id, **generator.LAYOUTS[layout_id], 'reasoning': scene['reasoning']}
        yield 'trace', ('Layout selection', 'Input', {'available_ids': list(generator.LAYOUTS), 'selected_id': layout_id})
        yield 'trace', ('Layout selection', 'Output', layout)
        yield 'layout', layout

        stage = 'final'
        yield 'trace', ('Final prompt', 'Input', {
            'scene': scene['full_prompt'], 'layout': layout_id, 'original_quote': inputs['quote'],
        })
        yield 'final', generator.build_final_prompt(scene, inputs)
    except RuntimeError as exc:
        yield 'error', {'stage': stage, 'message': str(exc), 'status': 503}
    except Exception:
        app.logger.exception('Prompt pipeline failed at %s', stage)
        yield 'error', {'stage': stage, 'message': 'Something went wrong while generating the prompt. Please retry.', 'status': 500}


# Show the prompt form or run the pipeline for a submission. Use the same template for the
# full-page response and for individual stage updates sent as newline-delimited JSON.
@app.route('/', methods=['GET', 'POST'])
def index():
    now = datetime.now(INDIA_TIMEZONE)
    form = {
        'location_key': LOCATION_KEY, 'preset_quote': QUOTES[0], 'custom_quote': QUOTES[0],
        'language': 'Hindi', 'date': now.date().isoformat(), 'time': now.strftime('%H:%M'),
    }
    page = {'form': form, 'quotes': QUOTES, 'languages': LANGUAGES, 'stages': STAGES, 'results': {}}
    if request.method == 'GET':
        return render_template('index.html', **page)

    form.update({name: request.form.get(name, value) for name, value in form.items()})
    form['custom_quote'] = request.form.get('custom_quote', '')
    streaming = request.headers.get('Accept') == STREAM_TYPE
    try:
        inputs = parse_inputs(form)
    except ValueError as exc:
        error = {'stage': 'error', 'message': str(exc)}
        if streaming:
            return Response(json.dumps(error, ensure_ascii=False) + '\n', status=400, mimetype=STREAM_TYPE)
        return render_template('index.html', error=error, **page), 400

    page['inputs'] = inputs
    results = page['results']
    updates = ((stage, value) for stage, value in pipeline_stages(inputs) if stage != 'trace')
    if streaming:
        # Render only completed panels and emit the first error as a final stream event.
        def stream():
            yield '{"stage":"start"}\n'
            for stage, value in updates:
                if stage == 'error':
                    yield json.dumps({'stage': 'error', 'message': value['message']}, ensure_ascii=False) + '\n'
                    return
                results[stage] = value
                event = {'stage': stage, 'html': render_template('index.html', fragment=stage, **page)}
                if stage == 'gemini':
                    event['selected'] = [value['selected_subject_ids'], value['selected_background_ids']]
                yield json.dumps(event, ensure_ascii=False) + '\n'

        return Response(stream_with_context(stream()), mimetype=STREAM_TYPE, headers={'Cache-Control': 'no-store'})

    results.update(updates)
    error = results.pop('error', None)
    return render_template('index.html', error=error, **page), error['status'] if error else 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
