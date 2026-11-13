import os
import signal
import subprocess
import sys
import time
from . import store
from .resources import process_birth


def reconcile():
    for task in store.active_jobs():
        if not task.get("supervisor_pid") or time.time() - task["created_at"] < 3:
            continue
        birth = process_birth(task["supervisor_pid"])
        if birth == "unknown" or birth and task.get("supervisor_birth") in (None, "unknown", birth):
            continue
        worker = task.get("worker_pid")
        expected = task.get("worker_birth")
        if worker and expected not in (None, "unknown") and process_birth(worker) == expected:
            try:
                if sys.platform == "win32":
                    store.run_process(
                        ["taskkill", "/PID", str(worker), "/T", "/F"],
                        capture_output=True,
                        timeout=15,
                    )
                else:
                    os.killpg(worker, signal.SIGKILL)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        cancelled = (store.root() / "jobs" / task["id"] / "cancel").exists()
        store.update_job(
            task["id"],
            state="CANCELLED" if cancelled else "FAILED",
            error="任务监督进程已中断；可查看已保存结果并创建重试任务",
            finished_at=time.time(),
        )
    for installation in store.all_items("installation"):
        if (
            installation["state"] != "preparing"
            or not installation.get("prepare_pid")
            or time.time() - installation["started_at"] < 3
        ):
            continue
        birth = process_birth(installation["prepare_pid"])
        if (
            birth == "unknown"
            or birth
            and installation.get("prepare_birth") in (None, "unknown", birth)
        ):
            continue
        previous = installation.get("previous")
        if previous and previous.get("state") == "ready":
            previous["last_error"] = "环境准备进程中断，已保留先前环境"
            store.put("installation", installation["id"], previous)
        else:
            installation.update(state="failed", error="环境准备进程中断，请重试")
            installation.pop("previous", None)
            store.put("installation", installation["id"], installation)
