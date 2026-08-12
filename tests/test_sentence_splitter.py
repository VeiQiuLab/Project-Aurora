import pytest

import modules.experience.voice.sentence_splitter as sentence_splitter_module
from modules.experience.voice.sentence_splitter import SentenceSplitter


def test_sentence_splitter_emits_sentences_across_chunks():
    splitter = SentenceSplitter()

    assert splitter.feed("你好，我是") == []
    assert splitter.feed(" Aurora。今天想") == ["你好，我是 Aurora。"]
    assert splitter.feed("聊什么？") == ["今天想聊什么？"]
    assert splitter.flush() == []


def test_sentence_splitter_flushes_unterminated_text():
    splitter = SentenceSplitter()

    splitter.feed("这是最后一句")

    assert splitter.flush() == ["这是最后一句"]
    assert splitter.pending_text == ""


def test_sentence_splitter_does_not_split_decimal_numbers():
    splitter = SentenceSplitter()

    assert splitter.feed("版本 3.8。下一句") == ["版本 3.8。"]


def test_sentence_splitter_rejects_non_string_chunks():
    with pytest.raises(TypeError):
        SentenceSplitter().feed(None)


def test_sentence_splitter_flushes_expired_unterminated_buffer(monkeypatch):
    timestamps = iter((100.0, 102.0, 102.0))
    monkeypatch.setattr(sentence_splitter_module, "monotonic", lambda: next(timestamps))
    splitter = SentenceSplitter(max_wait_seconds=1.5)
    assert splitter.feed("a long streamed response") == []
    assert splitter.feed(" continues") == ["a long streamed response"]
    assert splitter.pending_text == " continues"
    assert splitter.flush() == ["continues"]
    assert splitter.pending_text == ""


def test_sentence_splitter_clear_discards_pending_generation_text():
    splitter = SentenceSplitter()
    splitter.feed("pending text")
    splitter.clear()
    assert splitter.flush() == []
