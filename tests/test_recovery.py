import os
import signal
import time
from modeldock import store
from modeldock.cli import api
from conftest import wait_for, finish


def test_interrupted_supervisor_and_next_task(classifier, fixtures):
    job = api(
        "start_task",
        dict(
            model_instance_id=classifier["id"],
            paths=[str(fixtures / "red.png")],
            mode="benchmark",
            iterations=10000,
            warmup=0,
        ),
    )
    current = wait_for(
        lambda: store.job(job["id"]), lambda j: j["state"] == "RUNNING" and j.get("worker_pid")
    )
    os.kill(current["supervisor_pid"], signal.SIGTERM)
    time.sleep(3.1)
    api("state", {})
    recovered = api("task_detail", dict(task_id=job["id"]))
    assert recovered["state"] == "FAILED"
    assert "监督进程已中断" in recovered["error"]
    second = api(
        "start_task",
        dict(model_instance_id=classifier["id"], paths=[str(fixtures / "blue.png")], mode="single"),
    )
    assert finish(second["id"])["state"] == "SUCCEEDED"


def test_interrupted_environment_preserves_previous(environment):
    previous = store.get("installation", "efficientnet")
    failed = dict(
        id="efficientnet",
        state="preparing",
        prepare_pid=2147483646,
        prepare_birth="dead",
        started_at=time.time() - 10,
        previous=previous,
    )
    store.put("installation", "efficientnet", failed)
    api("state", {})
    current = store.get("installation", "efficientnet")
    assert current["state"] == "ready" and current["fingerprint"] == previous["fingerprint"]
    assert "进程中断" in current["last_error"]
