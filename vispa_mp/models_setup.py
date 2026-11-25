"""Where the ONNX files live, and how they are fetched.

Silero VAD v6.3 is MIT. WD EVA02-Large Tagger v3 is Apache-2.0.
PixAI is not downloaded here: it is only the measured fallback if WD mis-ranks mouths.
"""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
WD_DIR = MODELS / "wd-eva02-large-tagger-v3"
SILERO = MODELS / "silero_vad.onnx"
WD_ONNX = WD_DIR / "model.onnx"
WD_LABELS = WD_DIR / "selected_tags.csv"
WD_SHA256 = "9e768793060c7939b277ccb382783e8670e8a042d29d77aa736be0c8cc898bfc"

FILES = (
    ("https://github.com/snakers4/silero-vad/raw/refs/tags/v6.3/src/silero_vad/data/silero_vad.onnx", SILERO, None),
    ("https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx?download=true", WD_ONNX, WD_SHA256),
    ("https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv?download=true", WD_LABELS, None),
)


def ready():
    return SILERO.is_file() and SILERO.stat().st_size > 1_000_000 and WD_ONNX.is_file() and WD_LABELS.is_file()


def missing():
    return [str(path.name) for _, path, _ in FILES if not path.is_file() or path.stat().st_size < 1000]


def ensure(progress=None):
    """Download whatever is absent. An existing file is left in place."""
    for url, path, digest in FILES:
        if path.is_file() and path.stat().st_size > 1000 and (digest is None or _sha256(path) == digest):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(f"Downloading {path.name}")
        _download(url, path, progress)
        if digest and _sha256(path) != digest:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Unexpected hash for {path.name}. The file was removed.")
    stamp = MODELS / "sources.json"
    stamp.write_text(json.dumps({
        "silero": "v6.3 MIT https://github.com/snakers4/silero-vad",
        "tagger": "SmilingWolf/wd-eva02-large-tagger-v3 Apache-2.0",
    }, indent=2), encoding="utf-8")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url, path, progress):
    temporary = path.with_suffix(path.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "vispa-mp"})
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            output.write(chunk)
            read += len(chunk)
            if progress and total:
                progress(f"{path.name} {min(100, round(100 * read / total))} %")
    temporary.replace(path)
