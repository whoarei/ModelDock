import base64
import hashlib
import json
import runpy
from pathlib import Path

import pytest

prepare = runpy.run_path(str(Path(__file__).parents[1] / "scripts/release_assets.py"))["prepare"]


def test_release_manifest_matches_installer_and_signed_version(tmp_path):
    installer = tmp_path / "ModelDock_0.2.0_x64-setup.exe"
    installer.write_bytes(b"fixture installer")
    with pytest.raises(ValueError, match="缺少更新签名"):
        prepare(tmp_path, "0.2.0", "notes")
    assert prepare(tmp_path, "0.2.0", "notes", allow_unsigned=True) is None
    signature = installer.with_suffix(".exe.sig")
    # Metadata test only; this deliberately is not a cryptographically valid signature.
    signature.write_text(
        base64.b64encode(
            b"untrusted comment: fixture\nx\ntrusted comment: timestamp:0\tversion:0.1.0\ny"
        ).decode()
    )
    with pytest.raises(ValueError, match="签名必须绑定当前版本"):
        prepare(tmp_path, "0.2.0", "notes")
    signature.write_text(
        base64.b64encode(
            b"untrusted comment: fixture\nx\ntrusted comment: timestamp:0\tversion:0.2.0\ny"
        ).decode()
    )
    manifest = prepare(tmp_path, "0.2.0", "更新说明")
    data = json.loads(manifest.read_text())
    assert data["version"] == "0.2.0" and data["notes"] == "更新说明"
    assert data["platforms"]["windows-x86_64"]["url"].endswith("/v0.2.0/" + installer.name)
    assert data["platforms"]["windows-x86_64"]["signature"] == signature.read_text()
    assert (
        hashlib.sha256(installer.read_bytes()).hexdigest() in (tmp_path / "SHA256SUMS").read_text()
    )
