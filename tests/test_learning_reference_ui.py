"""Reference inspection reads bounded local stills, without touching the working edit."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from tests.test_learning_ui import reference
from vispa_mp.learning_data import validate_reference
from vispa_mp.learning_reference_ui import (
    PAGE_SIZE, PREVIEW_SIZE, THUMBNAIL_SIZE, ReferencePreviewDialog, _read_still,
)


def image(path, colour, size=QSize(320, 180)):
    bitmap = QImage(size, QImage.Format.Format_RGB32)
    bitmap.fill(QColor(colour))
    assert bitmap.save(str(path), "PNG")
    return str(path)


def preview_reference(tmp_path, count=8):
    result = reference()
    result["source"] = {"project_name": "Comic chapter", "timeline_name": "Marked timeline",
                        "media": [{"path": "private-video-file.mov"}]}
    result["timebase"] = {"fps": 25, "start_frame": 90_000, "start_timecode": "01:00:00:00"}
    template = result["samples"][0]
    samples = []
    for index in range(count):
        sample = deepcopy(template)
        sample.update(frame=90_000 + index * 25, source_frame=12 + index * 25,
                      roles=(["core", "page"], ["core"], ["extra"], [])[index % 4],
                      image=image(tmp_path / f"still-{index}.png", "red" if index % 2 == 0 else "lime"))
        samples.append(sample)
    result["samples"] = samples
    marked = sum(bool(sample["roles"]) for sample in samples)
    result["summary"] = {"markers": marked, "samples": count, "unlabelled": count - marked,
                         **{role: sum(role in sample["roles"] for sample in samples)
                            for role in ("page", "core", "extra")},
                         "ignored_automatic": 0, "ignored_other_colors": 0}
    return validate_reference(result)


def owner():
    widget = QWidget()
    widget.snapshot = {"timeline_name": "Working edit"}
    widget.proposals = [{"frame": 151, "color": "Cyan"}]
    widget._learning_profile = {"name": "Current preferences"}
    widget._learning_refs = ["untouched corpus"]
    return widget


def test_selecting_cached_stills_shows_exact_roles_and_frames_without_mutation(qapp, tmp_path):
    source = preview_reference(tmp_path)
    original = deepcopy(source)
    window = owner()
    working = deepcopy((window.snapshot, window.proposals, window._learning_profile, window._learning_refs))
    dialog = ReferencePreviewDialog(window, source)
    assert dialog.reference == source
    assert "Approved chapter" in dialog.heading.text()
    assert "Comic chapter" in dialog.source.text() and "Marked timeline" in dialog.source.text()
    assert dialog.preview.pixmap().toImage().pixelColor(0, 0) == QColor("red")
    assert dialog.cards[0].isChecked()
    QTest.mouseClick(dialog.cards[1], Qt.MouseButton.LeftButton)
    assert dialog.selected_index == 1
    assert dialog.cards[1].isChecked() and not dialog.cards[0].isChecked()
    assert dialog.preview.pixmap().toImage().pixelColor(0, 0) == QColor("lime")
    assert "Core\n01:00:01:00" in dialog.details.text()
    assert "Absolute timeline frame: 90025" in dialog.details.text()
    assert "Source frame: 37" in dialog.details.text()
    assert source == original
    assert (window.snapshot, window.proposals, window._learning_profile, window._learning_refs) == working


def test_cards_reserve_image_and_two_text_lines_under_real_window_stylesheet(qapp, tmp_path):
    from vispa_mp.ui import _theme
    window = owner()
    window.setStyleSheet(_theme())
    dialog = ReferencePreviewDialog(window, preview_reference(tmp_path))
    dialog.show()
    qapp.processEvents()
    for card in dialog.cards:
        assert card.height() >= 146
        # Both border states use 14 px total vertical border and padding.
        required = THUMBNAIL_SIZE.height() + 2 * card.fontMetrics().lineSpacing() + 8
        assert card.height() - 14 >= required
        icon = card.icon().actualSize(card.iconSize())
        assert icon.height() >= 85 and icon.width() >= 150
        assert len(card.text().splitlines()) == 2
    for offset in range(len(dialog.cards)):
        row, column, row_span, column_span = dialog.grid.getItemPosition(offset)
        assert (row, column, row_span, column_span) == (offset // 3, offset % 3, 1, 1)
    assert dialog.preview.width() >= 450
    dialog.next_page.click()
    dialog.filter.setCurrentIndex(dialog.filter.findData("extra"))
    qapp.processEvents()
    assert all(card.height() >= 146 for card in dialog.cards)
    dialog.close()


@pytest.mark.parametrize("key, expected", [("marked", [0, 1, 2, 4, 5, 6]),
                                         ("core", [0, 1, 4, 5]), ("extra", [2, 6]),
                                         ("page", [0, 4]), ("unmarked", [3, 7])])
def test_role_filters_include_page_starts_as_core(qapp, tmp_path, key, expected):
    window = owner()
    dialog = ReferencePreviewDialog(window, preview_reference(tmp_path))
    dialog.filter.setCurrentIndex(dialog.filter.findData(key))
    assert dialog.filtered_indices == expected
    assert [card.sample_index for card in dialog.cards] == expected
    assert dialog.selected_index in expected
    assert all(card.preview_available for card in dialog.cards)


def test_pagination_decodes_only_visible_twenty_four_stills_and_selection(qapp, tmp_path, monkeypatch):
    import vispa_mp.learning_reference_ui as ui
    source = preview_reference(tmp_path, count=53)
    read_paths = []
    read_still = ui._read_still

    def read(path, size):
        read_paths.append(path)
        return read_still(path, size)

    monkeypatch.setattr(ui, "_read_still", read)
    window = owner()
    dialog = ReferencePreviewDialog(window, source)
    marked = [index for index, sample in enumerate(source["samples"]) if sample["roles"]]
    assert len(dialog.cards) == PAGE_SIZE
    assert len(read_paths) == PAGE_SIZE + 1
    assert set(read_paths) == {source["samples"][index]["image"] for index in marked[:PAGE_SIZE]}
    assert dialog.page_label.text() == "1–24 of 40"
    assert not dialog.previous_page.isEnabled() and dialog.next_page.isEnabled()
    read_paths.clear()
    dialog.next_page.click()
    assert dialog.page == 1 and len(dialog.cards) == 16
    assert len(read_paths) == 17
    assert set(read_paths) == {source["samples"][index]["image"] for index in marked[PAGE_SIZE:]}
    assert dialog.page_label.text() == "25–40 of 40"
    assert dialog.previous_page.isEnabled() and not dialog.next_page.isEnabled()
    dialog.filter.setCurrentIndex(dialog.filter.findData("extra"))
    assert dialog.page == 0 and len(dialog.cards) == 13
    assert not dialog.previous_page.isEnabled() and not dialog.next_page.isEnabled()
    dialog._change_page(5)
    assert dialog.page == 0


def test_empty_filter_clears_selection_and_disables_copy(qapp, tmp_path):
    window = owner()
    dialog = ReferencePreviewDialog(window, preview_reference(tmp_path, count=1))
    dialog.filter.setCurrentIndex(dialog.filter.findData("extra"))
    assert not dialog.cards and dialog.selected_index is None
    assert dialog.page_label.text() == "0 images"
    assert "No images" in dialog.preview.text()
    assert not dialog.copy_details.isEnabled()
    assert not dialog.previous_page.isEnabled() and not dialog.next_page.isEnabled()


def test_legacy_and_missing_cache_previews_explain_reimport_without_media_access(qapp, tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Inspection attempted extraction, corpus access or model training")

    monkeypatch.setattr("vispa_mp.frames.extract_stills", forbidden)
    monkeypatch.setattr("vispa_mp.client.open_client", forbidden)
    monkeypatch.setattr("vispa_mp.learning_model.train_profile", forbidden)
    monkeypatch.setattr("vispa_mp.learning_data.list_references", forbidden)
    monkeypatch.setattr("vispa_mp.learning_data.import_timeline_reference", forbidden)
    source = preview_reference(tmp_path)
    for sample in source["samples"]:
        sample.pop("image")
    source["samples"][1]["image"] = str(tmp_path / "missing.png")
    source.pop("timebase")
    source["samples"][0].pop("source_frame")
    window = owner()
    dialog = ReferencePreviewDialog(window, validate_reference(source))
    assert all(not card.preview_available for card in dialog.cards)
    assert dialog.preview.pixmap().isNull()
    assert "Reimport" in dialog.preview.text()
    assert "not recorded" in dialog.warning.text()
    assert "Timecode unavailable" in dialog.details.text()
    assert "Source frame: not recorded" in dialog.details.text()
    QTest.mouseClick(dialog.cards[1], Qt.MouseButton.LeftButton)
    assert "Reimport" in dialog.preview_status.text()
    assert "90025" in dialog.details.text()
    dialog.filter.setCurrentIndex(dialog.filter.findData("unmarked"))
    assert all(not card.preview_available for card in dialog.cards)


def test_decoded_pixmaps_are_bounded_and_keep_the_source_aspect_ratio(qapp, tmp_path):
    path = image(tmp_path / "large.png", "red", QSize(3200, 1800))
    for bound in (THUMBNAIL_SIZE, PREVIEW_SIZE):
        pixmap = _read_still(path, bound)
        assert not pixmap.isNull()
        assert pixmap.width() <= bound.width() and pixmap.height() <= bound.height()
        assert abs(pixmap.width() / pixmap.height() - 16 / 9) < 0.02
        assert pixmap.toImage().pixelColor(0, 0) == QColor("red")


def test_unsafe_nonlocal_paths_and_unreadable_rasters_are_placeholders(qapp, tmp_path, monkeypatch):
    import vispa_mp.learning_reference_ui as ui
    fake = tmp_path / "broken.png"
    fake.write_text("not a bitmap")
    assert _read_still(str(fake), THUMBNAIL_SIZE).isNull()

    def reader_forbidden(*_args):
        pytest.fail("A nonlocal or unsupported image path reached the decoder")

    monkeypatch.setattr(ui, "QImageReader", reader_forbidden)
    for path in ("https://example.org/still.jpg", r"\\server\share\still.jpg", "//server/still.png",
                 "relative.png", "", str(tmp_path / "vector.svg")):
        assert _read_still(path, THUMBNAIL_SIZE).isNull()


def test_interlaced_display_rate_and_drop_frame_timecodes_are_preserved(qapp, tmp_path):
    source = preview_reference(tmp_path, count=1)
    source["timebase"] = {"fps": 50, "timecode_fps": 25, "start_frame": 180_000,
                          "start_timecode": "01:00:00:00"}
    source["samples"][0]["frame"] = 180_052
    window = owner()
    dialog = ReferencePreviewDialog(window, source)
    assert "01:00:01:01" in dialog.details.text()
    assert not dialog.timecode_warning
    source["timebase"] = {"fps": 29.97, "timecode_fps": 29.97, "drop": True,
                          "start_frame": 0, "start_timecode": "00:00:00;00"}
    source["samples"][0]["frame"] = 1800
    second = ReferencePreviewDialog(window, source)
    assert "00:01:00;02" in second.details.text()


def test_legacy_high_rate_without_display_rate_does_not_invent_resolve_timecode(qapp, tmp_path):
    source = preview_reference(tmp_path, count=1)
    source["timebase"]["fps"] = 50
    window = owner()
    dialog = ReferencePreviewDialog(window, source)
    assert "display rate was not recorded" in dialog.warning.text()
    assert "Timecode unavailable" in dialog.details.text()
    assert "90000" in dialog.details.text()


@pytest.mark.parametrize("timebase", [
    ["bad"], {"fps": True, "start_frame": 0, "start_timecode": "01:00:00:00"},
    {"fps": 0, "start_frame": 0, "start_timecode": "01:00:00:00"},
    {"fps": float("nan"), "start_frame": 0, "start_timecode": "01:00:00:00"},
    {"fps": 25, "start_timecode": "01:00:00:00"},
    {"fps": 25, "start_frame": True, "start_timecode": "01:00:00:00"},
    {"fps": 25, "start_frame": "0", "start_timecode": "01:00:00:00"},
    {"fps": 25, "start_frame": 0, "start_timecode": "not timecode"},
    {"fps": 25, "start_frame": 0, "start_timecode": "01:60:00:00"},
    {"fps": 25, "start_frame": 0, "start_timecode": "01:00:00:25"},
    *({"fps": 25, "start_frame": 0, "start_timecode": "01:00:00:00", "timecode_fps": value}
      for value in (False, -25, 0, float("inf"), "25", None)),
    {"fps": 25, "start_frame": 0, "start_timecode": "01:00:00:00", "drop": "false"},
])
def test_malformed_legacy_metadata_has_clear_fallback_without_crashing(qapp, tmp_path, monkeypatch, timebase):
    import vispa_mp.learning_reference_ui as ui
    copied = []

    class Clipboard:
        def setText(self, text):
            copied.append(text)

    monkeypatch.setattr(ui.QApplication, "clipboard", lambda: Clipboard())
    source = preview_reference(tmp_path, count=1)
    source["timebase"] = timebase
    source["source"] = ["bad"]
    window = owner()
    dialog = ReferencePreviewDialog(window, source)
    assert "Project: not recorded" in dialog.source.text()
    assert "Timeline: not recorded" in dialog.source.text()
    assert "Reimport" in dialog.warning.text()
    assert "Timecode unavailable" in dialog.details.text()
    dialog.copy_details.click()
    assert len(copied) == 1 and "Timecode unavailable" in copied[0]
    assert "Project: not recorded" in copied[0]


def test_copy_example_details_only_after_explicit_click_omits_private_paths(qapp, tmp_path, monkeypatch):
    import vispa_mp.learning_reference_ui as ui
    copied = []

    class Clipboard:
        def setText(self, text):
            copied.append(text)

    monkeypatch.setattr(ui.QApplication, "clipboard", lambda: Clipboard())
    window = owner()
    dialog = ReferencePreviewDialog(window, preview_reference(tmp_path))
    assert not copied
    dialog.copy_details.click()
    assert len(copied) == 1
    assert "Reference: Approved chapter" in copied[0]
    assert "Project: Comic chapter" in copied[0] and "Timeline: Marked timeline" in copied[0]
    assert "Page start · Core" in copied[0] and "01:00:00:00" in copied[0]
    assert "Absolute timeline frame: 90000" in copied[0] and "Source frame: 12" in copied[0]
    assert "private-video-file" not in copied[0] and str(tmp_path) not in copied[0]
    assert "features" not in copied[0]
    dialog.filter.setCurrentIndex(dialog.filter.findData("extra"))
    assert len(copied) == 1
