"""Prepare portable Tauri resources and checksum-verified uv binaries."""

import hashlib
import argparse
import io
import json
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rust-licenses", action="store_true")
    args = parser.parse_args()
    target = ROOT / "apps/desktop/src-tauri/resources/runtime"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("packages/controller", "packages/python-sdk/src", "plugins"):
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            ROOT / name,
            destination,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", "*.egg-info"),
        )
    notices = target / "licenses"
    shutil.copytree(ROOT / "tools/licenses", notices, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "LICENSE", notices / "ModelDock-LICENSE")
    if args.rust_licenses:
        process = subprocess.run(
            [
                "cargo",
                "metadata",
                "--manifest-path",
                str(ROOT / "apps/desktop/src-tauri/Cargo.toml"),
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                "x86_64-pc-windows-msvc",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        if process.returncode:
            raise RuntimeError(process.stderr[-4000:])
        packages = json.loads(process.stdout)["packages"]
        index = []
        for package in packages:
            index.append(
                {key: package.get(key) for key in ("name", "version", "license", "repository")}
            )
            directory = Path(package["manifest_path"]).parent
            files = [
                p
                for p in directory.iterdir()
                if p.is_file()
                and p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE"))
            ]
            if package.get("license_file"):
                license_file = Path(package["license_file"])
                if not license_file.is_absolute():
                    license_file = directory / license_file
                if license_file.is_file() and license_file not in files:
                    files.append(license_file)
            for source in files:
                destination = (
                    notices / "rust" / (package["name"] + "-" + package["version"]) / source.name
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        (notices / "rust-packages.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    checksums = json.loads((ROOT / "tools/uv-checksums.json").read_text(encoding="utf-8"))
    for platform, info in checksums.items():
        if platform == "version":
            continue
        destination = (
            target
            / "tools"
            / ("uv-" + platform + (".exe" if platform.startswith("windows") else ""))
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        cache = ROOT / ".cache" / (info["sha256"] + ".archive")
        cache.parent.mkdir(exist_ok=True)
        if not cache.exists():
            print("Downloading", info["url"], flush=True)
            with urllib.request.urlopen(info["url"], timeout=120) as response:
                blob = response.read()
            if hashlib.sha256(blob).hexdigest() != info["sha256"]:
                raise RuntimeError("uv archive checksum mismatch")
            cache.write_bytes(blob)
        blob = cache.read_bytes()
        if hashlib.sha256(blob).hexdigest() != info["sha256"]:
            raise RuntimeError("Cached uv archive checksum mismatch")
        if platform.startswith("windows"):
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                entry = next(n for n in archive.namelist() if Path(n).name == "uv.exe")
                destination.write_bytes(archive.read(entry))
        else:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
                entry = next(
                    n for n in archive.getmembers() if Path(n.name).name == "uv" and n.isfile()
                )
                destination.write_bytes(archive.extractfile(entry).read())
            destination.chmod(0o755)
    print("Prepared", target)


if __name__ == "__main__":
    main()
