"""Prefer installed local tools without probing slow network PATH entries."""

from vispa_mp import frames


def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(frames, "ROOT", tmp_path)
    monkeypatch.delenv("VISPA_MP_FFMPEG", raising=False)
    monkeypatch.delenv("FFMPEG", raising=False)


def test_bundled_ffmpeg_does_not_search_path(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    binary = tmp_path / "tools" / "ffmpeg" / "ffmpeg.exe"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr(frames.shutil, "which", lambda *_args: (_ for _ in ()).throw(
        AssertionError("The bundled tool must avoid PATH I/O")))
    assert frames.ffmpeg_path() == str(binary)


def test_explicit_override_wins_without_searching_path(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    binary = tmp_path / "my ffmpeg.exe"
    binary.touch()
    monkeypatch.setenv("VISPA_MP_FFMPEG", str(binary))
    monkeypatch.setattr(frames.shutil, "which", lambda *_args: (_ for _ in ()).throw(
        AssertionError("An explicit tool must avoid PATH I/O")))
    assert frames.ffmpeg_path() == str(binary)


def test_path_is_consulted_once_when_no_local_tool_is_available(tmp_path, monkeypatch):
    _isolated(tmp_path, monkeypatch)
    binary = tmp_path / "path ffmpeg.exe"
    binary.touch()
    calls = []
    monkeypatch.setattr(frames.shutil, "which", lambda name: calls.append(name) or str(binary))
    assert frames.ffmpeg_path() == str(binary)
    assert calls == ["ffmpeg"]
