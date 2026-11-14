"""Stream user-requested weight URLs into the current node's artifact cache."""

import hashlib
import json
import os
import re
import socket
import time
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import store
from .resources import process_birth
from modeldock_sdk.manifest import inside

MAX_BYTES = 2 * 1024**3
TERMINAL = {"succeeded", "failed", "cancelled"}


def validate_url(url):
    if not isinstance(url, str) or not 0 < len(url) <= 16384 or any(c in url for c in "\r\n\0"):
        raise ValueError("下载链接无效")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.port == 0:
            raise ValueError()
        if parsed.username is not None or parsed.password is not None:
            raise ValueError()
    except ValueError:
        raise ValueError("请使用 HTTP/HTTPS 下载直链，链接中不能包含用户名或密码") from None
    return url


def filename(value, formats):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 180
        or value[-1] in " ."
        or any(c in value for c in '/\\:*?"<>|\r\n\0')
        or any(ord(c) < 32 for c in value)
        or value.split(".", 1)[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("保存文件名无效，请仅填写文件名")
    if Path(value).suffix.lower().lstrip(".") not in formats:
        raise ValueError("所选模型仅支持这些权重格式：" + "、".join(formats))
    return value


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        if urlsplit(req.full_url).scheme == "https" and urlsplit(newurl).scheme != "https":
            raise ValueError("下载链接跳转到了不安全的 HTTP 地址，请使用 HTTPS 直链")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def directory(ident):
    if not isinstance(ident, str) or not re.fullmatch("[a-f0-9]{32}", ident):
        raise ValueError("下载标识无效")
    return store.root() / "downloads" / ident


def update(ident, **changes):
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT value FROM items WHERE kind='download' AND id=?", (ident,)
        ).fetchone()
        if row is None:
            raise ValueError("下载任务不存在")
        value = json.loads(row[0])
        if value["state"] in TERMINAL:
            return value
        if value["state"] == "cancelling" and changes.get("state") == "downloading":
            changes.pop("state")
        if value["state"] == "cancelling" and changes.get("state") in TERMINAL:
            changes = dict(state="cancelled", received=value["received"], finished_at=time.time())
        value.update(changes, updated_at=time.time())
        db.execute(
            "UPDATE items SET value=? WHERE kind='download' AND id=?", (json.dumps(value), ident)
        )
    return value


def status(ident):
    base = directory(ident)
    value = store.get("download", ident)
    if value is None:
        raise ValueError("下载任务不存在")
    if (
        value["state"] not in TERMINAL
        and not value.get("pid")
        and time.time() - value["created_at"] > 30
    ):
        value = update(
            ident, state="failed", error="下载启动已中断，请重试", finished_at=time.time()
        )
        for name in ("request.json", "weight.part"):
            (base / name).unlink(missing_ok=True)
    if (
        value["state"] not in TERMINAL
        and value.get("pid")
        and time.time() - value["created_at"] > 5
    ):
        birth = process_birth(value["pid"])
        if (
            birth is None
            or birth != "unknown"
            and value.get("birth") not in (None, "unknown", birth)
        ):
            value = update(
                ident, state="failed", error="下载进程已中断，请重试", finished_at=time.time()
            )
            for name in ("request.json", "weight.part"):
                (base / name).unlink(missing_ok=True)
    return value


def active():
    return [
        item
        for item in (status(d["id"]) for d in store.all_items("download"))
        if item["state"] not in TERMINAL
    ]


def start(args):
    plugin = store.get("plugin", args.get("plugin_id"))
    spec = (
        next((m for m in plugin["manifest"]["models"] if m["id"] == args.get("model_id")), None)
        if plugin
        else None
    )
    if not spec:
        raise ValueError("请选择插件支持的模型")
    formats = [f.lower() for f in spec["weight_formats"]]
    labels_path = None
    if args.get("pretrained") is True:
        preset = spec.get("extensions", {}).get("pretrained", {})
        candidates = preset.get("candidates", [])
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
            raise ValueError("此模型没有提供预训练权重下载来源")
        candidates = [
            dict(url=validate_url(c["url"]), filename=filename(c["filename"], formats))
            for c in candidates
        ]
        if preset.get("labels"):
            labels_path = str(inside(plugin["path"], preset["labels"]))
    else:
        raw_url = args.get("url", "")
        url = validate_url(raw_url.strip() if isinstance(raw_url, str) else raw_url)
        candidates = [dict(url=url, filename="")]
    name = args.get("filename", "").strip()
    if name:
        filename(name, formats)
    expected = args.get("sha256", "").strip().lower()
    if expected and not re.fullmatch("[a-f0-9]{64}", expected):
        raise ValueError("SHA-256 应为 64 位十六进制字符")
    active()  # Reconcile previously interrupted workers before applying the limit.
    ident = store.uid()
    value = dict(
        id=ident,
        state="queued",
        received=0,
        total=None,
        filename=name,
        node_id=os.environ.get("MODELDOCK_NODE_ID", "local"),
        created_at=time.time(),
    )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        count = sum(
            json.loads(row[0])["state"] not in TERMINAL
            for row in db.execute("SELECT value FROM items WHERE kind='download'")
        )
        if count >= 3:
            raise ValueError("当前节点最多同时下载 3 个权重文件")
        db.execute("INSERT INTO items VALUES('download',?,?)", (ident, json.dumps(value)))
    base = directory(ident)
    try:
        base.mkdir(parents=True)
        # Signed URLs may contain credentials. Keep them out of SQLite, API
        # responses and logs, and remove this private descriptor after reading.
        fd = os.open(base / "request.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                dict(
                    candidates=candidates,
                    filename=name,
                    formats=formats,
                    expected=expected,
                    labels_path=labels_path,
                ),
                stream,
            )
        child = store.spawn_controller("download", ident)
        update(ident, pid=child.pid, birth=process_birth(child.pid))
    except Exception:
        (base / "request.json").unlink(missing_ok=True)
        update(ident, state="failed", error="无法启动下载进程", finished_at=time.time())
        raise ValueError("无法启动下载进程，请重试") from None
    return status(ident)


def cancel(ident):
    value = status(ident)
    if value["state"] not in TERMINAL:
        (directory(ident) / "cancel").touch()
        value = update(ident, state="cancelling")
    return value


def run(ident):
    base = directory(ident)
    partial = base / "weight.part"
    received, total = 0, None

    def check_cancel():
        if (base / "cancel").exists():
            raise InterruptedError()

    def finish(**changes):
        # Terminal state means cleanup is already complete for API callers.
        partial.unlink(missing_ok=True)
        (base / "request.json").unlink(missing_ok=True)
        return update(ident, **changes, finished_at=time.time())

    try:
        with (base / "request.json").open(encoding="utf-8") as stream:
            spec = json.load(stream)
        (base / "request.json").unlink()
        check_cancel()
        update(ident, state="downloading", pid=os.getpid(), birth=process_birth(os.getpid()))
        response = None
        for index, candidate in enumerate(spec["candidates"]):
            check_cancel()
            request = Request(
                validate_url(candidate["url"]),
                headers={"User-Agent": "ModelDock", "Accept-Encoding": "identity"},
            )
            try:
                response = build_opener(Redirects()).open(request, timeout=30)
                break
            except HTTPError as exc:
                if exc.code != 404 or index == len(spec["candidates"]) - 1:
                    raise
                exc.close()
        with response:
            if response.status != 200:
                raise ValueError("服务器没有返回完整文件，请使用完整下载直链")
            if response.headers.get_content_type() in ("text/html", "application/xhtml+xml"):
                raise ValueError("链接返回的是网页，请使用权重文件的下载直链")
            header = response.headers.get("Content-Length")
            if header is not None:
                try:
                    total = int(header)
                except ValueError:
                    raise ValueError("服务器返回了无效文件长度") from None
                if not 0 < total <= MAX_BYTES:
                    raise ValueError("权重文件大小应为 1B–2GB")
            suggested = Message()
            suggested["Content-Disposition"] = response.headers.get("Content-Disposition", "")
            name = (
                spec["filename"]
                or candidate["filename"]
                or suggested.get_filename()
                or unquote(urlsplit(response.url).path.rsplit("/", 1)[-1])
            )
            if not name or not Path(name).suffix:
                name = "weights." + spec["formats"][0]
            name = filename(name, spec["formats"])
            update(ident, filename=name, total=total)
            sha = hashlib.sha256()
            last_update, deadline = 0, time.monotonic() + 3600
            with partial.open("wb") as stream:
                while True:
                    check_cancel()
                    if time.monotonic() > deadline:
                        raise ValueError("下载超过一小时，请检查网络后重试")
                    chunk = response.read1(256 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_BYTES or total is not None and received > total:
                        raise ValueError("下载内容超过允许的文件大小")
                    stream.write(chunk)
                    sha.update(chunk)
                    if time.monotonic() - last_update >= 0.2:
                        update(ident, received=received)
                        last_update = time.monotonic()
            if not received or total is not None and received != total:
                raise ValueError("文件下载不完整，请重试")
            checksum = sha.hexdigest()
            if spec["expected"] and spec["expected"] != checksum:
                raise ValueError("SHA-256 校验失败，文件未保存，请检查链接或校验值")
            check_cancel()
            target = store.root() / "artifacts" / checksum / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and store.digest(target) == checksum:
                partial.unlink()
            else:
                os.replace(partial, target)
            update(
                ident,
                state="succeeded",
                received=received,
                total=total,
                path=str(target),
                sha256=checksum,
                verified=bool(spec["expected"]),
                labels_path=spec.get("labels_path"),
                finished_at=time.time(),
            )
    except InterruptedError:
        finish(state="cancelled", received=received)
    except HTTPError as exc:
        finish(
            state="failed",
            error=f"服务器返回 HTTP {exc.code}，请检查下载直链与访问权限",
        )
    except (TimeoutError, socket.timeout):
        finish(state="failed", error="下载连接超时，请检查网络后重试")
    except URLError:
        finish(
            state="failed",
            error="无法连接下载服务器，请检查网络、证书或代理设置",
        )
    except ValueError as exc:
        finish(state="failed", error=str(exc))
    except Exception:
        finish(
            state="failed",
            error="下载失败，请检查网络与可用磁盘空间后重试",
        )
    finally:
        partial.unlink(missing_ok=True)
        (base / "request.json").unlink(missing_ok=True)
