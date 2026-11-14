"""Dependency-free manifest validation, also used before environments exist."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

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
        extensions = model.get("extensions", {})
        if not isinstance(extensions, dict):
            raise ValueError("模型 extensions 必须为对象")
        common = extensions.get("modeldock", {})
        if not isinstance(common, dict) or set(common) - {"family", "pretrained"}:
            raise ValueError("extensions.modeldock 包含未知字段")
        if "family" in common and (
            not isinstance(common["family"], str) or not common["family"].strip()
        ):
            raise ValueError("模型家族必须为非空字符串")
        if "pretrained" in common:
            preset = common["pretrained"]
            if not isinstance(preset, dict) or set(preset) - {
                "candidates",
                "labels",
                "parameters",
                "label_set",
                "license",
                "homepage",
            }:
                raise ValueError("预训练扩展字段无效")
            parameters = preset.get("parameters", {})
            if not isinstance(parameters, dict) or set(parameters) - schema["properties"].keys():
                raise ValueError("预训练参数必须在参数描述中声明")
            for key in ("label_set", "license", "homepage"):
                if key in preset and not isinstance(preset[key], str):
                    raise ValueError("预训练扩展的 " + key + " 必须为字符串")
            if "labels" in preset and not inside(root, preset["labels"]).is_file():
                raise ValueError("预训练类别路径必须为文件")
            candidates = preset.get("candidates")
            if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
                raise ValueError("预训练下载需提供 1 至 3 个候选文件")
            for candidate in candidates:
                if not isinstance(candidate, dict) or set(candidate) != {"url", "filename"}:
                    raise ValueError("预训练候选需要 url 和 filename")
                url, name = candidate["url"], candidate["filename"]
                if not isinstance(url, str) or any(c in url for c in "\r\n\0"):
                    raise ValueError("预训练 URL 无效")
                parsed = urlsplit(url)
                if (
                    parsed.scheme not in ("http", "https")
                    or not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                ):
                    raise ValueError("预训练来源必须为不含用户名密码的 HTTP/HTTPS URL")
                if (
                    not isinstance(name, str)
                    or not name
                    or any(c in name for c in '/\\:*?"<>|\r\n\0')
                    or Path(name).suffix.lstrip(".").lower() not in model["weight_formats"]
                ):
                    raise ValueError("预训练文件名或权重格式无效")
    return obj
