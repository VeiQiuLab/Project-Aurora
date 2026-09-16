"""Authenticated IPC and real production request construction, isolated roots only."""
import asyncio
import json
import threading
from unittest.mock import Mock, patch

import pytest
import jsonschema
from websockets.asyncio.client import connect
from test_production_sidecar import ROOT, SIDECAR, child_sidecar, envelope, fake_ollama, write_settings
from test_direct_chat import BridgeTests, model_server, request, cancel
from test_post_turn import MESSAGES, wait_for
from production_sidecar.composition import ProductionComposition
from production_sidecar.post_turn import PostTurnCoordinator
from modules.settings_service import RULES, SettingsService
from validate_contracts import validate_message, ContractError
from settings_contract import KEYS


def test_settings_examples_schema_allowlist(tmp_path):
    assert set(RULES) == KEYS
    directory = SIDECAR.parent / "contracts"
    schema = json.loads((directory / "ipc-v1.schema.json").read_text())
    examples = json.loads((directory / "ipc-v1.settings.examples.json").read_text())
    for event in examples:
        validate_message(event)
        jsonschema.validate(event, schema)
    bad = examples[-1]
    bad["payload"]["changed_keys"] = ["qq.access_token"]
    with pytest.raises(ContractError):
        validate_message(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


class SettingsRuntimeTests(BridgeTests):
    # Inherited chat/cancel regressions run against the same injected boundary.
    async def test_update_during_context_uses_one_snapshot_then_next_generation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, model_server() as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            composition = self.sidecar.composition
            entered, release = threading.Event(), threading.Event()
            original = composition.context.prepare
            def paused(*args, **kwargs):
                entered.set()
                assert release.wait(5)
                return original(*args, **kwargs)
            with patch.object(composition.context, "prepare", side_effect=paused):
                await bridge.start(self.connection, request())
                first = bridge.active
                assert await asyncio.to_thread(entered.wait, 3)
                composition.settings.apply_patch({"ollama.thinking_mode":"on","ollama.keep_alive":"5m",
                    "rag.pipeline_enabled":True,"persona.enabled":True},0)
                release.set()
                await asyncio.wait_for(first.task,5)
            assert calls[0]["think"] is False and calls[0]["keep_alive"] == "30m"
            assert first.handle.diagnostics["rag_enabled"] is False
            assert first.handle.diagnostics["persona_enabled"] is False
            await bridge.start(self.connection, request("2"))
            second = bridge.active
            await asyncio.wait_for(second.task,5)
            assert calls[1]["think"] is True and calls[1]["keep_alive"] == "5m"
            assert second.handle.diagnostics["rag_enabled"] is True
            assert second.handle.diagnostics["persona_enabled"] is True
            assert first.settings_snapshot.revision == 0 and second.settings_snapshot.revision == 1
            composition.close()

    async def test_update_during_http_does_not_change_running_policy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, model_server("blocked") as (host, calls):
            bridge = await self.setup_bridge(host, directory)
            await bridge.start(self.connection, request())
            first = bridge.active
            await self.wait_delta()
            self.sidecar.composition.settings.apply_patch({"ollama.thinking_mode":"on","ollama.keep_alive":None},0)
            assert calls[0]["think"] is False and calls[0]["keep_alive"] == "30m"
            assert first.settings_snapshot.policy.thinking_mode == "off"
            await bridge.cancel(self.connection,cancel())
            await asyncio.wait_for(first.task,3)
            assert first.terminal == "cancelled"
            self.sidecar.composition.close()

    async def test_host_and_model_change_reaches_next_request_only(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, model_server() as (old_host,old_calls), model_server() as (new_host,new_calls):
            bridge = await self.setup_bridge(old_host, directory)
            composition = self.sidecar.composition
            entered, release = threading.Event(), threading.Event()
            original = composition.context.prepare
            def paused(*args, **kwargs):
                entered.set()
                assert release.wait(5)
                return original(*args, **kwargs)
            with patch.object(composition.context, "prepare", side_effect=paused):
                await bridge.start(self.connection, request())
                first = bridge.active
                assert await asyncio.to_thread(entered.wait,3)
                composition.settings.apply_patch({"ollama.host":new_host,"chat_model":"test-model:latest",
                                                  "chat_model_mode":"manual"},0)
                release.set()
                await asyncio.wait_for(first.task,5)
            assert len(old_calls) == 1 and not new_calls
            assert old_calls[0]["model"] == "test-model"
            await bridge.start(self.connection, request("2"))
            second = bridge.active
            await asyncio.wait_for(second.task,5)
            assert new_calls[0]["model"] == "test-model:latest"
            assert len(old_calls) == 1
            composition.close()

    async def test_authenticated_settings_roundtrip_restart_noop_conflict(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, fake_ollama() as (host,calls):
            path = write_settings(directory, host, qq={"access_token":"fixture-secret"})
            for iteration in range(2):
                async with child_sidecar(directory) as (process, bootstrap, token):
                    async with connect(f"ws://127.0.0.1:{bootstrap['port']}", additional_headers={"Authorization":f"Bearer {token}"}) as ws:
                        await ws.send(json.dumps(envelope("hello",client="aurora-desktop",supported_versions=[1])))
                        ack = json.loads(await ws.recv())
                        assert ack["payload"]["capabilities"]["settings"] == {"read":True,"update":True,"ui":False}
                        await ws.send(json.dumps(envelope("settings.get.request")))
                        response = json.loads(await ws.recv())
                        validate_message(response)
                        assert "fixture-secret" not in json.dumps(response)
                        values = {d["key"]:d["value"] for d in response["payload"]["descriptors"]}
                        assert values["ollama.thinking_mode"] == ("on" if iteration else "off")
                        if not iteration:
                            await ws.send(json.dumps(envelope("settings.update.request",expected_revision=0,patch={"ollama.thinking_mode":"on"})))
                            for kind in ("settings.update.response","settings.changed"):
                                event = json.loads(await ws.recv())
                                validate_message(event)
                                assert event["type"] == kind and event["payload"]["revision"] == 1
                            for values, rev, code in [({"bad.key":True},1,"INVALID_SETTING"),
                                    ({"resolved_chat_model":"new"},1,"READ_ONLY"),
                                    ({"rag.pipeline_enabled":"yes"},1,"INVALID_VALUE"),
                                    ({"ollama.thinking_mode":"off"},0,"CONFLICT")]:
                                await ws.send(json.dumps(envelope("settings.update.request",expected_revision=rev,patch=values)))
                                event = json.loads(await ws.recv())
                                validate_message(event)
                                assert event["type"] == "error" and event["payload"]["code"] == code
                            before = path.stat().st_mtime_ns
                            await ws.send(json.dumps(envelope("settings.update.request",expected_revision=1,patch={"ollama.thinking_mode":"on"})))
                            assert json.loads(await ws.recv())["payload"]["changed_keys"] == []
                            assert path.stat().st_mtime_ns == before
                        await ws.send(json.dumps(envelope("shutdown.request")))
                        # No no-op change notification queued ahead of shutdown.
                        assert json.loads(await ws.recv())["type"] == "shutdown.ack"
                    await asyncio.wait_for(process.wait(),4)
            assert set(calls) == {("GET","/api/tags")}


def test_post_turn_snapshot_debounce_running_and_foreground_guard(tmp_path):
    composition = ProductionComposition(ROOT, write_settings(tmp_path,"http://127.0.0.1:1"),
        conversation_root=tmp_path/"conversations",context_root=tmp_path)
    cid = composition.conversations.create()["conversation_id"]
    composition.conversations.save_completed(cid,"test-model",MESSAGES)
    entered, release = threading.Event(), threading.Event()
    observed = []
    def title(model, messages, **kwargs):
        settings = kwargs["settings_store"]
        observed.append((model, settings.policy.keep_alive, settings.revision))
        entered.set()
        assert release.wait(3)
        observed.append((model, settings.policy.keep_alive, settings.revision))
        return "合成测试标题"
    coordinator = PostTurnCoordinator(composition, {"chat_with_messages":title}, Mock(), idle_seconds=.03)
    composition.post_turn = coordinator
    coordinator.foreground_started("N")
    snapshot = composition.settings.snapshot()
    coordinator.schedule(cid,"N",MESSAGES,"test-model",settings_snapshot=snapshot)
    coordinator.foreground_finished("N")
    composition.settings.apply_patch({"ollama.keep_alive":"5m","chat_model":"new-model"},0)
    coordinator.foreground_started("N+1")
    assert not entered.wait(.06)
    coordinator.foreground_finished("N+1")
    try:
        assert entered.wait(2)
        composition.settings.apply_patch({"ollama.keep_alive":"2m"},1)
        release.set()
        wait_for(lambda:any(e["event"]=="completed" for e in coordinator.events))
        assert observed == [("test-model","30m",0)] * 2
        assert composition.settings.policy.keep_alive == "2m"
    finally:
        release.set()
        composition.close()


def test_settings_rpc_never_mutates_memory_or_loads_model(tmp_path):
    s = SettingsService(tmp_path / "config.json")
    with patch("urllib.request.urlopen",side_effect=AssertionError("no network")), \
         patch("modules.memory.MemoryStore.queue_candidates",side_effect=AssertionError("no memory")):
        s.apply_patch({"chat_model":"not-installed:latest","ollama.host":"http://offline.invalid:11434"},0)
        s.describe()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.json"]
