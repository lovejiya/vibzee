import json
from datetime import datetime

from app import INDIA_TIMEZONE, LANGUAGES, QUOTES, parse_inputs, pipeline_stages
from landmark import LOCATION_KEY, LOCATION_NAME


# Print the stage data as readable JSON, keeping plain text prompts and Unicode quotes legible.
def show_step(operation, direction, value):
    print(f'\n{operation} · {direction}', flush=True)
    print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2), flush=True)


# Ask for the same quote, language, date, and time as the browser. Run the shared pipeline
# and show each operation's actual input and output, with a retry after a failed stage.
def main():
    print(f'Vibzee Image Prompt Generator\nLocation: {LOCATION_NAME}')
    print('\nPreset quotes')
    for index, quote in enumerate(QUOTES, 1):
        print(f'{index}. {quote}')

    choice = input('\nPreset number or custom quote [1]: ').strip() or '1'
    is_preset = choice.isascii() and choice.isdecimal() and 1 <= int(choice) <= len(QUOTES)
    quote = QUOTES[int(choice) - 1] if is_preset else choice
    default_language = 'Hindi' if is_preset else 'English'
    print(f'Languages: {", ".join(LANGUAGES)}')
    language = input(f'Quote language [{default_language}]: ').strip().title() or default_language
    now = datetime.now(INDIA_TIMEZONE)
    default_date = now.date().isoformat()
    default_time = now.strftime('%H:%M')
    fields = {
        'custom_quote': quote, 'language': language, 'location_key': LOCATION_KEY,
        'date': input(f'Date in IST [{default_date}]: ').strip() or default_date,
        'time': input(f'Time in IST [{default_time}]: ').strip() or default_time,
    }
    while True:
        show_step('Parse run inputs', 'Input', fields)
        try:
            inputs = parse_inputs(fields)
            break
        except ValueError as exc:
            print(exc)
            for key, label in (('language', 'Quote language'), ('date', 'Date in IST'), ('time', 'Time in IST')):
                fields[key] = input(f'{label} [{fields[key]}]: ').strip() or fields[key]
            fields['language'] = fields['language'].title()
    show_step('Parse run inputs', 'Output', inputs)

    while True:
        for stage, value in pipeline_stages(inputs):
            if stage == 'trace':
                show_step(*value)
            elif stage == 'gemini':
                show_step('Validated scene choices', 'Output', {
                    'subjects': value['chosen_subjects'], 'backgrounds': value['chosen_backgrounds'],
                    'reasoning': value['reasoning'],
                })
            elif stage == 'final':
                show_step('Final prompt', 'Output', value)
                return 0
            elif stage == 'error':
                print(f'\n{value["stage"].title()} failed. {value["message"]}')
        if input('Press Enter to retry, or type anything to quit: ').strip():
            return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (EOFError, KeyboardInterrupt):
        print('\nRun cancelled.')
        raise SystemExit(1)
