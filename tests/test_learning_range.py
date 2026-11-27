"""Explicit learning ranges keep credits out without shifting source pictures."""

from copy import deepcopy

import numpy as np
import pytest

from tests.test_learning_data import Sources, snapshot
from tests.test_learning_ui import inline, local_learning, notices, reference
from vispa_mp.learning_data import (import_timeline_reference, list_references, load_reference,
                                    reference_range, remove_reference, save_imported_reference, validate_reference)
from vispa_mp.markers import CORE
from vispa_mp.preset import DEFAULTS
from vispa_mp.ui import MainWindow


def test_only_in_out_examples_are_scored_and_reimport_replaces_original(tmp_path):
    data = snapshot(tmp_path)
    source = Sources()
    whole = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source)
    data.update(mark_in=110, mark_out=126)
    before = deepcopy(data)
    source = Sources()
    limited = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source, use_in_out=True)
    assert data == before
    assert all(110 <= frame["frame"] < 126 for frame in source.scored)
    assert {sample["frame"] for sample in limited["samples"] if sample["roles"]} == {117, 125}
    assert limited["source"]["range"] == [110, 126]
    assert limited["summary"]["ignored_outside_range"] == 1
    assert limited["id"] == whole["id"] and limited["group_id"] == whole["group_id"]
    folder = tmp_path / "references"
    save_imported_reference(whole, folder)
    save_imported_reference(limited, folder)
    assert len(list_references(folder)) == 1
    assert list_references(folder)[0] == limited


@pytest.mark.parametrize("start,end", [(None, None), (None, 130), (110, None), (True, 130),
                                       (110, 110), (130, 110), (99, 130), (110, 141)])
def test_bad_range_fails_before_video_extraction(tmp_path, start, end):
    data = snapshot(tmp_path)
    data.update(mark_in=start, mark_out=end)
    source = Sources()
    with pytest.raises(ValueError, match="[Ii]n.*Out"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source, use_in_out=True)
    assert source.filmstrip_calls == 0 and source.scored == []


def test_no_approved_marker_inside_range_has_clear_error(tmp_path):
    data = snapshot(tmp_path)
    data.update(mark_in=129, mark_out=131)
    source = Sources()
    with pytest.raises(ValueError, match="No approved.*inside"):
        import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=source, use_in_out=True)
    assert source.filmstrip_calls == 0


def test_odd_interlaced_in_keeps_exact_source_picture_and_field_frame(tmp_path):
    data = snapshot(tmp_path, start=180000, fps=50, interlaced=True)
    data.update(mark_in=180001, mark_out=180003, markers=[{"frame": 180001, "color": CORE}])
    result = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Sources(), use_in_out=True)
    chosen = next(sample for sample in result["samples"] if sample["roles"])
    assert chosen["frame"] == 180001 and chosen["source_frame"] == 50
    assert all(180001 <= sample["frame"] < 180003 for sample in result["samples"])


def test_speech_only_sees_audio_inside_the_import_range(tmp_path):
    data = snapshot(tmp_path)
    data.update(mark_in=110, mark_out=130, audio_clips=[dict(start=100, end=140, path="speech.wav", speed=1)])

    class Speech(Sources):
        def waveform(self, clip, fps):
            return np.arange(25600)

        def probabilities(self, audio):
            assert len(audio) == 12800 and audio[0] == 6400 and audio[-1] == 19199
            return [1.0] * (len(audio) // 512)

    result = import_timeline_reference(data, DEFAULTS, tmp_path / "cache", sources=Speech(), use_in_out=True)
    assert result["summary"]["markers"] == 2


def test_reference_rejects_examples_outside_its_declared_scope():
    data = reference()
    data["source"] = {"range": [12, 36]}
    with pytest.raises(ValueError, match="outside"):
        validate_reference(data)


def test_resolve_confirmation_uses_scope_and_forwards_explicit_option(qapp, local_learning, notices, monkeypatch):
    from tests.test_learning_ui import _resolve_client
    window = MainWindow(client=_resolve_client())
    client_read = window.client.read
    window.client.read = lambda: dict(client_read(), mark_in=90000, mark_out=90020)
    dialog = window._ensure_learning_dialog()
    dialog.approved.setChecked(True)
    dialog.reference_in_out.setChecked(True)
    received = []
    monkeypatch.setattr(local_learning, "import_timeline_reference", lambda *args, **kwargs: received.append(kwargs) or reference())
    inline(window, monkeypatch)
    window._import_current_learning_reference()
    qapp.processEvents()
    assert received[0]["use_in_out"] is True
    assert "In/Out only" in notices[1][0][3]


def test_remove_reference_archives_only_its_record(tmp_path):
    folder = tmp_path / "references"
    first, second = reference(), reference("chapter-b")
    save_imported_reference(first, folder)
    save_imported_reference(second, folder)
    archived = remove_reference(first["id"], folder)
    assert load_reference(archived)["id"] == first["id"]
    assert [ref["id"] for ref in list_references(folder)] == [second["id"]]


def test_remove_selected_references_does_not_touch_resolve_or_current_review(qapp, local_learning, notices):
    local_learning.save_reference(reference())
    local_learning.save_reference(reference("chapter-b"))
    window = MainWindow()
    window._refresh_learning_lists()
    dialog = window.learning_dialog
    for index in range(dialog.references.topLevelItemCount()):
        dialog.references.topLevelItem(index).setSelected(True)
    assert dialog.remove_reference.isEnabled()
    window._remove_learning_references()
    assert local_learning.list_references() == []
    assert "2 reference(s) removed" in dialog.operation.text()
    assert window.analysis is None and window._learning_profile is None
    assert notices[1] and "Resolve projects" in notices[1][0][3]
