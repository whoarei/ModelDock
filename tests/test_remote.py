import asyncio
import shutil
import sys
import threading
import time
import asyncssh
import pytest
from modeldock.cli import api
from conftest import wait_for


@pytest.mark.skipif(
    sys.platform != "linux" or not shutil.which("ssh-keyscan"),
    reason="Linux loopback SSH integration",
)
def test_ssh_deploy_upload_and_disconnected_task(environment, fixtures, tmp_path):
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    key = asyncssh.generate_private_key("ssh-ed25519")

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False

    async def execute(process):
        child = await asyncio.create_subprocess_shell(
            process.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        text = await process.stdin.read()
        stdout, stderr = await child.communicate(text.encode())
        process.stdout.write(stdout.decode(errors="replace"))
        process.stderr.write(stderr.decode(errors="replace"))
        process.exit(child.returncode)

    async def start(port):
        return await asyncssh.create_server(
            Server,
            "127.0.0.1",
            port,
            server_host_keys=[key],
            process_factory=execute,
            sftp_factory=asyncssh.SFTPServer,
        )

    listener = asyncio.run_coroutine_threadsafe(start(0), loop).result(10)
    port = listener.get_port()
    try:
        node = api(
            "add_node",
            dict(
                name="Loopback SSH",
                host="127.0.0.1",
                port=port,
                user="tester",
                work_root=str(tmp_path / "remote-node"),
            ),
        )
        with pytest.raises(ValueError, match="指纹"):
            api("connect_node", dict(id=node["id"]))
        keys = api("scan_node", dict(id=node["id"]))
        api("trust_node", dict(id=node["id"], fingerprints=[k["fingerprint"] for k in keys]))
        connected = api("connect_node", dict(id=node["id"]))
        assert (
            connected["status"] == "online"
            and connected["capabilities"]["platform"] == "linux-x86_64"
        )
        api(
            "install_plugin",
            dict(node_id=node["id"], plugin_id="efficientnet", profile_id="onnx-cpu"),
        )

        def installation():
            state = api("state", dict(node_id=node["id"]))
            return next(i for i in state["installations"] if i["id"] == "efficientnet")

        value = wait_for(installation, lambda i: i["state"] != "preparing", timeout=240)
        assert value["state"] == "ready", value
        model = api(
            "create_model",
            dict(
                node_id=node["id"],
                source="local",
                plugin_id="efficientnet",
                model_id="efficientnet_b0",
                name="Remote color classifier",
                weight_path=str(fixtures / "color-classifier.onnx"),
                labels_path=str(fixtures / "classification-labels.txt"),
                parameters={"top_k": 2},
            ),
        )
        assert model["state"] == "ready", model
        job = api(
            "start_task",
            dict(
                node_id=node["id"],
                source="local",
                model_instance_id=model["id"],
                paths=[str(fixtures / "red.png")],
                mode="benchmark",
                iterations=120,
                warmup=1,
            ),
        )
        # Each control request already closes its SSH session. Remove the listener
        # as well: the detached node supervisor must continue without any transport.
        listener.close()
        asyncio.run_coroutine_threadsafe(listener.wait_closed(), loop).result(10)
        time.sleep(0.8)
        listener = asyncio.run_coroutine_threadsafe(start(port), loop).result(10)
        result = wait_for(
            lambda: api("task_detail", dict(node_id=node["id"], task_id=job["id"])),
            lambda t: t["state"] in {"SUCCEEDED", "FAILED", "PARTIAL_FAILED", "CANCELLED"},
            timeout=90,
        )
        assert result["state"] == "SUCCEEDED", result
        assert result["completed"] == 120 and result["report"]["iterations"] == 120
        assert result["node_id"] == node["id"]
        assert result["results"][0]["prediction"]["top_k"][0]["label"] == "red"
        preview = api("preview", dict(node_id=node["id"], task_id=job["id"], sample_id="000000"))
        assert preview["url"].startswith("data:image/jpeg;base64,")
    finally:
        listener.close()
        asyncio.run_coroutine_threadsafe(listener.wait_closed(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
