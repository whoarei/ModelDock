from types import SimpleNamespace

import pytest

from modeldock_sdk import PluginError, validate_model_metadata
from modeldock_sdk.metadata import collect_model_metadata


def test_describe_is_optional_for_legacy_and_framework_independent_for_new_plugins():
    legacy = SimpleNamespace(
        session=SimpleNamespace(
            get_providers=lambda: ["LegacyCPU"],
            get_inputs=lambda: [
                SimpleNamespace(name="image", shape=[1, 3, "height", None], type="tensor(float)")
            ],
        )
    )
    old = collect_model_metadata(legacy, None)
    assert old["providers"] == ["LegacyCPU"] and old["inputs"][0]["type"] == "tensor(float)"
    assert collect_model_metadata(object(), None)["inputs"] == []
    new = SimpleNamespace(
        describe=lambda context: dict(
            schema_version="1",
            providers=["ExampleBackendCPU"],
            inputs=[dict(name="samples", shape=[None, 16], dtype="float32")],
            outputs=[dict(name="scores", shape=[None, 5], dtype="float32")],
            extensions={"example": {"layout": "NC"}},
        )
    )
    result = collect_model_metadata(new, None)
    assert result["outputs"][0]["shape"] == [None, 5]
    assert result["extensions"]["example"]["layout"] == "NC"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"schema_version": "2"},
        {"schema_version": "1", "unknown": 1},
        {"schema_version": "1", "providers": "cpu"},
        {"schema_version": "1", "inputs": [dict(name="x", shape=[True], dtype="float32")]},
        {"schema_version": "1", "inputs": [dict(name="x", shape=[-1], dtype="float32")]},
        {"schema_version": "1", "outputs": [dict(name="x", shape=[1])]},
        {"schema_version": "1", "extensions": {"bad": float("nan")}},
    ],
)
def test_invalid_describe_metadata_is_rejected(value):
    with pytest.raises(PluginError) as failure:
        validate_model_metadata(value)
    assert failure.value.code == "INVALID_MODEL_METADATA" and failure.value.phase == "describe"


def test_declared_non_callable_describe_is_an_interface_error():
    with pytest.raises(PluginError, match="可调用"):
        collect_model_metadata(SimpleNamespace(describe="invalid"), None)


def test_shared_manifest_extensions_are_validated_without_requiring_a_backend(tmp_path):
    import json
    import shutil
    from pathlib import Path
    from modeldock_sdk.manifest import read_manifest

    source = Path(__file__).resolve().parents[1] / "plugins/efficientnet"
    target = tmp_path / "plugin"
    shutil.copytree(source, target)
    path = target / "manifest.json"
    manifest = json.loads(path.read_text())
    extension = dict(
        family="Example",
        pretrained=dict(
            candidates=[dict(url="https://example.com/model.onnx", filename="model.onnx")],
            parameters=dict(top_k=1),
            label_set="Example classes",
        ),
    )
    manifest["models"][0]["extensions"] = dict(modeldock=extension, example=dict(custom=True))
    path.write_text(json.dumps(manifest))
    assert read_manifest(target)["models"][0]["extensions"]["modeldock"]["family"] == "Example"
    extension["pretrained"]["parameters"] = dict(undeclared_parameter=1)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="参数描述"):
        read_manifest(target)
