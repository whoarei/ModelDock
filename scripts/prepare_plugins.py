"""Build the pinned SDK wheel, vendor it, then create/check runtime lockfiles."""

import argparse
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = "1704067200"
    subprocess.run(
        [
            "uv",
            "build",
            "--package",
            "modeldock-sdk",
            "--wheel",
            "--out-dir",
            str(ROOT / "dist"),
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    version = tomllib.loads((ROOT / "packages/python-sdk/pyproject.toml").read_text())["project"][
        "version"
    ]
    source = ROOT / f"dist/modeldock_sdk-{version}-py3-none-any.whl"
    for name in ("efficientnet", "yolo", "timm"):
        plugin = ROOT / "plugins" / name
        project = tomllib.loads((plugin / "runtime/cpu/pyproject.toml").read_text())
        pinned = project["tool"]["uv"]["sources"]["modeldock-sdk"]["path"]
        if Path(pinned).name != source.name:
            print(f"Preserving {name}'s existing SDK pin: {Path(pinned).name}")
            continue
        (plugin / "vendor").mkdir(exist_ok=True)
        shutil.copyfile(source, plugin / "vendor" / source.name)
        if args.lock:
            subprocess.run(
                [
                    "uv",
                    "lock",
                    "--project",
                    str(plugin / "runtime/cpu"),
                    "--refresh-package",
                    "modeldock-sdk",
                    "--upgrade-package",
                    "modeldock-sdk",
                ],
                cwd=ROOT,
                check=True,
            )


if __name__ == "__main__":
    main()
