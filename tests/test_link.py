import threading
import time

import pytest

from tests.test_bridge import IDENTITY, Timeline
from vispa_mp.resolve_host import handle_once
from vispa_mp.resolve_link import FREE_HINT, Link, MailboxClient, install_resolve_script


class _Resolve:
    def __init__(self, timeline, project_id="project-1"):
        self.timeline = timeline
        self.project_id = project_id

    def GetUniqueId(self):
        return self.project_id

    def GetProjectManager(self):
        return self

    def GetCurrentProject(self):
        return self

    def GetCurrentTimeline(self):
        return self.timeline


def test_a_timeline_read_goes_through_the_mailbox(tmp_path):
    link = Link(tmp_path)
    link.write_status(True, "Episode")
    resolve = _Resolve(Timeline())
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            link.write_status(True, "Episode")
            handle_once(resolve, link)
            time.sleep(0.02)

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    try:
        client = MailboxClient(link, timeout=2)
        assert client.ping() == {"ok": True}
        snapshot = client.read()
    finally:
        stop.set()
        thread.join(timeout=1)
    assert snapshot["timeline_name"] == "Episode"
    assert snapshot["timeline_identity"] == IDENTITY
    assert snapshot["video_clips"][0]["path"] == "episode.mp4"
    assert snapshot["markers"][0]["automatic"] is False


def test_a_request_waits_until_the_script_is_run(tmp_path):
    link = Link(tmp_path)
    client = MailboxClient(link, timeout=0.3)
    try:
        client.ping()
    except RuntimeError as error:
        assert "VISPA_MP" in str(error)
        assert FREE_HINT.strip() in str(error)
    else:
        raise AssertionError("ping should wait for the script click")


def test_the_menu_script_is_lua_and_points_at_the_mailbox(tmp_path):
    from vispa_mp.resolve_link import mailbox_dir
    (tmp_path / "VISPA_MP.py").write_text("stale", encoding="utf-8")
    target = install_resolve_script(tmp_path)
    text = target.read_text(encoding="utf-8")
    assert target.name == "VISPA_MP.lua"
    assert "__MAILBOX__" not in text
    assert str(mailbox_dir()) in text
    assert "listening" in text
    assert "UIManager" not in text
    assert "UIDispatcher" not in text
    assert not (tmp_path / "VISPA_MP.py").exists()


@pytest.mark.parametrize("change", ["timeline", "project"])
def test_python_mailbox_refuses_a_target_changed_since_read(tmp_path, change):
    link = Link(tmp_path)
    original = Timeline()
    resolve = _Resolve(original)
    link.write_request({"id": "1", "cmd": "read"})
    assert handle_once(resolve, link) == (True, False)
    identity = link.read_response()["result"]["timeline_identity"]
    if change == "timeline":
        resolve.timeline = Timeline("timeline-2")
    else:
        resolve.project_id = "project-2"
    link.write_request({"id": "2", "cmd": "apply_checked", "expected_timeline": identity,
                        "proposals": [{"frame": 200, "color": "Green"}]})
    assert handle_once(resolve, link) == (True, False)
    answer = link.read_response()
    assert answer["ok"] is False and "not the analyzed timeline" in answer["error"]
    assert original.added == original.deleted == resolve.timeline.added == resolve.timeline.deleted == []


def test_clients_use_the_checked_command_with_the_original_identity(monkeypatch):
    from vispa_mp.client import ResolveClient
    requests = []
    def request(self, cmd, **payload):
        requests.append((cmd, payload))
        return {"placed": [10]}
    monkeypatch.setattr(ResolveClient, "request", request)
    monkeypatch.setattr(MailboxClient, "request", request)
    for client_type in (ResolveClient, MailboxClient):
        client = client_type.__new__(client_type)
        assert client.apply([{"frame": 10, "color": "Green"}], 0, 20, expected_timeline=IDENTITY) == {"placed": [10]}
    assert len(requests) == 2
    assert all(cmd == "apply_checked" and payload["expected_timeline"] == IDENTITY
               for cmd, payload in requests)
