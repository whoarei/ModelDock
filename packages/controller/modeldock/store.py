import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

TERMINAL = {"SUCCEEDED", "PARTIAL_FAILED", "FAILED", "CANCELLED"}
ACTIVE = {"PREPARING", "RUNNING", "CANCEL_REQUESTED"}


def run_process(*args, **kwargs):
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(*args, **kwargs)


def command_output(*args, **kwargs):
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.check_output(*args, **kwargs)


def root():
    value = os.environ.get("MODELDOCK_DATA_DIR")
    if value:
        return Path(value).resolve()
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "ModelDock"
    ).resolve()


def resources():
    return Path(
        os.environ.get("MODELDOCK_RESOURCES", Path(__file__).resolve().parents[3])
    ).resolve()


def connect():
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 30
    while True:
        db = sqlite3.connect(base / "app.sqlite", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            # WAL transitions can return SQLITE_BUSY immediately during parallel
            # first opens, even with busy_timeout. Do not rewrite headers on reads.
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                db.execute("PRAGMA journal_mode=WAL")
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS items(kind TEXT, id TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,id))"
                    )
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, state TEXT NOT NULL, value TEXT NOT NULL)"
                    )
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, value TEXT NOT NULL)"
                    )
                    db.execute("PRAGMA user_version=1")
            return db
        except sqlite3.OperationalError as exc:
            db.close()
            if (getattr(exc, "sqlite_errorcode", 0) & 255) not in (
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            ) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
        except Exception:
            db.close()
            raise


def uid():
    return uuid.uuid4().hex


def put(kind, ident, value):
    with connect() as db:
        db.execute(
            "INSERT INTO items VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value",
            (kind, ident, json.dumps(value, ensure_ascii=False)),
        )
    return value


def get(kind, ident, default=None):
    with connect() as db:
        row = db.execute("SELECT value FROM items WHERE kind=? AND id=?", (kind, ident)).fetchone()
    return json.loads(row[0]) if row else default


def all_items(kind):
    with connect() as db:
        return [
            json.loads(r[0])
            for r in db.execute("SELECT value FROM items WHERE kind=? ORDER BY id", (kind,))
        ]


def delete(kind, ident):
    with connect() as db:
        db.execute("DELETE FROM items WHERE kind=? AND id=?", (kind, ident))


def job(ident):
    with connect() as db:
        row = db.execute("SELECT value FROM jobs WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise ValueError("测试任务不存在")
    return json.loads(row[0])


def jobs():
    with connect() as db:
        rows = db.execute("SELECT value FROM jobs ORDER BY rowid DESC LIMIT 100").fetchall()
    return [json.loads(r[0]) for r in rows]


def active_jobs(db=None):
    if db is not None:
        return [
            json.loads(r[0])
            for r in db.execute(
                "SELECT value FROM jobs WHERE state NOT IN ('SUCCEEDED','FAILED','PARTIAL_FAILED','CANCELLED')"
            )
        ]
    with connect() as connection:
        return active_jobs(connection)


def new_job(value):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM items WHERE kind='installation' AND id=?", (value["plugin_id"],)
        ).fetchone()
        installed = json.loads(row[0]) if row else {}
        if (
            installed.get("state") != "ready"
            or installed.get("fingerprint") != value["environment_fingerprint"]
        ):
            raise ValueError("插件环境已变化，请刷新后重新提交任务")
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?)",
            (value["id"], value["state"], json.dumps(value, ensure_ascii=False)),
        )
    return value


def update_job(ident, **changes):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM jobs WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError("测试任务不存在")
        value = json.loads(row[0])
        if value["state"] in TERMINAL:
            return value
        if value["state"] == "CANCEL_REQUESTED" and changes.get("state") in (
            "RUNNING",
            "PREPARING",
        ):
            changes.pop("state")
        value.update(changes)
        value["updated_at"] = time.time()
        db.execute(
            "UPDATE jobs SET state=?,value=? WHERE id=?",
            (value["state"], json.dumps(value, ensure_ascii=False), ident),
        )
        db.execute(
            "INSERT INTO events(job_id,value) VALUES(?,?)",
            (
                ident,
                json.dumps(
                    dict(
                        state=value["state"],
                        completed=value.get("completed", 0),
                        failed=value.get("failed", 0),
                        at=value["updated_at"],
                    )
                ),
            ),
        )
    return value


def claim(ident):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        count = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE state IN ('PREPARING','RUNNING','CANCEL_REQUESTED')"
        ).fetchone()[0]
        if count:
            return False
        first = db.execute(
            "SELECT id FROM jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1"
        ).fetchone()
        if first is None or first[0] != ident:
            return False
        row = db.execute(
            "SELECT value FROM jobs WHERE id=? AND state='QUEUED'", (ident,)
        ).fetchone()
        if row is None:
            return False
        value = json.loads(row[0])
        from .resources import process_birth

        value.update(
            state="PREPARING",
            supervisor_pid=os.getpid(),
            supervisor_birth=process_birth(os.getpid()),
            started_at=time.time(),
        )
        db.execute(
            "UPDATE jobs SET state=?,value=? WHERE id=?",
            (value["state"], json.dumps(value, ensure_ascii=False), ident),
        )
    return True


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def cached_file(source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("文件不存在：" + str(source))
    sha = digest(source)
    destination = root() / "artifacts" / sha / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source != destination and (not destination.exists() or digest(destination) != sha):
        temporary = destination.with_name(destination.name + "." + uid() + ".tmp")
        shutil.copyfile(source, temporary)
        if digest(temporary) != sha:
            temporary.unlink(missing_ok=True)
            raise ValueError("复制过程中源文件发生变化")
        os.replace(temporary, destination)
    return dict(path=str(destination), sha256=sha, size=destination.stat().st_size)


def uv_binary():
    suffix = "windows-x86_64.exe" if sys.platform == "win32" else "linux-x86_64"
    for path in [
        resources() / "tools" / ("uv-" + suffix),
        root() / "tools" / ("uv-" + suffix),
    ]:
        if path.is_file():
            return str(path)
    found = shutil.which("uv")
    if not found:
        raise ValueError("未找到 uv。开发环境请安装 uv，发行包应携带 uv 工具。")
    return found


def environment_python(directory):
    return str(
        Path(directory) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    )


def platform_id():
    machine = platform.machine().lower()
    architecture = "x86_64" if machine in ("amd64", "x86_64") else machine
    return (
        (
            "windows"
            if sys.platform == "win32"
            else "linux"
            if sys.platform.startswith("linux")
            else sys.platform
        )
        + "-"
        + architecture
    )


def child_environment():
    env = os.environ.copy()
    env["MODELDOCK_DATA_DIR"] = str(root())
    env["MODELDOCK_RESOURCES"] = str(resources())
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(resources() / "packages/controller")
    return env


def spawn_controller(*args):
    env = child_environment()
    # The standard-library controller can import manifest validation without NumPy/Pillow.
    env["PYTHONPATH"] += os.pathsep + str(resources() / "packages/python-sdk/src")
    logs = root() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "controller.log").open("ab") as stream:
        return subprocess.Popen(
            [sys.executable, "-m", "modeldock.cli", *args],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            start_new_session=sys.platform != "win32",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
            if sys.platform == "win32"
            else 0,
        )
