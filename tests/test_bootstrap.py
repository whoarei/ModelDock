import json
import os
import subprocess
import sys
from pathlib import Path

from modeldock import store


def test_parallel_first_requests_initialize_one_complete_plugin_release(tmp_path, monkeypatch):
    directory = tmp_path / "并发首次启动"
    monkeypatch.setenv("MODELDOCK_DATA_DIR", str(directory))
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    code = "import sys,json;sys.stdin.readline();from modeldock.cli import api;v=api('state',{});print(json.dumps([p['id'] for p in v['plugins']]))"
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(6)
    ]
    try:
        for child in children:
            child.stdin.write(b"go\n")
            child.stdin.flush()
        for child in children:
            output, error = child.communicate(timeout=60)
            assert child.returncode == 0, error.decode(errors="replace")
            assert set(json.loads(output)) == {"efficientnet", "timm", "yolo"}
        for plugin in store.all_items("plugin"):
            release = Path(plugin["path"])
            assert list(release.rglob("manifest.json")) == [release / "manifest.json"]
            assert len(list(release.parent.iterdir())) == 1
        with store.connect() as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
