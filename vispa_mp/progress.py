"""The five steps of an analysis, reported to the window as they advance."""

import time

STEPS = (
    "Reading the video",
    "Finding the shots",
    "Listening for speech",
    "Extracting the images",
    "Recognizing the images",
)


class Steps:
    """Calls ``report`` with {step, steps, label, fraction, detail, left}.

    ``fraction`` is how far the current step is, 0 to 1. Updates inside a step
    are sent at most ten times a second, so a fast loop does not flood the window.
    """

    def __init__(self, report=None):
        self.report = report or (lambda _value: None)
        self.index = 0
        self._sent = 0.0

    def start(self, index, detail=""):
        self.index = index
        self.send(0.0, detail, force=True)

    def send(self, fraction, detail="", left="", force=False):
        if not self.index:
            return
        now = time.monotonic()
        fraction = max(0.0, min(1.0, float(fraction)))
        if not force and fraction < 1.0 and now - self._sent < 0.1:
            return
        self._sent = now
        self.report({
            "step": self.index, "steps": len(STEPS), "label": STEPS[self.index - 1],
            "fraction": fraction, "detail": detail, "left": left,
        })

    def part(self, detail=""):
        """A callback for one loop of the current step: fraction in, report out."""
        return lambda fraction: self.send(fraction, detail)
