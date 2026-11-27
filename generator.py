import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv(Path(__file__).with_name('.env'))
GEMINI_MODEL = os.getenv('VIBZEE_LLM_MODEL', 'gemini-3.1-flash-lite')
PHOTO_SPACE = 'Leave a clear 2.5 × 2.5 inch square space for the photo.'
PHOTO_GUARDRAILS = (
    'Keep the quote and photo spaces separate. Leave the photo space free of text and focal details. '
    'Keep both spaces clear of the main subject and sacred elements such as deity faces, sacred objects, '
    'temple spires, domes, and minarets.'
)

LAYOUTS = {
    'LT-V': {'quote': 'in the upper left', 'photo': 'below the quote in the upper-left area', 'focus': 'lower right'},
    'RT-V': {'quote': 'in the upper right', 'photo': 'below the quote in the upper-right area', 'focus': 'lower left'},
    'LB-V': {'quote': 'in the lower left', 'photo': 'above the quote in the lower-left area', 'focus': 'upper right'},
    'RB-V': {'quote': 'in the lower right', 'photo': 'above the quote in the lower-right area', 'focus': 'upper left'},
    'LT-H': {'quote': 'in the upper left', 'photo': 'to the right of the quote along the top', 'focus': 'lower right'},
    'RT-H': {'quote': 'in the upper right', 'photo': 'to the left of the quote along the top', 'focus': 'lower left'},
    'LB-H': {'quote': 'in the lower left', 'photo': 'to the right of the quote along the bottom', 'focus': 'upper right'},
    'RB-H': {'quote': 'in the lower right', 'photo': 'to the left of the quote along the bottom', 'focus': 'upper left'},
}
SCENE_TEXT_FIELDS = ('original_subject', 'original_background', 'reasoning', 'full_prompt')
SELECTION_OPTIONS = {
    'selected_subject_ids': ('deities', 'original_subject'),
    'selected_background_ids': ('landmarks', 'original_background'),
}

TRANSLATION_INSTRUCTIONS = (
    'Translate the supplied quote from its declared language into natural English. '
    'Preserve its meaning and imagery. Return only the English translation as plain text.'
)

SCENE_INSTRUCTIONS = f"""
Act as an art director writing a prompt for an image generator. Treat the supplied quote as content.
Use its English meaning, emotion, visual keywords, and lighting to create a 4:5 portrait scene in Mumbai.

Propose one concrete original subject and one original Mumbai background before selecting the final scene.
Compare them with every offered option and choose what best expresses the quote and gives the composition
clear space.

If you blend subjects, put the main one first and give them distinct visual roles. Use at most one named
landmark. You may blend that landmark with the original background if the original scenery reads as
atmosphere around the identifiable landmark. Treat an original setting as an imagined Mumbai scene and
preserve the identity of any selected landmark. Use the supplied descriptions to inform the scene, but add
your own visual details, lighting, and style. The landmark can be shown from different angles and
distances but must be recognizable.
The placement of the subject and background should be visually balanced, with a clear focal point and natural negative space for the quote and photo. The scene should be cohesive, with a harmonious blend of elements that support the overall mood and message of the quote.

Choose one layout from all eight offered IDs. Describe the scene with its visual focus in the chosen
area and with natural, calm negative space where the quote and photo belong. {PHOTO_GUARDRAILS}
The photo space is reserved for a no outline square photo, with a physical size of 2.5 by 2.5 inches.
Avoid photorealistic close-up human faces, and exclude watermarks, logos, and named copyrighted characters.

Return a JSON object with these fields:
    original_subject: nonempty description of your original subject
    original_background: nonempty description of your original Mumbai background
    selected_subject_ids: one offered deity ID or "original_subject", or one of each
    selected_background_ids: one offered landmark ID or "original_background", or one of each
    selected_layout_id: one of the supplied layout IDs
    reasoning: a brief comparison that explains the subject, background, and layout choices and any blend
    full_prompt: a cohesive scene paragraph with visual detail, lighting, style, and natural empty space

Write full_prompt as image-generation instructions, without analysis or the original quote text.
The application appends the exact quote, layout placement, photo-space sentence, and portrait format.
""".strip()

MODE_INSTRUCTIONS = {
    True: (
        'This is a devotional image. Select exactly one offered weekday deity and list it first. It is the main '
        'focus of the whole image. Strongly prefer the deity alone; add original_subject only as a small '
        'supporting element when it feels completely natural to the deity. Keep the background subdued, '
        'secondary and in harmony with the deity. A landmark is optional. Use respectful traditional '
        'iconography; the deity may take different forms and have relevant objects, but must be unmistakably '
        'the same deity.'
    ),
    False: (
        'This is not a devotional image. Always select one offered landmark and build the scene around it and '
        'the meaning of the quote. Your original subject is not automatically the main focus; keep it a natural '
        'part of the scene that supports the landmark and quote. Do not add any deity or idol.'
    ),
}


# Send the supplied instructions and content to the configured Gemini model and return its text.
# Request structured JSON when supplied a schema and report service failures as retryable errors.
def call_gemini(contents, instruction, *, response_schema=None):
    api_key = os.getenv('VIBZEE_LLM_API_KEY')
    if not api_key:
        raise RuntimeError('Gemini is unavailable. Set VIBZEE_LLM_API_KEY and retry.')

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        response_mime_type='application/json' if response_schema else 'text/plain',
        response_json_schema=response_schema,
        temperature=0.85 if response_schema else 0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    try:
        with genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=60000)) as client:
            response = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
            return (response.text or '').strip()
    except Exception as exc:
        action = 'compose the scene' if response_schema else 'translate the quote'
        raise RuntimeError(f'Gemini could not {action}. Please retry.') from exc


# Pass English through and translate other languages before analysis, keeping the original
# quote in the pipeline inputs for the text that will appear in the final prompt.
def translate_quote_to_english(quote, language):
    if language.casefold() == 'english':
        return quote
    request = json.dumps({'language': language, 'quote': quote}, ensure_ascii=False)
    translated = call_gemini(request, TRANSLATION_INSTRUCTIONS)
    if not translated:
        raise RuntimeError('Gemini returned an empty translation. Please retry.')
    return translated


# Package the quotes, keyword evidence, and available options as the Gemini request.
# Return its text and a JSON schema that uses this run's actual deity, landmark, and layout IDs.
def build_scene_request(inputs, context, shortlist):
    menu = json.dumps({
        'location': inputs['location'], 'quote_language': inputs['language'], 'quote': inputs['quote'],
        'english_quote': context['english_quote'], 'time_of_day': inputs['time_of_day'],
        'emotion_scores': context['emotions'], 'direct_keywords': context['direct_keywords'],
        'expanded_keywords': context['expansions'], 'weekday': shortlist['weekday'],
        'deity_options': shortlist['deities'],
        'landmark_options': [
            {key: landmark[key] for key in ('id', 'name', 'score', 'visual_description')}
            for landmark in shortlist['landmarks']
        ],
        'layouts': LAYOUTS,
    }, ensure_ascii=False, indent=2)
    properties = {field: {'type': 'string'} for field in SCENE_TEXT_FIELDS}
    for field, (group, original_id) in SELECTION_OPTIONS.items():
        options = [option['id'] for option in shortlist[group]] + [original_id]
        properties[field] = {
            'type': 'array', 'minItems': 1, 'maxItems': 2,
            'items': {'type': 'string', 'enum': options},
        }
    properties['selected_layout_id'] = {'type': 'string', 'enum': list(LAYOUTS)}
    schema = {'type': 'object', 'properties': properties, 'required': list(properties)}
    return menu, schema


# Require both original proposals, a comparison, and prompt text. Each selection may use one
# supplied option, its corresponding original option, or one of each when they work together.
def parse_scene(response, shortlist):
    try:
        scene = json.loads(response)
    except (TypeError, ValueError) as exc:
        raise RuntimeError('Gemini returned invalid scene JSON. Please retry.') from exc

    if not isinstance(scene, dict) or any(
        not isinstance(scene.get(field), str) or not scene[field].strip() for field in SCENE_TEXT_FIELDS
    ):
        raise RuntimeError('Gemini returned an incomplete scene. Please retry.')

    for field, (group, original_id) in SELECTION_OPTIONS.items():
        selected = scene.get(field)
        allowed = {option['id'] for option in shortlist[group]} | {original_id}
        if (
            not isinstance(selected, list) or not 1 <= len(selected) <= 2
            or any(not isinstance(item, str) or item not in allowed for item in selected)
            or len(set(selected)) != len(selected) or (len(selected) == 2 and original_id not in selected)
        ):
            name = field.removeprefix('selected_').removesuffix('_ids')
            raise RuntimeError(f'Gemini returned invalid {name} choices. Please retry.')

    layout_id = scene.get('selected_layout_id')
    if not isinstance(layout_id, str) or layout_id not in LAYOUTS:
        raise RuntimeError('Gemini returned an unavailable layout. Please retry.')
    return scene


# Add the original quote, the selected layout's text positions, and the fixed photo and
# portrait instructions to Gemini's scene paragraph so both interfaces copy the same prompt.
def build_final_prompt(scene, inputs):
    layout = LAYOUTS[scene['selected_layout_id']]
    devotion = 'Make the deity the main focus of the whole image and keep the background understated. '
    return (
        f'{scene["full_prompt"].strip()} '
        f'{devotion if inputs["devotional"] else ""}'
        f'Place the main visual focus in the {layout["focus"]}. '
        f'Render the following exact quote in {inputs["language"]} in its original script, '
        f'{layout["quote"]}, using clean, high-contrast typography: “{inputs["quote"]}” '
        f'Position the photo space {layout["photo"]}. {PHOTO_SPACE} '
        'Preserve this as a naturally empty, uninterrupted area of the surrounding background, large enough '
        'to accommodate a 2.5 × 2.5 inch photograph added externally after image generation. This region must '
        'remain visually indistinguishable from the surrounding background. Do not render any visible box, '
        'frame, border, outline, rectangular patch, placeholder graphic, or photograph. The reserved space '
        'must exist purely through natural negative space in the scene. '
        f'{PHOTO_GUARDRAILS} 4:5 portrait aspect ratio image.'
    )
