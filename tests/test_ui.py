from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionSlider, QToolButton

from vispa_mp.ui import MainWindow


def _frame(number, **overrides):
    base = {
        "frame": number, "sharpness": 100, "neighbor": 0.2, "signature": [float(number)] * 4,
        "open_mouth": 0.05, "closed_mouth": 0.8, "motion_blur": 0.0, "from_behind": 0.0,
        "face": 0.9, "expression": 0.2, "group": 0.05, "solo": 0.8, "image": "",
    }
    base.update(overrides)
    return base


def action_analysis():
    def frame(number):
        signature = {2: [0, 0, 0, 0], 12: [90, 90, 90, 90], 22: [0, 90, 0, 90]}[number]
        return _frame(number, signature=signature, face=0.9, expression=0.2, group=0, solo=0.2, closed_mouth=0.2)
    return {
        "fps": 24,
        "timebase": {"fps": 24, "start_frame": 0, "start_timecode": "01:00:00:00", "drop": False},
        "shots": [{
            "start": 0, "end": 24, "opening": False, "cut_grey": 0, "cut_colour": 0,
            "motion": 30, "frames": [frame(2), frame(12), frame(22)],
        }],
        "utterances": [],
        "manual_frames": [],
        "warnings": [],
    }


def three_page_analysis():
    shots = []
    for index, start in enumerate((0, 200, 400)):
        shots.append({
            "start": start, "end": start + 180, "opening": index == 0,
            "cut_grey": 0 if index == 0 else 80, "cut_colour": 0, "motion": 1,
            "frames": [_frame(start + 40), _frame(start + 100)],
        })
    return {
        "fps": 24,
        "timebase": {"fps": 24, "start_frame": 0, "start_timecode": "01:00:00:00", "drop": False},
        "shots": shots,
        "utterances": [],
        "manual_frames": [190],
        "warnings": [],
    }


def test_a_threshold_changes_the_list_without_a_new_analysis(qapp):
    window = MainWindow(client=None)
    window.show_analysis(action_analysis())
    assert sum(item["color"] == "Cyan" for item in window.proposals) == 2
    window.set_setting("action_extras", 0)
    assert [item["color"] for item in window.proposals] == ["Blue"]
    assert window.last_seek == "01:00:00:22"
    payload = window.apply_payload()
    assert payload["start"] is None
    assert payload["proposals"][0] == {"frame": 22, "color": "Blue"}
    assert window.page_target.text().startswith("Target: 1 page")


def test_the_page_name_does_not_open_its_markers(qapp):
    window = MainWindow(client=None)
    window.set_setting("episode_minutes", 0)  # three tiny pages, taken as they are
    window.show_analysis(three_page_analysis())
    assert [window.findChild(QPushButton, f"page-name-{page['id']}").text() for page in window.pages] == [
        "Page 1", "Page 2", "Page 3",
    ]
    page_id = window.pages[0]["id"]
    assert page_id not in window.open_pages
    assert len(window._rows[page_id]["row"].findChildren(QToolButton)) == 1
    window.findChild(QPushButton, f"page-name-{page_id}").click()
    assert page_id not in window.open_pages
    assert window.playhead_frame == window.pages[0]["items"][0]["proposal"]["frame"]
    window.findChild(QToolButton, f"page-arrow-{page_id}").click()
    assert page_id in window.open_pages
    window.findChild(QToolButton, f"page-arrow-{page_id}").click()
    assert page_id not in window.open_pages


def test_changing_page_moves_only_the_playhead(qapp):
    window = MainWindow(client=None)
    window.show()
    qapp.processEvents()
    window.set_setting("episode_minutes", 0)  # three tiny pages, taken as they are
    window.show_analysis(three_page_analysis())
    first = window.pages[0]["id"]
    window.findChild(QToolButton, f"page-arrow-{first}").click()
    opened = set(window.open_pages)
    playhead = window.playhead_frame
    window.pages_panel.setFocus()
    QTest.keyClick(window.pages_panel, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert window.open_pages == opened
    assert window.selected_page_id == window.pages[1]["id"]
    assert window.playhead_frame != playhead
    assert window.playhead_frame == window.pages[1]["items"][0]["proposal"]["frame"]
    assert window.last_seek == window.timecode_of(window.playhead_frame)
    kept_open = set(window.open_pages)
    kept_head = window.playhead_frame
    window.board_button.click()
    assert window.mode == "board"
    assert window.open_pages == kept_open
    assert window.playhead_frame == kept_head
    assert window.stack.currentIndex() == 1
    assert window.apply_button.text() == "Place markers"
    assert window.read_button.text() == "Read timeline"
    assert window.analyze_button.text() == "Analyze"
    window.strip_button.click()
    assert window.mode == "strip"
    assert window.open_pages == kept_open
    assert window.playhead_frame == kept_head


def test_a_swatch_recolors_the_proposal_and_leaves_the_manual_marker(qapp):
    window = MainWindow(client=None)
    window.set_setting("episode_minutes", 0)  # three tiny pages, taken as they are
    window.show_analysis(three_page_analysis())
    proposal = next(item for item in window.proposals if item["color"] == "Green")
    window.findChild(QPushButton, f"marker-{proposal['frame']}").click()
    window.color_buttons["Cyan"].click()
    updated = window._proposal(proposal["frame"])
    assert updated["color"] == "Cyan"
    assert updated["name"] == "Extra"
    assert 190 not in {item["frame"] for item in window.proposals}
    manual = window.findChild(QPushButton, "manual-190")
    assert manual is not None
    assert manual.text() == "manual · kept"
    colors = [(item["frame"], item["color"]) for item in window.proposals]
    manual.click()
    window.color_buttons["Green"].click()
    assert [(item["frame"], item["color"]) for item in window.proposals] == colors
    assert window.color_buttons["Green"].isEnabled() is False


def test_recalculate_does_not_call_analyze(qapp, monkeypatch):
    called = []
    monkeypatch.setattr("vispa_mp.ui.analyze", lambda *args, **kwargs: called.append(True))
    window = MainWindow(client=None)
    window.show_analysis(action_analysis())
    before = [(item["frame"], item["color"]) for item in window.proposals]
    window.recalculate_button.click()
    assert called == []
    assert [(item["frame"], item["color"]) for item in window.proposals] == before


def test_titlebar_is_the_vispa_caption(qapp):
    import sys
    window = MainWindow(client=None)
    window.resize(1280, 800)
    window.show()
    qapp.processEvents()
    bar = window.titlebar
    assert bar.height() == 30
    assert bar.caption == "VISPA MP"
    assert bar.brand.text() == "VISPA MP"
    assert not bar.draggable(bar.close_button.mapTo(bar, bar.close_button.rect().center()))
    assert bar.draggable(QPoint(80, 15))
    if sys.platform == "win32":
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    window.close()


def test_installed_scrollbar_has_no_arrow_buttons(qapp):
    from PySide6.QtWidgets import QScrollBar
    from vispa_mp.scrollbar_style import install_scrollbar_style
    install_scrollbar_style(qapp)
    bar = QScrollBar(Qt.Orientation.Vertical)
    bar.resize(16, 240)
    bar.setRange(0, 100)
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    style = bar.style()
    for part in (QStyle.SubControl.SC_ScrollBarAddLine, QStyle.SubControl.SC_ScrollBarSubLine):
        rect = style.subControlRect(QStyle.ComplexControl.CC_ScrollBar, option, part, bar)
        assert rect.isNull() or rect.isEmpty()
    assert style.pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, option, bar) == 16


def test_warnings_of_one_kind_are_told_once(qapp):
    from vispa_mp.ui import fold_warnings
    lines = ["No track is named CUE_SOURCE."] + [
        f"Page at frame {n}: 1 Core images, 1 in all, below the minimum." for n in (10, 20, 30)
    ] + ["Line at frame 5 has no examined image."]
    assert fold_warnings(lines) == [
        "No track is named CUE_SOURCE.",
        "3 pages have fewer images than the minimum (Settings › Pages › Images per page).",
        "Line at frame 5 has no examined image.",
    ]


def test_a_page_shows_all_its_images_and_the_board_draws_them(qapp):
    window = MainWindow(client=None)
    window.set_setting("episode_minutes", 0)
    analysis = three_page_analysis()
    analysis["shots"][0]["frames"].append(_frame(150, motion_blur=0.0))
    window.show_analysis(analysis)
    window.resize(1400, 800)
    window.show()
    page = window.pages[0]
    window._select_page(page["id"])
    qapp.processEvents()
    cards = [window.thumb_layout.itemAt(i).widget() for i in range(window.thumb_layout.count())]
    cards = [card for card in cards if card is not None]
    assert len(cards) == len(page["items"])
    assert all(card.isVisible() and card.width() > 100 for card in cards)
    # The board used EXTRA without importing it, and stopped drawing on every page.
    for item in page["items"]:
        if not item["manual"]:
            item["proposal"]["color"] = "Cyan"
    window.board.set_page(page["items"], (148, 210), None, False)
    window.board.resize(400, 600)
    window.board.grab()
    assert window.board._hits


def test_page_cards_sit_side_by_side_without_overlapping(qapp):
    window = MainWindow(client=None)
    window.set_setting("episode_minutes", 0)
    analysis = three_page_analysis()
    for shot in analysis["shots"]:
        shot["frames"] = [_frame(shot["start"] + offset) for offset in range(10, 170, 16)]
    window.show_analysis(analysis)
    window.resize(900, 700)
    window.show()
    window._select_page(window.pages[0]["id"])
    qapp.processEvents()
    cards = [window.thumb_layout.itemAt(i).widget() for i in range(window.thumb_layout.count())]
    cards = [card for card in cards if card is not None]
    assert len(cards) > 1
    for index, card in enumerate(cards):
        for other in cards[index + 1:]:
            assert not card.geometry().intersects(other.geometry())
    # All of them in view at once: the page wraps into rows instead of scrolling sideways.
    assert all(card.geometry().right() <= window.thumb_area.viewport().width() for card in cards)
