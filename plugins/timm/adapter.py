"""timm classification via local, strictly matching tensor checkpoints."""

from pathlib import Path
import math

from modeldock_sdk import PluginError, StagedPlugin


class Plugin(StagedPlugin):
    def load(self, context, model, instance):
        import timm
        import torch
        from timm.data import create_transform, resolve_model_data_config

        self.torch = torch
        self.labels = instance.get("labels")
        params = instance["effective_parameters"]
        self.classes = params["num_classes"]
        if params["top_k"] > self.classes:
            raise PluginError("Top-K 超过模型类别数", "INVALID_PARAMETERS", "load")
        if self.labels is not None and len(self.labels) != self.classes:
            raise PluginError("类别文件数量与模型类别数不一致", "MODEL_LOAD_FAILED", "load")
        torch.set_num_threads(int(instance.get("execution", {}).get("threads", 1)))
        cfg = model["config_data"]
        self.model = (
            timm.create_model(
                cfg["timm_name"],
                pretrained=False,
                num_classes=self.classes,
                pretrained_cfg=cfg["pretrained_cfg"],
            )
            .eval()
            .to("cpu")
        )
        path = Path(instance["weight_path"])
        try:
            if path.suffix.lower() == ".safetensors":
                from safetensors.torch import load_file

                weights = load_file(str(path), device="cpu")
            else:
                # Tensor-only loading; never fall back to executing pickled model objects.
                weights = torch.load(path, map_location="cpu", weights_only=True)
                if isinstance(weights, dict):
                    weights = weights.get("state_dict", weights.get("model", weights))
            if (
                not isinstance(weights, dict)
                or not weights
                or not all(
                    isinstance(k, str) and isinstance(v, torch.Tensor) for k, v in weights.items()
                )
            ):
                raise ValueError("需要 state_dict 张量权重")
            if all(k.startswith("module.") for k in weights):
                weights = {k[7:]: v for k, v in weights.items()}
            self.model.load_state_dict(weights, strict=True)
        except Exception as exc:
            raise PluginError(
                "权重与所选 timm 架构或类别数不匹配，或文件不是受支持的张量权重：" + str(exc)[:600],
                "MODEL_LOAD_FAILED",
                "load",
            ) from exc
        self.transform = create_transform(
            **resolve_model_data_config(self.model), is_training=False
        )
        size = cfg["pretrained_cfg"]["input_size"]
        self.input_size = list(size)
        self.data_config = resolve_model_data_config(self.model)
        self.timm_name = cfg["timm_name"]
        with torch.inference_mode():
            result = self.model(torch.zeros((1, *size)))
        if not isinstance(result, torch.Tensor) or tuple(result.shape) != (1, self.classes):
            raise PluginError("此模型不提供标准的 [1,类别数] 分类输出", "MODEL_LOAD_FAILED", "load")

    def describe(self, context):
        return dict(
            schema_version="1",
            providers=["PyTorchCPU"],
            inputs=[dict(name="images", shape=[1, *self.input_size], dtype="float32")],
            outputs=[dict(name="logits", shape=[1, self.classes], dtype="float32")],
            extensions=dict(timm=dict(model_name=self.timm_name, data_config=self.data_config)),
        )

    def preprocess(self, image, params, context):
        self.size = dict(width=image.width, height=image.height)
        return self.transform(image).unsqueeze(0)

    def infer(self, inputs, params, context):
        with self.torch.inference_mode():
            return self.model(inputs)

    def postprocess(self, output, sample, params, context):
        scores = self.torch.softmax(output[0].float(), dim=0).tolist()
        if any(not math.isfinite(v) for v in scores):
            raise PluginError("模型输出包含非有限值", "INVALID_PREDICTION", "postprocess", "sample")
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[: params["top_k"]]
        return dict(
            task="classification",
            result_schema="classification/1",
            sample_id=sample.sample_id,
            image_size=self.size,
            top_k=[
                dict(
                    class_id=i,
                    label=self.labels[i] if self.labels is not None else str(i),
                    score=scores[i],
                )
                for i in order
            ],
        )

    def close(self):
        self.model = None
