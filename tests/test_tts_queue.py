import time
from threading import Event, Lock

from modules.experience.voice.tts_queue import TTSQueue


def test_tts_queue_consumes_sentences_in_fifo_order():
    requests = []
    results = []
    lock = Lock()

    def synthesize(text, cancel_event):
        with lock:
            requests.append(text)
        return f"audio:{text}"

    queue = TTSQueue(synthesize, on_speech=lambda text, speech: results.append((text, speech)))
    queue.start()
    queue.put("第一句")
    queue.put("第二句")
    queue.put("第三句")

    assert queue.flush(timeout_seconds=1.0) is True
    assert requests == ["第一句", "第二句", "第三句"]
    assert results == [("第一句", "audio:第一句"), ("第二句", "audio:第二句"), ("第三句", "audio:第三句")]
    assert queue.close() is True


def test_tts_queue_cancel_skips_pending_items():
    started = Event()
    release = Event()
    requests = []

    def synthesize(text, cancel_event):
        requests.append(text)
        started.set()
        release.wait(1.0)
        return text

    queue = TTSQueue(synthesize)
    queue.start()
    queue.put("当前")
    queue.put("待取消")
    assert started.wait(1.0) is True

    queue.cancel(wait=False)
    release.set()

    assert queue.flush(timeout_seconds=1.0) is True
    assert queue.close() is True
    assert requests == ["当前"]


def test_tts_queue_records_worker_errors_and_continues():
    requests = []

    def synthesize(text, cancel_event):
        requests.append(text)
        if text == "失败":
            raise RuntimeError("synthetic failure")
        return text

    queue = TTSQueue(synthesize)
    queue.start()
    queue.put("失败")
    queue.put("继续")

    assert queue.flush(timeout_seconds=1.0) is True
    assert requests == ["失败", "继续"]
    assert isinstance(queue.last_error, RuntimeError)
    assert queue.close() is True


def test_tts_queue_rejects_stale_generation_before_enqueue():
    requests = []

    def synthesize(text, cancel_event):
        requests.append(text)
        return text

    queue = TTSQueue(synthesize, session_id="session", generation_id="active")
    queue.start()
    queue.put("stale", session_id="session", generation_id="old")
    queue.put("wrong session", session_id="old", generation_id="active")
    assert queue.flush(timeout_seconds=1.0) is True
    assert requests == []
    assert queue.close() is True
