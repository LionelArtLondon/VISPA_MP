"""Optional dialogue models download completely and never extract executable code."""

import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

import pytest

from vispa_mp import models_setup as setup


class Response(io.BytesIO):
    def __init__(self, data, **headers):
        super().__init__(data)
        self.headers = headers


def configure(tmp_path, monkeypatch, model=b"onnx" * 500):
    monkeypatch.setattr(setup, "MODELS", tmp_path)
    monkeypatch.setattr(setup, "SPEAKER_SEGMENTATION", tmp_path / "pyannote-segmentation-3.0" / "model.onnx")
    monkeypatch.setattr(setup, "SPEAKER_SEGMENTATION_SHA256", hashlib.sha256(model).hexdigest())
    return model


def archive(entries):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:bz2") as output:
        for name, content in entries:
            entry = tarfile.TarInfo(name)
            if isinstance(content, str):
                entry.type = tarfile.SYMTYPE
                entry.linkname = content
                output.addfile(entry)
            else:
                entry.size = len(content)
                output.addfile(entry, io.BytesIO(content))
    return data.getvalue()


def install_archive(payload, monkeypatch):
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(setup, "SPEAKER_ARCHIVE_SHA256", digest)
    calls = []

    def download(url, path, progress, **kwargs):
        calls.append((url, kwargs))
        assert kwargs["digest"] == digest
        Path(path).write_bytes(payload)

    monkeypatch.setattr(setup, "_download", download)
    return calls


def model_entries(model):
    prefix = setup._SPEAKER_ARCHIVE_ROOT
    return [(f"{prefix}/model.onnx", model), (f"{prefix}/LICENSE", b"MIT CNRS 2022"),
            (f"{prefix}/README.md", b"Official ONNX export")]


def test_missing_dialogue_model_does_not_disable_the_existing_visual_speech_analysis(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    core = [tmp_path / "silero.onnx", tmp_path / "tagger.onnx", tmp_path / "tags.csv"]
    for path, size in zip(core, (1_000_001, 2000, 2000)):
        path.write_bytes(b"x" * size)
    monkeypatch.setattr(setup, "SILERO", core[0])
    monkeypatch.setattr(setup, "WD_ONNX", core[1])
    monkeypatch.setattr(setup, "WD_LABELS", core[2])
    monkeypatch.setattr(setup, "FILES", tuple(("unused", path, None) for path in core))
    assert setup.ready()
    assert not setup.dialogue_ready()
    assert setup.missing() == ["pyannote-segmentation-3.0/model.onnx"]


def test_dialogue_readiness_checks_the_pinned_model_content(tmp_path, monkeypatch):
    model = configure(tmp_path, monkeypatch)
    setup.SPEAKER_SEGMENTATION.parent.mkdir()
    setup.SPEAKER_SEGMENTATION.write_bytes(model)
    assert setup.dialogue_ready()
    setup.SPEAKER_SEGMENTATION.write_bytes(b"corrupt" * 300)
    assert not setup.dialogue_ready()


def test_ensure_installs_only_whitelisted_model_docs_and_records_license(tmp_path, monkeypatch):
    model = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(setup, "FILES", ())
    payload = archive(model_entries(model) + [(f"{setup._SPEAKER_ARCHIVE_ROOT}/do-not-run.py", b"raise RuntimeError()"),
                                             (f"{setup._SPEAKER_ARCHIVE_ROOT}/model.int8.onnx", b"unused")])
    calls = install_archive(payload, monkeypatch)
    setup.ensure()
    assert setup.dialogue_ready()
    assert {path.name for path in setup.SPEAKER_SEGMENTATION.parent.iterdir()} == {"model.onnx", "LICENSE", "README.md"}
    assert setup.SPEAKER_SEGMENTATION.with_name("LICENSE").read_bytes() == b"MIT CNRS 2022"
    stamp = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
    assert stamp["speaker_segmentation"]["license"] == "MIT (CNRS 2022)"
    assert stamp["speaker_segmentation"]["sha256"] == hashlib.sha256(model).hexdigest()
    setup.ensure()
    assert len(calls) == 1
    assert not list(tmp_path.glob(".dialogue-download-*"))


@pytest.mark.parametrize("bad", ["../model.onnx", "/outside/model.onnx",
                               "sherpa-onnx-pyannote-segmentation-3-0/../../outside",
                               "sherpa-onnx-pyannote-segmentation-3-0\\outside",
                               "C:/outside", "other-prefix/model.onnx"])
def test_model_archive_rejects_unsafe_paths_without_changing_an_old_model(tmp_path, monkeypatch, bad):
    model = configure(tmp_path, monkeypatch)
    setup.SPEAKER_SEGMENTATION.parent.mkdir()
    setup.SPEAKER_SEGMENTATION.write_bytes(b"previous model")
    install_archive(archive(model_entries(model) + [(bad, b"bad")]), monkeypatch)
    with pytest.raises(RuntimeError, match="unsafe entry"):
        setup._install_speaker_segmentation(None)
    assert setup.SPEAKER_SEGMENTATION.read_bytes() == b"previous model"
    assert not list(tmp_path.glob(".dialogue-download-*"))


def test_model_archive_rejects_symlinks(tmp_path, monkeypatch):
    model = configure(tmp_path, monkeypatch)
    entries = model_entries(model) + [(f"{setup._SPEAKER_ARCHIVE_ROOT}/escape", "../../outside")]
    install_archive(archive(entries), monkeypatch)
    with pytest.raises(RuntimeError, match="unsafe entry"):
        setup._install_speaker_segmentation(None)
    assert not setup.SPEAKER_SEGMENTATION.exists()


def test_unselected_archive_members_also_obey_the_expanded_size_limit(tmp_path, monkeypatch):
    model = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(setup, "_MAX_SPEAKER_BYTES", 4000)
    entries = model_entries(model) + [(f"{setup._SPEAKER_ARCHIVE_ROOT}/ignored.py", b"x" * 4000)]
    install_archive(archive(entries), monkeypatch)
    with pytest.raises(RuntimeError, match="extracted size limit"):
        setup._install_speaker_segmentation(None)
    assert not setup.SPEAKER_SEGMENTATION.exists()


@pytest.mark.parametrize("case", ["oversized", "duplicate", "missing_license", "wrong_hash", "corrupt"])
def test_incomplete_or_unexpected_archives_are_rejected_before_publish(tmp_path, monkeypatch, case):
    model = configure(tmp_path, monkeypatch)
    entries = model_entries(model)
    if case == "oversized":
        monkeypatch.setattr(setup, "_MAX_SPEAKER_BYTES", 1000)
    elif case == "duplicate":
        entries.append(entries[0])
    elif case == "missing_license":
        entries = [entry for entry in entries if not entry[0].endswith("LICENSE")]
    elif case == "wrong_hash":
        entries[0] = entries[0][0], b"wrong" * 400
    payload = b"bad archive" if case == "corrupt" else archive(entries)
    install_archive(payload, monkeypatch)
    with pytest.raises(RuntimeError):
        setup._install_speaker_segmentation(None)
    assert not setup.SPEAKER_SEGMENTATION.exists()
    assert not list(tmp_path.glob(".dialogue-download-*"))


def test_truncated_download_retries_but_keeps_the_previous_file(tmp_path, monkeypatch):
    target = tmp_path / "model.onnx"
    target.write_bytes(b"previous")
    calls = []

    def open_url(*args, **kwargs):
        calls.append(True)
        return Response(b"short", **{"Content-Length": "100"})

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_url)
    with pytest.raises(RuntimeError, match="could not be completed"):
        setup._download("https://example.test/model", target, None)
    assert target.read_bytes() == b"previous"
    assert len(calls) == 3
    assert {path.name for path in tmp_path.iterdir()} == {"model.onnx"}


def test_optional_archive_download_recovers_truncation_with_verified_ranges(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 9000
    calls = []
    second_range_attempts = 0

    def open_url(request, **kwargs):
        nonlocal second_range_attempts
        requested = request.get_header("Range")
        calls.append(requested)
        if requested is None:
            return Response(payload[:100], **{"Content-Length": str(len(payload))})
        first, last = map(int, re.fullmatch(r"bytes=(\d+)-(\d+)", requested).groups())
        last = min(last, len(payload) - 1)
        data = payload[first:last + 1]
        if first == setup._RANGE_BYTES and second_range_attempts == 0:
            data = data[:100]
            second_range_attempts += 1
        return Response(data, **{"Content-Length": str(last - first + 1),
                                 "Content-Range": f"bytes {first}-{last}/{len(payload)}"})

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_url)
    target = tmp_path / "segmentation.tar.bz2"
    setup._download("https://example.test/model", target, None, max_bytes=20 * 1024 * 1024,
                    digest=hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    assert calls[0] is None and len(calls) == 5
    assert len(list(tmp_path.iterdir())) == 1


def test_range_response_cannot_inject_the_wrong_part_of_an_archive(tmp_path, monkeypatch):
    target = tmp_path / "archive"
    target.write_bytes(b"previous")

    def open_url(request, **kwargs):
        if request.get_header("Range") is None:
            return Response(b"short", **{"Content-Length": "100"})
        return Response(b"12345", **{"Content-Range": "bytes 1-5/100", "Content-Length": "5"})

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_url)
    with pytest.raises(RuntimeError, match="Invalid download range"):
        setup._download("https://example.test/archive", target, None, max_bytes=1000)
    assert target.read_bytes() == b"previous"


@pytest.mark.parametrize("headers", [{"Content-Length": "1000"}, {}])
def test_archive_download_size_limit_also_applies_when_length_is_unknown(tmp_path, monkeypatch, headers):
    monkeypatch.setattr(setup.urllib.request, "urlopen", lambda *args, **kwargs: Response(b"a" * 1000, **headers))
    with pytest.raises(RuntimeError, match="size limit"):
        setup._download("https://example.test/archive", tmp_path / "archive", None, max_bytes=100)
    assert not list(tmp_path.iterdir())


def test_hash_mismatch_does_not_replace_a_previous_download(tmp_path, monkeypatch):
    target = tmp_path / "model"
    target.write_bytes(b"previous")
    monkeypatch.setattr(setup.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(b"new data", **{"Content-Length": "8"}))
    with pytest.raises(RuntimeError, match="Unexpected hash"):
        setup._download("https://example.test/model", target, None, digest=hashlib.sha256(b"wanted").hexdigest())
    assert target.read_bytes() == b"previous"
    assert len(list(tmp_path.iterdir())) == 1


def test_interruption_propagates_without_retry_or_partial_files(tmp_path, monkeypatch):
    calls = []

    def open_url(*args, **kwargs):
        calls.append(True)
        return Response(b"data", **{"Content-Length": "4"})

    def stopped(_message):
        raise InterruptedError("stopped")

    monkeypatch.setattr(setup.urllib.request, "urlopen", open_url)
    with pytest.raises(InterruptedError, match="stopped"):
        setup._download("https://example.test/model", tmp_path / "model", stopped)
    assert len(calls) == 1 and not list(tmp_path.iterdir())
