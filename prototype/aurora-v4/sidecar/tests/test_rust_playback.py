"""B-3 Python orchestration/ACK tests, no physical audio device required."""
import copy
import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_voice import voice, wait_for
from test_production_sidecar import ROOT
from production_sidecar.rust_playback import RustPlayback
from production_sidecar.voice import create_playback
from modules.experience.voice.models import SpeechResult
from modules.experience.audio.playback import PlaybackEventType
from validate_contracts import validate_message, ContractError


def test_rejected_chat_cannot_steal_audio_reply_connection():
    from production_sidecar.server import ProductionSidecar

    async def exercise():
        owner, rejected = object(), object()
        sidecar = ProductionSidecar.__new__(ProductionSidecar)
        sidecar._audio_connection = None
        sidecar._metadata_connections = set()
        run = SimpleNamespace(connection=owner, request=SimpleNamespace(generation_id="g1"))

        async def start(connection, message):
            if sidecar.chat.active is None:
                sidecar.chat.active = run

        sidecar.chat = SimpleNamespace(active=None, start=start)
        await sidecar.start_chat(owner, {"generation_id":"g1"})
        assert sidecar._audio_connection is owner
        await sidecar.start_chat(rejected, {"generation_id":"g2"})
        assert sidecar._audio_connection is owner

    asyncio.run(exercise())


def fact(payload, state, error=""):
    return {"generation_id":payload["generation_id"],"revision":payload["revision"],"state":state,"error_code":error}


@pytest.fixture
def bridge(tmp_path):
    folder=tmp_path/"run";folder.mkdir();path=folder/"audio.wav";path.write_bytes(b"encoded fixture")
    sent=[]
    adapter=RustPlayback(tmp_path,lambda kind,payload: sent.append((kind,payload)) or True)
    adapter.bind("g1",1)
    yield adapter,SpeechResult(audio_path=str(path)),sent
    adapter.disconnected();adapter.shutdown()


def test_no_python_audio_fallback():
    with pytest.raises(RuntimeError,match="RUST_AUDIO_BRIDGE_REQUIRED"):
        create_playback()


def test_submit_once_started_complete_and_release_ack(bridge):
    adapter,speech,sent=bridge;events=[];adapter.subscribe(events.append)
    adapter.play(speech)
    assert sent==[("audio.play.request",{"generation_id":"g1","revision":1,"file":"run/audio.wav"})]
    assert not adapter.is_playing()
    with pytest.raises(RuntimeError):adapter.play(speech)
    adapter.accept(fact(sent[0][1],"started"));assert adapter.is_playing()
    adapter.accept(fact(sent[0][1],"started"));assert len(events)==1
    adapter.accept(fact(sent[0][1],"completed"));adapter.wait_stopped()
    assert [e.event_type for e in events]==[PlaybackEventType.STARTED,PlaybackEventType.COMPLETED]
    assert all(e.speech is speech for e in events)


def test_stop_waits_rust_fact_and_stale_fact_cannot_change_next(bridge):
    adapter,speech,sent=bridge;adapter.play(speech);old=sent[0][1]
    adapter.accept(fact(old,"started"));adapter.stop();adapter.stop()
    assert sent[-1][0]=="audio.stop.request"
    assert not adapter._stopped.is_set()  # not a fabricated idle on send
    adapter.accept(fact(old,"stopped"));adapter.wait_stopped()
    adapter.bind("g2",4);adapter.play(speech);new=sent[-1][1]
    adapter.accept(fact(old,"failed","AUDIO_DEVICE_FAILED"));assert not adapter._stopped.is_set()
    adapter.accept(fact(new,"started"));assert adapter.is_playing()
    adapter.accept(fact(new,"completed"));adapter.shutdown();adapter.shutdown()


@pytest.mark.parametrize("error",["AUDIO_DECODE_FAILED","AUDIO_DEVICE_UNAVAILABLE","AUDIO_DEVICE_FAILED","AUDIO_FILE_UNAVAILABLE"])
def test_errors_remain_playback_facts(bridge,error):
    adapter,speech,sent=bridge;events=[];adapter.subscribe(events.append);adapter.play(speech)
    adapter.accept(fact(sent[0][1],"failed",error));adapter.wait_stopped()
    assert events[-1].event_type is PlaybackEventType.FAILED
    assert events[-1].error==error


def test_path_outside_root_missing_and_disconnect(bridge,tmp_path):
    adapter,speech,sent=bridge
    with pytest.raises(FileNotFoundError):adapter.play(SpeechResult(audio_path=str(tmp_path/"missing.wav")))
    with pytest.raises(ValueError):adapter.play(SpeechResult(audio_path=str(ROOT/"README.md")))
    assert not sent
    adapter.play(speech);adapter.disconnected();adapter.wait_stopped()
    with pytest.raises(RuntimeError):adapter.bind("g2",2)


@pytest.mark.parametrize("cancel",[False,True])
def test_voice_authority_waits_rust_terminal_and_cleans_temp(voice,tmp_path,cancel):
    v,_,provider,_,events=voice
    v.audio_root=str(tmp_path)
    provider.result=SpeechResult(audio_bytes=b"encoded WAV fixture")
    sent=[];adapter=RustPlayback(tmp_path,lambda k,p: sent.append((k,p)) or True)
    v.playback_factory=lambda:adapter
    v.completed("g1","完整回复")
    wait_for(lambda:len(sent)>0);payload=sent[0][1]
    artifact=tmp_path/payload["file"];assert artifact.exists()
    assert v.snapshot()["state"]=="preparing"
    assert not v.completed("g1","重复")
    adapter.accept(fact(payload,"started"));assert v.snapshot()["state"]=="speaking"
    if cancel:
        v.stop("g1");assert v.snapshot()["state"]=="stopping"
        assert artifact.exists()
    adapter.accept(fact(payload,"stopped" if cancel else "completed"))
    wait_for(lambda:v.snapshot()["state"]=="idle")
    assert not artifact.exists()
    assert not v.completed("g1","迟到")
    assert len([s for s in sent if s[0]=="audio.play.request"])==1


def test_private_audio_contract_agrees_with_schema():
    import jsonschema
    schema=json.loads((ROOT/"prototype/aurora-v4/contracts/ipc-v1.schema.json").read_text())
    for kind,payload in [("audio.play.request",{"generation_id":"g","revision":2,"file":"run/audio.mp3"}),
                         ("audio.stop.request",{"generation_id":"g","revision":2}),
                         ("audio.event",{"generation_id":"g","revision":2,"state":"completed","error_code":""})]:
        message=dict(protocol="aurora-ipc",version=1,type=kind,payload=payload)
        validate_message(message);jsonschema.validate(message,schema)
        for field in ["text","endpoint","token","path"]:
            bad=copy.deepcopy(message);bad["payload"][field]="private"
            with pytest.raises(ContractError):validate_message(bad)
            with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,schema)


@pytest.mark.parametrize("phase",["preparing","speaking","stopping"])
def test_shutdown_in_each_phase_joins_after_rust_release(voice,tmp_path,phase):
    v,_,provider,_,_=voice
    v.audio_root=str(tmp_path);provider.result=SpeechResult(audio_bytes=b"encoded fixture")
    sent=[];adapter=RustPlayback(tmp_path,lambda k,p:sent.append((k,p)) or True)
    v.playback_factory=lambda:adapter;v.completed("g1","text")
    wait_for(lambda:bool(sent));payload=sent[0][1];artifact=tmp_path/payload["file"]
    if phase in {"speaking","stopping"}:adapter.accept(fact(payload,"started"))
    if phase=="stopping":v.stop("g1")
    closer=threading.Thread(target=v.close);closer.start()
    try:
        wait_for(lambda:any(k=="audio.stop.request" for k,_ in sent))
        assert artifact.exists();assert closer.is_alive()
        adapter.accept(fact(payload,"stopped"));closer.join(2)
        assert not closer.is_alive();assert not v._workers;assert not artifact.exists()
        assert len([k for k,_ in sent if k=="audio.stop.request"])==1
    finally:
        adapter.disconnected();closer.join(3)
