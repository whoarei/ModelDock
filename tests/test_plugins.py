import zipfile
from pathlib import Path

import pytest
from modeldock import store
from modeldock.cli import api
from modeldock.plugins import unpack
from modeldock_sdk import Context, PluginError, Sample, validate_prediction


def test_environments_are_per_plugin(environment):
    a, b = [store.get("installation", name) for name in ("efficientnet", "yolo")]
    assert a["environment"] != b["environment"]
    assert Path(a["python"]).is_file() and Path(b["python"]).is_file()
    assert len(a["fingerprint"]) == 64
    assert len(api("state", {})["plugins"][0]["manifest"]["models"]) == 2


def test_zip_traversal_is_rejected(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as output:
        output.writestr("../outside.txt", "bad")
    with pytest.raises(ValueError):
        unpack(path, tmp_path / "target")
    assert not (tmp_path / "outside.txt").exists()


def test_score_and_coordinate_contract(tmp_path):
    sample = Sample("000001", tmp_path / "image.jpg")
    model = dict(task="detection", result_schema="detection/1")
    value = dict(
        task="detection",
        result_schema="detection/1",
        sample_id="000001",
        image_size=dict(width=100, height=80),
        detections=[dict(class_id=0, label="0", score=0.8, bbox_xyxy=[1, 2, 101, 79])],
    )
    with pytest.raises(PluginError, match="原图坐标"):
        validate_prediction(value, model, sample)
    value["detections"][0]["bbox_xyxy"][2] = 99
    assert validate_prediction(value, model, sample) == value
    value["detections"][0]["score"] = float("nan")
    with pytest.raises(PluginError):
        validate_prediction(value, model, sample)


def test_artifact_registration_and_cancel(tmp_path):
    context = Context("task", "local", tmp_path)
    with pytest.raises(ValueError):
        context.artifacts.write_bytes("../evil.png", b"bad")
    from io import BytesIO
    from PIL import Image

    data = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(data, format="PNG")
    artifact = context.artifacts.write_bytes("heatmap.png", data.getvalue(), sample_id="000001")
    assert context.artifacts.registry[artifact["artifact_id"]] == artifact
    (tmp_path / "cancel").touch()
    with pytest.raises(PluginError) as error:
        context.raise_if_cancelled()
    assert error.value.code == "CANCELLED"
