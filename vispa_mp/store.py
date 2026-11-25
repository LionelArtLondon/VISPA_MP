"""What an analysis leaves on disk, so closing VISPA MP loses nothing.

- Tagger scores, one line per still, appended as they come. A stopped or
  crashed run keeps everything it scored, and the next run skips those images.
- Whole analyses, one JSON file per set of inputs. Reading the same timeline
  again restores the review without running ffmpeg, Silero or the tagger.
"""

import json
import os
from pathlib import Path


class ScoreStore:
    def __init__(self, cache, model_id):
        self.path = Path(cache) / "scores" / f"{model_id}.jsonl"
        self.scores = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short when the app was closed mid-write
            if isinstance(item, dict) and isinstance(item.get("scores"), dict):
                self.scores[str(item.get("key"))] = item["scores"]

    @staticmethod
    def key_of(image):
        return Path(image).stem

    def get(self, image):
        return self.scores.get(self.key_of(image))

    def put(self, image, scores):
        key = self.key_of(image)
        self.scores[key] = scores
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"key": key, "scores": scores}) + "\n")


def analyses_dir(cache):
    return Path(cache) / "analyses"


def load_analysis(cache, key):
    try:
        text = (analyses_dir(cache) / f"{key}.json").read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save_analysis(cache, key, analysis):
    folder = analyses_dir(cache)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{key}.json"
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(analysis, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(partial, target)
