import json
import os
from functools import cache
from pathlib import Path
from time import monotonic
from urllib.parse import quote, unquote, urlsplit

import requests


MODEL_DIR = Path(__file__).resolve().parent / 'models' / 'go_emotions'
CONCEPTNET_API = 'https://api.conceptnet.io'
CONCEPTNET_RELATIONS = {'Synonym', 'SimilarTo', 'RelatedTo', 'HasProperty', 'SymbolOf', 'IsA', 'AtLocation'}


# Convert a graph label, spaCy phrase, or landmark tag to the same matching form.
def normalize_keyword(text):
    return ' '.join(text.casefold().replace('_', ' ').split())


# Load and reuse the English parser for noun chunks, entities, and token lemmas.
@cache
def _english_nlp():
    try:
        import spacy

        return spacy.load('en_core_web_sm')
    except (ImportError, OSError) as exc:
        raise RuntimeError('The spaCy English model is unavailable. Install the project requirements.') from exc


# Preserve named entities and useful noun phrases, then add content words and their lemmas.
# Retain surface forms such as "woods" when the lemma has a different graph entry.
def extract_keywords(english_quote):
    doc = _english_nlp()(english_quote)
    terms = [entity.text for entity in doc.ents]
    for chunk in doc.noun_chunks:
        if chunk.root.pos_ in {'NOUN', 'PROPN'}:
            words = [token.text for token in chunk if token.is_alpha and token.pos_ not in {'DET', 'PRON'}]
            if len(words) > 1:
                terms.append(' '.join(words))
    for token in doc:
        if token.is_alpha and not token.is_stop and token.pos_ in {'NOUN', 'PROPN', 'VERB', 'ADJ'}:
            terms.extend((token.text, token.lemma_ or token.text))
    return list(dict.fromkeys(normalize_keyword(term) for term in terms))


# Load the quantized classifier, its tokenizer, and the label order from the model config.
# Reuse them across requests and bound tokenizer input to the model's context length.
@cache
def _emotion_model():
    try:
        import onnxruntime
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(MODEL_DIR / 'tokenizer.json'))
        tokenizer.enable_truncation(max_length=512)
        labels = json.loads((MODEL_DIR / 'config.json').read_text(encoding='utf-8'))['id2label']
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 1
        session = onnxruntime.InferenceSession(
            str(MODEL_DIR / 'model_quantized.onnx'), sess_options=options, providers=['CPUExecutionProvider'],
        )
        return tokenizer, session, labels
    except Exception as exc:
        raise RuntimeError('The GoEmotions model could not load. Prepare the project model files.') from exc


# Encode the whole English quote, run the classifier, and apply sigmoid independently
# to each label so several emotions can be relevant to the same quote.
def detect_emotions(english_quote):
    tokenizer, session, labels = _emotion_model()
    try:
        import numpy as np

        encoded = tokenizer.encode(english_quote)
        features = {
            'input_ids': encoded.ids,
            'attention_mask': encoded.attention_mask,
            'token_type_ids': encoded.type_ids,
        }
        model_inputs = {item.name: np.array([features[item.name]], dtype=np.int64) for item in session.get_inputs()}
        logits = session.run(None, model_inputs)[0][0]
        scores = 1 / (1 + np.exp(-np.clip(logits, -80, 80)))
        return {labels[str(i)]: float(scores[i]) for i in np.argsort(-scores, kind='stable')}
    except Exception as exc:
        raise RuntimeError('Emotion analysis failed. Please retry.') from exc


# Follow ConceptNet pages for each extracted term and record the other English endpoint
# of each relevant edge. Keep the seed and direction so the CLI can explain the match.
# On a timeout or service error, return the edges collected so far with a partial status.
def expand_keywords(keywords):
    edges = {}
    if not keywords:
        return [], 'No terms to expand'

    service = os.getenv('VIBZEE_CONCEPTNET_API_URL', CONCEPTNET_API).rstrip('/')
    deadline = monotonic() + 12
    try:
        with requests.Session() as session:
            session.headers.update({'Accept': 'application/json', 'User-Agent': 'Vibzee/2.0'})
            for seed in keywords:
                term = seed.replace(' ', '_')
                node = f'/c/en/{term}'
                page = f"/c/en/{quote(term, safe='')}?limit=100"
                visited = set()
                while page and page not in visited:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError

                    visited.add(page)
                    address = urlsplit(page)
                    path = f'{service}/{address.path.lstrip("/")}'
                    response = session.get(f'{path}?{address.query}', timeout=min(3, remaining))
                    if response.status_code == 404:
                        break
                    response.raise_for_status()
                    result = response.json()

                    for edge in result['edges']:
                        relation = edge['rel']['label']
                        start = edge['start']
                        end = edge['end']
                        if relation not in CONCEPTNET_RELATIONS or start.get('language') != 'en' or end.get('language') != 'en':
                            continue
                        start_id = unquote(start.get('term') or start.get('@id', ''))
                        end_id = unquote(end.get('term') or end.get('@id', ''))
                        if start_id == node or start_id.startswith(f'{node}/'):
                            other = end
                        elif end_id == node or end_id.startswith(f'{node}/'):
                            other = start
                        else:
                            continue
                        keyword = normalize_keyword(other['label'])
                        if keyword and keyword != seed:
                            evidence = {
                                'keyword': keyword, 'seed': seed, 'relation': relation,
                                'start': start['label'], 'end': end['label'], 'source': edge.get('@id', ''),
                            }
                            edges[(seed, keyword, relation, evidence['start'], evidence['end'])] = evidence

                    page = (result.get('view') or {}).get('nextPage')
    except (requests.RequestException, TimeoutError, KeyError, TypeError, ValueError, AttributeError):
        status = 'ConceptNet partial results' if edges else 'ConceptNet unavailable; using extracted keywords'
        return list(edges.values()), status
    return list(edges.values()), 'ConceptNet lookup complete'
