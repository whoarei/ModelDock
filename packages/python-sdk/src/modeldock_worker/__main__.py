import argparse
import contextlib
import importlib
import importlib.metadata
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
from modeldock_sdk import Context, PluginError, Sample, StagedPlugin, validate_prediction
from modeldock_sdk.manifest import inside
from modeldock_sdk.metadata import collect_model_metadata


def load(descriptor, context, overrides=None, threads=1):
    from jsonschema import validate

    package, instance = descriptor["plugin"], dict(descriptor["instance"])
    model = dict(next(m for m in package["manifest"]["models"] if m["id"] == instance["model_id"]))
    model["config_data"] = json.loads(
        inside(package["path"], model["config"]).read_text(encoding="utf-8-sig")
    )
    schema = json.loads(
        inside(package["path"], model["parameter_schema"]).read_text(encoding="utf-8-sig")
    )
    params = {
        key: value["default"]
        for key, value in schema.get("properties", {}).items()
        if "default" in value
    }
    params.update(instance.get("parameters", {}))
    params.update(overrides or {})
    try:
        validate(params, schema)
    except Exception as exc:
        raise PluginError(
            "参数不符合模型约定：" + str(exc).splitlines()[0],
            "INVALID_PARAMETERS",
            "load",
        ) from exc
    instance.update(
        weight_path=instance["weight"]["path"],
        effective_parameters=params,
        execution=dict(threads=threads),
    )
    sys.path.insert(0, package["path"])
    module, name = package["manifest"]["entrypoint"].split(":")
    plugin = getattr(importlib.import_module(module), name)()
    timing_mode = model.get("capabilities", {}).get("timing_mode", "predict_total")
    if timing_mode == "staged" and not isinstance(plugin, StagedPlugin):
        raise ValueError("声明 staged 计时的插件必须继承 StagedPlugin")
    for method in ("load", "predict", "close"):
        if not callable(getattr(plugin, method, None)):
            raise ValueError("插件缺少接口：" + method)
    try:
        plugin.load(context, model, instance)
    except BaseException:
        try:
            plugin.close()
        except Exception:
            pass
        raise
    return plugin, model, instance, params


def validate_model(path):
    descriptor = json.loads(Path(path).read_text(encoding="utf-8"))
    context = Context("validation", "local", Path(path).parent)
    with contextlib.redirect_stdout(sys.stderr):
        plugin, model, instance, params = load(descriptor, context)
        try:
            metadata = dict(
                parameters=params, task=model["task"], **collect_model_metadata(plugin, context)
            )
        finally:
            plugin.close()
    print(json.dumps(metadata, ensure_ascii=False, allow_nan=False))


def run(ident):
    from modeldock import store

    directory = store.root() / "jobs" / ident
    config = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    context = Context(ident, store.job(ident)["node_id"], directory)
    plugin = None
    records = []
    fatal = None
    cancelled = False
    loaded = 0
    params = {}
    loop_started = None
    processing_wall = 0
    try:
        context.raise_if_cancelled()
        if (
            store.digest(config["instance"]["weight"]["path"])
            != config["instance"]["weight"]["sha256"]
        ):
            raise ValueError("权重文件发生变化")
        start = time.perf_counter_ns()
        plugin, model, instance, params = load(
            config, context, config.get("parameters"), config["threads"]
        )
        loaded = (time.perf_counter_ns() - start) / 1e6
        store.update_job(ident, state="RUNNING", phase="warmup", load_ms=loaded)
        context.phase = "warmup"
        for index in range(config["warmup"]):
            context.raise_if_cancelled()
            value = config["inputs"][index % len(config["inputs"])]
            sample = Sample(str(index).zfill(6), Path(value["path"]), value["sha256"])
            try:
                plugin.predict(sample, params, context)
            except PluginError as exc:
                if exc.scope != "sample":
                    raise
        context.phase = "measurement"
        store.update_job(ident, phase="measurement")
        loop_started = time.perf_counter_ns()
        last_update = 0
        try:
            for index in range(config["iterations"]):
                context.raise_if_cancelled()
                value = config["inputs"][index % len(config["inputs"])]
                sample = Sample(str(index).zfill(6), Path(value["path"]), value["sha256"])
                record = dict(
                    record_schema="sample-result/1",
                    task_id=ident,
                    sample_id=sample.sample_id,
                    filename=sample.path.name,
                    status="failed",
                    prediction=None,
                    error=None,
                    timings_ms={},
                )
                try:
                    context.timings = {}
                    start = time.perf_counter_ns()
                    prediction = plugin.predict(sample, params, context)
                    elapsed = (time.perf_counter_ns() - start) / 1e6
                    validate_prediction(
                        prediction,
                        model,
                        sample,
                        instance.get("labels"),
                        context.artifacts.registry,
                    )
                    if (
                        sample.sample_id in context.image_sizes
                        and prediction["image_size"] != context.image_sizes[sample.sample_id]
                    ):
                        raise PluginError(
                            "结果尺寸与原图不一致",
                            "INVALID_PREDICTION",
                            "validate",
                            "sample",
                        )
                    timings = dict(
                        decode_ms=None,
                        preprocess_ms=None,
                        inference_ms=None,
                        postprocess_ms=None,
                        sample_total_ms=elapsed,
                    )
                    if model.get("capabilities", {}).get("timing_mode") == "staged":
                        timings.update(context.timings)
                    record.update(status="succeeded", prediction=prediction, timings_ms=timings)
                except PluginError as exc:
                    if exc.code == "CANCELLED":
                        raise
                    record["error"] = exc.as_dict()
                    if exc.scope != "sample":
                        raise
                records.append(record)
                # Persist before publishing the completed count. Forced cancellation
                # must retain every sample already shown as completed in the UI.
                with (directory / "results.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                if time.monotonic() - last_update > 0.2:
                    store.update_job(
                        ident,
                        completed=len(records),
                        failed=sum(r["status"] != "succeeded" for r in records),
                    )
                    last_update = time.monotonic()
        finally:
            processing_wall = (time.perf_counter_ns() - loop_started) / 1e6
    except PluginError as exc:
        if exc.code == "CANCELLED":
            cancelled = True
        else:
            fatal = exc.as_dict()
    except Exception as exc:
        import traceback

        traceback.print_exc()
        fatal = dict(
            code="PLUGIN_EXECUTION_FAILED",
            message=str(exc),
            phase="execute",
            scope="task",
            retryable=False,
        )
    finally:
        if plugin:
            try:
                plugin.close()
            except Exception as exc:
                context.log("warning", "资源释放失败", dict(message=str(exc)))
    try:
        if (
            store.digest(config["instance"]["weight"]["path"])
            != config["instance"]["weight"]["sha256"]
        ):
            fatal = dict(code="WEIGHT_CHANGED", message="测试期间权重发生变化", phase="finalize")
    except Exception as exc:
        fatal = dict(code="WEIGHT_CHANGED", message=str(exc), phase="finalize")
    success = [r for r in records if r["status"] == "succeeded"]
    metrics = dict(
        count=len(success),
        failed=len(records) - len(success),
        processing_wall_ms=processing_wall,
        load_ms=loaded,
        throughput=len(success) / (processing_wall / 1000) if processing_wall else 0,
        stages={},
    )
    for field in (
        "sample_total_ms",
        "decode_ms",
        "preprocess_ms",
        "inference_ms",
        "postprocess_ms",
    ):
        values = [r["timings_ms"][field] for r in success if r["timings_ms"].get(field) is not None]
        metrics["stages"][field] = (
            dict(
                mean=float(np.mean(values)),
                p50=float(np.percentile(values, 50)),
                p95=float(np.percentile(values, 95)),
            )
            if values
            else None
        )
    artifacts_start = time.perf_counter_ns()
    preview_dir = directory / "previews"
    preview_dir.mkdir(exist_ok=True)
    if records:
        store.update_job(ident, phase="artifacts", completed=len(records), failed=metrics["failed"])
    for record in records:
        if (directory / "cancel").exists():
            cancelled = True
            break
        if record["status"] != "succeeded":
            continue
        try:
            value = config["inputs"][int(record["sample_id"]) % len(config["inputs"])]
            image = context.read_image(Sample(record["sample_id"], Path(value["path"])))
            image.thumbnail((2048, 2048))
            image.save(preview_dir / (record["sample_id"] + ".jpg"), quality=88)
        except Exception as exc:
            context.log("warning", "预览生成失败", dict(message=str(exc)))
    metrics["artifact_write_ms"] = (time.perf_counter_ns() - artifacts_start) / 1e6
    with (directory / "results.jsonl").open("w", encoding="utf-8") as output:
        for row in records:
            output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    dependencies = {}
    verification_started = time.perf_counter_ns()
    try:
        if any(store.digest(item["path"]) != item["sha256"] for item in config["inputs"]):
            raise ValueError("测试期间输入文件发生变化")
    except Exception as exc:
        fatal = dict(
            code="INPUT_CHANGED",
            message="输入文件验证失败：" + str(exc),
            phase="finalize",
            scope="task",
            retryable=False,
        )
    metrics["input_verification_ms"] = (time.perf_counter_ns() - verification_started) / 1e6
    for name in ("modeldock-sdk", "onnxruntime", "numpy", "Pillow"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    cancelled = cancelled or (directory / "cancel").exists()
    report = dict(
        version="0.1.0",
        task_id=ident,
        parameters=params,
        model_configuration=config.get("model_configuration"),
        input_tensors=config["instance"].get("validation", {}).get("inputs", []),
        providers=config["instance"].get("validation", {}).get("providers"),
        model_name=config["instance"]["name"],
        model_id=config["instance"]["model_id"],
        plugin_version=config["plugin"]["manifest"]["version"],
        plugin_digest=config["plugin"]["digest"],
        weight_sha256=config["instance"]["weight"]["sha256"],
        labels_sha256=(config["instance"].get("label_artifact") or {}).get("sha256"),
        input_manifest_digest=config.get("input_manifest_digest"),
        unique_inputs=len(config["inputs"]),
        iterations=config["iterations"],
        warmup=config["warmup"],
        batch_size=1,
        threads=config["threads"],
        precision="model-defined",
        input_dtype=(config["instance"].get("validation", {}).get("inputs") or [{}])[0].get(
            "type", "plugin-defined"
        ),
        environment_fingerprint=config["installation"]["fingerprint"],
        profile=config["installation"]["profile_id"],
        system=platform.platform(),
        python=sys.version.split()[0],
        dependencies=dependencies,
        metrics=metrics,
        resources=store.job(ident).get("resources", []),
        artifacts=list(context.artifacts.registry.values()),
        percentile_method="linear",
        mode="pipeline",
        processing_window="Prediction, result validation and record bookkeeping; excludes loading, warmup, previews and network",
        input_cache="OS file cache; decoded on each execution",
        complete=not cancelled and fatal is None and len(records) == config["iterations"],
        fatal_error=fatal,
    )
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    if (directory / "cancel").exists():
        cancelled = True
    state = (
        "CANCELLED"
        if cancelled
        else "FAILED"
        if fatal or not success
        else "PARTIAL_FAILED"
        if len(success) != len(records)
        else "SUCCEEDED"
    )
    store.update_job(
        ident,
        state=state,
        phase="finished",
        completed=len(records),
        failed=metrics["failed"],
        metrics=metrics,
        finished_at=time.time(),
        error=fatal["message"] if fatal else None,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate")
    group.add_argument("--task")
    args = parser.parse_args()
    if args.validate:
        validate_model(args.validate)
    else:
        run(args.task)
