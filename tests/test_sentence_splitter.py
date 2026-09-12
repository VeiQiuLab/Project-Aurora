import random

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


@pytest.mark.parametrize("punctuation", ["。", "！", "？", "!", "?"])
def test_hard_boundary_emits_short_complete_sentence(punctuation):
    splitter = SentenceSplitter()

    assert splitter.feed(f"好{punctuation}") == [f"好{punctuation}"]


def test_english_period_and_paragraph_boundaries_emit_in_order():
    splitter = SentenceSplitter()

    assert splitter.feed("Hello. Next paragraph\r\nLast") == ["Hello.", "Next paragraph"]
    assert splitter.flush() == ["Last"]


def test_trailing_english_period_waits_for_lookahead_or_final_flush():
    splitter = SentenceSplitter()

    assert splitter.feed("Hello.") == []
    assert splitter.flush() == ["Hello."]


@pytest.mark.parametrize("ellipsis", ["……", "…………", "...", "....."])
def test_ellipsis_is_one_boundary_without_empty_segments(ellipsis):
    splitter = SentenceSplitter()

    assert splitter.feed(f"等等{ellipsis}继续。") == [f"等等{ellipsis}", "继续。"]


@pytest.mark.parametrize("punctuation", ["；", ";", "：", ":"])
def test_semicolon_and_colon_split_after_minimum(punctuation):
    splitter = SentenceSplitter(min_soft_chars=6, target_chars=10, max_chars=20)

    assert splitter.feed(f"一二三四五{punctuation}后续") == [f"一二三四五{punctuation}"]
    assert splitter.flush() == ["后续"]


def test_short_soft_fragment_is_merged_with_later_hard_sentence():
    splitter = SentenceSplitter()

    assert splitter.feed("很短；继续说完。") == ["很短；继续说完。"]


def test_comma_only_splits_at_target_length():
    splitter = SentenceSplitter(min_soft_chars=4, target_chars=8, max_chars=20)

    assert splitter.feed("短句，") == []
    assert splitter.feed("继续达到长度，尾巴") == ["短句，继续达到长度，"]
    assert splitter.flush() == ["尾巴"]


@pytest.mark.parametrize("number", ["3.14", "0.5", "12.345"])
def test_decimal_periods_are_protected(number):
    splitter = SentenceSplitter()

    assert splitter.feed(f"数值是 {number}。下一句。") == [f"数值是 {number}。", "下一句。"]


@pytest.mark.parametrize(
    "protected_text",
    [
        "https://example.com/path",
        "http://example.com",
        "example.com",
        "www.example.com",
        "test@example.com",
    ],
)
def test_network_identifiers_are_not_split_at_periods(protected_text):
    splitter = SentenceSplitter(max_chars=100)

    assert splitter.feed(f"请访问 {protected_text}。完成。") == [
        f"请访问 {protected_text}。",
        "完成。",
    ]


@pytest.mark.parametrize("abbreviation", ["e.g.", "i.e.", "Dr.", "Mr.", "Ms.", "U.S.", "A.I."])
def test_common_abbreviations_are_not_split(abbreviation):
    splitter = SentenceSplitter(max_chars=100)

    assert splitter.feed(f"Use {abbreviation} as one token. Done.") == [
        f"Use {abbreviation} as one token.",
    ]
    assert splitter.flush() == ["Done."]


def test_markdown_link_url_is_protected():
    splitter = SentenceSplitter(max_chars=100)

    text = "打开 [OpenAI](https://openai.com) 查看。下一句。"
    assert splitter.feed(text) == ["打开 [OpenAI](https://openai.com) 查看。", "下一句。"]


def test_inline_code_is_not_split_internally():
    splitter = SentenceSplitter(max_chars=100)

    assert splitter.feed("调用 `foo.bar()`，然后继续。") == ["调用 `foo.bar()`，然后继续。"]


def test_fenced_code_is_protected_from_internal_punctuation_and_newlines():
    splitter = SentenceSplitter(max_chars=200)
    text = "示例：```python\nvalue = 1.0\nprint(value)\n```说明完成。"

    assert splitter.feed(text) == [text]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("“你好。”", "“你好。”"),
        ("「你好。」", "「你好。」"),
        ("(hello.)", "(hello.)"),
        ("（你好。）", "（你好。）"),
        ("【完成！】", "【完成！】"),
        ("《可以？》", "《可以？》"),
        ('"hello."', '"hello."'),
    ],
)
def test_closing_quote_or_bracket_stays_with_segment(text, expected):
    splitter = SentenceSplitter()

    assert splitter.feed(text) == [expected]


def test_closing_quote_can_arrive_in_next_chunk():
    splitter = SentenceSplitter()

    assert splitter.feed("“你好。") == []
    assert splitter.feed("”下一句。") == ["“你好。”", "下一句。"]


def test_punctuation_can_arrive_in_next_chunk():
    splitter = SentenceSplitter()

    assert splitter.feed("你好") == []
    assert splitter.feed("。") == ["你好。"]


def test_url_can_cross_chunk_boundary():
    splitter = SentenceSplitter(max_chars=100)

    assert splitter.feed("https://example") == []
    assert splitter.feed(".com 是网站。") == ["https://example.com 是网站。"]


def test_decimal_can_cross_chunk_boundary():
    splitter = SentenceSplitter()

    assert splitter.feed("数值是 3.") == []
    assert splitter.feed("14。") == ["数值是 3.14。"]


def test_unicode_ellipsis_can_cross_chunk_boundary():
    splitter = SentenceSplitter()

    assert splitter.feed("这是…") == []
    assert splitter.feed("…下一句。") == ["这是……", "下一句。"]


def test_hard_maximum_prevents_unbounded_unpunctuated_buffer():
    splitter = SentenceSplitter(min_soft_chars=4, target_chars=8, max_chars=16)

    assert splitter.feed("一二三四五六七八九十一二三四五六七") == ["一二三四五六七八九十一二三四五六"]
    assert splitter.pending_text == "七"


def test_hard_maximum_prefers_nearest_soft_boundary_then_whitespace():
    splitter = SentenceSplitter(min_soft_chars=12, target_chars=14, max_chars=16)

    assert splitter.feed("short,abcdefghijk") == ["short,"]
    assert splitter.pending_text == "abcdefghijk"

    splitter.clear()
    assert splitter.feed("alpha beta gamma delta") == ["alpha beta"]
    assert splitter.pending_text == "gamma delta"


def test_hard_maximum_does_not_split_unicode_combining_sequence():
    splitter = SentenceSplitter(min_soft_chars=2, target_chars=3, max_chars=4)
    text = "abcde\u0301f"

    segments = splitter.feed(text) + splitter.flush()
    assert "".join(segments) == text
    assert not segments[1].startswith("\u0301")


def test_flush_is_idempotent_and_next_feed_starts_clean_cycle():
    splitter = SentenceSplitter()

    splitter.feed("第一轮残余")
    assert splitter.flush() == ["第一轮残余"]
    assert splitter.flush() == []
    assert splitter.feed("第二轮。") == ["第二轮。"]


def test_clear_resets_text_and_deadline_state(monkeypatch):
    timestamps = iter((10.0, 11.0))
    monkeypatch.setattr(sentence_splitter_module, "monotonic", lambda: next(timestamps))
    splitter = SentenceSplitter(min_soft_chars=4)

    splitter.feed("旧 generation 文本")
    splitter.clear()
    assert splitter.pending_text == ""
    assert splitter.pending_since_monotonic is None
    assert splitter.last_append_monotonic is None
    assert splitter.feed("新文本。") == ["新文本。"]


def test_late_feed_after_clear_cannot_restore_old_pending_text():
    splitter = SentenceSplitter()
    splitter.feed("旧的未完成文本")
    splitter.clear()

    assert splitter.feed("迟到 chunk。") == ["迟到 chunk。"]


def test_flush_due_uses_last_append_and_requires_enough_text(monkeypatch):
    timestamps = iter((100.0, 100.3, 200.0))
    monkeypatch.setattr(sentence_splitter_module, "monotonic", lambda: next(timestamps))
    splitter = SentenceSplitter(min_soft_chars=6, max_wait_seconds=0.5)

    splitter.feed("足够长度文本")
    assert splitter.flush_due(100.49) is False
    assert splitter.flush_due(100.5) is True
    assert splitter.feed("继续") == []
    assert splitter.flush_due(100.79) is False
    assert splitter.flush_due(100.8) is True

    short = SentenceSplitter(min_soft_chars=6, max_wait_seconds=0.5)
    short.feed("短文")
    assert short.flush_due(999.0) is False


def test_empty_and_whitespace_only_chunks_do_not_create_pending_state():
    splitter = SentenceSplitter()

    assert splitter.feed("") == []
    assert splitter.feed("   \r\n") == []
    assert splitter.pending_text == ""
    assert splitter.flush_due(999.0) is False


def test_incremental_reconstruction_has_no_lost_or_duplicate_characters():
    text = "你好，访问 https://example.com/path；数值 3.14……再看 `foo.bar()`。结尾无标点🙂"

    for chunk_size in range(1, 12):
        splitter = SentenceSplitter(max_chars=100)
        emitted = []
        for offset in range(0, len(text), chunk_size):
            emitted.extend(splitter.feed(text[offset : offset + chunk_size]))
        emitted.extend(splitter.flush())
        assert "".join(emitted).replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize(
    "text",
    [
        "Visit example.com. Done.",
        "Use e.g. one example. Done.",
        "Wait... Continue.",
    ],
)
def test_ambiguous_period_constructs_are_stable_across_every_chunk_boundary(text):
    for boundary in range(1, len(text)):
        splitter = SentenceSplitter(max_chars=100)
        emitted = splitter.feed(text[:boundary])
        emitted.extend(splitter.feed(text[boundary:]))
        emitted.extend(splitter.flush())
        assert "".join(emitted).replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_soft_chars": 0},
        {"target_chars": 0},
        {"max_chars": 0},
        {"min_soft_chars": 12, "target_chars": 11},
        {"target_chars": 32, "max_chars": 31},
        {"max_chars": 64, "absolute_max_chars": 63},
        {"max_wait_seconds": 0},
        {"max_wait_seconds": float("inf")},
    ],
)
def test_invalid_segmentation_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        SentenceSplitter(**kwargs)


def test_wrapper_internal_ellipsis_waits_for_closing_quote():
    splitter = SentenceSplitter()
    text = "他说：“我觉得可以……不过还需要再看看。”然后就停下来了。"

    assert splitter.feed(text) == [
        "他说：“我觉得可以……不过还需要再看看。”",
        "然后就停下来了。",
    ]


def test_wrapper_and_ellipsis_state_survives_chunk_boundary():
    splitter = SentenceSplitter()

    assert splitter.feed("他说：“可以……") == []
    assert splitter.feed("继续。”下一句。") == ["他说：“可以……继续。”", "下一句。"]


def test_nested_wrapper_keeps_internal_ellipsis_until_outer_quote_closes():
    splitter = SentenceSplitter()
    text = "他说：“这个（其实还可以……）不过要测试。”然后继续。"

    assert splitter.feed(text) == [
        "他说：“这个（其实还可以……）不过要测试。”",
        "然后继续。",
    ]


def test_question_mark_absorbs_closing_quote_before_emit():
    splitter = SentenceSplitter()

    assert splitter.feed("他说：“真的可以吗？”然后离开。") == [
        "他说：“真的可以吗？”",
        "然后离开。",
    ]


def test_long_wrapper_may_cross_normal_max_until_safe_close():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=128,
    )
    quoted = "“" + "很长引用内容" * 8 + "。”"

    assert splitter.feed("他说：" + quoted + "然后继续。") == [
        "他说：",
        quoted,
        "然后继续。",
    ]


def test_wrapper_absolute_cut_preserves_balance_and_internal_punctuation_mode():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=48,
    )
    text = "他说：“" + ("引用内容……仍未结束" * 8) + "。”然后继续。"
    emitted = []
    peak = 0

    for offset in range(0, len(text), 13):
        emitted.extend(splitter.feed(text[offset : offset + 13]))
        peak = max(peak, len(splitter.pending_text))
    emitted.extend(splitter.flush())

    assert peak <= splitter.absolute_max_chars
    assert "".join(emitted) == text
    assert all(not segment.startswith("……") for segment in emitted)
    assert emitted[-1] == "然后继续。"


def test_long_url_adjacent_to_chinese_crosses_normal_max_without_internal_split():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=32,
        absolute_max_chars=256,
    )
    url = "https://example.com/" + "very-long-path-segment-" * 5 + "end"
    text = "网址是" + url + "。后续文本。"
    emitted = []

    for offset in range(0, len(text), 19):
        emitted.extend(splitter.feed(text[offset : offset + 19]))
    emitted.extend(splitter.flush())

    assert emitted == ["网址是", url + "。", "后续文本。"]
    assert "".join(emitted) == text


def test_long_markdown_link_is_kept_whole_beyond_normal_max():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=32,
        absolute_max_chars=256,
    )
    link = "[文档](https://example.com/" + "path-segment-" * 6 + "index.html)"
    text = "请看" + link + "，然后继续。"
    emitted = []

    for offset in range(0, len(text), 17):
        emitted.extend(splitter.feed(text[offset : offset + 17]))
    emitted.extend(splitter.flush())

    assert emitted == ["请看", link + "，", "然后继续。"]
    assert "".join(emitted) == text


def test_long_inline_code_is_kept_whole_beyond_normal_max():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=32,
        absolute_max_chars=256,
    )
    code = "`" + "object.foo.bar(123.45)." * 5 + "done()`"
    text = "运行" + code + "。结束。"
    emitted = []

    for offset in range(0, len(text), 17):
        emitted.extend(splitter.feed(text[offset : offset + 17]))
    emitted.extend(splitter.flush())

    assert emitted == ["运行", code + "。", "结束。"]
    assert "".join(emitted) == text


def test_long_fenced_code_is_kept_whole_beyond_normal_max():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=32,
        absolute_max_chars=512,
    )
    fence = "`" * 3
    code = fence + "python\n" + "value = foo.bar(123.45)\n" * 8 + fence
    text = "代码如下：" + code + "\n后续文本。"
    emitted = []

    for offset in range(0, len(text), 23):
        emitted.extend(splitter.feed(text[offset : offset + 23]))
    emitted.extend(splitter.flush())

    assert emitted == ["代码如下：", code, "后续文本。"]
    assert "".join("".join(emitted).split()) == "".join(text.split())


@pytest.mark.parametrize("kind", ["url", "fence"])
def test_absolute_defensive_cut_is_bounded_and_preserves_protected_mode(kind):
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=64,
    )
    if kind == "url":
        protected = "https://example.com/" + "abc.def/" * 30 + "end"
        text = "前文" + protected + "。后文。"
    else:
        fence = "`" * 3
        protected = fence + "python\n" + "value = foo.bar(123.45)\n" * 20 + fence
        text = "前文" + protected + "\n后文。"
    emitted = []
    peak = 0

    for offset in range(0, len(text), 11):
        emitted.extend(splitter.feed(text[offset : offset + 11]))
        peak = max(peak, len(splitter.pending_text))
    emitted.extend(splitter.flush())

    assert peak <= splitter.absolute_max_chars
    assert "".join("".join(emitted).split()) == "".join(text.split())
    if kind == "url":
        protected_segments = emitted[1:-1]
        assert all("。" not in segment for segment in protected_segments[:-1])
    else:
        protected_segments = emitted[1:-1]
        assert all("value = foo.bar" in segment for segment in protected_segments)
        assert all(
            len(segment) >= splitter.absolute_max_chars - 2
            for segment in protected_segments[:-1]
        )
        assert protected_segments[0].startswith("```python")
        assert protected_segments[-1].endswith("```")


def test_clear_resets_protected_continuation_after_defensive_cut():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=32,
    )
    splitter.feed("```" + "code.with.period\n" * 3)

    splitter.clear()

    assert splitter.feed("普通句子。") == ["普通句子。"]


def test_timeout_does_not_flush_incomplete_protected_or_wrapper_state():
    splitter = SentenceSplitter(min_soft_chars=4, max_wait_seconds=0.5)
    splitter.feed("网址是https://example.com/unfinished")
    assert splitter.flush_due(splitter.last_append_monotonic + 10.0) is False

    splitter.clear()
    splitter.feed("他说：“这段引用尚未关闭")
    assert splitter.flush_due(splitter.last_append_monotonic + 10.0) is False

    splitter.clear()
    splitter.feed("```python\nvalue = foo.bar()")
    assert splitter.flush_due(splitter.last_append_monotonic + 10.0) is False


def test_url_start_allows_chinese_but_rejects_ascii_identifier_prefix():
    splitter = SentenceSplitter(max_chars=100)

    assert splitter.feed("网址是https://example.com/path。") == [
        "网址是https://example.com/path。"
    ]

    invalid = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=128,
    )
    emitted = invalid.feed("foohttps://example.com/a-very-long-path")
    assert emitted[0] == "foohttps:"
    assert len(invalid.pending_text) <= invalid.absolute_max_chars


def test_ascii_apostrophe_in_contraction_is_not_treated_as_wrapper():
    splitter = SentenceSplitter()

    assert splitter.feed("Don't split. Next.") == ["Don't split."]
    assert splitter.flush() == ["Next."]


def test_markdown_link_followed_by_domain_suffix_across_chunks_stays_whole():
    splitter = SentenceSplitter()
    chunks = (
        "数值是 3.",
        "14，网站是 [https://example](https://example)",
        ".com/path。然后他说：“可以",
        "……",
        "继续。”",
    )
    emitted = []

    for chunk in chunks:
        emitted.extend(splitter.feed(chunk))
    emitted.extend(splitter.flush())

    assert emitted == [
        "数值是 3.14，网站是 [https://example](https://example).com/path。",
        "然后他说：“可以……继续。”",
    ]


def test_completed_markdown_link_keeps_following_sentence_period():
    splitter = SentenceSplitter(max_chars=32)
    link = "[https://example.com/docs](https://example.com/docs)"

    assert splitter.feed(link + ". Next sentence.") == [link + "."]
    assert splitter.flush() == ["Next sentence."]


def test_randomized_chunk_boundaries_preserve_text_and_protected_constructs():
    url = "https://example.com/a.long/path"
    markdown = "[OpenAI 文档](https://openai.com/docs/v3.14/index.html)"
    inline = "`foo.bar(3.14)`"
    fence = "```python\nvalue = foo.bar(3.14)\nprint(value)\n```"
    quoted = "他说：“可以……继续。”"
    text = (
        "网址是" + url + "。请看" + markdown + "，运行" + inline +
        "。" + quoted + "代码：" + fence + "\n结束。"
    )

    for seed in range(40):
        rng = random.Random(seed)
        chunks = []
        offset = 0
        while offset < len(text):
            size = rng.randint(1, 17)
            chunks.append(text[offset : offset + size])
            offset += size

        splitter = SentenceSplitter(max_chars=32, absolute_max_chars=256)
        emitted = []
        for chunk in chunks:
            emitted.extend(splitter.feed(chunk))
        emitted.extend(splitter.flush())

        normalized = lambda value: "".join(value.split())
        assert normalized("".join(emitted)) == normalized(text)
        for protected in (url, markdown, inline, fence, quoted):
            assert sum(protected in segment for segment in emitted) == 1


def test_never_closed_fence_is_bounded_and_retains_continuation_mode():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=64,
    )
    text = "```python\n" + "value = foo.bar(123.45)\n" * 18
    emitted = []
    peak = 0

    for offset in range(0, len(text), 9):
        emitted.extend(splitter.feed(text[offset : offset + 9]))
        peak = max(peak, len(splitter.pending_text))
    emitted.extend(splitter.flush())

    assert peak <= splitter.absolute_max_chars
    assert "".join("".join(emitted).split()) == "".join(text.split())
    assert all(
        len(segment) >= splitter.absolute_max_chars - 1
        for segment in emitted[:-1]
    )


def test_malformed_markdown_is_bounded_and_recovers_after_late_close():
    splitter = SentenceSplitter(
        min_soft_chars=4,
        target_chars=8,
        max_chars=16,
        absolute_max_chars=64,
    )
    opening = "前文[broken](https://example.com/" + "path.with.period/" * 12
    emitted = []
    peak = 0

    for offset in range(0, len(opening), 11):
        emitted.extend(splitter.feed(opening[offset : offset + 11]))
        peak = max(peak, len(splitter.pending_text))
    emitted.extend(splitter.feed(")。后文。"))
    emitted.extend(splitter.flush())

    assert peak <= splitter.absolute_max_chars
    assert "".join("".join(emitted).split()) == "".join((opening + ")。后文。").split())
    assert emitted[-1] == "后文。"
