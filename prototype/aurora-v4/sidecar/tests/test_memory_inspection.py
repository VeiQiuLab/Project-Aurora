"""Memory visibility never approves, repairs, deletes, normalizes or logs bodies."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from websockets.asyncio.client import connect
from test_production_sidecar import SIDECAR, child_sidecar, envelope, fake_ollama, write_settings
from modules.memory import MemoryStore
from production_sidecar.memory_inspection import InspectionError, read_memory
from validate_contracts import ContractError, validate_message


def payload(collection="saved", record_id=None, offset=0):
    return {"collection": collection, "record_id": record_id, "offset": offset}


def seed(root):
    directory = Path(root) / "memory"
    directory.mkdir(parents=True)
    saved = [{"id":"saved-1","content":"喜欢安静阅读","type":"preference","enabled":False,"metadata":{"state":"archived","confidence":0.9}}]
    candidates = [{"id":"candidate-1","content":"候选内容，不是正式记忆","status":"pending","source":"chat","risk":{"level":"low"}},
                  {"id":"old","content":"已经拒绝","status":"rejected"}]
    for name, value in [("memories.json",saved),("memory_candidates.json",candidates)]:
        (directory / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return MemoryStore(directory / "memories.json", read_only=True)


def snapshot_files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in Path(root).rglob("*") if path.is_file()}


def test_saved_pending_and_full_detail_keep_real_fields(tmp_path):
    store = seed(tmp_path)
    saved = read_memory(store, payload())
    assert saved["total"] == 1 and saved["source"] == "primary"
    detail = read_memory(store, payload(record_id=saved["records"][0]["inspection_id"]))
    assert detail["records"][0]["fields"]["metadata"] == {"state":"archived","confidence":0.9}
    assert detail["records"][0]["fields"]["enabled"] is False
    pending = read_memory(store, payload("pending"))
    assert pending["total"] == 1
    detail = read_memory(store, payload("pending", pending["records"][0]["inspection_id"]))
    assert detail["records"][0]["fields"]["risk"] == {"level":"low"}


def test_reads_never_write_or_auto_approve_delete_legacy_records(tmp_path, caplog):
    store = seed(tmp_path)
    # No persisted identity/timestamps: inspection must not manufacture them.
    store.file_path.write_text('[{"content":"legacy","metadata":{}}]', encoding="utf-8")
    before = snapshot_files(tmp_path)
    with patch.object(store, "_write", side_effect=AssertionError("write")), patch.object(store, "_write_candidates", side_effect=AssertionError("write")), patch.object(store, "approve_candidate", side_effect=AssertionError("approve")), patch.object(store, "reject_candidate", side_effect=AssertionError("reject")), patch.object(store, "delete", side_effect=AssertionError("delete")):
        for collection in ("saved", "pending"):
            first = read_memory(store, payload(collection))
            second = read_memory(store, payload(collection))
            assert first == second
            read_memory(store, payload(collection, first["records"][0]["inspection_id"]))
    assert snapshot_files(tmp_path) == before
    legacy = read_memory(store, payload())["records"][0]
    assert "id" not in legacy["fields"] and "created_time" not in legacy["fields"]
    assert legacy["fields"]["metadata"] == {}
    assert "legacy" not in caplog.text and "候选内容" not in caplog.text


def test_empty_missing_does_not_create_directory(tmp_path):
    store = MemoryStore(tmp_path / "absent" / "memories.json", read_only=True)
    for collection in ("saved", "pending"):
        assert read_memory(store, payload(collection))["records"] == []
    assert not (tmp_path / "absent").exists()


def test_corrupt_is_error_backup_is_marked_and_never_repaired(tmp_path):
    store = seed(tmp_path)
    good = store.file_path.read_bytes()
    store.file_path.write_text("BROKEN", encoding="utf-8")
    with pytest.raises(OSError): read_memory(store, payload())
    store.file_path.with_name("memories.json.bak").write_bytes(good)
    before = snapshot_files(tmp_path)
    assert read_memory(store, payload())["source"] == "backup"
    assert snapshot_files(tmp_path) == before


def test_preview_pagination_changed_record_and_large_detail(tmp_path):
    store = seed(tmp_path)
    values = [{"content":f"{i}:" + "记忆" * 100} for i in range(25)]
    store.file_path.write_text(json.dumps(values), encoding="utf-8")
    first = read_memory(store, payload())
    assert len(first["records"]) == 20 and first["total"] == 25
    assert len(first["records"][0]["content"]) == 160
    assert len(read_memory(store, payload(offset=20))["records"]) == 5
    old = first["records"][0]["inspection_id"]
    assert len(read_memory(store, payload(record_id=old))["records"][0]["content"]) > 160
    store.file_path.write_text('[{"content":"changed"}]', encoding="utf-8")
    with pytest.raises(InspectionError, match="MEMORY_NOT_FOUND"): read_memory(store, payload(record_id=old))
    store.file_path.write_text(json.dumps([{"content":"x"*32769}]), encoding="utf-8")
    identifier = read_memory(store, payload())["records"][0]["inspection_id"]
    with pytest.raises(InspectionError, match="MEMORY_RECORD_TOO_LARGE"): read_memory(store, payload(record_id=identifier))


@pytest.mark.parametrize("bad", [payload("approve"), payload("delete"), payload(record_id="../file"), payload(record_id=int("1"*64)), payload(offset=-1), payload(offset=True), {**payload(),"approve":True}])
def test_wire_rejects_mutation_traversal_and_invalid_bounds(bad):
    with pytest.raises(ContractError): validate_message(envelope("memory.read.request", request="memory-test", **bad))


def test_contract_schema_agrees_for_real_projections(tmp_path):
    store = seed(tmp_path)
    schema = json.loads((SIDECAR.parent / "contracts/ipc-v1.schema.json").read_text(encoding="utf-8"))
    for collection in ("saved", "pending"):
        requests = [payload(collection)]
        initial = read_memory(store, requests[0])
        requests.append(payload(collection, initial["records"][0]["inspection_id"]))
        for request in requests:
            for message in [envelope("memory.read.request",request="memory-test",**request), envelope("memory.read.response",request="memory-test",**read_memory(store, request))]:
                validate_message(message)
                jsonschema.validate(message, schema)


def test_authenticated_real_sidecar_reads_and_failure_retry_without_mutation(tmp_path):
    async def run():
        with fake_ollama() as (host, calls):
            write_settings(tmp_path, host)
            store = seed(tmp_path)
            before = snapshot_files(tmp_path / "memory")
            async with child_sidecar(tmp_path) as (process, bootstrap, token):
                async with connect(f"ws://127.0.0.1:{bootstrap['port']}", additional_headers={"Authorization":f"Bearer {token}"}) as ws:
                    await ws.send(json.dumps(envelope("hello", client="aurora-desktop", supported_versions=[1])))
                    await ws.recv()
                    async def read(request):
                        await ws.send(json.dumps(envelope("memory.read.request", request="memory-native", **request)))
                        response = json.loads(await ws.recv()); validate_message(response); return response
                    for collection in ("saved", "pending"):
                        response = await read(payload(collection))
                        assert response["type"] == "memory.read.response"
                        detail = await read(payload(collection, response["payload"]["records"][0]["inspection_id"]))
                        assert detail["payload"]["operation"] == "detail"
                    assert snapshot_files(tmp_path / "memory") == before
                    original = store.file_path.read_bytes()
                    store.file_path.write_text("broken", encoding="utf-8")
                    assert (await read(payload()))["payload"]["code"] == "MEMORY_READ_FAILED"
                    store.file_path.write_bytes(original)
                    assert (await read(payload()))["type"] == "memory.read.response"
                    await ws.send(json.dumps(envelope("shutdown.request")))
                    assert json.loads(await ws.recv())["type"] == "shutdown.ack"
                await asyncio.wait_for(process.wait(), 5)
            assert all(method == "GET" for method, path in calls)
    asyncio.run(run())
