"""Where the ONNX files live, and how they are fetched.

Silero VAD v6.3 and pyannote segmentation 3.0 are MIT.
WD EVA02-Large Tagger v3 is Apache-2.0.
PixAI is not downloaded here: it is only the measured fallback if WD mis-ranks mouths.
"""

import hashlib
import http.client
import json
import re
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
WD_DIR = MODELS / "wd-eva02-large-tagger-v3"
SILERO = MODELS / "silero_vad.onnx"
WD_ONNX = WD_DIR / "model.onnx"
WD_LABELS = WD_DIR / "selected_tags.csv"
WD_SHA256 = "9e768793060c7939b277ccb382783e8670e8a042d29d77aa736be0c8cc898bfc"
SPEAKER_SEGMENTATION = MODELS / "pyannote-segmentation-3.0" / "model.onnx"
SPEAKER_SEGMENTATION_SHA256 = "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079"
SPEAKER_ARCHIVE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                       "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
SPEAKER_ARCHIVE_SHA256 = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
_SPEAKER_ARCHIVE_ROOT = "sherpa-onnx-pyannote-segmentation-3-0"
_MAX_SPEAKER_BYTES = 20 * 1024 * 1024
_RANGE_BYTES = 1024 * 1024

FILES = (
    ("https://github.com/snakers4/silero-vad/raw/refs/tags/v6.3/src/silero_vad/data/silero_vad.onnx", SILERO, None),
    ("https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx?download=true", WD_ONNX, WD_SHA256),
    ("https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv?download=true", WD_LABELS, None),
)


def ready():
    return SILERO.is_file() and SILERO.stat().st_size > 1_000_000 and WD_ONNX.is_file() and WD_LABELS.is_file()


def dialogue_ready():
    """Dialogue segmentation is optional; the original analysis remains usable."""
    try:
        return (SPEAKER_SEGMENTATION.is_file() and SPEAKER_SEGMENTATION.stat().st_size > 1000
                and _sha256(SPEAKER_SEGMENTATION) == SPEAKER_SEGMENTATION_SHA256)
    except OSError:
        return False


def missing():
    absent = [str(path.name) for _, path, _ in FILES if not path.is_file() or path.stat().st_size < 1000]
    if not dialogue_ready():
        absent.append("pyannote-segmentation-3.0/model.onnx")
    return absent


def ensure(progress=None):
    """Download whatever is absent. An existing file is left in place."""
    for url, path, digest in FILES:
        if path.is_file() and path.stat().st_size > 1000 and (digest is None or _sha256(path) == digest):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(f"Downloading {path.name}")
        _download(url, path, progress, digest=digest)
        if digest and _sha256(path) != digest:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Unexpected hash for {path.name}. The file was removed.")
    if not dialogue_ready():
        _install_speaker_segmentation(progress)
    stamp = MODELS / "sources.json"
    stamp.write_text(json.dumps({
        "silero": "v6.3 MIT https://github.com/snakers4/silero-vad",
        "tagger": "SmilingWolf/wd-eva02-large-tagger-v3 Apache-2.0",
        "speaker_segmentation": {
            "model": "pyannote/segmentation-3.0", "license": "MIT (CNRS 2022)",
            "source": SPEAKER_ARCHIVE_URL, "sha256": SPEAKER_SEGMENTATION_SHA256,
        },
    }, indent=2), encoding="utf-8")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _IncompleteDownload(RuntimeError):
    pass


def _read_download(response, output, name, progress, max_bytes=None):
    total = int(response.headers.get("Content-Length") or 0)
    if max_bytes is not None and total > max_bytes:
        raise RuntimeError(f"{name} exceeds the download size limit.")
    read = 0
    while True:
        chunk = response.read(1 << 20)
        if not chunk:
            break
        read += len(chunk)
        if max_bytes is not None and read > max_bytes:
            raise RuntimeError(f"{name} exceeds the download size limit.")
        output.write(chunk)
        if progress and total:
            progress(f"{name} {min(100, round(100 * read / total))} %")
    if total and read != total:
        raise _IncompleteDownload(f"Incomplete download for {name}: {read}/{total} bytes.")
    content_range = response.headers.get("Content-Range")
    if content_range:
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
        if not match or tuple(map(int, match.groups())) != (0, read - 1, read):
            raise _IncompleteDownload(f"Only part of {name} was received.")


def _download_ranges(url, output, name, progress, max_bytes):
    """Bounded archive fallback for proxies that truncate long responses."""
    offset, total = 0, None
    while total is None or offset < total:
        expected_end = offset + _RANGE_BYTES - 1
        if total is not None:
            expected_end = min(expected_end, total - 1)
        request = urllib.request.Request(url, headers={"User-Agent": "vispa-mp",
                                                       "Range": f"bytes={offset}-{expected_end}"})
        last_error = None
        for _attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    content_range = response.headers.get("Content-Range")
                    if not content_range and offset == 0:
                        _read_download(response, output, name, progress, max_bytes)
                        return
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range or "")
                    if not match:
                        raise _IncompleteDownload(f"The server did not return the requested part of {name}.")
                    begin, end, received_total = map(int, match.groups())
                    if (begin != offset or end < begin or end != min(expected_end, received_total - 1)
                            or received_total > max_bytes or total is not None and received_total != total):
                        raise RuntimeError(f"Invalid download range for {name}.")
                    data = response.read(end - begin + 2)
                    if len(data) != end - begin + 1:
                        raise _IncompleteDownload(f"Incomplete download range for {name}.")
                    total = received_total
                output.write(data)
                offset += len(data)
                if progress:
                    progress(f"{name} {min(100, round(100 * offset / total))} %")
                break
            except InterruptedError:
                raise
            except (OSError, http.client.IncompleteRead, _IncompleteDownload) as error:
                last_error = error
                # The full-response fallback may have written a partial prefix.
                output.seek(offset)
                output.truncate()
        else:
            raise RuntimeError(f"The download of {name} could not be completed.") from last_error


def _download(url, path, progress, *, max_bytes=None, digest=None):
    """Publish only complete, optionally hash-checked files; retain old copies."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    temporary = Path(temporary_name)
    import os
    os.close(descriptor)
    try:
        last_error = None
        for _attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "vispa-mp"})
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                    _read_download(response, output, path.name, progress, max_bytes)
                break
            except InterruptedError:
                raise
            except (OSError, http.client.IncompleteRead, _IncompleteDownload) as error:
                last_error = error
                if max_bytes is not None:
                    with temporary.open("wb") as output:
                        _download_ranges(url, output, path.name, progress, max_bytes)
                    break
        else:
            raise RuntimeError(f"The download of {path.name} could not be completed.") from last_error
        if digest is not None and _sha256(temporary) != digest:
            raise RuntimeError(f"Unexpected hash for {path.name}; the previous file was kept.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _install_speaker_segmentation(progress):
    MODELS.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("Downloading dialogue speaker segmentation")
    with tempfile.TemporaryDirectory(prefix=".dialogue-download-", dir=MODELS) as work:
        work = Path(work)
        archive = work / "segmentation.tar.bz2"
        _download(SPEAKER_ARCHIVE_URL, archive, progress, max_bytes=_MAX_SPEAKER_BYTES,
                  digest=SPEAKER_ARCHIVE_SHA256)
        selected = {}
        expanded_bytes = 0
        try:
            with tarfile.open(archive, "r:bz2") as source:
                for count, member in enumerate(source, 1):
                    path = PurePosixPath(member.name)
                    if (count > 128 or path.is_absolute() or "\\" in member.name
                            or any(part in (".", "..") or ":" in part for part in path.parts)
                            or not path.parts or path.parts[0] != _SPEAKER_ARCHIVE_ROOT
                            or not (member.isdir() or member.isfile())):
                        raise RuntimeError("The dialogue model archive contains an unsafe entry.")
                    if member.isfile():
                        expanded_bytes += member.size
                        if member.size < 0 or expanded_bytes > _MAX_SPEAKER_BYTES:
                            raise RuntimeError("The dialogue model archive exceeds the extracted size limit.")
                    if member.isdir() or len(path.parts) != 2 or path.name not in ("model.onnx", "LICENSE", "README.md"):
                        continue
                    limit = _MAX_SPEAKER_BYTES if path.name == "model.onnx" else 256 * 1024
                    if path.name in selected or member.size <= 0 or member.size > limit:
                        raise RuntimeError("The dialogue model archive has invalid files or sizes.")
                    stream = source.extractfile(member)
                    if stream is None:
                        raise RuntimeError("The dialogue model archive is incomplete.")
                    with stream:
                        data = stream.read(member.size + 1)
                    if len(data) != member.size:
                        raise RuntimeError("The dialogue model archive is incomplete.")
                    selected[path.name] = data
            if not {"model.onnx", "LICENSE"} <= selected.keys():
                raise RuntimeError("The dialogue model archive is missing its model or license.")
            if hashlib.sha256(selected["model.onnx"]).hexdigest() != SPEAKER_SEGMENTATION_SHA256:
                raise RuntimeError("The dialogue model has an unexpected hash; the previous file was kept.")
        except (tarfile.TarError, OSError, EOFError) as error:
            raise RuntimeError("The dialogue model archive could not be read completely.") from error
        SPEAKER_SEGMENTATION.parent.mkdir(parents=True, exist_ok=True)
        for name in ("LICENSE", "README.md", "model.onnx"):
            if name in selected:
                temporary = work / name
                temporary.write_bytes(selected[name])
                temporary.replace(SPEAKER_SEGMENTATION.parent / name)
