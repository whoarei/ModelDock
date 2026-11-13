import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import finish, wait_for
from modeldock import store
from modeldock.cli import api


def test_classification_partial_failure_and_exports(classifier, fixtures):
    job = api(
        "start_task",
        dict(
            model_instance_id=classifier["id"],
            paths=[
                str(fixtures / "red.png"),
                str(fixtures / "blue.png"),
                str(fixtures / "broken.jpg"),
            ],
            mode="benchmark",
            iterations=6,
            warmup=2,
        ),
    )
    result = finish(job["id"])
    assert result["state"] == "PARTIAL_FAILED", result
    assert result["completed"] == 6 and result["failed"] == 2
    predictions = [
        row["prediction"]["top_k"][0]["label"]
        for row in result["results"]
        if row["status"] == "succeeded"
    ]
    assert predictions == ["red", "blue", "red", "blue"]
    assert result["report"]["warmup"] == 2 and result["metrics"]["count"] == 4
    assert result["metrics"]["stages"]["inference_ms"]["p95"] > 0
    assert result["metrics"]["throughput"] > 0
    assert result["report"]["weight_sha256"] == classifier["weight"]["sha256"]
    preview = api("preview", dict(task_id=job["id"], sample_id="000000"))
    assert preview["url"].startswith("data:image/jpeg;base64,")
    exported = json.loads(api("export", dict(task_id=job["id"], format="json"))["content"])
    assert exported["id"] == job["id"] and len(exported["results"]) == 6
    csv = api("export", dict(task_id=job["id"], format="csv"))["content"]
    assert "broken.jpg" in csv and "sample_total_ms" in csv


def test_yolo_nms_and_original_coordinates(detector, fixtures):
    job = api(
        "start_task",
        dict(
            model_instance_id=detector["id"],
            paths=[str(fixtures / "red.png")],
            mode="single",
        ),
    )
    result = finish(job["id"])
    assert result["state"] == "SUCCEEDED", result
    prediction = result["results"][0]["prediction"]
    assert prediction["image_size"] == dict(width=960, height=640)
    assert len(prediction["detections"]) == 2
    person = next(d for d in prediction["detections"] if d["class_id"] == 0)
    assert person["bbox_xyxy"] == pytest.approx([240, 81, 720, 561], abs=0.1)
    assert person["score"] == pytest.approx(0.95)


def test_load_rejects_label_and_shape_mismatch(environment, fixtures):
    value = api(
        "create_model",
        dict(
            plugin_id="efficientnet",
            model_id="efficientnet_b1",
            weight_path=str(fixtures / "color-classifier.onnx"),
            parameters={"top_k": 2},
        ),
    )
    assert value["state"] == "invalid" and "输入尺寸不匹配" in value["error"]


def test_cancel_idempotency_and_queue(classifier, fixtures):
    ident = uuid.uuid4().hex
    args = dict(
        task_id=ident,
        model_instance_id=classifier["id"],
        paths=[str(fixtures / "red.png")],
        mode="benchmark",
        iterations=10000,
        warmup=0,
    )
    with ThreadPoolExecutor(2) as pool:
        values = list(pool.map(lambda _: api("start_task", args), range(2)))
    assert all(v["id"] == ident for v in values)
    wait_for(lambda: store.job(ident), lambda t: t["state"] == "RUNNING")
    with pytest.raises(ValueError, match="未完成任务"):
        api("uninstall_plugin", dict(plugin_id="efficientnet"))
    second = api(
        "start_task",
        dict(
            model_instance_id=classifier["id"],
            paths=[str(fixtures / "blue.png")],
            mode="single",
        ),
    )
    assert store.job(second["id"])["state"] == "QUEUED"
    api("cancel_task", dict(task_id=ident))
    cancelled = finish(ident)
    assert cancelled["state"] == "CANCELLED"
    assert not cancelled.get("report", {}).get("complete", False)
    assert finish(second["id"])["state"] == "SUCCEEDED"


def test_single_mode_rejects_multiple_inputs(classifier, fixtures):
    with pytest.raises(ValueError, match="一张图片"):
        api(
            "start_task",
            dict(
                model_instance_id=classifier["id"],
                paths=[str(fixtures / "red.png"), str(fixtures / "blue.png")],
                mode="single",
            ),
        )


def test_retry_preserves_configuration_and_rejects_changed_input(classifier, fixtures, tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes((fixtures / "red.png").read_bytes())
    original = api(
        "start_task",
        dict(
            model_instance_id=classifier["id"],
            paths=[str(image)],
            mode="benchmark",
            iterations=3,
            warmup=1,
            parameters={"top_k": 1},
        ),
    )
    first = finish(original["id"])
    assert first["state"] == "SUCCEEDED"
    repeated = api("retry_task", dict(task_id=original["id"]))
    result = finish(repeated["id"])
    assert result["state"] == "SUCCEEDED" and result["retry_of"] == original["id"]
    assert result["report"]["parameters"] == {"top_k": 1}
    assert result["report"]["input_manifest_digest"] == first["report"]["input_manifest_digest"]
    image.write_bytes((fixtures / "blue.png").read_bytes())
    with pytest.raises(ValueError, match="输入文件已变化"):
        api("retry_task", dict(task_id=original["id"]))
