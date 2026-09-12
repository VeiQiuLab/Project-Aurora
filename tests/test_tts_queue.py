from dataclasses import FrozenInstanceError
from threading import Event, Lock

import pytest

from modules.experience.voice.models import SpeechSegment
from modules.experience.voice.tts_queue import TTSQueue


def segment(index, text=None, *, session_id="session", generation_id="generation"):
    return SpeechSegment(
        session_id=session_id,
        generation_id=generation_id,
        segment_index=index,
        text=text or f"segment-{index}",
    )


def events(queue):
    return [item["event"] for item in queue.diagnostics]


def test_speech_segment_is_immutable_and_validated():
    item = segment(0, "hello")

    with pytest.raises(FrozenInstanceError):
        item.text = "changed"
    with pytest.raises(ValueError, match="text"):
        SpeechSegment("session", "generation", 0, "  ")
    with pytest.raises(ValueError, match="segment_index"):
        SpeechSegment("session", "generation", -1, "text")
    with pytest.raises(ValueError, match="session_id"):
        SpeechSegment("", "generation", 0, "text")


def test_tts_queue_consumes_segments_in_fifo_order_with_lifecycle_diagnostics():
    requests = []
    results = []
    lock = Lock()

    def synthesize(item, cancel_event):
        with lock:
            requests.append(item.segment_index)
        return f"audio:{item.text}"

    queue = TTSQueue(
        synthesize,
        on_speech=lambda item, speech: results.append((item.segment_index, speech)),
        session_id="session",
        generation_id="generation",
    )
    queue.start()
    for index in range(3):
        item = segment(index)
        queue.note_emitted(item)
        assert queue.put(item) is True

    assert queue.flush(timeout_seconds=1.0) is True
    assert requests == [0, 1, 2]
    assert results == [
        (0, "audio:segment-0"),
        (1, "audio:segment-1"),
        (2, "audio:segment-2"),
    ]
    for name in (
        "segment_emitted",
        "segment_enqueued",
        "segment_dequeued",
        "segment_tts_started",
        "segment_tts_completed",
        "segment_playback_started",
        "segment_completed",
    ):
        assert name in events(queue)
    assert all("text" not in entry for entry in queue.diagnostics)
    assert queue.close() is True


def test_tts_queue_rejects_non_segment_and_stale_generation_before_enqueue():
    requests = []
    queue = TTSQueue(
        lambda item, _cancel: requests.append(item.text),
        session_id="session",
        generation_id="active",
        generation_active=lambda session_id, generation_id: (
            session_id == "session" and generation_id == "active"
        ),
    )
    queue.start()

    with pytest.raises(TypeError, match="SpeechSegment"):
        queue.put("plain text")
    assert queue.put(segment(0, session_id="old", generation_id="active")) is False
    assert queue.put(segment(0, session_id="session", generation_id="old")) is False

    assert queue.flush(timeout_seconds=1.0) is True
    assert requests == []
    assert events(queue).count("stale_dropped") == 2
    assert queue.close() is True


def test_generation_becoming_stale_after_enqueue_is_dropped_at_dequeue():
    active = Event()
    active.set()
    requests = []
    queue = TTSQueue(
        lambda item, _cancel: requests.append(item.text),
        session_id="session",
        generation_id="generation",
        generation_active=lambda _session, _generation: active.is_set(),
    )
    assert queue.put(segment(0)) is True
    active.clear()
    queue.start()

    assert queue.flush(1.0) is True
    assert requests == []
    assert any(
        item["event"] == "stale_dropped" and item.get("checkpoint") == "dequeue"
        for item in queue.diagnostics
    )
    assert queue.close() is True


def test_generation_becoming_stale_before_synthesize_is_dropped():
    checks = 0
    requests = []

    def active(_session, _generation):
        nonlocal checks
        checks += 1
        return checks < 4

    queue = TTSQueue(
        lambda item, _cancel: requests.append(item.text),
        session_id="session",
        generation_id="generation",
        generation_active=active,
    )
    queue.start()
    assert queue.put(segment(0)) is True

    assert queue.flush(1.0) is True
    assert requests == []
    assert any(
        item["event"] == "stale_dropped" and item.get("checkpoint") == "before_tts"
        for item in queue.diagnostics
    )
    assert queue.close() is True


def test_cancel_during_synthesize_discards_late_result_and_pending_segments():
    started = Event()
    release = Event()
    requests = []
    played = []

    def synthesize(item, _cancel_event):
        requests.append(item.segment_index)
        started.set()
        release.wait(1.0)
        return f"audio:{item.text}"

    queue = TTSQueue(
        synthesize,
        on_speech=lambda item, _speech: played.append(item.segment_index),
        session_id="session",
        generation_id="generation",
    )
    queue.start()
    queue.put(segment(0))
    queue.put(segment(1))
    assert started.wait(1.0) is True

    assert queue.cancel(wait=False) is False
    release.set()

    assert queue.flush(1.0) is True
    assert queue.cancel() is True
    assert requests == [0]
    assert played == []
    assert queue.last_error is None
    assert "segment_cancelled" in events(queue)


def test_cancel_during_playback_callback_does_not_mark_segment_completed():
    playback_started = Event()
    release = Event()

    def on_speech(_item, _speech):
        playback_started.set()
        release.wait(1.0)

    queue = TTSQueue(
        lambda item, _cancel: item.text,
        on_speech=on_speech,
        session_id="session",
        generation_id="generation",
    )
    queue.start()
    queue.put(segment(0))
    assert playback_started.wait(1.0) is True

    queue.cancel(wait=False)
    release.set()

    assert queue.flush(1.0) is True
    assert queue.cancel() is True
    assert "segment_completed" not in events(queue)
    assert queue.last_error is None


def test_segment_failure_is_generation_fail_fast_and_discards_later_work():
    requests = []
    failures = []

    def synthesize(item, _cancel_event):
        requests.append(item.segment_index)
        if item.segment_index == 0:
            raise RuntimeError("synthetic failure")
        return item.text

    queue = TTSQueue(
        synthesize,
        session_id="session",
        generation_id="generation",
        on_generation_failed=lambda item, error: failures.append((item, error)),
    )
    queue.put(segment(0))
    queue.put(segment(1))
    queue.start()

    assert queue.flush(1.0) is True
    assert requests == [0]
    assert len(failures) == 1
    assert isinstance(queue.last_error, RuntimeError)
    assert "segment_failed" in events(queue)
    assert any(item.get("reason") == "generation_failed" for item in queue.diagnostics)
    assert queue.close() is True


def test_cancellation_side_effect_error_remains_cancelled_not_failed():
    started = Event()
    release = Event()

    def synthesize(_item, _cancel_event):
        started.set()
        release.wait(1.0)
        raise OSError("socket closed")

    queue = TTSQueue(
        synthesize,
        session_id="session",
        generation_id="generation",
    )
    queue.start()
    queue.put(segment(0))
    assert started.wait(1.0) is True
    queue.cancel(wait=False)
    release.set()

    assert queue.flush(1.0) is True
    assert queue.cancel() is True
    assert queue.last_error is None
    assert "segment_failed" not in events(queue)
    assert "segment_cancelled" in events(queue)


def test_duplicate_and_lower_indices_are_rejected_while_skip_is_diagnostic():
    requested = []
    queue = TTSQueue(
        lambda item, _cancel: requested.append(item.segment_index),
        session_id="session",
        generation_id="generation",
    )
    assert queue.put(segment(0)) is True
    assert queue.put(segment(0, "duplicate")) is False
    assert queue.put(segment(2)) is True
    assert queue.put(segment(1, "lower")) is False
    queue.start()

    assert queue.flush(1.0) is True
    assert requested == [0, 2]
    reasons = [
        item.get("reason")
        for item in queue.diagnostics
        if item["event"] == "ordering_anomaly"
    ]
    assert reasons == ["duplicate_or_lower_index", "skipped_index", "duplicate_or_lower_index"]
    assert queue.close() is True


def test_repeated_cancel_close_and_shutdown_leave_no_worker():
    queue = TTSQueue(
        lambda item, _cancel: item.text,
        session_id="session",
        generation_id="generation",
    )
    queue.start()
    queue.put(segment(0))

    assert queue.cancel() is True
    assert queue.cancel() is True
    assert queue.close() is True
    assert queue.shutdown() is True
    assert queue.running is False


def test_generation_n_late_completion_cannot_enter_generation_n_plus_one():
    old_started = Event()
    release_old = Event()
    active_generation = {"value": "old"}
    played = []

    def active(_session, generation_id):
        return generation_id == active_generation["value"]

    def old_synthesize(item, _cancel):
        old_started.set()
        release_old.wait(1.0)
        return item.text

    old_queue = TTSQueue(
        old_synthesize,
        on_speech=lambda item, _speech: played.append(("old", item.segment_index)),
        session_id="session",
        generation_id="old",
        generation_active=active,
    )
    old_queue.start()
    old_queue.put(segment(0, generation_id="old"))
    old_queue.put(segment(1, generation_id="old"))
    assert old_started.wait(1.0) is True

    active_generation["value"] = "new"
    old_queue.cancel(wait=False)
    new_queue = TTSQueue(
        lambda item, _cancel: item.text,
        on_speech=lambda item, _speech: played.append(("new", item.segment_index)),
        session_id="session",
        generation_id="new",
        generation_active=active,
    )
    new_queue.start()
    assert new_queue.put(segment(0, generation_id="new")) is True
    release_old.set()

    assert old_queue.flush(1.0) is True
    assert new_queue.flush(1.0) is True
    assert old_queue.cancel() is True
    assert new_queue.close() is True
    assert played == [("new", 0)]
