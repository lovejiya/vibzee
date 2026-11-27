import json
from pathlib import Path

from context import normalize_keyword


LANDMARK_DATA = Path(__file__).resolve().parent / 'data' / 'landmark_db.json'
LOCATION_NAME = 'Mumbai'
LOCATION_KEY = 'mumbai'
# The landmark data scores four periods, so map the other lighting periods onto them.
SCORED_PERIODS = {'pre-dawn': 'night', 'dawn': 'morning', 'late-morning': 'morning', 'dusk': 'evening'}


# Score every Mumbai landmark from tag coverage, emotion fit, and time fit. Preserve
# the individual matches and contributions, then sort by score with file order for ties.
def rank_landmarks(time_of_day, keywords, expansions, emotions):
    try:
        landmarks = json.loads(LANDMARK_DATA.read_text(encoding='utf-8'))['landmarks']
    except (OSError, ValueError, KeyError) as exc:
        raise RuntimeError('Mumbai landmark data could not be loaded.') from exc

    if len(landmarks) < 3:
        raise RuntimeError('At least three Mumbai landmarks are needed to generate a scene.')

    direct = set(keywords)
    expanded = {term['keyword'] for term in expansions}
    ranked = []
    for landmark in landmarks:
        tags = {normalize_keyword(tag) for tag in landmark['keywords']}
        direct_matches = sorted(tags & direct)
        expanded_matches = sorted((tags & expanded) - direct)
        keyword_points = round(40 * (len(direct_matches) + 0.5 * len(expanded_matches)) / max(1, len(tags)), 2)

        affinities = landmark['emotions']
        fits = {label: confidence * affinities.get(label, 0) for label, confidence in emotions.items()}
        best_emotion = max(fits, key=fits.get) if fits else None
        emotion_fit = fits.get(best_emotion, 0)
        emotion_points = round(30 * emotion_fit, 2)

        time_fit = landmark['time_of_day'].get(SCORED_PERIODS.get(time_of_day, time_of_day), 0)
        time_points = round(30 * time_fit, 2)
        ranked.append({
            'id': landmark['id'], 'name': landmark['name'], 'visual_description': landmark['visual_description'],
            'score': round(keyword_points + emotion_points + time_points, 2),
            'keyword_points': keyword_points, 'emotion_points': emotion_points, 'time_points': time_points,
            'direct_matches': direct_matches, 'expanded_matches': expanded_matches, 'tag_count': len(tags),
            'emotion_match': best_emotion if emotion_fit > 0 else None, 'emotion_fit': emotion_fit,
            'time_of_day': time_of_day, 'time_fit': time_fit,
        })

    return sorted(ranked, key=lambda record: -record['score'])
