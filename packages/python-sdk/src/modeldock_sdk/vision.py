"""Reference ONNX adapters. ORT is supplied by the plugin runtime, not the SDK."""

import numpy as np
from PIL import Image

from .core import PluginError, StagedPlugin


def nms(boxes, scores, classes, threshold, limit):
    order = np.lexsort((np.arange(len(scores)), -scores))
    keep = []
    while len(order) and len(keep) < limit:
        index = int(order[0])
        keep.append(index)
        remaining = order[1:]
        if not len(remaining):
            break
        tl = np.maximum(boxes[index, :2], boxes[remaining, :2])
        br = np.minimum(boxes[index, 2:], boxes[remaining, 2:])
        intersection = np.maximum(br - tl, 0).prod(1)
        area = (boxes[index, 2:] - boxes[index, :2]).prod()
        other = (boxes[remaining, 2:] - boxes[remaining, :2]).prod(1)
        iou = intersection / np.maximum(area + other - intersection, 1e-9)
        order = remaining[(iou <= threshold) | (classes[remaining] != classes[index])]
    return keep


class OnnxVision(StagedPlugin):
    def load(self, context, model, instance):
        import onnxruntime as ort

        self.model = model
        self.config = model["config_data"]
        self.labels = instance.get("labels")
        self.params = instance["effective_parameters"]
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(instance.get("execution", {}).get("threads", 1))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            instance["weight_path"],
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].type != "tensor(float)" or len(inputs[0].shape) != 4:
            raise PluginError(
                "参考插件只接受单输入 NCHW float32 图像模型",
                "MODEL_LOAD_FAILED",
                "load",
            )
        self.input_name = inputs[0].name
        height, width = self.config["input_size"]
        shape = inputs[0].shape
        if any(
            isinstance(actual, int) and actual != expected
            for actual, expected in zip(shape, [1, 3, height, width])
        ):
            raise PluginError(
                f"输入尺寸不匹配：模型 {shape}，配置 {[1, 3, height, width]}",
                "MODEL_LOAD_FAILED",
                "load",
            )
        shape = self.session.get_outputs()[0].shape
        if model["task"] == "classification":
            if len(shape) != 2 or isinstance(shape[0], int) and shape[0] != 1:
                raise PluginError("分类输出必须为 [1,类别数]", "MODEL_LOAD_FAILED", "load")
            count = shape[-1]
            if isinstance(count, int):
                self.check_classes(count)
        else:
            if len(shape) != 3 or isinstance(shape[0], int) and shape[0] != 1:
                raise PluginError(
                    "YOLO 输出必须为 [1,4+类别数,候选数]", "MODEL_LOAD_FAILED", "load"
                )
            if isinstance(shape[1], int):
                self.check_classes(shape[1] - 4)

    def check_classes(self, count):
        if count < 1 or self.labels is not None and len(self.labels) != count:
            raise PluginError("类别文件数量与模型输出不匹配", "MODEL_LOAD_FAILED", "load")
        if self.model["task"] == "classification" and self.params["top_k"] > count:
            raise PluginError("Top-K 超过模型类别数", "INVALID_PARAMETERS", "load")

    def preprocess(self, image, params, context):
        height, width = self.config["input_size"]
        self.size = dict(width=image.width, height=image.height)
        if self.model["task"] == "classification":
            short = self.config["resize_short"]
            ratio = short / min(image.width, image.height)
            image = image.resize(
                (round(image.width * ratio), round(image.height * ratio)),
                Image.Resampling.BICUBIC,
            )
            left = (image.width - width) // 2
            top = (image.height - height) // 2
            image = image.crop((left, top, left + width, top + height))
            pixels = np.asarray(image, dtype=np.float32) / 255
            pixels = (pixels - np.array(self.config["mean"], dtype=np.float32)) / np.array(
                self.config["std"], dtype=np.float32
            )
        else:
            self.ratio = min(width / image.width, height / image.height)
            new_width, new_height = (
                round(image.width * self.ratio),
                round(image.height * self.ratio),
            )
            self.padding = ((width - new_width) // 2, (height - new_height) // 2)
            canvas = Image.new("RGB", (width, height), (114, 114, 114))
            canvas.paste(
                image.resize((new_width, new_height), Image.Resampling.BILINEAR),
                self.padding,
            )
            pixels = np.asarray(canvas, dtype=np.float32) / 255
        return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])

    def infer(self, inputs, params, context):
        return self.session.run(None, {self.input_name: inputs})[0]

    def postprocess(self, outputs, sample, params, context):
        base = dict(
            result_schema=self.model["result_schema"],
            sample_id=sample.sample_id,
            task=self.model["task"],
            image_size=self.size,
        )
        if self.model["task"] == "classification":
            values = np.asarray(outputs, dtype=np.float64).reshape(-1)
            self.check_classes(len(values))
            if not np.isfinite(values).all():
                raise PluginError("模型输出含非有限数值", "INVALID_PREDICTION", scope="sample")
            if self.config.get("output_activation", "logits") == "logits":
                values = np.exp(values - values.max())
                values /= values.sum()
            elif np.any(values < 0) or np.any(values > 1) or abs(values.sum() - 1) > 1e-3:
                raise PluginError("分类概率输出无效", "INVALID_PREDICTION", scope="sample")
            order = np.lexsort((np.arange(len(values)), -values))[: params["top_k"]]
            base["top_k"] = [
                dict(
                    class_id=int(i),
                    label=self.labels[i] if self.labels else str(i),
                    score=float(values[i]),
                )
                for i in order
            ]
        else:
            outputs = np.asarray(outputs)
            if outputs.ndim != 3 or outputs.shape[0] != 1 or outputs.shape[1] < 5:
                raise PluginError("不支持该 YOLO 输出布局", "INVALID_PREDICTION", scope="sample")
            self.check_classes(outputs.shape[1] - 4)
            rows = outputs[0].T
            if not np.isfinite(rows).all():
                raise PluginError("YOLO 输出含非有限数值", "INVALID_PREDICTION", scope="sample")
            classes = rows[:, 4:].argmax(1)
            scores = rows[np.arange(len(rows)), 4 + classes]
            selected = scores >= params["confidence"]
            rows, classes, scores = rows[selected], classes[selected], scores[selected]
            if np.any(scores > 1) or np.any(scores < 0):
                raise PluginError("YOLO 分数应为 0–1", "INVALID_PREDICTION", scope="sample")
            boxes = np.concatenate(
                [rows[:, :2] - rows[:, 2:4] / 2, rows[:, :2] + rows[:, 2:4] / 2], axis=1
            )
            boxes[:, [0, 2]] = (boxes[:, [0, 2]] - self.padding[0]) / self.ratio
            boxes[:, [1, 3]] = (boxes[:, [1, 3]] - self.padding[1]) / self.ratio
            boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, self.size["width"])
            boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, self.size["height"])
            valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
            boxes, classes, scores = boxes[valid], classes[valid], scores[valid]
            indices = nms(boxes, scores, classes, params["iou"], params["max_detections"])
            detections = [
                dict(
                    class_id=int(classes[i]),
                    label=self.labels[int(classes[i])] if self.labels else str(classes[i]),
                    score=float(scores[i]),
                    bbox_xyxy=boxes[i].astype(float).tolist(),
                )
                for i in indices
            ]
            base["detections"] = sorted(
                detections, key=lambda d: (-d["score"], d["class_id"], *d["bbox_xyxy"])
            )
        return base

    def close(self):
        self.session = None
