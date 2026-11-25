"""Anime tag scores: mouth, blur, how many people, expression.

WD EVA02-Large Tagger v3 (Apache-2.0) was trained on illustrated frames.
Scores are compared inside one line, not against one threshold for a whole episode.
"""

GROUP_TAGS = ("2girls", "2boys", "3girls", "3boys", "4girls", "4boys", "5girls", "5boys",
              "6+girls", "6+boys", "multiple_girls", "multiple_boys")
SOLO_TAGS = ("solo", "1girl", "1boy")
FACE_TAGS = SOLO_TAGS + GROUP_TAGS
EXPRESSION_TAGS = ("smile", "grin", "serious", "angry", "annoyed", "surprised",
                   "flying_sweatdrops", "sweat", ":d", "screaming", "frown", "blush")
# A speaking drawing we want shows the dark inside of the mouth. Teeth on top of
# that inside are better. A tooth line with no cavity is a different pose.
INTERIOR_TAGS = ("open_mouth", "tongue", "uvula")
TEETH_ONLY_TAGS = ("upper_teeth_only", "lower_teeth_only", "clenched_teeth")
# Raise this when features_from_probs changes: saved scores are then read again.
SCORE_VERSION = 1


def model_id(model_path):
    """Names the saved scores of one model file and one version of the features."""
    import hashlib
    from pathlib import Path
    path = Path(model_path)
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}-{stat.st_mtime_ns}"
    except OSError:
        stamp = "missing"
    raw = f"{path.name}|{stamp}|{SCORE_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def providers():
    import onnxruntime as ort
    available = ort.get_available_providers()
    chosen = [name for name in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider") if name in available]
    return chosen or available


def features_from_probs(probs):
    """The few scores the rules actually read."""
    def score(*names):
        return max((float(probs.get(name, 0.0)) for name in names), default=0.0)

    group = score(*GROUP_TAGS)
    solo = score(*SOLO_TAGS)
    return {
        "open_mouth": score("open_mouth"),
        "closed_mouth": score("closed_mouth"),
        "teeth": score("teeth"),
        "tongue": score("tongue"),
        "uvula": score("uvula"),
        "upper_teeth_only": score("upper_teeth_only"),
        "lower_teeth_only": score("lower_teeth_only"),
        "clenched_teeth": score("clenched_teeth"),
        "motion_blur": score("motion_blur"),
        "from_behind": score("from_behind"),
        "group": group,
        "solo": solo,
        "face": max(score(*FACE_TAGS), group, solo),
        "expression": score(*EXPRESSION_TAGS),
    }


def _sigmoid(values):
    import numpy as np
    return 1.0 / (1.0 + np.exp(-values))


class Tagger:
    def __init__(self, model_path, labels_path):
        import onnxruntime as ort
        self.session = ort.InferenceSession(str(model_path), providers=providers())
        self.input = self.session.get_inputs()[0]
        self.labels = _labels(labels_path)
        shape = self.input.shape
        numbers = [int(part) for part in shape if isinstance(part, int) and part > 3]
        self.size = numbers[0] if numbers else 448
        self.channels_first = len(shape) == 4 and shape[1] == 3

    def score_path(self, path):
        from PIL import Image
        with Image.open(path) as image:
            prepared = _prepare(image.convert("RGB"), self.size, self.channels_first)
        return self.score_batch(prepared)[0]

    def score_batch(self, batch):
        import numpy as np
        outputs = self.session.run(None, {self.input.name: batch})[0]
        scores = []
        for row in np.asarray(outputs):
            values = np.asarray(row, dtype=np.float32).reshape(-1)
            if values.size and (float(values.min()) < 0 or float(values.max()) > 1):
                values = _sigmoid(values)
            probs = {name: float(values[index]) for index, name in enumerate(self.labels) if index < values.size}
            scores.append(features_from_probs(probs))
        return scores


def _labels(path):
    names = []
    for line in Path_read(path).splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2 and parts[1]:
            names.append(parts[1])
    if not names:
        raise RuntimeError(f"Empty labels: {path}")
    return names


def Path_read(path):
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8")


def _prepare(image, size, channels_first):
    import numpy as np
    from PIL import Image
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    if side != size:
        canvas = canvas.resize((size, size), Image.Resampling.BICUBIC)
    array = np.asarray(canvas, dtype=np.float32)[:, :, ::-1]
    if channels_first:
        array = np.transpose(array, (2, 0, 1))
    return array[None, ...]
