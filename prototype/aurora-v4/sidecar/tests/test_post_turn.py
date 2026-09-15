import threading
import time
from unittest.mock import Mock, patch

import pytest

from test_production_sidecar import ROOT, ProductionComposition, write_settings
from production_sidecar.direct_chat import DirectChatAdapter
from production_sidecar.post_turn import PostTurnCoordinator, Deferred


MESSAGES = [{"role": "user", "content": "我喜欢简洁的黑白界面。"},
            {"role": "assistant", "content": "明白。"}]


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


@pytest.fixture
def rig(tmp_path):
    config = write_settings(tmp_path, "http://127.0.0.1:1")
    composition = ProductionComposition(ROOT, config_file=config,
        conversation_root=tmp_path / "conversations", context_root=tmp_path)
    store = composition.conversations
    cid = store.create()["conversation_id"]
    store.save_completed(cid, "test-model", MESSAGES)
    call, changed = Mock(return_value="界面风格"), Mock()
    coordinator = PostTurnCoordinator(composition, {"chat_with_messages": call}, changed, idle_seconds=.04)
    composition.post_turn = coordinator
    yield composition, coordinator, cid, call, changed
    composition.close()
    assert coordinator.worker is None or not coordinator.worker.is_alive()


def schedule(rig, generation="g1", **kwargs):
    _, coordinator, cid, _, _ = rig
    return coordinator.schedule(cid, generation, MESSAGES, "test-model", **kwargs)


@pytest.mark.parametrize("status", ["cancelled", "failed", "backend_lost", "rejected"])
def test_noncompleted_does_not_run(rig, status):
    assert not schedule(rig, status=status)
    assert rig[1].worker is None
    assert not rig[3].called


def test_completed_once_production_memory_title_metadata(rig):
    composition, coordinator, cid, call, changed = rig
    assert schedule(rig)
    assert not schedule(rig)
    wait_for(lambda: any(e["event"] == "completed" for e in coordinator.events))
    assert call.call_count == 1
    assert call.call_args.kwargs == {"timeout": 20, "thinking_mode": "off", "num_predict": 32, "diagnostics": {}}
    assert composition.conversations.get(cid)["title"] == "界面风格"
    assert changed.call_count == 2
    assert "messages" not in changed.call_args.args[0]
    memory = composition.context.memory
    assert memory is composition.context.memory
    assert memory.list_memories() == []
    assert memory.list_candidates()
    assert all(c["status"] == "pending" for c in memory.list_candidates())
    assert not memory.file_path.exists()  # no confirmed memory write/delete
    time.sleep(.08)
    assert call.call_count == 1


def test_foreground_resets_full_debounce_and_stale_finish_does_not_release(rig):
    coordinator, call = rig[1], rig[3]
    coordinator.idle_seconds = .15
    schedule(rig)
    time.sleep(.09)
    coordinator.foreground_started("next")
    coordinator.foreground_finished("old")
    time.sleep(.12)
    assert not call.called
    coordinator.foreground_finished("next")
    time.sleep(.09)
    assert not call.called
    wait_for(lambda: call.called)


def test_final_guard_race_does_not_consume_attempt_or_write_fallback(rig):
    composition, coordinator, cid, call, _ = rig
    real = coordinator._guard
    n = 0
    def guard(epoch):
        nonlocal n
        n += 1
        if n == 3:
            coordinator.foreground_started("race")
        real(epoch)
    with patch.object(coordinator, "_guard", side_effect=guard):
        schedule(rig)
        wait_for(lambda: coordinator.foreground == "race")
        assert not call.called
        assert cid not in coordinator.title_attempts
        assert composition.conversations.get(cid)["title"] == "New Conversation"
        coordinator.foreground_finished("race")
        wait_for(lambda: call.called)


@pytest.mark.parametrize("title,manual", [("用户标题", False), ("New Conversation", True)])
def test_existing_or_manual_title_skips(rig, title, manual):
    composition, coordinator, cid, call, _ = rig
    with composition.conversations.transaction(cid):
        composition.conversations.manager.save(cid, "test-model", MESSAGES,
            title=title, metadata={"title_manual": manual})
    schedule(rig)
    wait_for(lambda: any(e["event"] == "completed" for e in coordinator.events))
    assert not call.called


def test_shutdown_pending_restart_does_not_recover_history(rig):
    composition, coordinator, cid, call, _ = rig
    coordinator.foreground_started("active")
    schedule(rig)
    coordinator.close()
    assert not schedule(rig, "other")
    assert not call.called
    replacement = PostTurnCoordinator(composition, {"chat_with_messages": call}, Mock(), idle_seconds=0)
    assert replacement.worker is None and not replacement.pending
    replacement.close()


def test_offline_title_failure_does_not_damage_completed_conversation(rig):
    composition, coordinator, cid, call, _ = rig
    call.side_effect = OSError("private error body")
    schedule(rig)
    wait_for(lambda: any(e["event"] == "completed" for e in coordinator.events))
    assert composition.conversations.get(cid)["messages"] == MESSAGES
    assert "private error body" not in str(list(coordinator.events))
    assert call.call_count == 1


def test_memory_failure_isolated_intelligence_title_continue(rig):
    composition, coordinator, cid, call, _ = rig
    with patch.object(composition.context.memory, "queue_candidates", side_effect=OSError()):
        schedule(rig)
        wait_for(lambda: call.called)
    assert any(e["event"] == "memory_failed" for e in coordinator.events)


def test_running_title_shutdown_no_late_save(rig):
    composition, coordinator, cid, call, changed = rig
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        release.wait(2)
        return "晚到标题"
    call.side_effect = blocked
    schedule(rig)
    assert entered.wait(2)
    started = time.monotonic()
    coordinator.close()
    assert time.monotonic() - started < .5
    release.set()
    coordinator.worker.join(2)
    assert composition.conversations.get(cid)["title"] == "New Conversation"


def test_title_and_new_turn_save_are_serialized_without_losing_messages(rig):
    composition, coordinator, cid, call, _ = rig
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        release.wait(2)
        return "界面风格"
    call.side_effect = blocked
    schedule(rig)
    assert entered.wait(2)
    newer = MESSAGES + [{"role": "user", "content": "继续"}, {"role": "assistant", "content": "好"}]
    composition.conversations.save_completed(cid, "test-model", newer)
    release.set()
    wait_for(lambda: any(e["event"] == "completed" for e in coordinator.events))
    assert composition.conversations.get(cid)["messages"] == newer
    assert composition.conversations.get(cid)["title"] == "界面风格"


def test_actual_title_request_policy(rig):
    composition = rig[0]
    api = DirectChatAdapter(composition).api
    import json
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"message":{"content":"ok"}}'
    with patch("urllib.request.urlopen", return_value=response) as opened:
        api["chat_with_messages"]("test-model", [{"role": "user", "content": "fixture"}],
            timeout=20, thinking_mode="off", num_predict=32)
    payload = json.loads(opened.call_args.args[0].data)
    assert payload["think"] is False
    assert payload["options"]["num_predict"] == 32
    assert payload["keep_alive"] == composition.settings.policy.keep_alive
    assert opened.call_args.kwargs["timeout"] == 20


def test_cpu_work_does_not_block_foreground_hook_and_title_is_deferred(rig):
    composition, coordinator, _, call, _ = rig
    entered, release = threading.Event(), threading.Event()
    original = composition.context.memory.queue_candidates
    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)
    with patch.object(composition.context.memory, "queue_candidates", side_effect=slow):
        schedule(rig)
        assert entered.wait(2)
        start = time.monotonic()
        coordinator.foreground_started("foreground")
        assert time.monotonic() - start < .1
        release.set()
        wait_for(lambda: coordinator.pending[0]["cpu_done"])
        assert not call.called
        coordinator.foreground_finished("foreground")
        wait_for(lambda: call.called)


def test_existing_title_skips_after_coordinator_restart(rig):
    composition, coordinator, cid, call, _ = rig
    schedule(rig)
    wait_for(lambda: not coordinator.pending)
    coordinator.close()
    replacement = PostTurnCoordinator(composition, {"chat_with_messages": call}, Mock(), idle_seconds=0)
    try:
        replacement.schedule(cid, "new-instance-generation", MESSAGES, "test-model")
        wait_for(lambda: not replacement.pending)
        assert call.call_count == 1
    finally:
        replacement.close()


def test_analyzer_parity_empty_signals_and_frozen_context(rig):
    from modules.conversation_intelligence import analyze_conversation
    composition, coordinator, cid, _, _ = rig
    before = composition.context.prepare("界面", [], threading.Event())
    expected = analyze_conversation(MESSAGES)
    schedule(rig)
    wait_for(lambda: not coordinator.pending)
    actual = composition.conversations.manager.load(cid)["metadata"]["conversation_intelligence"]
    for key in ("summary", "topics", "important_events", "memory_signals", "analysis_version"):
        assert actual[key] == expected[key]
    assert actual["memory_signals"] == []
    assert "conversation_memory_trigger" not in composition.conversations.manager.load(cid)["metadata"]
    after = composition.context.prepare("界面", [], threading.Event())
    assert before.system_context == after.system_context
    assert before.diagnostics["memory_item_count"] == after.diagnostics["memory_item_count"] == 0


def test_atomic_memory_reads_during_candidate_writes(rig):
    composition, coordinator, _, _, _ = rig
    store = composition.context.memory
    store.file_path.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    def writer():
        try:
            for i in range(20):
                store.queue_candidates(f"我喜欢第{i}种测试界面风格。", source="chat")
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=writer)
    thread.start()
    while thread.is_alive():
        assert isinstance(store.list_memories(), list)
        assert isinstance(store.list_candidates(), list)
    thread.join()
    assert not errors


def test_nonstreaming_diagnostics_only_counts_and_metrics(rig):
    import json
    api = DirectChatAdapter(rig[0]).api
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps({"message": {"content": "title", "thinking": "hidden-body"},
        "load_duration": 1000000, "eval_count": 3}).encode()
    diagnostics = {}
    with patch("urllib.request.urlopen", return_value=response):
        assert api["chat_with_messages"]("test-model", [{"role": "user", "content": "fixture"}], diagnostics=diagnostics) == "title"
    assert diagnostics == {"load_duration_ms": 1, "eval_count": 3, "reasoning_chars": 11}
    assert "hidden-body" not in str(diagnostics)


@pytest.mark.parametrize("schedule_failure", [False, True])
def test_foreground_terminal_after_persistence_before_optional_background(tmp_path, schedule_failure):
    import asyncio
    from test_direct_chat import model_server, request
    from production_sidecar.server import ProductionSidecar
    from mock_sidecar.server import validate_message
    async def exercise(host):
        composition = ProductionComposition(ROOT, write_settings(tmp_path, host),
            conversation_root=tmp_path / "conversations", context_root=tmp_path)
        sidecar = ProductionSidecar("test", composition)
        coordinator = composition.post_turn
        cid = composition.conversations.create()["conversation_id"]
        events = []
        async def send(connection, event):
            validate_message(event)
            if event["type"] == "chat.completed":
                assert composition.conversations.get(cid)["message_count"] >= 2
                assert not coordinator.pending
                assert coordinator.foreground == "g1"
            events.append(event)
        sidecar.send = send
        message = request()
        message["payload"]["conversation_id"] = cid
        try:
            if schedule_failure:
                coordinator.schedule = Mock(side_effect=RuntimeError("private optional failure"))
            await sidecar.start_chat(object(), message)
            await sidecar.chat.active.task
            assert events[-1]["payload"]["terminal_state"] == "completed"
            assert coordinator.foreground is None
            assert len(coordinator.pending) == (0 if schedule_failure else 1)
        finally:
            composition.close()
    with model_server() as (host, _):
        asyncio.run(exercise(host))
