import json
from pathlib import Path


DEITY_DATA = Path(__file__).resolve().parent / 'data' / 'daily_deities.json'
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


# Use the selected date's weekday to retrieve the eligible Hindu deity records in file order.
def get_daily_deities(selected_date):
    weekday = WEEKDAYS[selected_date.weekday()]
    try:
        options = json.loads(DEITY_DATA.read_text(encoding='utf-8'))[weekday]
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError('Weekday deity data could not be loaded.') from exc
    if not options:
        raise RuntimeError(f'There are no deity options for {weekday.title()}.')
    return weekday, options
