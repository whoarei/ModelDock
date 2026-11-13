import json
import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


class PluginError(Exception):
    def __init__(
        self,
        message,
        code="PLUGIN_EXECUTION_FAILED",
        phase="predict",
        scope="task",
        retryable=False,
    ):
        super().__init__(message)
        self.code, self.phase, self.scope, self.retryable = (
            code,
            phase,
            scope,
            retryable,
        )

    def as_dict(self):
        return dict(
            code=self.code,
            message=str(self),
            phase=self.phase,
            scope=self.scope,
            retryable=self.retryable,
        )


@dataclass(frozen=True)
class Sample:
    sample_id: str
    path: Path
    sha256: str = ""
    media_type: str = "image"


class Context:
    def __init__(self, task_id, node_id, directory):
        self.task_id, self.node_id = task_id, node_id
        self.directory = Path(directory)
        self.phase = "measurement"
        self.timings = {}
        self.image_sizes = {}
        self.artifacts = ArtifactWriter(self)

    def raise_if_cancelled(self):
        if (self.directory / "cancel").exists():
            raise PluginError("任务已取消", "CANCELLED", scope="task")

    def log(self, level, message, fields=None):
        import sys

        print(
            json.dumps(
                dict(level=level, message=str(message), fields=fields or {}),
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )

    def read_image(self, sample):
        from PIL import Image, ImageOps

        try:
            with Image.open(sample.path) as src:
                image = ImageOps.exif_transpose(src).convert("RGB")
                self.image_sizes[sample.sample_id] = dict(width=image.width, height=image.height)
                return image
        except Exception as exc:
            raise PluginError(
                f"图片解码失败：{exc}", "INPUT_DECODE_FAILED", "decode", "sample"
            ) from exc


class StagedPlugin:
    def predict(self, sample, params, context):
        context.raise_if_cancelled()
        started = time.perf_counter_ns()
        image = context.read_image(sample)
        decoded = time.perf_counter_ns()
        inputs = self.preprocess(image, params, context)
        preprocessed = time.perf_counter_ns()
        self.synchronize(context)
        before_infer = time.perf_counter_ns()
        output = self.infer(inputs, params, context)
        self.synchronize(context)
        after_infer = time.perf_counter_ns()
        result = self.postprocess(output, sample, params, context)
        if result.get("image_size") != dict(width=image.width, height=image.height):
            raise PluginError("结果尺寸与原图不一致", "INVALID_PREDICTION", "validate", "sample")
        after_post = time.perf_counter_ns()
        context.timings = dict(
            decode_ms=(decoded - started) / 1e6,
            preprocess_ms=(preprocessed - decoded) / 1e6,
            inference_ms=(after_infer - before_infer) / 1e6,
            postprocess_ms=(after_post - after_infer) / 1e6,
            sample_total_ms=(after_post - started) / 1e6,
        )
        context.raise_if_cancelled()
        return result

    def synchronize(self, context):
        pass

    def close(self):
        pass


class ArtifactWriter:
    def __init__(self, context):
        self.context = context
        self.registry = {}

    def write_bytes(
        self,
        name,
        data,
        media_type="image/png",
        kind="visualization",
        sample_id=None,
        title=None,
    ):
        self.context.raise_if_cancelled()
        if title is not None and not isinstance(title, str):
            raise ValueError("产物标题必须为字符串")
        if (
            not isinstance(name, str)
            or not name
            or name in (".", "..")
            or any(c in name for c in "/\\\0\r\n")
        ):
            raise ValueError("产物文件名无效")
        if (
            media_type not in ("image/png", "image/jpeg")
            or not isinstance(data, bytes)
            or len(data) > 32 * 1024**2
        ):
            raise ValueError("0.1.0 产物须为不超过 32MB 的 PNG/JPEG")
        from PIL import Image
        from io import BytesIO

        try:
            with Image.open(BytesIO(data)) as image:
                if image.format != ("PNG" if media_type == "image/png" else "JPEG"):
                    raise ValueError("产物格式与媒体类型不一致")
                image.verify()
        except Exception as exc:
            raise ValueError("产物不是有效的 PNG/JPEG 图片") from exc
        ident = uuid.uuid4().hex
        value = dict(
            artifact_id=ident,
            kind=kind,
            media_type=media_type,
            sample_id=sample_id,
            title=title or name,
        )
        if self.context.phase == "warmup":
            return value
        directory = self.context.directory / "artifacts"
        directory.mkdir(exist_ok=True)
        (directory / (ident + ".bin")).write_bytes(data)
        (directory / (ident + ".json")).write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
        self.registry[ident] = value
        return value


def validate_prediction(result, model, sample, labels=None, artifacts_registry=None):
    try:
        json.dumps(result, allow_nan=False)
        if (
            result["sample_id"] != sample.sample_id
            or result["task"] != model["task"]
            or result["result_schema"] != model["result_schema"]
        ):
            raise ValueError("结果与样本或任务协议不匹配")
        width, height = result["image_size"]["width"], result["image_size"]["height"]
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            raise ValueError("原图尺寸无效")
        items = result["top_k"] if model["task"] == "classification" else result["detections"]
        if not isinstance(items, list) or (model["task"] == "classification" and not items):
            raise ValueError("结果列表无效")
        seen, order = set(), []
        for item in items:
            cls, score = item["class_id"], item["score"]
            if (
                type(cls) is not int
                or cls < 0
                or type(score) not in (float, int)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError("类别或分数无效")
            if labels is not None:
                if cls >= len(labels) or item["label"] != labels[cls]:
                    raise ValueError("类别映射不匹配")
            elif item["label"] != str(cls):
                raise ValueError("无标签文件时 label 必须为 class_id 字符串")
            if model["task"] == "classification":
                if cls in seen:
                    raise ValueError("分类结果包含重复类别")
                seen.add(cls)
                order.append((-score, cls))
            else:
                x1, y1, x2, y2 = item["bbox_xyxy"]
                if not all(
                    type(v) in (int, float) and math.isfinite(v) for v in (x1, y1, x2, y2)
                ) or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise ValueError("检测框必须为原图坐标且位于图像范围内")
                order.append((-score, cls, x1, y1, x2, y2))
        if order != sorted(order):
            raise ValueError("结果未按约定稳定排序")
        if model["task"] == "classification" and sum(i["score"] for i in items) > 1.00001:
            raise ValueError("分类概率之和超过 1")
        for artifact in result.get("artifacts", []):
            if (
                not isinstance(artifact, dict)
                or (artifacts_registry or {}).get(artifact.get("artifact_id")) != artifact
            ):
                raise ValueError("产物引用未经 SDK 写入器登记")
        return result
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PluginError(
            f"预测结果不符合协议：{exc}", "INVALID_PREDICTION", "validate", "sample"
        ) from exc
