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
