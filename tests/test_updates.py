from modeldock.cli import api
from modeldock import store


def test_update_waits_for_tasks_and_environment_operations(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELDOCK_DATA_DIR", str(tmp_path))
    assert api("update_readiness", {})["ready"]
    store.put("installation", "update-test", dict(id="update-test", state="uninstalling"))
    try:
        readiness = api("update_readiness", {})
        assert not readiness["ready"] and readiness["preparing_environments"] == 1
        assert "环境" in readiness["reason"]
    finally:
        store.delete("installation", "update-test")
    ident = store.uid()
    with store.connect() as db:
        import json

        db.execute(
            "INSERT INTO jobs VALUES(?,?,?)",
            (ident, "QUEUED", json.dumps(dict(id=ident, state="QUEUED"))),
        )
    try:
        readiness = api("update_readiness", {})
        assert not readiness["ready"] and readiness["active_tasks"] == 1
        assert "任务" in readiness["reason"]
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (ident,))
    assert api("update_readiness", {})["ready"]
