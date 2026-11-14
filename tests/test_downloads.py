import hashlib
import json
from pathlib import Path

import pytest

from conftest import finish, wait_for
from modeldock import downloads, store
from modeldock.cli import api


@pytest.fixture
def isolated_downloads(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELDOCK_DATA_DIR", str(tmp_path / "下载 数据"))
    store.put(
        "plugin", "yolo", dict(manifest=dict(models=[dict(id="yolov8n", weight_formats=["onnx"])]))
    )


def begin(url, **extra):
    return api("start_download", dict(plugin_id="yolo", model_id="yolov8n", url=url, **extra))


def done(ident):
    return wait_for(
        lambda: api("download_status", dict(id=ident)), lambda d: d["state"] in downloads.TERMINAL
    )


def test_download_redirect_checksum_and_content_cache(isolated_downloads, file_server):
    base, state = file_server
    sha = hashlib.sha256(state["payload"]).hexdigest()
    first = done(begin(base + "/redirect?token=private-query", sha256=sha)["id"])
    assert first["state"] == "succeeded" and first["verified"] and first["sha256"] == sha
    assert first["received"] == first["total"] == len(state["payload"])
    assert Path(first["path"]).read_bytes() == state["payload"]
    assert "private-query" not in json.dumps(store.get("download", first["id"]))
    assert not (downloads.directory(first["id"]) / "request.json").exists()
    second = done(begin(base + "/model.onnx")["id"])
    assert second["path"] == first["path"]


def test_unknown_length_and_utf8_filename(isolated_downloads, file_server):
    base, state = file_server
    result = done(begin(base + "/without-length")["id"])
    assert result["state"] == "succeeded" and result["total"] is None
    assert (
        result["filename"] == "模型.onnx" and Path(result["path"]).read_bytes() == state["payload"]
    )


@pytest.mark.parametrize(
    "route,extra,message",
    [
        ("/missing", {}, "HTTP 404"),
        ("/html", {}, "网页"),
        ("/huge", {}, "2GB"),
        ("/truncated", {}, "不完整"),
        ("/unsafe-name", {}, "文件名"),
        ("/model.onnx", {"sha256": "0" * 64}, "校验失败"),
        ("/redirect-file", {}, "HTTP 302"),
    ],
)
def test_failed_downloads_never_expose_partial_files(
    isolated_downloads, file_server, route, extra, message
):
    base, _ = file_server
    result = done(begin(base + route + "?token=keep-private", **extra)["id"])
    assert result["state"] == "failed" and message in result["error"], result
    assert "path" not in result and "keep-private" not in result["error"]
    assert not (downloads.directory(result["id"]) / "weight.part").exists()
    assert not (downloads.directory(result["id"]) / "request.json").exists()


def test_download_progress_cancel_and_update_guard(isolated_downloads, file_server):
    base, _ = file_server
    value = begin(base + "/slow.onnx")
    ident = value["id"]
    try:
        progress = wait_for(
            lambda: api("download_status", dict(id=ident)), lambda d: d["received"] > 0
        )
        assert 0 < progress["received"] < progress["total"]
        readiness = api("update_readiness", {})
        assert not readiness["ready"] and readiness["active_downloads"] == 1
        api("cancel_download", dict(id=ident))
        result = done(ident)
        assert result["state"] == "cancelled" and "path" not in result
        assert not (downloads.directory(ident) / "weight.part").exists()
        assert api("update_readiness", {})["ready"]
    finally:
        if downloads.status(ident)["state"] not in downloads.TERMINAL:
            api("cancel_download", dict(id=ident))
            done(ident)


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/model.onnx",
        "ftp://example.com/model.onnx",
        "https://user:password@example.com/model.onnx",
        "https://example.com:0/model.onnx",
    ],
)
def test_invalid_url_rejected_before_starting(isolated_downloads, url):
    with pytest.raises(ValueError):
        begin(url)
    assert not store.all_items("download")


def test_url_weight_loads_and_runs_real_onnx(environment, fixtures, file_server):
    base, state = file_server
    state["payload"] = (fixtures / "color-classifier.onnx").read_bytes()
    downloaded = done(
        api(
            "start_download",
            dict(plugin_id="efficientnet", model_id="efficientnet_b0", url=base + "/model.onnx"),
        )["id"]
    )
    assert downloaded["state"] == "succeeded"
    model = api(
        "create_model",
        dict(
            plugin_id="efficientnet",
            model_id="efficientnet_b0",
            weight_path=downloaded["path"],
            labels_path=str(fixtures / "classification-labels.txt"),
            parameters={"top_k": 2},
        ),
    )
    assert model["state"] == "ready", model
    task = api(
        "start_task",
        dict(model_instance_id=model["id"], paths=[str(fixtures / "red.png")], mode="single"),
    )
    result = finish(task["id"])
    assert (
        result["state"] == "SUCCEEDED"
        and result["results"][0]["prediction"]["top_k"][0]["label"] == "red"
    )
