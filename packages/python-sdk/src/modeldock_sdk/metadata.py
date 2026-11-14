"""Backend-independent optional describe(context) contract and legacy bridge."""

import json

from .core import PluginError


def validate_model_metadata(value):
    try:
        if not isinstance(value, dict) or value.get("schema_version") != "1":
            raise ValueError("describe 必须返回 schema_version 为 1 的对象")
        if set(value) - {"schema_version", "providers", "inputs", "outputs", "extensions"}:
            raise ValueError("未知字段应放入 extensions")
        providers = value.get("providers", [])
        if not isinstance(providers, list) or not all(
            isinstance(p, str) and p.strip() for p in providers
        ):
            raise ValueError("providers 必须为非空名称的列表")
        if "extensions" in value and not isinstance(value["extensions"], dict):
            raise ValueError("extensions 必须为对象")
        for field in ("inputs", "outputs"):
            tensors = value.get(field, [])
            if not isinstance(tensors, list):
                raise ValueError(field + " 必须为列表")
            seen = set()
            for tensor in tensors:
                if not isinstance(tensor, dict) or set(tensor) - {
                    "name",
                    "shape",
                    "dtype",
                    "type",
                    "extensions",
                }:
                    raise ValueError("张量描述字段无效")
                name, shape, dtype = tensor.get("name"), tensor.get("shape"), tensor.get("dtype")
                if not isinstance(name, str) or not name or name in seen:
                    raise ValueError("张量名称必须非空且同组唯一")
                seen.add(name)
                if not isinstance(dtype, str) or not dtype.strip():
                    raise ValueError("张量需要 dtype")
                if not isinstance(shape, list) or not all(
                    d is None or type(d) is int and d >= 0 or isinstance(d, str) and bool(d)
                    for d in shape
                ):
                    raise ValueError("shape 应使用非负整数、符号维度或 null")
                if "extensions" in tensor and not isinstance(tensor["extensions"], dict):
                    raise ValueError("张量 extensions 必须为对象")
        # Normalize tuples in extension data and reject tensors, arrays and NaN.
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise PluginError(
            "模型元数据不符合 describe/1：" + str(exc), "INVALID_MODEL_METADATA", "describe"
        ) from exc


def collect_model_metadata(plugin, context):
    describe = getattr(plugin, "describe", None)
    if describe is not None and not callable(describe):
        raise PluginError("describe 必须为可调用方法", "INVALID_MODEL_METADATA", "describe")
    if callable(describe):
        return validate_model_metadata(describe(context))
    # SDK 0.1.0 exposed session metadata by convention. Preserve that behavior
    # for old adapters only; new adapters implement the public describe hook.
    session = getattr(plugin, "session", None)
    value = dict(schema_version="1", providers=[], inputs=[])
    if callable(getattr(session, "get_providers", None)):
        value["providers"] = session.get_providers()
    if callable(getattr(session, "get_inputs", None)):
        value["inputs"] = [
            dict(name=i.name, shape=list(i.shape), dtype=i.type, type=i.type)
            for i in session.get_inputs()
        ]
    return validate_model_metadata(value)
