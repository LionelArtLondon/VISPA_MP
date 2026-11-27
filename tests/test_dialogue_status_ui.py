"""The automatic dialogue feature has a visible status, not another knob."""

from PySide6.QtCore import QCoreApplication, QEvent

from tests.test_ui import action_analysis
from vispa_mp.ui import MainWindow


def test_speech_settings_show_voice_change_status_without_a_new_selection_setting(qapp):
    window = MainWindow(client=None)
    try:
        assert "automatically" in window.dialogue_status_note.text()
        assert "_dialogue_status" not in window.widgets
        analysis = action_analysis()
        analysis["speech_tracks"] = [{"start": 0, "end": 100, "probs": [0.9] * 40,
                                       "speaker_changes": [{"time": 1.0, "confidence": 0.9}],
                                       "dialogue_status": {"state": "ready", "changes": 1}}]
        window.show_analysis(analysis)
        assert "1 detected" in window.dialogue_status_note.text()
        window.analysis["speech_tracks"][0].pop("dialogue_status")
        window.recompute()
        assert "Analyze again" in window.dialogue_status_note.text()
    finally:
        window._project_dirty = False
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
