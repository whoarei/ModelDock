"""Create deterministic tensor checkpoints for real timm model execution tests.

These are synthetic weights and cannot measure pretrained model accuracy.
Run with a prepared timm plugin interpreter.
"""

import argparse
from pathlib import Path


def create(directory, model_name="mobilenetv3_small_050.lamb_in1k", classes=3):
    import timm
    import torch
    from safetensors.torch import save_file

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    model = timm.create_model(model_name, pretrained=False, num_classes=classes).eval()
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.get_classifier().bias[1] = 8
    save_file(model.state_dict(), str(directory / "timm-classifier.safetensors"))
    torch.save(dict(state_dict=model.state_dict()), directory / "timm-classifier.pth")
    (directory / "timm-labels.txt").write_text("red\ngreen\nblue\n", encoding="utf-8")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--model", default="mobilenetv3_small_050.lamb_in1k")
    parser.add_argument("--classes", type=int, default=3)
    args = parser.parse_args()
    create(args.directory, args.model, args.classes)
