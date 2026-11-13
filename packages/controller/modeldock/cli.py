import argparse
import base64
import json
import os
import platform
import sys
from pathlib import Path

from . import __version__, plugins, store, tasks


def initialize():
    for name in ("efficientnet", "yolo"):
        directory = store.resources() / "plugins" / name
        if not store.get("plugin", name) and (directory / "manifest.json").is_file():
            plugins.register(directory)


def plugin_metadata():
    values = store.all_items("plugin")
    for plugin in values:
        for model in plugin["manifest"]["models"]:
            for source, dest in (
                ("parameter_schema", "parameter_schema_data"),
                ("config", "config_data"),
            ):
                model[dest] = json.loads(
                    (Path(plugin["path"]) / model[source]).read_text(encoding="utf-8-sig")
                )
    return values


def local(command, args):
    if command in ("start_download", "download_status", "cancel_download"):
        from . import downloads

        if command == "start_download":
            return downloads.start(args)
        return (
            downloads.status(args["id"])
            if command == "download_status"
            else downloads.cancel(args["id"])
        )
    if command == "update_readiness":
        from .recovery import reconcile
        from . import downloads

        reconcile()
        active = store.active_jobs()
        preparing = [
            i
            for i in store.all_items("installation")
            if i["state"] in ("preparing", "uninstalling")
        ]
        downloading = downloads.active()
        return dict(
            ready=not active and not preparing and not downloading,
            reason="请先完成或取消本机测试任务，再安装应用更新"
            if active
            else (
                "请等待本机插件环境准备或卸载完成，再安装应用更新"
                if preparing
                else ("请等待本机权重下载完成或取消下载，再安装应用更新" if downloading else "")
            ),
            active_tasks=len(active),
            preparing_environments=len(preparing),
            active_downloads=len(downloading),
        )
    if command == "probe":
        import subprocess

        return dict(
            platform=store.platform_id(),
            python=sys.version.split()[0],
            uv=store.command_output(
                [store.uv_binary(), "--version"], text=True, encoding="utf-8", errors="replace"
            ).strip(),
        )
    if command == "probe_background":
        import subprocess

        token = args["token"]
        if len(token) != 32 or not token.isalnum():
            raise ValueError("探测标识无效")
        directory = store.root() / "probes"
        directory.mkdir(parents=True, exist_ok=True)
        script = (
            "import time,pathlib;time.sleep(1);pathlib.Path("
            + repr(str(directory / token))
            + ").write_text('alive')"
        )
        subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return dict(started=True)
    if command == "probe_check":
        token = args["token"]
        if len(token) != 32 or not token.isalnum():
            raise ValueError("探测标识无效")
        return dict(alive=(store.root() / "probes" / token).is_file())
    if command == "ensure_upload" or command == "finish_upload":
        sha = args["sha256"]
        name = args["name"]
        if (
            len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
            or not name
            or any(c in name for c in "/\\\r\n\0")
            or name in (".", "..")
        ):
            raise ValueError("上传文件标识无效")
        directory = store.root() / "uploads" / sha
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        if command == "finish_upload":
            temporary = args["temporary"]
            if not temporary.startswith(".upload-") or any(c in temporary for c in "/\\\r\n\0"):
                raise ValueError("临时文件标识无效")
            source = directory / temporary
            if store.digest(source) != sha:
                source.unlink(missing_ok=True)
                raise ValueError("上传文件摘要不匹配")
            os.replace(source, target)
            return dict(path=str(target))
        return dict(
            path=str(target),
            temporary=str(directory / (".upload-" + store.uid())),
            exists=target.is_file() and store.digest(target) == sha,
        )
    if command == "state":
        from .recovery import reconcile

        reconcile()
        initialize()
        installs = store.all_items("installation")
        for item in installs:
            path = store.root() / "plugins" / item["id"] / "prepare.log"
            if path.exists():
                with path.open("rb") as f:
                    f.seek(max(0, path.stat().st_size - 6000))
                    item["logs"] = f.read().decode("utf-8", errors="replace")
        return dict(
            node=dict(
                id=os.environ.get("MODELDOCK_NODE_ID", "local"),
                name=platform.node(),
                platform=store.platform_id(),
                python=sys.version.split()[0],
                cpu=platform.processor() or platform.machine(),
                data_dir=str(store.root()),
            ),
            plugins=plugin_metadata(),
            installations=installs,
            models=store.all_items("model"),
            tasks=store.jobs(),
            version=__version__,
        )
    if command == "import_plugin":
        return plugins.register(args["path"])
    if command == "install_plugin":
        return plugins.install(args["plugin_id"], args["profile_id"])
    if command == "uninstall_plugin":
        return plugins.uninstall(args["plugin_id"])
    if command == "create_model":
        return tasks.create_model(args)
    if command == "delete_model":
        if any(j["model_id"] == args["id"] for j in store.active_jobs()):
            raise ValueError("模型仍有未完成任务")
        store.delete("model", args["id"])
        return dict(ok=True)
    if command == "start_task":
        return tasks.start(args)
    if command == "retry_task":
        return tasks.retry(args["task_id"])
    if command == "cancel_task":
        return tasks.cancel(args["task_id"])
    if command == "task_detail":
        return tasks.details(args["task_id"])
    if command == "export":
        return tasks.export(args["task_id"], args.get("format", "json"))
    if command == "preview":
        value = store.job(args["task_id"])
        if args.get("artifact_id"):
            ident = args["artifact_id"]
            if (
                not isinstance(ident, str)
                or len(ident) != 32
                or any(c not in "0123456789abcdef" for c in ident)
            ):
                raise ValueError("产物标识无效")
            directory = store.root() / "jobs" / value["id"] / "artifacts"
            metadata = json.loads((directory / (ident + ".json")).read_text(encoding="utf-8"))
            if metadata["media_type"] not in ("image/png", "image/jpeg"):
                raise ValueError("不支持预览此产物")
            return dict(
                url="data:"
                + metadata["media_type"]
                + ";base64,"
                + base64.b64encode((directory / (ident + ".bin")).read_bytes()).decode()
            )
        sample_id = args["sample_id"]
        if not isinstance(sample_id, str) or not sample_id.isdigit() or len(sample_id) != 6:
            raise ValueError("样本标识无效")
        path = store.root() / "jobs" / value["id"] / "previews" / (sample_id + ".jpg")
        if not path.exists():
            return dict(url=None)
        return dict(url="data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode())
    raise ValueError("未知命令：" + command)


def api(command, args):
    if command in (
        "add_node",
        "scan_node",
        "trust_node",
        "connect_node",
        "remove_node",
    ):
        from . import remote

        return getattr(remote, command)(args)
    node_id = args.get("node_id", "local")
    if node_id != "local":
        from .remote import dispatch

        value = dispatch(node_id, command, args)
    else:
        value = local(command, args)
    if command == "state":
        value["nodes"] = [dict(id="local", name="本机", kind="local")] + store.all_items("node")
    if command == "export" and args.get("destination"):
        Path(args["destination"]).write_text(value["content"], encoding="utf-8")
        return dict(saved=True, path=args["destination"])
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["api", "prepare", "supervise", "serve", "download"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--port", type=int, default=4317)
    args = parser.parse_args()
    if args.action == "download":
        from .downloads import run

        run(args.value)
        return
    if args.action == "prepare":
        plugins.prepare(args.value)
        return
    if args.action == "supervise":
        tasks.supervise(args.value)
        return
    if args.action == "serve":
        from .server import serve

        serve(args.port)
        return
    try:
        request = json.load(sys.stdin)
        data = api(request["command"], request.get("args", {}))
        response = dict(ok=True, data=data)
    except Exception as exc:
        response = dict(ok=False, error=dict(message=str(exc), code=type(exc).__name__))
    print(json.dumps(response, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
