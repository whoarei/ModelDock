"""Generate the bundled, versioned classification catalog with the pinned timm runtime.

Run using the Python interpreter from plugins/timm's prepared CPU environment.
No model weights are downloaded or bundled by this script.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    "resnet*",
    "efficientnet_b*",
    "tf_efficientnet_b*",
    "mobilenetv3_*",
    "mobilenetv4_conv_small*",
    "convnext_tiny*",
    "convnext_small*",
    "vit_tiny*",
    "vit_small*",
    "swin_tiny*",
    "regnet[xy]_00*",
    "densenet*",
]


def main():
    import timm
    from timm.data import ImageNetInfo
    from timm.models import get_pretrained_cfg, model_entrypoint

    if timm.__version__ != "1.0.31":
        raise ValueError("Use the locked timm 1.0.31 runtime to rebuild the catalog")
    plugin = ROOT / "plugins/timm"
    (plugin / "configs").mkdir(exist_ok=True)
    (plugin / "labels").mkdir(exist_ok=True)
    (plugin / "labels/imagenet-1k.txt").write_text(
        "\n".join(ImageNetInfo().label_descriptions()) + "\n", encoding="utf-8"
    )
    models = []
    for name in timm.list_models(PATTERNS, pretrained=True):
        cfg = get_pretrained_cfg(name)
        if cfg.num_classes != 1000 or not cfg.hf_hub_id or cfg.input_size[0] != 3:
            continue
        ident = "model_" + hashlib.sha256(name.encode()).hexdigest()[:16]
        family = model_entrypoint(name).__module__.rsplit(".", 1)[-1]
        config = dict(
            timm_name=name, pretrained_cfg=cfg.to_dict(), input_size=list(cfg.input_size[1:])
        )
        (plugin / f"configs/{ident}.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        base = "https://huggingface.co/" + cfg.hf_hub_id.rstrip("/") + "/resolve/main/"
        models.append(
            dict(
                id=ident,
                name=name,
                task="classification",
                result_schema="classification/1",
                weight_formats=["safetensors", "pth", "pt", "bin"],
                config=f"configs/{ident}.json",
                parameter_schema="schemas/params.json",
                capabilities=dict(timing_mode="staged", pure_inference_benchmark=False),
                extensions=dict(
                    modeldock=dict(
                        family=family,
                        pretrained=dict(
                            labels="labels/imagenet-1k.txt",
                            parameters=dict(num_classes=1000),
                            label_set="ImageNet-1k",
                            license=cfg.license or "参见模型发布页",
                            homepage="https://huggingface.co/" + cfg.hf_hub_id,
                            candidates=[
                                dict(url=base + f, filename=f)
                                for f in ("model.safetensors", "pytorch_model.bin")
                            ],
                        ),
                    )
                ),
            )
        )
    manifest = dict(
        schema_version="1",
        id="timm",
        name="timm 图像分类",
        version="0.1.0",
        sdk_version=">=0.1.1,<0.2",
        entrypoint="adapter:Plugin",
        runtime_profiles=[
            dict(
                id="torch-cpu",
                project_dir="runtime/cpu",
                platforms=["windows-x86_64", "linux-x86_64"],
                providers=["PyTorchCPU"],
            )
        ],
        models=models,
        extensions=dict(
            timm=dict(version=timm.__version__, catalog_scope="ImageNet-1k classification")
        ),
    )
    (plugin / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Generated {len(models)} classification entries from timm {timm.__version__}")


if __name__ == "__main__":
    main()
