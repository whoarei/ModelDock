import hashlib
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from modeldock_sdk.manifest import inside, read_manifest

from . import store


def unpack(archive, target):
    target = Path(target).resolve()
    seen = set()
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > 5000 or sum(i.file_size for i in bundle.infolist()) > 1024**3:
            raise ValueError("插件包过大")
        for entry in bundle.infolist():
            path = (target / entry.filename).resolve()
            if (
                path == target
                or target not in path.parents
                or path in seen
                or (entry.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("插件归档路径无效或包含符号链接")
            seen.add(path)
        bundle.extractall(target)


def register(path, *, only_if_missing=False):
    source = Path(path).resolve()
    staging = store.root() / "staging" / store.uid()
    staging.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.is_dir():
            if any(p.is_symlink() for p in source.rglob("*")):
                raise ValueError("插件目录不允许符号链接")
            shutil.copytree(
                source,
                staging,
                ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".git"),
            )
        else:
            staging.mkdir()
            unpack(source, staging)
        manifest = read_manifest(staging)
        sha = hashlib.sha256()
        for file in sorted(p for p in staging.rglob("*") if p.is_file()):
            sha.update(str(file.relative_to(staging)).replace("\\", "/").encode())
            sha.update(bytes.fromhex(store.digest(file)))
        package_digest = sha.hexdigest()
        ident = manifest["id"]
        target = (
            store.root()
            / "plugins"
            / ident
            / "releases"
            / (manifest["version"] + "-" + package_digest[:16])
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            try:
                staging.rename(target)
            except OSError:
                # A parallel bootstrap may have published the identical package.
                # rename is atomic; shutil.move would nest the losing staging dir.
                if not (target / "manifest.json").is_file():
                    raise
        value = dict(
            id=ident,
            manifest=manifest,
            digest=package_digest,
            path=str(target),
            imported_at=time.time(),
        )
        if only_if_missing:
            with store.connect() as db:
                db.execute(
                    "INSERT INTO items VALUES('plugin',?,?) ON CONFLICT(kind,id) DO NOTHING",
                    (ident, json.dumps(value, ensure_ascii=False)),
                )
                row = db.execute(
                    "SELECT value FROM items WHERE kind='plugin' AND id=?", (ident,)
                ).fetchone()
            return json.loads(row[0])
        previous = store.get("plugin", ident)
        active = store.get("installation", ident)
        if active and active.get("state") == "preparing":
            raise ValueError("插件正在准备环境，请等待完成后再导入")
        if (
            previous
            and previous["digest"] != package_digest
            and any(j["plugin_id"] == ident for j in store.active_jobs())
        ):
            raise ValueError("插件有未完成任务，不能替换插件包")
        store.put("plugin", ident, value)
        return value
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def install(ident, profile_id):
    plugin = store.get("plugin", ident)
    if not plugin:
        raise ValueError("插件不存在")
    profile = next(
        (p for p in plugin["manifest"]["runtime_profiles"] if p["id"] == profile_id),
        None,
    )
    if profile is None or store.platform_id() not in profile["platforms"]:
        raise ValueError("当前节点不支持该运行方案")
    if any(j["plugin_id"] == ident for j in store.active_jobs()):
        raise ValueError("该插件仍有未完成任务")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if any(j["plugin_id"] == ident for j in store.active_jobs(db)):
            raise ValueError("该插件仍有未完成任务")
        row = db.execute(
            "SELECT value FROM items WHERE kind='installation' AND id=?", (ident,)
        ).fetchone()
        previous = json.loads(row[0]) if row else None
        if previous and previous["state"] in ("preparing", "uninstalling"):
            raise ValueError("环境已在准备中")
        value = dict(
            id=ident,
            state="preparing",
            profile_id=profile_id,
            plugin_digest=plugin["digest"],
            previous=previous,
            started_at=time.time(),
        )
        db.execute(
            "INSERT INTO items VALUES('installation',?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value",
            (ident, json.dumps(value)),
        )
    child = store.spawn_controller("prepare", ident)
    from .resources import process_birth

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM items WHERE kind='installation' AND id=?", (ident,)
        ).fetchone()
        current = json.loads(row[0]) if row else None
        if current and current["state"] == "preparing":
            current.update(prepare_pid=child.pid, prepare_birth=process_birth(child.pid))
            db.execute(
                "UPDATE items SET value=? WHERE kind='installation' AND id=?",
                (json.dumps(current), ident),
            )
    return value


def prepare(ident):
    installation = store.get("installation", ident)
    if not installation or installation["state"] != "preparing":
        return
    from .resources import process_birth

    installation.update(prepare_pid=os.getpid(), prepare_birth=process_birth(os.getpid()))
    previous = installation.get("previous")
    plugin = store.get("plugin", ident)
    profile = next(
        p for p in plugin["manifest"]["runtime_profiles"] if p["id"] == installation["profile_id"]
    )
    project = inside(plugin["path"], profile["project_dir"])
    logfile = store.root() / "plugins" / ident / "prepare.log"
    installation["log_path"] = str(logfile)
    store.put("installation", ident, installation)
    environment = store.root() / "plugins" / ident / "envs" / store.uid()
    try:
        uv = store.uv_binary()
        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = str(environment)
        env.pop("VIRTUAL_ENV", None)
        # All versions come from the plugin's lockfile; no implicit upgrades.
        with logfile.open("wb") as output:
            process = store.run_process(
                [uv, "sync", "--project", str(project), "--locked", "--no-dev"],
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        if process.returncode:
            raise ValueError("依赖同步失败，请查看安装日志")
        python = store.environment_python(environment)
        check = (
            "import importlib.metadata as m; from packaging.specifiers import SpecifierSet; import modeldock_worker; assert m.version('modeldock-sdk') in SpecifierSet("
            + repr(plugin["manifest"]["sdk_version"])
            + ")"
        )
        module, name = plugin["manifest"]["entrypoint"].split(":")
        check += (
            "; import sys,importlib; sys.path.insert(0,"
            + repr(plugin["path"])
            + "); cls=getattr(importlib.import_module("
            + repr(module)
            + "),"
            + repr(name)
            + "); assert all(callable(getattr(cls,k,None)) for k in ('load','predict','close'))"
        )
        store.run_process([python, "-c", check], check=True, capture_output=True, timeout=30)
        uv_version = store.command_output(
            [uv, "--version"], text=True, encoding="utf-8", errors="replace"
        ).strip()
        python_version = store.command_output(
            [python, "--version"], text=True, encoding="utf-8", errors="replace"
        ).strip()
        fingerprint = hashlib.sha256(
            (
                plugin["digest"]
                + installation["profile_id"]
                + store.platform_id()
                + uv_version
                + python_version
                + store.digest(project / "uv.lock")
            ).encode()
        ).hexdigest()
        installation.update(
            state="ready",
            environment=str(environment),
            python=python,
            fingerprint=fingerprint,
            python_version=python_version,
            uv_version=uv_version,
            error=None,
            ready_at=time.time(),
        )
        installation.pop("previous", None)
        store.put("installation", ident, installation)
        if previous and previous.get("environment") and previous["environment"] != str(environment):
            shutil.rmtree(previous["environment"], ignore_errors=True)
    except Exception as exc:
        shutil.rmtree(environment, ignore_errors=True)
        if previous and previous.get("state") == "ready":
            previous["last_error"] = str(exc)
            store.put("installation", ident, previous)
        else:
            installation.pop("previous", None)
            installation.update(state="failed", error=str(exc))
            store.put("installation", ident, installation)


def uninstall(ident):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if any(j["plugin_id"] == ident for j in store.active_jobs(db)):
            raise ValueError("插件仍有未完成任务")
        row = db.execute(
            "SELECT value FROM items WHERE kind='installation' AND id=?", (ident,)
        ).fetchone()
        installation = json.loads(row[0]) if row else None
        if installation and installation["state"] == "preparing":
            raise ValueError("请等待环境准备结束")
        if installation:
            changed = {**installation, "state": "uninstalling"}
            db.execute(
                "UPDATE items SET value=? WHERE kind='installation' AND id=?",
                (json.dumps(changed), ident),
            )
    if installation and installation.get("environment"):
        shutil.rmtree(installation["environment"], ignore_errors=True)
    store.delete("installation", ident)
    return dict(ok=True)
