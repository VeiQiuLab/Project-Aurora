"""Authenticated real Python IPC, using isolated fixtures only."""
import asyncio
import json

import jsonschema
import pytest
from websockets.asyncio.client import connect

from modules.memory import MemoryStore
from modules.memory_coordination import fingerprint
from modules.memory_governance_validation import validate_request
from test_production_sidecar import SIDECAR, child_sidecar, envelope, fake_ollama, write_settings
from validate_contracts import validate_message, ContractError


def request(action, record, operation_id, content=None, confirmed=False):
    return dict(operation_id=operation_id, action=action, id=record["id"], expected_version=fingerprint(record), content=content, confirmed=confirmed)


def test_real_ipc_governance_persistence_context_and_error_isolation(tmp_path):
    async def run():
        with fake_ollama() as (host, calls):
            write_settings(tmp_path, host)
            store = MemoryStore(tmp_path / "memory/memories.json",read_only=True)
            store.file_path.parent.mkdir()
            untouched = store.create("fact","Unrelated preserved record")
            candidates = store.queue_candidate_records([
                {"type":"preference","content":"User prefers quiet reading rooms.","score":.9},
                {"type":"instruction","content":"Use clear isolated fixture wording.","score":.9}])
            schema = json.loads((SIDECAR.parent / "contracts/ipc-v1.schema.json").read_text())
            async with child_sidecar(tmp_path) as (process,bootstrap,token):
                async with connect(f"ws://127.0.0.1:{bootstrap['port']}",additional_headers={"Authorization":f"Bearer {token}"}) as ws:
                    await ws.send(json.dumps(envelope("hello",client="aurora-desktop",supported_versions=[1])));await ws.recv()
                    async def perform(req):
                        wire = envelope("memory.write.request",request="memory-operation-1",**req)
                        validate_message(wire);jsonschema.validate(wire,schema)
                        await ws.send(json.dumps(wire));response=json.loads(await ws.recv())
                        validate_message(response);jsonschema.validate(response,schema)
                        return response
                    approve=request("approve",candidates[0],"approve-1")
                    first=await perform(approve)
                    assert first["type"]=="memory.write.response"
                    assert (await perform(approve))["payload"]==first["payload"]
                    saved_id=first["payload"]["saved_id"]
                    saved=next(item for item in store.inspect_records("saved")[0] if item["id"]==saved_id)
                    assert saved_id in {item["id"] for item in store.retrieve("quiet reading rooms",max_results=10)}
                    assert (await perform(request("reject",candidates[1],"reject-1")))["type"]=="memory.write.response"
                    edit=request("edit",saved,"edit-1",content="User prefers bright reading rooms.")
                    assert (await perform(edit))["type"]=="memory.write.response"
                    conflict=await perform(request("delete",saved,"stale-delete",confirmed=True))
                    assert conflict["payload"]["code"]=="MEMORY_CONFLICT"
                    updated=next(item for item in store.inspect_records("saved")[0] if item["id"]==saved_id)
                    assert updated["content"]=="User prefers bright reading rooms."
                    assert (await perform(request("delete",updated,"delete-1",confirmed=True)))["type"]=="memory.write.response"
                    assert store.inspect_records("saved")[0]==[untouched]
                    assert store.retrieve("reading rooms",max_results=10)==[]
                    await ws.send(json.dumps(envelope("memory.read.request",request="memory-read-1",collection="saved",record_id=None,offset=0)))
                    response=json.loads(await ws.recv());assert response["payload"]["total"]==1
                    await ws.send(json.dumps(envelope("shutdown.request")));assert json.loads(await ws.recv())["type"]=="shutdown.ack"
                await asyncio.wait_for(process.wait(),5)
            assert MemoryStore(store.file_path).list_candidates("pending")==[]
    asyncio.run(run())


@pytest.mark.parametrize("change", [{"confirmed":False},{"id":"../x"},{"action":"clear"},{"expected_version":"bad"},{"content":"extra"}])
def test_contract_and_store_reject_unconfirmed_or_invalid_mutation(change):
    req=request("delete",{"id":"target"},"op-1",confirmed=True)|change
    with pytest.raises(ValueError):validate_request(req)
    with pytest.raises(ContractError):validate_message(envelope("memory.write.request",request="memory-1",**req))


def test_new_context_uses_approved_and_edited_content_and_excludes_deleted_memory(tmp_path):
    from production_sidecar.composition import ProductionComposition
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"persona":{"enabled":False},"knowledge":{"enabled":False},
        "rag":{"pipeline_enabled":False},"memory":{"retrieval_threshold":0}}),encoding="utf-8")
    composition = ProductionComposition(root=tmp_path,config_file=config,context_root=tmp_path)
    store = composition.context.memory
    store.file_path.parent.mkdir()
    candidate = store.queue_candidate_records([{"type":"preference","content":"用户偏好安静阅读","score":.9}])[0]
    approved = store.govern(request("approve",candidate,"context-approve"))
    assert "用户偏好安静阅读" in composition.context.prepare("安静阅读").system_context
    saved = next(item for item in store.inspect_records("saved")[0] if item["id"]==approved["saved_id"])
    store.govern(request("edit",saved,"context-edit",content="用户偏好明亮阅读"))
    fresh = composition.context.prepare("明亮阅读").system_context
    assert "用户偏好明亮阅读" in fresh and "用户偏好安静阅读" not in fresh
    updated = store.inspect_records("saved")[0][0]
    store.govern(request("delete",updated,"context-delete",confirmed=True))
    assert "用户偏好明亮阅读" not in composition.context.prepare("明亮阅读").system_context
