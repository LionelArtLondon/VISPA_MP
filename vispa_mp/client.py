"""The UI talks to Resolve through a small JSON process."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from vispa_mp.resolve_link import FREE_HINT, MailboxClient, free_script_installed, link_running


def _python_candidates():
    found = []
    override = os.environ.get("VISPA_MP_RESOLVE_PYTHON")
    if override:
        found.append(override)
    found.append(sys.executable)
    try:
        listed = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        listed = None
    if listed and listed.returncode == 0:
        for line in listed.stdout.splitlines():
            parts = line.strip().split()
            if parts and Path(parts[-1]).is_file() and parts[-1] not in found:
                found.append(parts[-1])
    return found


class ResolveClient:
    def __init__(self, python=None):
        self.lock = threading.Lock()
        self.errors = []
        self.python = python or os.environ.get("VISPA_MP_RESOLVE_PYTHON") or sys.executable
        self.proc = self._open(self.python)

    def _open(self, python):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        process = subprocess.Popen(
            [python, "-u", "-m", "vispa_mp.resolve_bridge"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env=env, cwd=root, creationflags=flags,
        )
        threading.Thread(target=self._drain, args=(process,), daemon=True).start()
        return process

    def _drain(self, process):
        if process.stderr is None:
            return
        for line in process.stderr:
            self.errors.append(line.rstrip())

    def request(self, cmd, **payload):
        with self.lock:
            if self.proc.poll() is not None:
                raise RuntimeError(self._failure("The Resolve bridge stopped."))
            message = {"id": 1, "cmd": cmd, **payload}
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(self._failure("Resolve did not answer."))
            answer = json.loads(line)
            if not answer.get("ok"):
                raise RuntimeError(answer.get("error") or "Resolve refused the command.")
            return answer.get("result")

    def _failure(self, fallback):
        detail = " ".join(self.errors[-6:])
        return f"{fallback} {detail}".strip()

    def ping(self):
        return self.request("ping")

    def read(self):
        return self.request("read")

    def seek(self, timecode):
        return self.request("seek", timecode=timecode)

    def apply(self, proposals, start=None, end=None, expected_timeline=None):
        # A distinct command makes old scripts refuse instead of ignoring the guard.
        return self.request("apply_checked", proposals=proposals, start=start, end=end,
                            expected_timeline=expected_timeline)

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()


def open_client():
    """Use the menu script when it is installed. Studio can still answer directly."""
    if free_script_installed() or link_running():
        return MailboxClient()
    cache = Path(__file__).resolve().parents[1] / "cache" / "resolve_python.txt"
    ordered = []
    if cache.is_file():
        ordered.append(cache.read_text(encoding="utf-8").strip())
    ordered.extend(_python_candidates())
    seen = set()
    last_error = None
    for python in ordered:
        if not python or python in seen or not Path(python).is_file():
            continue
        seen.add(python)
        client = ResolveClient(python)
        try:
            client.ping()
        except Exception as error:
            last_error = error
            client.close()
            continue
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(python, encoding="utf-8")
        return client
    message = str(last_error) if last_error else "No Python could reach Resolve."
    if FREE_HINT.strip() not in message:
        message += FREE_HINT
    raise RuntimeError(message)
