"""Prepare stable Windows update metadata and checksums from a signed installer."""

import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(directory, version, notes, allow_unsigned=False):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("稳定版版本号必须为 MAJOR.MINOR.PATCH")
    directory = Path(directory)
    installer = directory / f"ModelDock_{version}_x64-setup.exe"
    if not installer.is_file():
        raise ValueError(f"缺少当前版本安装包：{installer.name}")
    signature_file = installer.with_suffix(".exe.sig")
    manifest = directory / "latest.json"
    if signature_file.exists():
        signature = signature_file.read_text(encoding="utf-8").strip()
        # The cryptographic check is performed by Tauri before installation. Here
        # enforce that packaging did not pair metadata with another signed version.
        decoded = base64.b64decode(signature, validate=True).decode("utf-8")
        comments = [line for line in decoded.splitlines() if line.startswith("trusted comment: ")]
        if len(comments) != 1 or f"version:{version}" not in comments[0].split("\t"):
            raise ValueError("签名必须绑定当前版本；签名时使用 --app-version")
        manifest.write_text(
            json.dumps(
                dict(
                    version=version,
                    notes=notes,
                    pub_date=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    platforms={
                        "windows-x86_64": dict(
                            signature=signature,
                            url=f"https://github.com/whoarei/ModelDock/releases/download/v{version}/{installer.name}",
                        )
                    },
                ),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif not allow_unsigned:
        raise ValueError("缺少更新签名；不能发布在线更新清单")
    else:
        manifest.unlink(missing_ok=True)
    assets = [installer] + ([signature_file, manifest] if signature_file.exists() else [])
    (directory / "SHA256SUMS").write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in assets),
        encoding="utf-8",
    )
    return manifest if manifest.exists() else None


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--version", default=json.loads((ROOT / "apps/desktop/package.json").read_text())["version"]
    )
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true")
    parser.add_argument(
        "--record",
        action="store_true",
        help="Write a public signature record for the publishing workflow",
    )
    args = parser.parse_args()
    notes = (args.notes or ROOT / f"docs/releases/{args.version}.md").read_text(encoding="utf-8")
    result = prepare(args.directory, args.version, notes, args.allow_unsigned)
    if args.record:
        if result is None:
            raise ValueError("只有已签名的安装包可以生成发布记录")
        installer = args.directory / f"ModelDock_{args.version}_x64-setup.exe"
        record = dict(
            version=args.version,
            installer_sha256=hashlib.sha256(installer.read_bytes()).hexdigest(),
            signature=installer.with_suffix(".exe.sig").read_text(encoding="utf-8").strip(),
        )
        target = ROOT / "release-signatures" / f"v{args.version}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(
        "Signed updater metadata prepared"
        if result
        else "Unsigned draft assets prepared; local signing required"
    )


if __name__ == "__main__":
    main()
