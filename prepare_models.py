from pathlib import Path
from shutil import copyfileobj
from tempfile import NamedTemporaryFile
from urllib.request import urlopen


MODEL_DIR = Path(__file__).resolve().parent / 'models' / 'go_emotions'
MODEL_URL = 'https://huggingface.co/SamLowe/roberta-base-go_emotions-onnx/resolve/90ee0c1'
ASSETS = ('config.json', 'tokenizer.json', 'onnx/model_quantized.onnx')


# Fetch the pinned tokenizer, labels, and quantized weights into the runtime model folder.
# Download into a temporary file and replace the target only after the full transfer succeeds.
def prepare_models():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for asset in ASSETS:
        target = MODEL_DIR / Path(asset).name
        if target.is_file():
            continue

        print(f'Fetching {target.name}', flush=True)
        with urlopen(f'{MODEL_URL}/{asset}', timeout=60) as response:
            with NamedTemporaryFile(dir=MODEL_DIR, delete=False) as temporary:
                staged = Path(temporary.name)
                try:
                    copyfileobj(response, temporary)
                    temporary.close()
                    staged.chmod(0o644)
                    staged.replace(target)
                finally:
                    staged.unlink(missing_ok=True)


if __name__ == '__main__':
    prepare_models()
