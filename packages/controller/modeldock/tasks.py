import csv
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import store

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def create_model(args):
    plugin = store.get("plugin", args["plugin_id"])
    installation = store.get("installation", args["plugin_id"])
    if (
        not plugin
        or not installation
        or installation["state"] != "ready"
        or installation["plugin_digest"] != plugin["digest"]
    ):
        raise ValueError("请先准备当前插件版本的运行环境")
    model = next((m for m in plugin["manifest"]["models"] if m["id"] == args["model_id"]), None)
    if model is None:
        raise ValueError("插件未声明此模型")
    weight = store.cached_file(args["weight_path"])
    if Path(weight["path"]).suffix.lstrip(".").lower() not in model["weight_formats"]:
        raise ValueError("权重格式与支持模型不一致")
    labels = None
    label_artifact = None
    if args.get("labels_path"):
        label_artifact = store.cached_file(args["labels_path"])
        labels = Path(label_artifact["path"]).read_text(encoding="utf-8-sig").splitlines()
        if not labels or any(not line.strip() for line in labels):
            raise ValueError("类别文件不能为空或含空行")
        labels = [line.strip() for line in labels]
    value = dict(
        id=store.uid(),
        name=args.get("name", "").strip() or model["name"],
        plugin_id=plugin["id"],
        model_id=model["id"],
        task=model["task"],
        weight=weight,
        labels=labels,
        label_artifact=label_artifact,
        parameters=args.get("parameters", {}),
        state="validating",
        created_at=time.time(),
    )
    store.put("model", value["id"], value)
    descriptor = store.root() / "staging" / (value["id"] + ".json")
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    descriptor.write_text(
        json.dumps(
            dict(plugin=plugin, installation=installation, instance=value),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [
                installation["python"],
                "-m",
                "modeldock_worker",
                "--validate",
                str(descriptor),
            ],
            env=store.child_environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if result.returncode:
            raise ValueError((result.stderr or result.stdout or "模型加载失败")[-4000:])
        value.update(state="ready", validation=json.loads(result.stdout))
    except Exception as exc:
        value.update(state="invalid", error=str(exc))
    finally:
        descriptor.unlink(missing_ok=True)
    return store.put("model", value["id"], value)


def start(args):
    instance = store.get("model", args["model_instance_id"])
    if not instance or instance["state"] != "ready":
        raise ValueError("请选择已通过加载验证的模型实例")
    plugin = store.get("plugin", instance["plugin_id"])
    installation = store.get("installation", instance["plugin_id"])
    if (
        not installation
        or installation["state"] != "ready"
        or installation["plugin_digest"] != plugin["digest"]
    ):
        raise ValueError("当前插件环境未就绪")
    files = []
    for value in args.get("paths", []):
        path = Path(value).resolve()
        if path.is_dir():
            files.extend(
                p
                for p in sorted(path.rglob("*"))
                if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
            )
        elif path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            files.append(path)
        else:
            raise ValueError("图片或目录不存在，或图片格式不支持")
    files = list(dict.fromkeys(str(p) for p in files))
    if not files or len(files) > 10000:
        raise ValueError("请选择 1 至 10000 张图片")
    mode = args.get("mode", "batch")
    if mode not in ("single", "batch", "benchmark"):
        raise ValueError("不支持的测试模式")
    if mode == "single" and len(files) != 1:
        raise ValueError("单图模式只能选择一张图片")
    iterations = int(args.get("iterations", 100)) if mode == "benchmark" else len(files)
    warmup = int(args.get("warmup", 10)) if mode == "benchmark" else 0
    if not 1 <= iterations <= 10000 or not 0 <= warmup <= 10000:
        raise ValueError("执行次数应为 1–10000，预热次数应为 0–10000")
    threads = int(args.get("threads", 1))
    if not 1 <= threads <= 64:
        raise ValueError("线程数应为 1–64")
    ident = args.get("task_id") or store.uid()
    if (
        not isinstance(ident, str)
        or len(ident) != 32
        or any(c not in "0123456789abcdef" for c in ident)
    ):
        raise ValueError("任务标识无效")
    config = dict(
        instance=instance,
        plugin=plugin,
        installation=installation,
        paths=files,
        mode=mode,
        iterations=iterations,
        warmup=warmup,
        threads=threads,
        parameters=args.get("parameters", {}),
        timeout_seconds=min(max(int(args.get("timeout_seconds", 3600)), 10), 86400),
    )
    config_digest = (
        __import__("hashlib")
        .sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode())
        .hexdigest()
    )
    try:
        existing = store.job(ident)
    except ValueError:
        existing = None
    if existing:
        if existing["config_digest"] != config_digest:
            raise ValueError("任务标识已关联其他配置")
        return existing
    value = dict(
        id=ident,
        state="QUEUED",
        plugin_id=instance["plugin_id"],
        model_id=instance["id"],
        model_name=instance["name"],
        task=instance["task"],
        mode=mode,
        total=iterations,
        completed=0,
        failed=0,
        created_at=time.time(),
        config_digest=config_digest,
        environment_fingerprint=installation["fingerprint"],
        retry_of=args.get("retry_of"),
        node_id=os.environ.get("MODELDOCK_NODE_ID", "local"),
    )
    try:
        store.new_job(value)
    except __import__("sqlite3").IntegrityError:
        existing = store.job(ident)
        if existing["config_digest"] != config_digest:
            raise ValueError("任务标识已关联其他配置")
        return existing
    try:
        directory = store.root() / "jobs" / ident
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "task.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
        child = store.spawn_controller("supervise", ident)
        from .resources import process_birth

        store.update_job(ident, supervisor_pid=child.pid, supervisor_birth=process_birth(child.pid))
    except Exception as exc:
        store.update_job(ident, state="FAILED", error=str(exc))
        raise
    return value


def retry(ident):
    original = store.job(ident)
    if original["state"] not in store.TERMINAL:
        raise ValueError("任务尚未结束")
    config = json.loads((store.root() / "jobs" / ident / "task.json").read_text(encoding="utf-8"))
    active = store.get("installation", original["plugin_id"])
    if not active or active.get("fingerprint") != config["installation"]["fingerprint"]:
        raise ValueError("运行环境已变化，无法按原配置重测；请在工作台新建测试")
    if not store.get("model", original["model_id"]):
        raise ValueError("原模型实例已删除，请重新导入")
    for item in config.get("inputs", []):
        if not Path(item["path"]).is_file() or store.digest(item["path"]) != item["sha256"]:
            raise ValueError("输入文件已变化，无法按原配置重测")
    return start(
        dict(
            model_instance_id=original["model_id"],
            paths=config["paths"],
            mode=config["mode"],
            iterations=config["iterations"],
            warmup=config["warmup"],
            threads=config["threads"],
            parameters=config["parameters"],
            timeout_seconds=config["timeout_seconds"],
            retry_of=ident,
        )
    )


def cancel(ident):
    value = store.job(ident)
    if value["state"] in store.TERMINAL:
        return value
    (store.root() / "jobs" / ident / "cancel").touch()
    if value["state"] == "QUEUED":
        return store.update_job(ident, state="CANCELLED", finished_at=time.time())
    return store.update_job(ident, state="CANCEL_REQUESTED")


def supervise(ident):
    directory = store.root() / "jobs" / ident
    while not store.claim(ident):
        if store.job(ident)["state"] in store.TERMINAL:
            return
        time.sleep(0.25)
    process = None
    try:
        config = json.loads((directory / "task.json").read_text(encoding="utf-8"))
        if (directory / "cancel").exists():
            store.update_job(ident, state="CANCELLED", finished_at=time.time())
            return
        for path in config["paths"]:
            if not Path(path).is_file():
                raise ValueError("输入文件已丢失：" + path)
        config["inputs"] = [dict(path=p, sha256=store.digest(p)) for p in config["paths"]]
        config["input_manifest_digest"] = (
            __import__("hashlib")
            .sha256(json.dumps(config["inputs"], sort_keys=True).encode())
            .hexdigest()
        )
        (directory / "task.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
        env = store.child_environment()
        with (directory / "worker.log").open("wb") as output:
            process = subprocess.Popen(
                [
                    config["installation"]["python"],
                    "-m",
                    "modeldock_worker",
                    "--task",
                    ident,
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=sys.platform != "win32",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            from .resources import process_birth

            store.update_job(ident, worker_pid=process.pid, worker_birth=process_birth(process.pid))
            start_time = time.monotonic()
            cancel_time = None
            resource_samples = []
            last_sample = 0
            while process.poll() is None:
                (directory / "heartbeat").touch()
                if (directory / "cancel").exists():
                    cancel_time = cancel_time or time.monotonic()
                if time.monotonic() - start_time > config["timeout_seconds"]:
                    raise TimeoutError("测试任务超时")
                if cancel_time and time.monotonic() - cancel_time > 5:
                    terminate(process)
                    store.update_job(ident, state="CANCELLED", finished_at=time.time())
                    return
                if time.monotonic() - last_sample >= 0.5:
                    from .resources import rss_mb

                    rss = rss_mb(process.pid)
                    if rss is not None:
                        resource_samples.append(
                            dict(elapsed=time.monotonic() - start_time, rss_mb=rss)
                        )
                        if len(resource_samples) > 3600:
                            resource_samples = resource_samples[::2]
                        store.update_job(ident, resources=resource_samples)
                    last_sample = time.monotonic()
                time.sleep(0.2)
        if store.job(ident)["state"] not in store.TERMINAL:
            store.update_job(
                ident,
                state="CANCELLED" if (directory / "cancel").exists() else "FAILED",
                error="工作进程异常退出，请查看日志",
                finished_at=time.time(),
            )
    except Exception as exc:
        if process and process.poll() is None:
            terminate(process)
        store.update_job(ident, state="FAILED", error=str(exc), finished_at=time.time())


def terminate(process):
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15)


def details(ident):
    value = store.job(ident)
    directory = store.root() / "jobs" / ident
    records = []
    file = directory / "results.jsonl"
    if file.exists():
        for index, line in enumerate(file.read_text(encoding="utf-8").splitlines()):
            if index >= 10000:
                break
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    value["results"] = records
    logfile = directory / "worker.log"
    if logfile.exists():
        with logfile.open("rb") as f:
            f.seek(max(0, logfile.stat().st_size - 12000))
            value["logs"] = f.read().decode("utf-8", errors="replace")
    if (directory / "report.json").exists():
        value["report"] = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    return value


def export(ident, format):
    value = details(ident)
    if format == "json":
        content = json.dumps(value, ensure_ascii=False, indent=2)
    elif format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "sample_id",
                "filename",
                "status",
                "sample_total_ms",
                "inference_ms",
                "predictions",
                "error",
            ]
        )
        for row in value["results"]:
            writer.writerow(
                [
                    row["sample_id"],
                    row.get("filename"),
                    row["status"],
                    row.get("timings_ms", {}).get("sample_total_ms"),
                    row.get("timings_ms", {}).get("inference_ms"),
                    json.dumps(row.get("prediction"), ensure_ascii=False),
                    row.get("error", {}).get("message", "") if row.get("error") else "",
                ]
            )
        content = "\ufeff" + output.getvalue()
    else:
        raise ValueError("仅支持 JSON / CSV")
    return dict(filename="modeldock-" + ident[:8] + "." + format, content=content)
