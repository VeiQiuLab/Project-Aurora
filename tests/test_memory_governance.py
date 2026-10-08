"""Data safety gates use only tmp_path, including actual child processes."""
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.memory import MemoryStore
from modules.memory_coordination import fingerprint


def request(action, record, op="test-1", **changes):
    return dict(operation_id=op, action=action, id=record["id"],
                expected_version=fingerprint(record), content=None, confirmed=action == "delete") | changes


def records(store):
    return store.inspect_records("saved")[0]


def test_all_operations_receipts_and_unchanged_other_records(tmp_path):
    store = MemoryStore(tmp_path / "memories.json", read_only=True)
    tmp_path.mkdir(exist_ok=True)
    other = store.create("fact", "Unrelated preserved data")
    candidates = store.queue_candidate_records([
        {"type": "fact", "content": "One isolated candidate", "score": .9},
        {"type": "instruction", "content": "Another isolated candidate", "score": .9}])
    candidate = candidates[0]
    approve = request("approve", candidate)
    result = store.govern(approve)
    assert result["saved_id"] and len(records(store)) == 2
    assert store.govern(approve) == result
    assert MemoryStore(store.file_path, read_only=True).govern(approve) == result
    assert len(records(store)) == 2
    store.govern(request("reject", candidates[1], "reject-1"))
    assert store.list_candidates("pending") == []
    assert len(store.list_candidates("rejected")) == 1
    saved = next(r for r in records(store) if r["id"] == result["saved_id"])
    edit = request("edit", saved, "edit-1", content="New user content")
    store.govern(edit)
    assert store.govern(edit)["status"] == "completed"
    edited = next(r for r in records(store) if r["id"] == saved["id"])
    assert edited["content"] == "New user content"
    with pytest.raises(ValueError, match="MEMORY_CONFLICT"):
        store.govern(request("delete", saved, "stale-delete"))
    delete = request("delete", edited, "delete-1")
    deleted = store.govern(delete)
    assert store.govern(delete) == deleted
    assert records(store) == [other]
    with pytest.raises(ValueError, match="MEMORY_CONFLICT"):
        store.govern(delete | {"id": other["id"]})
    assert records(store) == [other]


@pytest.mark.parametrize("changes", [{"confirmed": False}, {"id": "../store"}, {"id": ""}, {"action": "clear"},
    {"expected_version": "bad"}, {"operation_id": ""}, {"content": "unexpected"}, {"all": True}])
def test_invalid_delete_never_writes(tmp_path, changes):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.create("fact", "Preserved")
    before = store.file_path.read_bytes()
    with pytest.raises(ValueError):
        store.govern(request("delete", item) | changes)
    assert store.file_path.read_bytes() == before
    assert not store.journal_file.exists()


@pytest.mark.parametrize("content", ["", "  \n ", None, 123, "x" * 32769], ids=["empty","blank","null","number","oversized"])
def test_invalid_edit_never_writes(tmp_path, content):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.create("fact", "Preserved")
    before = store.file_path.read_bytes()
    with pytest.raises(ValueError):
        store.govern(request("edit", item, content=content))
    assert store.file_path.read_bytes() == before


def test_failure_before_intent_leaves_both_files_unchanged(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.queue_candidate_records([{"type": "fact", "content": "Isolated pending record", "score": .9}])[0]
    before = store.candidates_file.read_bytes()
    with patch.object(store, "_write_candidates", side_effect=OSError("staging failure")):
        with pytest.raises(OSError): store.govern(request("approve", item))
    assert not store.file_path.exists()
    assert store.candidates_file.read_bytes() == before
    assert not store.journal_file.exists()


def test_second_store_failure_blocks_reads_until_recovery(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    candidate = store.queue_candidate_records([{"type": "fact", "content": "Pending record", "score": .9}])[0]
    real_replace = store._replace_text
    def fail(path, text):
        if path == store.candidates_file: raise OSError("second file failure")
        real_replace(path, text)
    with patch.object(MemoryStore, "_replace_text", side_effect=fail):
        with pytest.raises(OSError): store.govern(request("approve", candidate))
        # Primary is physically half-written; no API exposes that state.
        assert len(json.loads(store.file_path.read_text())) == 1
        with pytest.raises(OSError): store.inspect_records("saved")
        with pytest.raises(OSError): MemoryStore(store.file_path).list_candidates()
    recovered = MemoryStore(store.file_path)
    assert len(records(recovered)) == 1
    assert recovered.list_candidates("pending") == []
    result = recovered.govern(request("approve", candidate))
    assert result["saved_id"] == records(recovered)[0]["id"]
    assert len(records(recovered)) == 1


def test_concurrent_updates_and_delete_preserve_unrelated_edit(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    first = store.create("fact", "First original")
    second = store.create("fact", "Second original")
    start = threading.Barrier(2)
    def run(req):
        start.wait(5)
        return MemoryStore(store.file_path).govern(req)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run, request("edit", first, "edit-first", content="First updated")),
                   pool.submit(run, request("edit", second, "edit-second", content="Second updated"))]
        for f in futures: f.result(10)
    saved = {r["id"]: r for r in records(store)}
    assert saved[first["id"]]["content"] == "First updated"
    assert saved[second["id"]]["content"] == "Second updated"
    start.reset()
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run, request("edit", saved[first["id"]], "edit-again", content="First retained")),
                   pool.submit(run, request("delete", saved[second["id"]], "delete-second"))]
        for f in futures: f.result(10)
    assert len(records(store)) == 1 and records(store)[0]["content"] == "First retained"


def test_same_record_conflict_and_duplicate_approve_concurrency(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.create("fact", "Original content")
    def run(req):
        try: return MemoryStore(store.file_path).govern(req)["status"]
        except (ValueError, KeyError) as error: return str(error).strip("\'")
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(run, [request("edit", item, "edit-a", content="Edit A"), request("delete", item, "delete-a")]))
    assert sorted(outcomes) == ["MEMORY_CONFLICT", "completed"] or sorted(outcomes) == ["MEMORY_NOT_FOUND", "completed"]


CHILD = '''
import json, os, sys, time
from pathlib import Path
from modules.memory import MemoryStore
store=MemoryStore(Path(sys.argv[1]))
request=json.loads(sys.argv[2])
stage=sys.argv[3]
real=store._replace_text
def replace(path,text):
    real(path,text)
    if path.name==stage:
        print("INTERRUPT_READY",flush=True)
        time.sleep(60)
store._replace_text=replace
try:
    print(json.dumps(store.govern(request)),flush=True)
except (ValueError,KeyError) as error:
    print("CONFLICT",flush=True)
'''


@pytest.mark.parametrize("stage", ["memory_operation_intent.json", "memories.json", "memory_candidates.json", "memory_operations.json"])
def test_process_interruption_restart_redo_exactly_once(tmp_path, stage):
    store = MemoryStore(tmp_path / "memories.json")
    candidate = store.queue_candidate_records([{"type": "fact", "content": "Process crash fixture", "score": .9}])[0]
    req = request("approve", candidate)
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(store.file_path), json.dumps(req), stage],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "INTERRUPT_READY"
    finally:
        child.terminate()
        child.wait(10)
    restarted = MemoryStore(store.file_path, read_only=True)
    assert len(records(restarted)) == 1
    assert restarted.list_candidates("pending") == []
    result = restarted.govern(req)
    assert result["saved_id"] == records(restarted)[0]["id"]
    assert len(records(restarted)) == 1


def test_real_cross_process_serialization_and_conflict(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    items = [store.create("fact", f"Original {i}") for i in range(4)]
    reqs = [request("edit", item, f"process-{i}", content=f"Updated {i}") for i, item in enumerate(items)]
    children = [subprocess.Popen([sys.executable,"-c",CHILD,str(store.file_path),json.dumps(req),"none"],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for req in reqs]
    for child in children:
        out, err = child.communicate(timeout=15)
        assert child.returncode == 0 and "completed" in out, err
    assert {r["content"] for r in records(store)} == {f"Updated {i}" for i in range(4)}
    current = records(store)[0]
    reqs = [request("edit",current,f"conflict-{i}",content=f"Winner {i}") for i in range(2)]
    children = [subprocess.Popen([sys.executable,"-c",CHILD,str(store.file_path),json.dumps(req),"none"],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for req in reqs]
    outputs = [child.communicate(timeout=15)[0] for child in children]
    assert sum("completed" in out for out in outputs) == 1
    assert sum("CONFLICT" in out for out in outputs) == 1
    assert len(records(store)) == 4


def test_read_only_inspection_and_corrupt_journal_fail_closed(tmp_path):
    store = MemoryStore(tmp_path / "absent/memories.json", read_only=True)
    assert records(store) == [] and not store.file_path.parent.exists()
    store.file_path.parent.mkdir()
    store.journal_file.write_text("broken", encoding="utf-8")
    with pytest.raises(OSError, match="MEMORY_RECOVERY_REQUIRED"):
        store.inspect_records("saved")


@pytest.mark.parametrize("action", ["edit", "delete", "reject"])
def test_failure_before_intent_and_after_intent_recovers_exact_target(tmp_path, action):
    store = MemoryStore(tmp_path / "memories.json")
    other = store.create("fact", "Unrelated original")
    target = store.create("fact", "Target original") if action != "reject" else store.queue_candidate_records([
        {"type":"instruction", "content":"Pending isolated instruction", "score":.9}])[0]
    req = request(action, target, content="Changed target" if action == "edit" else None)
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    real = store._replace_text
    def fail_intent(path, text):
        if path == store.journal_file: raise OSError("intent write failed")
        real(path, text)
    with patch.object(store,"_replace_text",side_effect=fail_intent):
        with pytest.raises(OSError): store.govern(req)
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
    def fail_receipt(path, text):
        if path == store.operations_file: raise OSError("receipt write failed")
        real(path,text)
    with patch.object(store,"_replace_text",side_effect=fail_receipt):
        with pytest.raises(OSError): store.govern(req)
        with pytest.raises(OSError): store.inspect_records("saved")
    assert MemoryStore(store.file_path).govern(req)["status"] == "completed"
    assert next(r for r in records(store) if r["id"] == other["id"]) == other
    if action == "edit": assert next(r for r in records(store) if r["id"] == target["id"])["content"] == "Changed target"
    if action == "delete": assert all(r["id"] != target["id"] for r in records(store))
    if action == "reject": assert store.list_candidates("rejected")[0]["id"] == target["id"]


@pytest.mark.parametrize("same_operation", [True, False])
def test_concurrent_approval_never_duplicates(tmp_path, same_operation):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.queue_candidate_records([{"type":"fact","content":"Concurrent approval fixture","score":.9}])[0]
    def run(index):
        try:
            return MemoryStore(store.file_path).govern(request("approve",item,"approve-1" if same_operation else f"approve-{index}"))
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(2) as pool: results = list(pool.map(run,[1,2]))
    assert len(records(store)) == 1 and store.list_candidates("pending") == []
    if same_operation: assert results[0] == results[1]
    else: assert sum(result == "MEMORY_CONFLICT" for result in results) == 1


def test_missing_target_and_legacy_unrelated_fields_preserved(tmp_path):
    store = MemoryStore(tmp_path / "memories.json",read_only=True)
    unrelated = {"id":"legacy-other","type":"fact","content":"Original legacy","metadata":{}}
    target = {"id":"legacy-target","type":"fact","content":"Original target","metadata":{}}
    store.file_path.write_text(json.dumps([unrelated,target]))
    store.govern(request("edit",target,content="Changed target"))
    assert records(store)[0] == unrelated
    assert records(store)[1]["id"] == target["id"]
    before = store.file_path.read_bytes()
    with pytest.raises(KeyError): store.govern(request("delete",unrelated,"bad-id") | {"id":"missing"})
    assert store.file_path.read_bytes() == before


def test_coordinated_backup_never_restores_pending_only_after_approval(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.queue_candidate_records([{"type":"fact","content":"Backup consistency fixture","score":.9}])[0]
    store.govern(request("approve",item))
    store.candidates_file.write_text("broken")
    assert store.list_candidates("pending") == []
    assert len(store.list_candidates("approved")) == 1 and len(records(store)) == 1


@pytest.mark.parametrize("action", ["edit","delete"])
def test_edit_delete_process_interruption_and_recovery(tmp_path,action):
    store = MemoryStore(tmp_path / "memories.json")
    other = store.create("fact","Unrelated stable")
    item = store.create("fact","Target original")
    req = request(action,item,content="Target changed" if action=="edit" else None)
    child = subprocess.Popen([sys.executable,"-c",CHILD,str(store.file_path),json.dumps(req),"memories.json"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try: assert child.stdout.readline().strip() == "INTERRUPT_READY"
    finally: child.terminate(); child.wait(10)
    restarted = MemoryStore(store.file_path)
    assert restarted.govern(req)["status"] == "completed"
    assert records(restarted)[0] == other
    if action=="delete": assert records(restarted) == [other]
    else: assert records(restarted)[1]["content"] == "Target changed"


@pytest.mark.parametrize("same_operation", [True,False])
def test_cross_process_approval_duplicate_and_distinct_retry_safety(tmp_path,same_operation):
    store = MemoryStore(tmp_path / "memories.json")
    item = store.queue_candidate_records([{"type":"fact","content":"Cross-process approve fixture","score":.9}])[0]
    reqs = [request("approve",item,"approve-1" if same_operation else f"approve-{index}") for index in (1,2)]
    children = [subprocess.Popen([sys.executable,"-c",CHILD,str(store.file_path),json.dumps(req),"none"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for req in reqs]
    outputs = [child.communicate(timeout=15)[0] for child in children]
    assert all(child.returncode==0 for child in children)
    assert len(records(store))==1 and len(store.list_candidates("approved"))==1
    if same_operation: assert outputs[0]==outputs[1]
    else: assert sum("completed" in out for out in outputs)==1 and sum("CONFLICT" in out for out in outputs)==1


def test_content_reverting_to_original_does_not_revalidate_old_snapshot(tmp_path):
    store = MemoryStore(tmp_path / "memories.json")
    first = store.create("fact","Already edited original")
    store.govern(request("edit",first,"initial-edit",content="Initial edited content"))
    stale = records(store)[0]
    store.govern(request("edit",stale,"edit-away",content="Different content"))
    current = records(store)[0]
    store.govern(request("edit",current,"edit-back",content=stale["content"]))
    latest = records(store)[0]
    assert latest["content"]==stale["content"] and fingerprint(latest)!=fingerprint(stale)
    with pytest.raises(ValueError,match="MEMORY_CONFLICT"):
        store.govern(request("delete",stale,"stale-aba-delete"))
    assert records(store)==[latest]
