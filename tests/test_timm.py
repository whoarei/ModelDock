import json
from pathlib import Path

import pytest

from conftest import ROOT, finish
from modeldock import store
from modeldock.cli import api


def spec(name):
    return next(m for m in store.get("plugin", "timm")["manifest"]["models"] if m["name"] == name)


def create(directory, name="mobilenetv3_small_050.lamb_in1k", suffix="safetensors", **extra):
    return api(
        "create_model",
        dict(
            plugin_id="timm",
            model_id=spec(name)["id"],
            weight_path=str(directory / f"timm-classifier.{suffix}"),
            labels_path=str(directory / "timm-labels.txt"),
            parameters=dict(num_classes=3, top_k=2),
            **extra,
        ),
    )


def test_timm_catalog_is_versioned_and_uses_separate_environment(timm_runtime):
    installation, _ = timm_runtime
    plugin = store.get("plugin", "timm")
    models = plugin["manifest"]["models"]
    assert len(models) == 209 and len({m["id"] for m in models}) == len(models)
    assert plugin["manifest"]["extensions"]["timm"]["version"] == "1.0.31"
    assert installation["environment"] != store.get("installation", "efficientnet")["environment"]
    assert {m["extensions"]["modeldock"]["family"] for m in models} >= {
        "resnet",
        "efficientnet",
        "vision_transformer",
    }
    for model in models:
        cfg = json.loads((Path(plugin["path"]) / model["config"]).read_text())
        assert cfg["timm_name"] == model["name"] and cfg["pretrained_cfg"]["num_classes"] == 1000
        assert (
            model["extensions"]["modeldock"]["pretrained"]["candidates"][0]["filename"]
            == "model.safetensors"
        )


@pytest.mark.parametrize("suffix", ["safetensors", "pth"])
def test_timm_classification_timing_and_reproducible_checkpoint(timm_runtime, fixtures, suffix):
    _, directory = timm_runtime
    model = create(directory, suffix=suffix)
    assert model["state"] == "ready", model
    assert model["validation"]["providers"] == ["PyTorchCPU"]
    assert model["validation"]["inputs"][0]["shape"] == [1, 3, 224, 224]
    task = api(
        "start_task",
        dict(
            model_instance_id=model["id"],
            paths=[str(fixtures / "red.png")],
            mode="benchmark",
            warmup=1,
            iterations=2,
            threads=1,
        ),
    )
    result = finish(task["id"])
    assert result["state"] == "SUCCEEDED", result
    assert result["results"][0]["prediction"]["top_k"][0]["label"] == "green"
    assert result["metrics"]["count"] == 2
    assert result["metrics"]["stages"]["inference_ms"]["mean"] > 0


@pytest.mark.parametrize(
    "name", ["efficientnet_b0.ra_in1k", "vit_tiny_patch16_224.augreg_in21k_ft_in1k"]
)
def test_same_plugin_runs_cnn_and_transformer(timm_runtime, fixtures, tmp_path, name):
    installation, _ = timm_runtime
    store.run_process(
        [
            installation["python"],
            str(ROOT / "scripts/create_timm_fixtures.py"),
            str(tmp_path),
            "--model",
            name,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    model = create(tmp_path, name=name)
    assert model["state"] == "ready", model
    task = api(
        "start_task",
        dict(model_instance_id=model["id"], paths=[str(fixtures / "red.png")], mode="single"),
    )
    result = finish(task["id"])
    assert result["state"] == "SUCCEEDED", result
    assert result["results"][0]["prediction"]["top_k"][0]["label"] == "green"


def test_timm_rejects_wrong_architecture_and_class_count(timm_runtime):
    _, directory = timm_runtime
    wrong = create(directory, name="resnet18.a1_in1k")
    assert wrong["state"] == "invalid" and "不匹配" in wrong["error"]
    wrong = api(
        "create_model",
        dict(
            plugin_id="timm",
            model_id=spec("mobilenetv3_small_050.lamb_in1k")["id"],
            weight_path=str(directory / "timm-classifier.pth"),
            parameters=dict(num_classes=1000, top_k=5),
        ),
    )
    assert wrong["state"] == "invalid" and "类别数不匹配" in wrong["error"]
