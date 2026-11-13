import importlib.util
import time
from pathlib import Path

import pytest
from modeldock import store
from modeldock.cli import api

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    spec = importlib.util.spec_from_file_location(
        "create_fixtures", ROOT / "scripts/create_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create(tmp_path_factory.mktemp("model-fixtures"))


@pytest.fixture(scope="session")
def environment(tmp_path_factory):
    import os

    root = tmp_path_factory.mktemp("modeldock 数据")
    old = {key: os.environ.get(key) for key in ("MODELDOCK_DATA_DIR", "MODELDOCK_RESOURCES")}
    os.environ.update(MODELDOCK_DATA_DIR=str(root), MODELDOCK_RESOURCES=str(ROOT))
    api("state", {})
    for name in ("efficientnet", "yolo"):
        api("install_plugin", dict(plugin_id=name, profile_id="onnx-cpu"))
        wait_for(
            lambda: store.get("installation", name),
            lambda i: i["state"] != "preparing",
            timeout=240,
        )
        installation = store.get("installation", name)
        assert installation["state"] == "ready", installation
    yield root
    for task in store.jobs():
        if task["state"] not in store.TERMINAL:
            api("cancel_task", dict(task_id=task["id"]))
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def wait_for(read, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if predicate(value):
            return value
        time.sleep(0.05)
    raise AssertionError(f"Timed out, last state: {value}")


@pytest.fixture(scope="session")
def classifier(environment, fixtures):
    value = api(
        "create_model",
        dict(
            plugin_id="efficientnet",
            model_id="efficientnet_b0",
            name="Color classifier",
            weight_path=str(fixtures / "color-classifier.onnx"),
            labels_path=str(fixtures / "classification-labels.txt"),
            parameters={"top_k": 2},
        ),
    )
    assert value["state"] == "ready", value
    return value


@pytest.fixture(scope="session")
def detector(environment, fixtures):
    value = api(
        "create_model",
        dict(
            plugin_id="yolo",
            model_id="yolov8n",
            name="Detection fixture",
            weight_path=str(fixtures / "detection-fixture.onnx"),
            labels_path=str(fixtures / "detection-labels.txt"),
        ),
    )
    assert value["state"] == "ready", value
    return value


def finish(ident):
    wait_for(lambda: store.job(ident), lambda t: t["state"] in store.TERMINAL, timeout=60)
    return api("task_detail", dict(task_id=ident))


@pytest.fixture
def file_server():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from modeldock import downloads

    state = dict(payload=b"modeldock weight fixture" * 4096)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            route = self.path.split("?", 1)[0]
            if route == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/model.onnx")
                self.end_headers()
                return
            if route == "/redirect-file":
                self.send_response(302)
                self.send_header("Location", "file:///should-not-be-read")
                self.end_headers()
                return
            if route == "/missing":
                self.send_error(404)
                return
            payload = state["payload"]
            if route == "/slow.onnx":
                payload = b"s" * 8 * 1024**2
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html" if route == "/html" else "application/octet-stream"
            )
            if route != "/without-length":
                length = (
                    downloads.MAX_BYTES + 1
                    if route == "/huge"
                    else len(payload) + (100 if route == "/truncated" else 0)
                )
                self.send_header("Content-Length", str(length))
            if route == "/without-length":
                self.send_header(
                    "Content-Disposition", "attachment; filename*=UTF-8''%E6%A8%A1%E5%9E%8B.onnx"
                )
            if route == "/unsafe-name":
                self.send_header("Content-Disposition", 'attachment; filename="../escape.onnx"')
            self.end_headers()
            if route == "/huge":
                return
            try:
                for offset in range(0, len(payload), 8192):
                    self.wfile.write(payload[offset : offset + 8192])
                    self.wfile.flush()
                    if route == "/slow.onnx":
                        time.sleep(0.02)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()
    thread.join(5)
