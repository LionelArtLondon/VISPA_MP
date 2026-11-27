"""Compare automatic selections from one measured chapter, without side effects."""

from copy import deepcopy

from vispa_mp.analyze import refresh_utterances
from vispa_mp.learning_model import validate_profile
from vispa_mp.rules import propose


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise InterruptedError("Profile comparison cancelled.")


def build_comparison(analysis, settings, profile, *, progress=None, cancel=None):
    """Return standard and personal proposals from identical measured inputs.

    MP review edits are deliberately excluded from both automatic selections.
    Existing Resolve markers remain protected. No sources, models, cache files,
    preferences or Resolve connections are opened by this operation.
    """
    _cancelled(cancel)
    if (not isinstance(analysis, dict) or not isinstance(analysis.get("shots"), list)
            or not any(isinstance(shot, dict) and shot.get("frames") for shot in analysis["shots"])):
        raise ValueError("Analyze a chapter with examined images before comparing selection profiles.")
    if not isinstance(settings, dict):
        raise ValueError("The selection settings cannot be read for this comparison.")
    personal = validate_profile(profile)
    measured, options = deepcopy(analysis), deepcopy(settings)
    measured.pop("_budget_user_proposals", None)
    measured.pop("_budget_excluded_frames", None)
    if measured.get("speech_tracks"):
        measured["utterances"] = refresh_utterances(measured, options)
    variants = []
    for name, selected in (("MP standard rules", None), (personal["name"], personal)):
        _cancelled(cancel)
        if progress is not None:
            progress("Comparing selection: " + name)
        _cancelled(cancel)
        result = propose(measured, options, profile=selected)
        _cancelled(cancel)
        variants.append({"name": name, "profile": selected,
                         "proposals": result["proposals"], "warnings": result["warnings"]})
    return {"analysis": measured, "settings": options, "variants": variants}
