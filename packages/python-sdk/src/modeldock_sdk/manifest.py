"""Dependency-free manifest validation, also used before environments exist."""

import json
import re
from pathlib import Path

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def inside(root, value):
    root = Path(root).resolve()
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("插件文件必须使用非空相对路径")
    path = (root / value).resolve()
    if path != root and root not in path.parents:
        raise ValueError("插件文件路径越界")
    if not path.exists():
        raise ValueError(f"插件文件不存在：{value}")
    return path


def read_manifest(root):
    root = Path(root)
    obj = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    required = {
        "schema_version",
        "id",
        "name",
        "version",
        "sdk_version",
        "entrypoint",
        "runtime_profiles",
        "models",
    }
    if required - obj.keys() or obj.keys() - required - {"extensions"}:
        raise ValueError("清单缺少必填字段或包含未知字段")
    if obj["schema_version"] != "1" or not IDENTIFIER.fullmatch(obj["id"]):
        raise ValueError("不支持的清单版本或插件标识")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", obj["version"]):
        raise ValueError("插件版本必须为 MAJOR.MINOR.PATCH")
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", obj["entrypoint"]):
        raise ValueError("入口必须为 模块:类")
    for field in ("name", "sdk_version"):
        if not isinstance(obj[field], str) or not obj[field].strip():
            raise ValueError(f"清单字段无效：{field}")
    for field in ("runtime_profiles", "models"):
        values = obj[field]
        if not isinstance(values, list) or not values:
            raise ValueError(f"{field} 必须为非空列表")
        seen = set()
        for item in values:
            if (
                not isinstance(item, dict)
                or not IDENTIFIER.fullmatch(str(item.get("id", "")))
                or item["id"] in seen
            ):
                raise ValueError(f"{field} 包含无效或重复标识")
            seen.add(item["id"])
    for profile in obj["runtime_profiles"]:
        for name in ("platforms", "providers"):
            if (
                not isinstance(profile.get(name), list)
                or not profile[name]
                or not all(isinstance(s, str) for s in profile[name])
            ):
                raise ValueError(f"运行方案缺少 {name}")
        directory = inside(root, profile["project_dir"])
        for name in ("pyproject.toml", "uv.lock", ".python-version"):
            inside(directory, name)
    for model in obj["models"]:
        if (
            model.get("task") not in ("classification", "detection")
            or model.get("result_schema") != model["task"] + "/1"
        ):
            raise ValueError("不支持的任务或结果协议")
        if (
            not isinstance(model.get("name"), str)
            or not model["name"].strip()
            or not isinstance(model.get("weight_formats"), list)
            or not model["weight_formats"]
            or not all(isinstance(v, str) and v.isalnum() for v in model["weight_formats"])
        ):
            raise ValueError("模型需要名称与权重格式")
        config = json.loads(inside(root, model["config"]).read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("模型配置必须为 JSON 对象")
        schema = json.loads(inside(root, model["parameter_schema"]).read_text(encoding="utf-8-sig"))
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise ValueError("参数描述必须为 object，且提供 properties")
        supported = {
            "type",
            "title",
            "description",
            "properties",
            "required",
            "additionalProperties",
            "default",
            "minimum",
            "maximum",
            "enum",
            "x-modeldock",
        }

        def check(part):
            if not isinstance(part, dict) or set(part) - supported:
                raise ValueError("参数描述包含不支持的校验关键字")
            for child in part.get("properties", {}).values():
                check(child)

        check(schema)
    return obj
