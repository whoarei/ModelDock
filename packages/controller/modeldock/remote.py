"""OpenSSH transport. No passwords or private-key contents are stored."""

import base64
import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from . import store


def node(ident):
    value = store.get("node", ident)
    if not value:
        raise ValueError("远程节点不存在")
    return value


def add_node(args):
    host = str(args.get("host", "")).strip()
    user = str(args.get("user", "")).strip()
    port = int(args.get("port", 22))
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", host)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", user)
        or not 1 <= port <= 65535
    ):
        raise ValueError("SSH 主机、用户或端口无效")
    key = args.get("key_path", "").strip()
    if key and not Path(key).is_file():
        raise ValueError("SSH 私钥文件不存在")
    value = dict(
        id=store.uid(),
        name=args.get("name", "").strip() or host,
        kind="ssh",
        host=host,
        user=user,
        port=port,
        key_path=key,
        work_root=args.get("work_root", "").strip() or "~/.local/share/modeldock",
        status="unconfigured",
        trusted=False,
    )
    return store.put("node", value["id"], value)


def scan_node(args):
    value = node(args["id"])
    executable = shutil.which("ssh-keyscan")
    if not executable:
        raise ValueError("未找到 ssh-keyscan，请启用 Windows OpenSSH 客户端")
    process = subprocess.run(
        [executable, "-T", "5", "-p", str(value["port"]), value["host"]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    keys = []
    for line in process.stdout.splitlines():
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            fingerprint = "SHA256:" + base64.b64encode(
                hashlib.sha256(base64.b64decode(parts[2], validate=True)).digest()
            ).decode().rstrip("=")
        except ValueError:
            continue
        keys.append(dict(line=line, type=parts[1], fingerprint=fingerprint))
    if not keys:
        raise ValueError("无法读取主机公钥：" + (process.stderr or "请检查主机和端口")[-1000:])
    value["scanned_keys"] = keys
    store.put("node", value["id"], value)
    return keys


def known_hosts(value):
    return store.root() / "ssh" / (value["id"] + "_known_hosts")


def trust_node(args):
    value = node(args["id"])
    keys = value.get("scanned_keys", [])
    selected = set(args.get("fingerprints", []))
    if not selected or not selected.issubset({k["fingerprint"] for k in keys}):
        raise ValueError("请选择已核对的主机指纹")
    path = known_hosts(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(k["line"] for k in keys if k["fingerprint"] in selected) + "\n",
        encoding="utf-8",
    )
    value.update(trusted=True, status="trusted")
    store.put("node", value["id"], value)
    return value


def options(value):
    if not value.get("trusted") or not known_hosts(value).is_file():
        raise ValueError("请先扫描并核对 SSH 主机指纹")
    args = [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        'UserKnownHostsFile="' + known_hosts(value).as_posix().replace('"', '\\"') + '"',
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
    ]
    if value.get("key_path"):
        args.extend(["-i", value["key_path"], "-o", "IdentitiesOnly=yes"])
    return args


def ssh(value, command, payload=None, timeout=60):
    executable = shutil.which("ssh")
    if not executable:
        raise ValueError("未找到 OpenSSH 客户端")
    process = subprocess.run(
        [
            executable,
            *options(value),
            "-p",
            str(value["port"]),
            "-T",
            value["user"] + "@" + value["host"],
            command,
        ],
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if process.returncode:
        raise ValueError("SSH 执行失败：" + (process.stderr or process.stdout)[-3000:])
    try:
        return json.loads(process.stdout)
    except ValueError as exc:
        raise ValueError("SSH 节点返回了无效响应：" + process.stdout[-1000:]) from exc


BOOTSTRAP = """import base64,hashlib,io,json,os,pathlib,sys,zipfile
sys.stdin.reconfigure(encoding="utf-8");sys.stdout.reconfigure(encoding="utf-8")
if sys.version_info < (3,11): raise RuntimeError("节点需要 Python 3.11 或更新版本")
r=json.load(sys.stdin)
root=pathlib.Path(r["root"]).expanduser().resolve()
blob=base64.b64decode(r["bundle"])
if hashlib.sha256(blob).hexdigest()!=r["digest"]:raise RuntimeError("部署包校验失败")
target=root/"controller"/r["digest"][:20]
target.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(io.BytesIO(blob)) as z:
 for entry in z.infolist():
  p=(target/entry.filename).resolve()
  if target not in p.parents:raise RuntimeError("部署路径越界")
 z.extractall(target)
uv=target/"tools/uv-linux-x86_64"
if uv.exists():uv.chmod(0o755)
print(json.dumps({"root":str(root),"resources":str(target),"python":sys.executable}))
"""


RPC = """import json,os,sys
sys.stdin.reconfigure(encoding="utf-8");sys.stdout.reconfigure(encoding="utf-8")
r=json.load(sys.stdin)
os.environ["MODELDOCK_DATA_DIR"]=r["root"]
os.environ["MODELDOCK_RESOURCES"]=r["resources"]
os.environ["MODELDOCK_NODE_ID"]=r["node_id"]
sys.path[:0]=[r["resources"]+"/packages/controller",r["resources"]+"/packages/python-sdk/src"]
from modeldock.cli import local
try:out={"ok":True,"data":local(r["command"],r["args"])}
except Exception as e:out={"ok":False,"error":str(e)}
print(json.dumps(out,ensure_ascii=False,allow_nan=False))
"""


def rpc(value, command, args=None, timeout=90):
    if not value.get("resources"):
        raise ValueError("请先检查并部署远程节点")
    result = ssh(
        value,
        shlex.quote(value["python"]) + " -c " + shlex.quote(RPC),
        dict(
            root=value["root"],
            resources=value["resources"],
            node_id=value["id"],
            command=command,
            args=args or {},
        ),
        timeout,
    )
    if not result["ok"]:
        raise ValueError(result["error"])
    return result["data"]


def connect_node(args):
    value = node(args["id"])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("packages/controller", "packages/python-sdk/src"):
            for path in sorted((store.resources() / directory).rglob("*.py")):
                archive.write(path, path.relative_to(store.resources()).as_posix())
        uv = store.resources() / "tools/uv-linux-x86_64"
        if uv.is_file():
            archive.write(uv, "tools/uv-linux-x86_64")
    blob = stream.getvalue()
    try:
        deployed = ssh(
            value,
            "python3 -c " + shlex.quote(BOOTSTRAP),
            dict(
                root=value["work_root"],
                bundle=base64.b64encode(blob).decode(),
                digest=hashlib.sha256(blob).hexdigest(),
            ),
            120,
        )
        value.update(deployed)
        capabilities = rpc(value, "probe")
        token = store.uid()
        rpc(value, "probe_background", dict(token=token))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            time.sleep(0.3)
            if rpc(value, "probe_check", dict(token=token))["alive"]:
                break
        else:
            raise ValueError("节点未通过 SSH 断开后的后台进程存活检查")
        value.update(
            status="online",
            capabilities=capabilities,
            last_error=None,
            checked_at=time.time(),
        )
    except Exception as exc:
        value.update(status="unreachable", last_error=str(exc))
        store.put("node", value["id"], value)
        raise
    return store.put("node", value["id"], value)


def upload(value, source):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("上传文件不存在")
    sha = store.digest(source)
    target = rpc(value, "ensure_upload", dict(sha256=sha, name=source.name))
    if target["exists"]:
        return target["path"]
    executable = shutil.which("sftp")
    if not executable:
        raise ValueError("未找到 sftp 客户端")

    def quote(path):
        if any(c in str(path) for c in "\r\n\0"):
            raise ValueError("文件名包含不支持的字符")
        return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'

    host = "[" + value["host"] + "]" if ":" in value["host"] else value["host"]
    process = subprocess.run(
        [
            executable,
            *options(value),
            "-P",
            str(value["port"]),
            "-b",
            "-",
            value["user"] + "@" + host,
        ],
        input="put " + quote(source) + " " + quote(target["temporary"]) + "\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=900,
    )
    if process.returncode:
        raise ValueError("SFTP 上传失败：" + process.stderr[-2000:])
    return rpc(
        value,
        "finish_upload",
        dict(sha256=sha, name=source.name, temporary=Path(target["temporary"]).name),
    )["path"]


def dispatch(ident, command, args):
    value = node(ident)
    args = dict(args)
    args.pop("node_id", None)
    args.pop("destination", None)
    if command == "install_plugin":
        from .cli import initialize, plugin_metadata

        initialize()
        plugin = store.get("plugin", args["plugin_id"])
        if plugin is None:
            raise ValueError("请先在本机导入该插件包")
        bundle = store.root() / "staging" / (plugin["digest"] + ".zip")
        bundle.parent.mkdir(parents=True, exist_ok=True)
        if not bundle.exists():
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(Path(plugin["path"]).rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(plugin["path"]).as_posix())
        uploaded = upload(value, bundle)
        rpc(value, "import_plugin", dict(path=uploaded))
    if command == "import_plugin":
        from .plugins import register

        return register(args["path"])
    if args.pop("source", "remote") == "local":
        if command == "create_model":
            args["weight_path"] = upload(value, args["weight_path"])
            if args.get("labels_path"):
                args["labels_path"] = upload(value, args["labels_path"])
        if command == "start_task":
            from .tasks import IMAGE_SUFFIXES

            sources = []
            for path in map(Path, args.get("paths", [])):
                sources.extend(
                    [
                        p
                        for p in sorted(path.rglob("*"))
                        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
                    ]
                    if path.is_dir()
                    else [path]
                )
            if len(sources) > 10000:
                raise ValueError("最多上传 10000 张图片")
            args["paths"] = [upload(value, p) for p in sources]
    result = rpc(value, command, args, timeout=180)
    if command == "state":
        from .cli import initialize

        initialize()
        existing = {p["id"] for p in result["plugins"]}
        from .cli import plugin_metadata

        result["plugins"] += [p for p in plugin_metadata() if p["id"] not in existing]
        value.update(status="online", last_error=None)
        store.put("node", ident, value)
    return result


def remove_node(args):
    value = node(args["id"])
    store.delete("node", value["id"])
    known_hosts(value).unlink(missing_ok=True)
    return dict(ok=True)
