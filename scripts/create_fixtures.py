"""Tiny real ONNX graphs for tests; these are not EfficientNet/YOLO weights."""

from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from PIL import Image


def create(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    graph = helper.make_graph(
        [
            helper.make_node("ReduceMean", ["image"], ["rgb"], axes=[2, 3], keepdims=0),
            helper.make_node("MatMul", ["rgb", "weights"], ["logits"]),
        ],
        "color-classifier",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, 224, 224])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 2])],
        initializer=[
            numpy_helper.from_array(
                np.array([[2, -2], [0, 0], [-2, 2]], dtype=np.float32), "weights"
            )
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.save(model, directory / "color-classifier.onnx")
    values = np.array(
        [
            [
                [320, 325, 100],
                [320, 325, 100],
                [320, 310, 100],
                [320, 310, 100],
                [0.95, 0.8, 0.1],
                [0.1, 0.1, 0.9],
            ]
        ],
        dtype=np.float32,
    )
    graph = helper.make_graph(
        [helper.make_node("Constant", [], ["detections"], value=numpy_helper.from_array(values))],
        "constant-detection-fixture",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, [1, 3, 640, 640])],
        [helper.make_tensor_value_info("detections", TensorProto.FLOAT, [1, 6, 3])],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 10
    onnx.save(model, directory / "detection-fixture.onnx")
    (directory / "classification-labels.txt").write_text("red\nblue\n", encoding="utf-8")
    (directory / "detection-labels.txt").write_text("person\ncar\n", encoding="utf-8")
    Image.new("RGB", (960, 640), (235, 55, 65)).save(directory / "red.png")
    Image.new("RGB", (640, 960), (40, 95, 235)).save(directory / "blue.png")
    (directory / "broken.jpg").write_bytes(b"intentionally broken image")
    return directory


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="fixtures/generated")
    args = parser.parse_args()
    print(create(args.directory))
