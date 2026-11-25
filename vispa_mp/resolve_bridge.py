"""Read and write the open Resolve timeline.

Video track 1 and audio track 1 only. Upper tracks are colour grades and are ignored.
Run this module as the bridge process: it speaks one JSON object per line.
"""

import json
import os
import sys

from vispa_mp.markers import AUTOMATIC, cue_warning, is_automatic, plan_apply
from vispa_mp.timebase import absolute_mark, parse_fps

VIDEO_TRACK = 1
# Same number as SCRIPT_VERSION in resolve_scripts/VISPA_MP.lua.
SCRIPT_VERSION = 2
AUDIO_TRACK = 1


def configure_resolve_env():
    api = os.environ.get("RESOLVE_SCRIPT_API") or r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
    library = os.environ.get("RESOLVE_SCRIPT_LIB") or r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    os.environ["RESOLVE_SCRIPT_API"] = api
    os.environ["RESOLVE_SCRIPT_LIB"] = library
    modules = os.path.join(api, "Modules")
    if modules not in sys.path:
        sys.path.append(modules)


def connect():
    configure_resolve_env()
    try:
        import DaVinciResolveScript as script
    except ImportError as error:
        raise RuntimeError(
            "This bridge's Python cannot load fusionscript.dll. "
            "Set VISPA_MP_RESOLVE_PYTHON to a Python that matches Resolve. "
            f"({error})"
        ) from error
    resolve = script.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("DaVinci Resolve is not open, or External scripting using is not set to Local.")
    return resolve


def _setting(timeline, *keys):
    for key in keys:
        try:
            value = timeline.GetSetting(key)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return None


def _clip(item):
    try:
        media = item.GetMediaPoolItem()
    except Exception:
        media = None
    props = {}
    if media is not None:
        try:
            props = media.GetClipProperty() or {}
        except Exception:
            props = {}
    path = props.get("File Path") or ""
    if not path:
        return None
    start = int(item.GetStart())
    end = int(item.GetEnd())
    source_start = int(item.GetSourceStartFrame() or 0)
    source_end = int(item.GetSourceEndFrame() or 0)
    if source_end <= source_start:
        source_end = source_start + max(0, end - start)
    fps = parse_fps(props.get("FPS"))
    return {
        "name": item.GetName() or "",
        "start": start,
        "end": end,
        "source_start": source_start,
        "source_end": source_end,
        "path": path,
        "fps": fps,
        "speed": _speed(item),
    }


def _speed(item):
    getter = getattr(item, "GetSpeed", None)
    if getter is None:
        return None
    try:
        value = getter()
    except Exception:
        return None
    if isinstance(value, dict):
        for key in ("speed", "playbackSpeed", "Speed"):
            if key in value:
                return value[key]
    return value if isinstance(value, (int, float, str)) else None


def _markers(timeline):
    raw = timeline.GetMarkers() or {}
    markers = []
    for frame, info in raw.items():
        number = int(float(frame))
        info = info or {}
        custom = info.get("customData")
        if not custom:
            getter = getattr(timeline, "GetMarkerCustomData", None)
            if getter is not None:
                try:
                    custom = getter(number)
                except Exception:
                    custom = ""
        markers.append({
            "frame": number,
            "color": str(info.get("color") or ""),
            "name": str(info.get("name") or ""),
            "note": str(info.get("note") or ""),
            "duration": int(float(info.get("duration") or 1)),
            "custom_data": str(custom or ""),
            "automatic": is_automatic(custom),
        })
    markers.sort(key=lambda marker: marker["frame"])
    return markers


def _marks(timeline, start_frame):
    try:
        raw = timeline.GetMarkInOut() or {}
    except Exception:
        raw = {}
    video = raw.get("video") or {}
    return absolute_mark(video.get("in"), start_frame), absolute_mark(video.get("out"), start_frame)


def _track_names(timeline, track_type):
    try:
        count = int(timeline.GetTrackCount(track_type) or 0)
    except Exception:
        count = 0
    names = []
    for index in range(1, count + 1):
        try:
            names.append(timeline.GetTrackName(track_type, index) or "")
        except Exception:
            names.append("")
    return names


def read_timeline(timeline):
    """A JSON-ready snapshot of video 1, audio 1, markers and the in/out range."""
    if timeline is None:
        raise RuntimeError("No timeline is open.")
    start_frame = int(timeline.GetStartFrame() or 0)
    fps = parse_fps(_setting(timeline, "timelineFrameRate")) or 24.0
    drop_raw = str(_setting(timeline, "timelineDropFrameTimecode") or "").lower()
    interlace_raw = str(_setting(timeline, "timelineInterlaceProcessing") or "").lower()
    playback_fps = parse_fps(_setting(timeline, "timelinePlaybackFrameRate"))
    video_names = _track_names(timeline, "video")
    video = []
    for item in timeline.GetItemListInTrack("video", VIDEO_TRACK) or []:
        clip = _clip(item)
        if clip:
            video.append(clip)
    audio = []
    if int(timeline.GetTrackCount("audio") or 0) >= AUDIO_TRACK:
        for item in timeline.GetItemListInTrack("audio", AUDIO_TRACK) or []:
            clip = _clip(item)
            if clip:
                audio.append(clip)
    mark_in, mark_out = _marks(timeline, start_frame)
    warning = cue_warning(video_names)
    warnings = [warning] if warning else []
    if not video:
        warnings.append("Video 1 has no clip linked to a file.")
    if not audio:
        warnings.append("Audio 1 has no clip linked to a file. Lines will not be detected.")
    snapshot = {
        "timeline_name": timeline.GetName() or "",
        "interlaced": interlace_raw in ("1", "true"),
        "script_version": SCRIPT_VERSION,
        "start_frame": start_frame,
        "end_frame": int(timeline.GetEndFrame() or 0),
        "fps": fps,
        "drop": drop_raw in ("1", "true"),
        "start_timecode": timeline.GetStartTimecode() or "00:00:00:00",
        "video_track_name": video_names[0] if video_names else "",
        "video_clips": video,
        "audio_clips": audio,
        "markers": _markers(timeline),
        "mark_in": mark_in,
        "mark_out": mark_out,
        "warnings": warnings,
    }
    if playback_fps:
        snapshot["playback_fps"] = playback_fps
    return snapshot


def apply_markers(timeline, proposals, start=None, end=None):
    """Replace vispa-mp markers in the range. Markers placed by hand stay."""
    existing = _markers(timeline)
    delete, add, skipped = plan_apply(existing, proposals, start, end)
    for frame in delete:
        timeline.DeleteMarkerAtFrame(int(frame))
    placed = []
    for proposal in add:
        frame = int(proposal["frame"])
        # Colour is the whole marker. Name and note stay empty: the exporter
        # already builds the filename data from the colour alone.
        ok = timeline.AddMarker(frame, proposal["color"], "", "", 1, AUTOMATIC)
        if ok:
            placed.append(frame)
        else:
            skipped.append(frame)
    return {"deleted": delete, "placed": placed, "skipped": skipped}


def dispatch(command, timeline):
    name = command.get("cmd")
    if name == "ping":
        return {"ok": True}
    if name == "read":
        return read_timeline(timeline)
    if name == "seek":
        ok = timeline.SetCurrentTimecode(command["timecode"])
        return {"ok": bool(ok), "timecode": command["timecode"]}
    if name == "apply":
        return apply_markers(timeline, command.get("proposals") or [], command.get("start"), command.get("end"))
    raise RuntimeError(f"Unknown command: {name}")


def serve(resolve):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        try:
            timeline = None
            if message.get("cmd") != "ping":
                project = resolve.GetProjectManager().GetCurrentProject()
                if not project:
                    raise RuntimeError("No project is open.")
                timeline = project.GetCurrentTimeline()
            result = dispatch(message, timeline)
            payload = {"id": message.get("id"), "ok": True, "result": result}
        except Exception as error:
            payload = {"id": message.get("id"), "ok": False, "error": str(error)}
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main():
    try:
        resolve = connect()
    except Exception as error:
        sys.stdout.write(json.dumps({"id": None, "ok": False, "error": str(error)}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 1
    serve(resolve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
