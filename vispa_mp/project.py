"""Portable review projects: measured images and the user's unplaced markers.

A .vispamp file contains JSON and stills, never the original video or models.
It keeps the original Resolve identity; opening it cannot grant a new target.
"""

from copy import deepcopy
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from PIL import Image

from vispa_mp.preset import DEFAULTS, FRAME_FORMATS
from vispa_mp.timebase import parse_timecode
from vispa_mp.timeline_identity import normalize_identity

FILE_KIND = "vispa-mp-project"
FILE_VERSION = 1
FILE_FILTER = "VISPA MP project (*.vispamp)"
_IMAGE_NAME = re.compile(r"images/([0-9a-f]{64})\.jpg\Z")
_MAX_JSON = 64 * 1024 * 1024
_MAX_IMAGE = 16 * 1024 * 1024
_MAX_TOTAL = 2 * 1024 * 1024 * 1024


def _integer(value):
    # Frame selections cross Qt's signed-int signals as well as Resolve's API.
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 31) <= value < 2 ** 31


def _page_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and -(2 ** 63) <= value < 2 ** 63


def _number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _invalid(detail):
    raise ValueError(f"This VISPA MP project is incomplete or damaged: {detail}.")


def _image_nodes(project):
    for shot in project["analysis"]["shots"]:
        yield from shot["frames"]
    yield from project["proposals"]


def _interval(value):
    return (isinstance(value, dict) and _integer(value.get("start"))
            and _integer(value.get("end")) and value["end"] >= value["start"])


def _validate_cameras(cameras):
    if not isinstance(cameras, dict):
        _invalid("the saved zoom and position cannot be read")
    for mode in ("strip", "board"):
        state = cameras.get(mode)
        if state is None:
            continue
        if not isinstance(state, dict):
            _invalid(f"the saved {mode} zoom and position cannot be read")
        centre = state.get("center")
        if (not isinstance(centre, list) or len(centre) != 2
                or any(not _number(value) or abs(value) > 1e6 for value in centre)):
            _invalid(f"the saved {mode} position cannot be read")
        zoom = state.get("zoom")
        if mode == "strip":
            if "zoom" not in state or (zoom is not None and (not _number(zoom) or not 1 <= zoom <= 720)):
                _invalid("the saved strip zoom cannot be read")
            columns = state.get("columns")
            if not _integer(columns) or not 1 <= columns <= 4096:
                _invalid("the saved strip arrangement cannot be read")
        elif not _number(zoom) or not 1 <= zoom <= 8:
            _invalid("the saved board zoom cannot be read")


def _validate_page_layout(layout):
    """An optional editorial order, independent of the source frame positions."""
    if layout is None:
        return
    if not isinstance(layout, list):
        _invalid("the saved page arrangement cannot be read")
    page_ids, frames = set(), set()
    for page in layout:
        if (not isinstance(page, dict) or not _page_id(page.get("id"))
                or not isinstance(page.get("frames"), list) or not page["frames"]
                or any(not _integer(frame) for frame in page["frames"])):
            _invalid("a saved page arrangement cannot be read")
        if page["id"] in page_ids or any(frame in frames for frame in page["frames"]):
            _invalid("the saved page arrangement contains duplicate pages or images")
        if len(set(page["frames"])) != len(page["frames"]):
            _invalid("the saved page arrangement contains duplicate images")
        page_ids.add(page["id"])
        frames.update(page["frames"])


def _validate(project, internal=False):
    if not isinstance(project, dict) or project.get("kind") != FILE_KIND:
        raise ValueError("This file is not a VISPA MP project.")
    if not _integer(project.get("version")) or project["version"] != FILE_VERSION:
        raise ValueError("This project uses an unsupported version. Open it with the matching version of VISPA MP.")
    for key in ("snapshot", "analysis", "settings", "view"):
        if not isinstance(project.get(key), dict):
            _invalid(f"{key} is missing")
    snapshot, analysis = project["snapshot"], project["analysis"]
    identity = normalize_identity(analysis.get("timeline_identity"))
    if identity is None or identity != normalize_identity(snapshot.get("timeline_identity")):
        _invalid("the analyzed project and timeline cannot be verified")
    for source in (snapshot, analysis):
        if not _number(source.get("fps")) or source["fps"] <= 0:
            _invalid("the timeline rate is missing")
        for name in ("project_name", "timeline_name"):
            if name in source and not isinstance(source[name], str):
                _invalid(f"the {name.replace('_', ' ')} is unreadable")
    base = analysis.get("timebase")
    if not isinstance(base, dict) or not _integer(base.get("start_frame")):
        _invalid("the analyzed timeline start is missing")
    if not _number(base.get("fps")) or base["fps"] != analysis["fps"]:
        _invalid("the analyzed timecode rate is missing")
    for source in (snapshot, analysis, base):
        if "warnings" in source and (not isinstance(source["warnings"], list)
                                     or any(not isinstance(item, str) for item in source["warnings"])):
            _invalid("the timeline warnings cannot be read")
        if source.get("timecode_fps") is not None and (
                not _number(source["timecode_fps"]) or source["timecode_fps"] <= 0):
            _invalid("the displayed timecode rate cannot be read")
    try:
        if not isinstance(base.get("start_timecode"), str):
            _invalid("the analyzed timecode is missing")
        parse_timecode(base["start_timecode"], base.get("timecode_fps") or base["fps"])
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("The analyzed timecode in this project cannot be read.") from error
    if not _integer(snapshot.get("start_frame")) or snapshot["start_frame"] != base["start_frame"]:
        _invalid("the snapshot and analyzed timeline starts differ")
    if analysis["fps"] != snapshot["fps"]:
        _invalid("the snapshot and analyzed timeline rates differ")
    span = analysis.get("range")
    if span is not None and (not isinstance(span, list) or len(span) != 2
                             or not all(_integer(frame) for frame in span) or span[1] < span[0]):
        _invalid("the analyzed In/Out range cannot be read")
    for key in ("video_clips", "audio_clips", "markers"):
        if key in snapshot and (not isinstance(snapshot[key], list)
                                or any(not isinstance(item, dict) for item in snapshot[key])):
            _invalid(f"{key.replace('_', ' ')} cannot be read")
    shots = analysis.get("shots")
    if not isinstance(shots, list):
        _invalid("the analyzed images are missing")
    for shot in shots:
        if (not isinstance(shot, dict) or not _integer(shot.get("start"))
                or not _integer(shot.get("end")) or shot["end"] <= shot["start"]
                or not isinstance(shot.get("frames"), list)):
            _invalid("an analyzed shot cannot be read")
        for frame in shot["frames"]:
            if not isinstance(frame, dict) or not _integer(frame.get("frame")):
                _invalid("an analyzed image cannot be read")
    proposals = project.get("proposals")
    if not isinstance(proposals, list):
        _invalid("the prepared markers are missing")
    for marker in proposals:
        if (not isinstance(marker, dict) or not _integer(marker.get("frame"))
                or marker.get("color") not in ("Green", "Blue", "Cyan")):
            _invalid("a prepared marker cannot be read")
        if "origin_frame" in marker and not _integer(marker["origin_frame"]):
            _invalid("a prepared marker's original frame cannot be read")
        for key in ("note", "name", "rule"):
            if key in marker and not isinstance(marker[key], str):
                _invalid("a prepared marker caption cannot be read")
    for key in ("manual_frames",):
        if key in analysis and (not isinstance(analysis[key], list)
                                or any(not _integer(frame) for frame in analysis[key])):
            _invalid("the hand-placed markers cannot be read")
    for key in ("utterances", "speech_tracks"):
        if key in analysis and (not isinstance(analysis[key], list)
                                or any(not isinstance(item, dict) for item in analysis[key])):
            _invalid("the speech analysis cannot be read")
        for part in analysis.get(key, []):
            if not _interval(part):
                _invalid("a speech interval cannot be read")
            if key == "speech_tracks" and (not isinstance(part.get("probs"), list)
                                           or any(not _number(value) for value in part["probs"])):
                _invalid("the saved speech probabilities cannot be read")
    for key, value in project["settings"].items():
        default = DEFAULTS.get(key)
        if default is None:
            continue
        valid = (isinstance(value, bool) if isinstance(default, bool) else
                 _number(value) if isinstance(default, (int, float)) else isinstance(value, type(default)))
        if not valid:
            _invalid(f"the {key} setting cannot be read")
    view = project["view"]
    if "page_layout" in view:
        _validate_page_layout(view["page_layout"])
    if "cameras" in view:
        _validate_cameras(view["cameras"])
    choices = {"page_format": ("A5", "A4", "B5", "Custom"), "orientation": ("portrait", "landscape"),
               "mode": ("strip", "board"), "view_filter": ("all", "core", "starts"),
               "frame_format": FRAME_FORMATS}
    for key, options in choices.items():
        if key in view and view[key] not in options:
            _invalid("the saved view cannot be read")
    for key in ("custom_width", "custom_height"):
        if key in view and (not _number(view[key]) or not 10 <= view[key] <= 2000):
            _invalid("the page dimensions cannot be read")
    if "show_board_labels" in view and not isinstance(view["show_board_labels"], bool):
        _invalid("the board label visibility cannot be read")
    for key in ("frame_custom_width", "frame_custom_height"):
        if key in view and (not _number(view[key]) or not 0.1 <= view[key] <= 100):
            _invalid("the preview frame proportions cannot be read")
    if "excluded_frames" in view and (not isinstance(view["excluded_frames"], list)
                                       or any(not _integer(frame) for frame in view["excluded_frames"])):
        _invalid("the removed marker proposals cannot be read")
    if "suggestions_height" in view and (not _integer(view["suggestions_height"])
                                          or not 120 <= view["suggestions_height"] <= 4000):
        _invalid("the suggestions panel height cannot be read")
    for key in ("selected_frame", "playhead_frame"):
        if key in view and view[key] is not None and not _integer(view[key]):
            _invalid("the saved selection cannot be read")
    if "selected_page_id" in view and view["selected_page_id"] is not None and not _page_id(view["selected_page_id"]):
        _invalid("the saved page selection cannot be read")
    if "selected_manual" in view and not isinstance(view["selected_manual"], bool):
        _invalid("the saved selection cannot be read")
    if "open_pages" in view and (not isinstance(view["open_pages"], list)
                                or any(not _page_id(page) for page in view["open_pages"])):
        _invalid("the saved pages cannot be read")
    if "rule_warnings" in view and (not isinstance(view["rule_warnings"], list)
                                   or any(not isinstance(warning, str) for warning in view["rule_warnings"])):
        _invalid("the saved rule warnings cannot be read")
    for node in _image_nodes(project):
        path = node.get("image")
        if path is not None and not isinstance(path, str):
            _invalid("an image reference cannot be read")
        if path and internal and not _IMAGE_NAME.fullmatch(path):
            _invalid("an image reference is not inside the project")
        for key in ("sharpness", "neighbor", "open_mouth", "closed_mouth", "motion_blur", "from_behind",
                    "group", "solo", "face", "expression", "cavity", "mouth", "teeth", "strength",
                    "tongue", "uvula", "upper_teeth_only", "lower_teeth_only", "clenched_teeth"):
            if key in node and not _number(node[key]):
                _invalid("an image score cannot be read")
        if "signature" in node and (not isinstance(node["signature"], list)
                                    or any(not _number(value) for value in node["signature"])):
            _invalid("an image signature cannot be read")


def _check_image(data, name):
    if not data or len(data) > _MAX_IMAGE:
        _invalid(f"the image {name} is empty or too large")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 16_777_216:
                _invalid(f"the image {name} is too large")
            image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError(f"The image {name} in this project cannot be read.") from error


def save_project(path, snapshot, analysis, proposals, settings, view):
    """Atomically save the exact prepared markers, their analysis and all stills."""
    project = deepcopy({"kind": FILE_KIND, "version": FILE_VERSION, "snapshot": snapshot,
                        "analysis": analysis, "proposals": proposals, "settings": settings, "view": view})
    _validate(project)
    images, by_source = {}, {}
    for node in _image_nodes(project):
        source = node.get("image")
        if not source:
            continue
        if source not in by_source:
            try:
                data = Path(source).read_bytes()
            except OSError as error:
                raise ValueError(f"The review image {source} is missing or cannot be read. The project was not saved.") from error
            _check_image(data, source)
            name = f"images/{hashlib.sha256(data).hexdigest()}.jpg"
            images.setdefault(name, Path(source))
            by_source[source] = name
        node["image"] = by_source[source]
    try:
        metadata = json.dumps(project, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("The current review contains data that cannot be saved.") from error
    if len(metadata) > _MAX_JSON:
        raise ValueError("This project contains too much analysis data to save.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}-", suffix=".part", dir=target.parent)
    os.close(descriptor)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("project.json", metadata)
            total = len(metadata)
            for name, source in images.items():
                data = source.read_bytes()
                if hashlib.sha256(data).hexdigest() != _IMAGE_NAME.fullmatch(name)[1]:
                    raise ValueError("A review image changed during saving. Please save the project again.")
                total += len(data)
                if total > _MAX_TOTAL:
                    raise ValueError("This project contains too many images to save.")
                archive.writestr(name, data, compress_type=ZIP_STORED)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _reject_constant(_value):
    _invalid("a numeric value is unreadable")


def load_project(path, cache):
    """Read a complete review without models or source media, retaining its origin.

    Only known image entries are materialized. No path from the archive is ever
    passed to extractall, and failed loads never return a partially restored review.
    """
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or "project.json" not in names:
                _invalid("the project index is missing or duplicated")
            if (len(entries) > 50_000 or sum(entry.file_size for entry in entries) > _MAX_TOTAL
                    or any(name != "project.json" and not _IMAGE_NAME.fullmatch(name) for name in names)):
                _invalid("the archive contains unsupported entries")
            if archive.getinfo("project.json").file_size > _MAX_JSON:
                _invalid("the project index is too large")
            metadata = archive.read("project.json")
            project = json.loads(metadata.decode("utf-8"), parse_constant=_reject_constant)
            _validate(project, internal=True)
            wanted = {node["image"] for node in _image_nodes(project) if node.get("image")}
            if wanted != set(names) - {"project.json"}:
                _invalid("a saved image is missing or unexpected")
            if any(archive.getinfo(name).file_size > _MAX_IMAGE for name in wanted):
                _invalid("a saved image is too large")
            root = (Path(cache) / "projects").resolve()
            root.mkdir(parents=True, exist_ok=True)
            fingerprint = hashlib.sha256(metadata).hexdigest()
            folder = root / fingerprint
            staging = Path(tempfile.mkdtemp(prefix=f"{fingerprint}-", dir=root))
            try:
                (staging / "images").mkdir()
                for name in sorted(wanted):
                    data = archive.read(name)
                    if hashlib.sha256(data).hexdigest() != _IMAGE_NAME.fullmatch(name)[1]:
                        _invalid("a saved image failed its integrity check")
                    _check_image(data, name)
                    (staging / name).write_bytes(data)
                # Reuse an intact materialization; otherwise keep a fresh folder
                # instead of deleting or following an existing filesystem link.
                intact = folder.is_dir() and all(
                    (folder / name).resolve().is_relative_to(root)
                    and (folder / name).is_file()
                    and hashlib.sha256((folder / name).read_bytes()).hexdigest() == _IMAGE_NAME.fullmatch(name)[1]
                    for name in wanted)
                if not folder.exists():
                    os.replace(staging, folder)
                elif not intact:
                    folder = staging
                    staging = None
                for node in _image_nodes(project):
                    if node.get("image"):
                        node["image"] = str(folder / node["image"])
            finally:
                if staging is not None and staging.exists() and staging.resolve().parent == root:
                    shutil.rmtree(staging)
            return {key: project[key] for key in ("snapshot", "analysis", "proposals", "settings", "view")}
    except (BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, RuntimeError, EOFError) as error:
        raise ValueError("This VISPA MP project cannot be read. It may be damaged or use an unsupported format.") from error
