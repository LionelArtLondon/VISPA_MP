"""Read validated chapter examples without changing Resolve or a live review.

Reference files keep measured features and labels, not video or executable model
objects. Their group is based on source media, so edits of the same footage can
be kept together when a personal profile is evaluated.
"""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import tempfile
import uuid

from vispa_mp.analyze import Live, _normal_speed
from vispa_mp.candidates import candidate_frames
from vispa_mp.learning_model import FEATURE_NAMES, feature_vector
from vispa_mp.markers import CORE, EXTRA, PAGE, is_automatic
from vispa_mp.progress import Steps
from vispa_mp.shots import build_shots
from vispa_mp.speech import dialogue_turns, map_turns
from vispa_mp.timeline_identity import normalize_identity

ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = ROOT / "cache" / "learning" / "references"
PROFILES_DIR = ROOT / "cache" / "learning" / "profiles"
REFERENCE_KIND = "vispa-mp-reference"
REFERENCE_VERSION = 1
MAX_REFERENCE_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_PATH = 32767
_ROLES = {PAGE: ["core", "page"], CORE: ["core"], EXTRA: ["extra"]}


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 31) <= value < 2 ** 31


def _finite(value):
    try:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))
    except OverflowError:
        return False


def _cancelled(cancel):
    if cancel is not None and cancel():
        raise InterruptedError("Reference import was cancelled. No reference was saved.")


def _notify(progress, text):
    if progress is not None:
        progress(text)


def _dialogue_reference_summary(statuses):
    return {"tracks": len(statuses), "ready_tracks": sum(status.get("state") == "ready" for status in statuses),
            "changes": sum(int(status.get("changes") or 0) for status in statuses),
            "warnings": list(dict.fromkeys(status["detail"] for status in statuses
                                           if status.get("state") != "ready" and status.get("detail")))}


def _valid_preview_path(value):
    """A local bitmap path only; availability is deliberately checked by the UI.

    References remain trainable after the cache is removed. Validation must not
    open images, contact a network share, or extract replacement video frames.
    """
    return (isinstance(value, str) and 0 < len(value) <= MAX_PREVIEW_PATH
            and value == value.strip() and not any(ord(char) < 32 for char in value)
            and "://" not in value and not value.replace("\\", "/").startswith("//")
            and (PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute())
            and PureWindowsPath(value).suffix.lower() in (".jpg", ".jpeg", ".png"))


def _source_media(snapshot):
    media = {}
    for clip in snapshot.get("video_clips") or []:
        path = str(clip.get("path") or "")
        if not path:
            continue
        canonical = str(Path(path).resolve()).casefold()
        try:
            size = Path(path).stat().st_size
        except OSError:
            size = None
        media[canonical] = {"path": str(Path(path).resolve()), "size": size}
    return [media[key] for key in sorted(media)]


def _group_id(snapshot, override=None):
    if override is not None:
        if not isinstance(override, str) or not override.strip():
            raise ValueError("The chapter group must have a name.")
        return override.strip()
    # Do not put availability or mtime in this identity: a portable review must
    # remain grouped with its original video when that drive is disconnected.
    paths = [item["path"].casefold() for item in _source_media(snapshot)]
    if not paths:
        raise ValueError("The reference has no source-media identity. Choose a chapter group explicitly.")
    return "media-" + hashlib.sha256(json.dumps(paths).encode("utf-8")).hexdigest()[:24]


def _reference_id(snapshot):
    identity = normalize_identity(snapshot.get("timeline_identity"))
    key = identity or {
        "project": snapshot.get("project_name") or "",
        "timeline": snapshot.get("timeline_name") or "",
        "media": [item["path"].casefold() for item in _source_media(snapshot)],
        "fps": snapshot.get("fps"), "start": snapshot.get("start_frame"), "end": snapshot.get("end_frame"),
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _labels(markers, include_automatic=False):
    selected, ignored_automatic, ignored_other = {}, 0, 0
    for marker in markers:
        if marker.get("color") not in _ROLES:
            ignored_other += 1
            continue
        automatic = marker.get("automatic") or is_automatic(marker.get("custom_data") or marker.get("customData"))
        if automatic and not include_automatic:
            ignored_automatic += 1
            continue
        frame = marker.get("frame")
        if not _integer(frame):
            raise ValueError("A reference marker has an invalid timeline frame.")
        roles = _ROLES[marker["color"]]
        if frame in selected and selected[frame] != roles:
            raise ValueError("Two reference markers disagree about the role of one image.")
        selected[frame] = list(roles)
    if not selected:
        raise ValueError("No validated Page start, Core or Extra markers were found. Open a completed "
                         "timeline with hand-placed markers, or import a reviewed VISPA MP project.")
    return selected, ignored_automatic, ignored_other


def reference_range(snapshot, use_in_out=False):
    """Resolve's normalized, half-open timeline range for an explicit import."""
    if not isinstance(use_in_out, bool):
        raise ValueError("The reference In/Out option must be true or false.")
    if not use_in_out:
        return None
    start, end = snapshot.get("mark_in"), snapshot.get("mark_out")
    if not _integer(start) or not _integer(end) or end <= start:
        raise ValueError("Set both an In and an Out around the useful chapter in Resolve, then retry. "
                         "The Out must be after the In. Disable the In/Out option to import the whole timeline.")
    first, last = snapshot.get("start_frame"), snapshot.get("end_frame")
    if not _integer(first) or not _integer(last) or start < first or end > last:
        raise ValueError("The reference In/Out range is outside the timeline. Set new In and Out points in Resolve.")
    return [start, end]


def _make_reference(snapshot, shots, selected, name=None, group_id=None, utterances=(), ignored=(0, 0), origin="Resolve"):
    fps = float(snapshot.get("fps") or 24)
    samples, seen = [], set()
    for shot in shots:
        for frame in shot.get("frames") or []:
            number = int(frame["frame"])
            if number in seen:
                continue
            seen.add(number)
            sample = {"frame": number, "shot": int(shot["start"]),
                      "features": list(feature_vector(frame, shot, fps=fps, utterances=utterances)),
                      "roles": list(selected.get(number, []))}
            if "source_frame" in frame:
                sample["source_frame"] = int(frame["source_frame"])
            if frame.get("signature"):
                sample["signature"] = list(frame["signature"])
            if _valid_preview_path(frame.get("image")):
                # Live.score_many has already extracted this exact source still;
                # loaded .vispamp reviews already materialized their saved stills.
                # Older measured analyses may lack a usable local preview. This
                # optional convenience must never invalidate their training data.
                sample["image"] = frame["image"]
            samples.append(sample)
    missing = sorted(set(selected) - seen)
    if missing:
        raise ValueError(f"{len(missing)} marked images could not be measured exactly (first frame {missing[0]}). "
                         "The reference was not imported; check the source media and timeline alignment.")
    summary = {"markers": len(selected), "samples": len(samples), "unlabelled": len(samples) - len(selected),
               "core": sum("core" in roles for roles in selected.values()),
               "extra": sum("extra" in roles for roles in selected.values()),
               "page": sum("page" in roles for roles in selected.values()),
               "ignored_automatic": ignored[0], "ignored_other_colors": ignored[1]}
    title = name.strip() if isinstance(name, str) else ""
    title = title or snapshot.get("timeline_name") or "Reference chapter"
    reference = {"kind": REFERENCE_KIND, "version": REFERENCE_VERSION, "id": _reference_id(snapshot),
                 "name": title, "group_id": _group_id(snapshot, group_id), "feature_names": list(FEATURE_NAMES),
                 "samples": sorted(samples, key=lambda sample: sample["frame"]), "summary": summary,
                 "source": {"type": origin, "project_name": snapshot.get("project_name") or "",
                            "timeline_name": snapshot.get("timeline_name") or "",
                            "timeline_identity": normalize_identity(snapshot.get("timeline_identity")),
                            "media": _source_media(snapshot), "speech_analyzed": bool(snapshot.get("audio_clips"))},
                 "timebase": {"fps": fps, "start_frame": int(snapshot.get("start_frame") or 0),
                              "start_timecode": snapshot.get("start_timecode") or "00:00:00:00"}}
    for key in ("timecode_fps", "drop"):
        if snapshot.get(key) is not None:
            reference["timebase"][key] = deepcopy(snapshot[key])
    return validate_reference(reference)


def _validate_clips(snapshot, markers):
    clips = list(snapshot.get("video_clips") or [])
    if not clips:
        raise ValueError("Video 1 has no source clip to learn from.")
    fps = float(snapshot.get("fps") or 0)
    shown = float(snapshot.get("timecode_fps") or snapshot.get("playback_fps") or fps)
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(shown) or shown <= 0:
        raise ValueError("The reference timeline frame rate cannot be read.")
    for clip in clips:
        if (not _integer(clip.get("start")) or not _integer(clip.get("end"))
                or clip["end"] <= clip["start"] or not isinstance(clip.get("path"), str) or not clip["path"]):
            raise ValueError("A Video 1 source clip cannot be aligned with the reference markers.")
        if (not _integer(clip.get("source_start")) or not _integer(clip.get("source_end"))
                or clip["source_start"] < 0 or clip["source_end"] <= clip["source_start"]):
            raise ValueError("A Video 1 clip's source In/Out positions cannot be verified for exact reference extraction.")
        if not _normal_speed(clip.get("speed")):
            raise ValueError("Retimed Video 1 clips cannot be imported as exact training references. "
                             "Use a timeline with normal-speed source clips.")
        source_fps = float(clip.get("fps") or shown)
        if not math.isfinite(source_fps) or abs(source_fps - shown) >= 0.01:
            raise ValueError("Source and displayed timeline frame rates differ. The exact marked images "
                             "cannot be verified; use matching rates for the training reference.")
        expected = (clip["end"] - clip["start"]) * source_fps / fps
        if abs((clip["source_end"] - clip["source_start"]) - expected) > 2:
            raise ValueError("A Video 1 clip has a retimed or inconsistent source span. "
                             "The reference was not imported with uncertain frame positions.")
    ordered = sorted(clips, key=lambda clip: clip["start"])
    if any(left["end"] > right["start"] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("The timeline contains overlapping Video 1 clips. Consolidate transitions before importing exact training references.")
    for number in markers:
        matching = [clip for clip in clips if clip["start"] <= number < clip["end"]]
        if len(matching) != 1:
            detail = "overlapping Video 1 clips" if matching else "a gap or missing Video 1 clip"
            raise ValueError(f"The marker at frame {number} falls on {detail}. "
                             "The exact source image cannot be used as a reference.")
    return clips, fps


def import_timeline_reference(snapshot, settings, cache, sources=None, name=None, group_id=None,
                              include_automatic=False, progress=None, cancel=None, use_in_out=False):
    """Import a normalized Resolve snapshot, without writing to Resolve.

    The normal review's In/Out setting is independent: only the explicit import
    option limits the examples. Skip-marked is always ignored for references.
    Selected frames and their source neighbours are added beyond the candidate
    cap, so an expert's choice can never disappear just because it was not one of
    the automatic candidates.
    """
    snapshot = deepcopy(snapshot)
    span = reference_range(snapshot, use_in_out)
    identifier, source_group = _reference_id(snapshot), _group_id(snapshot, group_id)
    selected, automatic, other = _labels(snapshot.get("markers") or [], include_automatic)
    outside = 0
    if span is not None:
        inside = {number: roles for number, roles in selected.items() if span[0] <= number < span[1]}
        outside = len(selected) - len(inside)
        selected = inside
        if not selected:
            raise ValueError("No approved Page start, Core or Extra markers are inside the selected In/Out range. "
                             "Move the In/Out points or disable the range option before importing.")
        for kind in ("video_clips", "audio_clips"):
            retained = []
            for clip in snapshot.get(kind) or []:
                if not _integer(clip.get("start")) or not _integer(clip.get("end")):
                    raise ValueError("A source clip cannot be located relative to the reference In/Out range.")
                if clip["start"] < span[1] and clip["end"] > span[0]:
                    retained.append(clip)
            snapshot[kind] = retained
    clips, fps = _validate_clips(snapshot, selected)
    _cancelled(cancel)
    if sources is None:
        sources = Live(cache, steps=Steps(progress), cancel=cancel)
    settings = dict(settings or {}, skip_marked_shots=False, use_in_out=False)
    _notify(progress, "Reading reference video sources…")
    strips = []
    for clip in clips:
        _cancelled(cancel)
        strips.append(sources.filmstrip(clip))
    _notify(progress, "Locating reference shots and exact marked images…")
    full_shots = build_shots(clips, strips, fps, cancel=cancel, settings=settings)
    utterances = []
    dialogue_statuses = []
    if snapshot.get("audio_clips"):
        if not hasattr(sources, "waveform") or not hasattr(sources, "probabilities"):
            raise ValueError("The reference's speech analysis is unavailable. It was not imported with incomplete speech features.")
        _notify(progress, "Measuring speech context for the reference images…")
        for clip in snapshot["audio_clips"]:
            _cancelled(cancel)
            if not _normal_speed(clip.get("speed")):
                raise ValueError("Retimed Audio 1 clips cannot supply aligned speech-training features.")
            audio = sources.waveform(clip, fps)
            speech_start = int(clip["start"])
            if span is not None:
                speech_start = max(speech_start, span[0])
                speech_end = min(int(clip["end"]), span[1])
                left = math.floor((speech_start - int(clip["start"])) / fps * 16000)
                right = math.ceil((speech_end - int(clip["start"])) / fps * 16000)
                audio = audio[left:right]
                if not len(audio):
                    raise ValueError("Audio inside the selected In/Out range could not be read for reference speech features.")
            probabilities = list(sources.probabilities(audio))
            dialogue = sources.dialogue(audio) if hasattr(sources, "dialogue") else {}
            if dialogue.get("dialogue_status"):
                status = dialogue["dialogue_status"]
                dialogue_statuses.append(status)
                if status.get("state") != "ready":
                    _notify(progress, status.get("detail") or "Voice changes unavailable; using speech timing.")
            utterances.extend(map_turns(dialogue_turns(probabilities, settings, dialogue.get("speaker_changes") or ()),
                                        speech_start, fps))
    by_source = {}
    for shot in full_shots:
        for frame in shot["frames"]:
            by_source.setdefault((frame["media"], frame["source_frame"]), []).append((shot, frame))
    forced = {}
    for number in selected:
        clip = next(clip for clip in clips if clip["start"] <= number < clip["end"])
        source_fps = float(clip.get("fps") or fps)
        source_frame = int(clip.get("source_start") or 0) + math.floor((number - clip["start"]) * source_fps / fps + 1e-9)
        matches = [(shot, frame) for shot, frame in by_source.get((clip["path"], source_frame), [])
                   if shot["start"] <= number < shot["end"]]
        if len(matches) != 1:
            raise ValueError(f"The exact source image for marker frame {number} could not be read. "
                             "The reference was not imported.")
        shot, measured = matches[0]
        exact = dict(measured, frame=number)
        forced.setdefault(id(shot), []).append(exact)
    shots, chosen = [], []
    for shot in full_shots:
        _cancelled(cancel)
        if span is not None and (shot["end"] <= span[0] or shot["start"] >= span[1]):
            continue
        working = shot
        if span is not None:
            within = {frame["frame"]: dict(frame) for frame in shot["frames"] if span[0] <= frame["frame"] < span[1]}
            within.update({frame["frame"]: frame for frame in forced.get(id(shot), [])})
            working = dict(shot, start=max(shot["start"], span[0]), end=min(shot["end"], span[1]),
                           frames=[within[number] for number in sorted(within)])
            if not working["frames"]:
                continue
        candidates = {frame["frame"]: dict(frame) for frame in candidate_frames(working, utterances, settings)}
        for exact in forced.get(id(shot), []):
            for neighbour in working["frames"]:
                if abs(neighbour["source_frame"] - exact["source_frame"]) <= 2:
                    candidates.setdefault(neighbour["frame"], dict(neighbour))
            candidates[exact["frame"]] = exact
        measured_shot = dict(working, frames=[candidates[number] for number in sorted(candidates)])
        shots.append(measured_shot)
        chosen.extend(measured_shot["frames"])
    _notify(progress, f"Measuring {len(chosen)} reference and alternative images…")
    if hasattr(sources, "score_many"):
        sources.score_many(chosen)
    else:
        for frame in chosen:
            _cancelled(cancel)
            frame.update(sources.score(frame))
    _cancelled(cancel)
    reference = _make_reference(snapshot, shots, selected, name, source_group,
                                utterances=utterances, ignored=(automatic, other))
    if dialogue_statuses:
        reference["source"]["dialogue_analysis"] = _dialogue_reference_summary(dialogue_statuses)
    reference["id"] = identifier
    if span is not None:
        reference["source"]["range"] = span
        reference["summary"]["ignored_outside_range"] = outside
    reference = validate_reference(reference)
    _notify(progress, f"Reference ready: {reference['summary']['markers']} marked images.")
    return reference


def reference_from_project(project, name=None, group_id=None):
    """Use explicitly validated review choices without opening or changing Resolve."""
    if not isinstance(project, dict) or not isinstance(project.get("analysis"), dict):
        raise ValueError("This VISPA MP project has no measured analysis to learn from.")
    snapshot = deepcopy(project.get("snapshot") or {})
    analysis = project["analysis"]
    selected, automatic, other = _labels(project.get("proposals") or [], include_automatic=True)
    snapshot.setdefault("fps", analysis.get("fps") or 24)
    snapshot.setdefault("timeline_identity", analysis.get("timeline_identity"))
    snapshot.setdefault("timeline_name", analysis.get("timeline_name") or "Reference chapter")
    snapshot.setdefault("project_name", analysis.get("project_name") or "")
    # Portable projects retain the complete display timebase in the analysis.
    # Older snapshots may not repeat the half-rate interlaced or drop-frame fields.
    base = analysis.get("timebase")
    if isinstance(base, dict):
        for key in ("timecode_fps", "start_timecode", "drop"):
            if snapshot.get(key) is None and base.get(key) is not None:
                snapshot[key] = deepcopy(base[key])
    reference = _make_reference(snapshot, deepcopy(analysis.get("shots") or []), selected, name, group_id,
                                utterances=analysis.get("utterances") or [], ignored=(automatic, other), origin="VISPA MP")
    statuses = [track["dialogue_status"] for track in analysis.get("speech_tracks") or []
                if track.get("dialogue_status")]
    if statuses:
        reference["source"]["dialogue_analysis"] = _dialogue_reference_summary(statuses)
    reference["editorial"] = {"page_layout": deepcopy((project.get("view") or {}).get("page_layout")),
                              "excluded_frames": list((project.get("view") or {}).get("excluded_frames") or [])}
    return validate_reference(reference)


def validate_reference(reference):
    """Validate portable numeric training data; unknown versions are never guessed."""
    if (not isinstance(reference, dict) or reference.get("kind") != REFERENCE_KIND
            or type(reference.get("version")) is not int or reference["version"] != REFERENCE_VERSION):
        raise ValueError("This is not a supported VISPA MP training reference.")
    for key in ("id", "name", "group_id"):
        if not isinstance(reference.get(key), str) or not reference[key].strip() or len(reference[key]) > 2048:
            raise ValueError(f"The training reference {key} is missing or invalid.")
    if "enabled" in reference and not isinstance(reference["enabled"], bool):
        raise ValueError("The training reference's corpus inclusion must be true or false.")
    if reference.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("This reference uses an incompatible visual feature version. Import it again.")
    samples = reference.get("samples")
    if not isinstance(samples, list) or not samples or len(samples) > 500_000:
        raise ValueError("The training reference images are missing or too numerous.")
    source = reference.get("source")
    scope = source.get("range") if isinstance(source, dict) else None
    if scope is not None and (not isinstance(scope, list) or len(scope) != 2
                              or not all(_integer(number) for number in scope) or scope[1] <= scope[0]):
        raise ValueError("The reference In/Out range cannot be read.")
    seen, labelled = set(), 0
    for sample in samples:
        if (not isinstance(sample, dict) or not _integer(sample.get("frame")) or not _integer(sample.get("shot"))
                or sample["frame"] in seen):
            raise ValueError("A training reference image is duplicated or invalid.")
        seen.add(sample["frame"])
        if scope is not None and not scope[0] <= sample["frame"] < scope[1]:
            raise ValueError("A reference image is outside its saved In/Out range.")
        features, roles = sample.get("features"), sample.get("roles")
        if (not isinstance(features, list) or len(features) != len(FEATURE_NAMES)
                or any(not _finite(value) or not 0 <= value <= 1 for value in features)):
            raise ValueError("A training reference contains unreadable visual features.")
        if (not isinstance(roles, list) or any(role not in ("core", "extra", "page") for role in roles)
                or len(set(roles)) != len(roles) or "page" in roles and "core" not in roles
                or "extra" in roles and len(roles) != 1):
            raise ValueError("A training reference contains incompatible image roles.")
        if "source_frame" in sample and not _integer(sample["source_frame"]):
            raise ValueError("A training reference source frame is invalid.")
        if "image" in sample and not _valid_preview_path(sample["image"]):
            raise ValueError("A training reference preview must use an absolute local JPEG or PNG image path.")
        if "signature" in sample and (not isinstance(sample["signature"], list) or len(sample["signature"]) > 4096
                                       or any(not _finite(value) for value in sample["signature"])):
            raise ValueError("A training reference image signature is invalid.")
        labelled += bool(roles)
    if not labelled or not isinstance(reference.get("summary"), dict):
        raise ValueError("The training reference contains no validated image choices.")
    summary = reference["summary"]
    expected = {"markers": labelled, "samples": len(samples), "unlabelled": len(samples) - labelled,
                **{role: sum(role in sample["roles"] for sample in samples) for role in ("core", "extra", "page")}}
    for key, count in expected.items():
        if type(summary.get(key)) is not int or summary[key] != count:
            raise ValueError("The training reference summary does not match its validated image choices.")
    try:
        encoded = json.dumps(reference, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("The training reference contains unsupported data.") from error
    if len(encoded.encode("utf-8")) > MAX_REFERENCE_BYTES:
        raise ValueError("The training reference is too large.")
    validated = deepcopy(reference)
    validated.setdefault("enabled", True)
    return validated


def _reference_path(reference_id, folder=None):
    if not isinstance(reference_id, str) or not reference_id.strip() or len(reference_id) > 2048:
        raise ValueError("The training reference identity is missing or invalid.")
    folder = Path(folder) if folder is not None else REFERENCES_DIR
    name = hashlib.sha256(reference_id.encode("utf-8")).hexdigest()[:32] + ".json"
    return folder / name


def _group_name(group_id):
    if not isinstance(group_id, str) or not group_id.strip() or len(group_id.strip()) > 2048:
        raise ValueError("Choose a source chapter group between 1 and 2048 characters.")
    return group_id.strip()


def save_reference(reference, folder=None):
    reference = validate_reference(reference)
    folder = Path(folder) if folder is not None else REFERENCES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = _reference_path(reference["id"], folder)
    descriptor, temporary = tempfile.mkstemp(prefix=".reference-", suffix=".part", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(reference, handle, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target


def save_imported_reference(reference, folder=None, *, group_id=None):
    """Replace measured data while retaining corpus choices made after import.

    Re-importing a timeline must not silently include a chapter the user had
    excluded or undo a corrected source group. Only a new explicit group field
    in the import dialog overrides the stored group.
    """
    imported = validate_reference(reference)
    target = _reference_path(imported["id"], folder)
    if target.is_file():
        existing = load_reference(target)
        if existing["id"] != imported["id"]:
            raise ValueError("The saved reference identity changed. Refresh the corpus before importing again.")
        imported["enabled"] = existing.get("enabled", True)
        imported["group_id"] = existing["group_id"] if group_id is None else _group_name(group_id)
    elif group_id is not None:
        imported["group_id"] = _group_name(group_id)
    return save_reference(imported, folder)


def update_reference(reference_id, *, enabled=None, group_id=None, folder=None):
    """Atomically change inclusion/group metadata, leaving examples intact."""
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("Corpus inclusion must be true or false.")
    if group_id is not None:
        group_id = _group_name(group_id)
    target = _reference_path(reference_id, folder)
    if not target.is_file():
        raise ValueError("The selected reference no longer exists. Refresh the corpus list.")
    reference = load_reference(target)
    if reference["id"] != reference_id:
        raise ValueError("The selected reference identity changed. Refresh the corpus list.")
    if enabled is not None:
        reference["enabled"] = enabled
    if group_id is not None:
        reference["group_id"] = group_id
    save_reference(reference, folder)
    return reference


def remove_reference(reference_id, folder=None):
    """Retire one reference from the corpus, retaining a recoverable JSON copy."""
    target = _reference_path(reference_id, folder)
    if not target.is_file():
        raise ValueError("The selected reference no longer exists. Refresh the chapter list.")
    reference = load_reference(target)
    if reference["id"] != reference_id:
        raise ValueError("The selected reference identity changed. Refresh the chapter list.")
    archive = target.parent.parent / "reference_archive"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / f"{target.stem}-{uuid.uuid4().hex}.json"
    os.replace(target, destination)
    return destination


def _page_statistics(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {"count": len(values), "mean": sum(values) / len(values), "median": median,
            "min": ordered[0], "max": ordered[-1]}


def corpus_summary(references):
    """Describe included marker choices, never estimate unseen image quality.

    Per-page values count only marked images after an observed Page start and
    before the next one. Images before the first start remain unassigned. The
    last observed page can be partial, so these are neither source-wide density
    measurements nor an automatic recommendation for the user's settings.
    """
    if not isinstance(references, (list, tuple)):
        raise ValueError("The reference corpus cannot be read.")
    result = {"references": len(references), "active_references": 0, "excluded_references": 0,
              "duplicate_references": 0, "groups": 0, "samples": 0, "page": 0, "core": 0, "extra": 0,
              "extra_core_ratio": None, "observed_pages": 0,
              "core_per_page": _page_statistics([]), "extra_per_page": _page_statistics([]),
              "before_first_start": {"core": 0, "extra": 0}, "conflicting_media": [], "warnings": [],
              "notes": ["Page statistics describe marked images after observed page starts; partial chapter ranges can contain partial pages.",
                        "Source groups use media paths. Copies or renamed videos must be assigned to the same chapter group manually."]}
    seen, groups, media_groups = set(), set(), {}
    cores_per_page, extras_per_page = [], []
    for raw in references:
        reference = validate_reference(raw)
        if not reference.get("enabled", True):
            result["excluded_references"] += 1
            continue
        if reference["id"] in seen:
            result["duplicate_references"] += 1
            continue
        seen.add(reference["id"])
        result["active_references"] += 1
        groups.add(reference["group_id"])
        result["samples"] += len(reference["samples"])
        page = None
        for sample in sorted(reference["samples"], key=lambda sample: sample["frame"]):
            roles = sample["roles"]
            for role in ("page", "core", "extra"):
                result[role] += role in roles
            if "page" in roles:
                if page is not None:
                    cores_per_page.append(page["core"])
                    extras_per_page.append(page["extra"])
                page = {"core": 0, "extra": 0}
            target = page if page is not None else result["before_first_start"]
            target["core"] += "core" in roles
            target["extra"] += "extra" in roles
        if page is not None:
            cores_per_page.append(page["core"])
            extras_per_page.append(page["extra"])
        source = reference.get("source") or {}
        media = source.get("media", ()) if isinstance(source, dict) else ()
        media = [media] if isinstance(media, str) else media
        if isinstance(media, (list, tuple)):
            for entry in media:
                path = entry.get("path") if isinstance(entry, dict) else entry
                if isinstance(path, str) and path:
                    canonical = os.path.normcase(os.path.abspath(path))
                    media_groups.setdefault(canonical, set()).add(reference["group_id"])
    result["groups"] = len(groups)
    result["observed_pages"] = len(cores_per_page)
    result["core_per_page"] = _page_statistics(cores_per_page)
    result["extra_per_page"] = _page_statistics(extras_per_page)
    result["extra_core_ratio"] = result["extra"] / result["core"] if result["core"] else None
    for path, identities in sorted(media_groups.items()):
        if len(identities) > 1:
            result["conflicting_media"].append({"name": Path(path).name, "groups": sorted(identities)})
            result["warnings"].append(f"The source video {Path(path).name} is included in different chapter groups. Group its versions together before training.")
    if not result["active_references"]:
        result["warnings"].append("No reference chapters are included in the next training run.")
    else:
        if result["groups"] == 1:
            result["warnings"].append("Only one source chapter group is included; independent chapter validation is unavailable.")
        elif result["groups"] == 2:
            result["warnings"].append("Two source chapter groups allow one held-out group and leave one group for training.")
        for role, label in (("core", "Core"), ("extra", "Extra"), ("page", "Page start")):
            if not result[role]:
                result["warnings"].append(f"The included corpus has no approved {label} examples; this role cannot learn from it.")
    if result["duplicate_references"]:
        result["warnings"].append("Duplicate reference identities are counted only once, as they are during training.")
    return result


def load_reference(path):
    path = Path(path)
    if path.stat().st_size > MAX_REFERENCE_BYTES:
        raise ValueError("The training reference is too large.")
    try:
        reference = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda _value:
                               (_ for _ in ()).throw(ValueError("Non-finite reference value")))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("The training reference cannot be read.") from error
    return validate_reference(reference)


def list_references(folder=None):
    folder = Path(folder) if folder is not None else REFERENCES_DIR
    if not folder.is_dir():
        return []
    references = [load_reference(path) for path in sorted(folder.glob("*.json"))]
    return sorted(references, key=lambda reference: (reference["name"].casefold(), reference["id"]))
