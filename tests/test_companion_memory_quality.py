"""V4-8E isolated quality and governance-boundary acceptance."""
from copy import deepcopy
import json
import pytest
from modules.memory import MemoryExtractor, MemoryStore
from modules.memory_intelligence import analyze_memory_candidates
from modules.memory_retrieval import retrieve_memories, format_memory_context
from tests.memory_quality_corpus import CANDIDATES, RETRIEVAL, MEMORIES, evaluate


@pytest.mark.parametrize('name,messages,expected', CANDIDATES, ids=[c[0] for c in CANDIDATES])
def test_candidate_corpus(name, messages, expected):
    before = deepcopy(messages)
    actual = MemoryExtractor().extract(messages)
    assert [item['content'] for item in actual] == expected
    assert messages == before
    for item in actual:
        source = item['source_detail']
        assert messages[source['message_index']]['role'] == 'user'
        assert source['quote'] in messages[source['message_index']]['content']


@pytest.mark.parametrize('name,prompt,history,expected', RETRIEVAL, ids=[c[0] for c in RETRIEVAL])
def test_retrieval_corpus(name, prompt, history, expected):
    before = deepcopy(MEMORIES)
    assert [m['id'] for m in retrieve_memories(prompt, MEMORIES, history=history)] == expected
    assert MEMORIES == before


def test_direct_analyzer_cannot_turn_assistant_into_user():
    assert analyze_memory_candidates([{'role': 'assistant', 'content': 'I prefer detailed replies.'}]) == []


def test_source_is_traceable_after_user_approval(tmp_path):
    store = MemoryStore(tmp_path)
    candidate = store.queue_candidates('我喜欢简洁的回复。', provenance={
        'conversation_id': 'fixture-conversation', 'generation_id': 'fixture-generation'})[0]
    saved = store.approve_candidate(candidate['id'])
    source = saved['metadata']['source_detail']
    assert source['conversation_id'] == 'fixture-conversation'
    assert source['generation_id'] == 'fixture-generation'
    assert source['message_index'] == 0 and source['quote'] == '我喜欢简洁的回复。'


def test_pending_only_and_repeated_across_conversations(tmp_path):
    store = MemoryStore(tmp_path)
    first = store.queue_candidates('我喜欢简洁的回复。')
    assert len(first) == 1 and first[0]['status'] == 'pending'
    assert store.list_memories() == []
    assert store.queue_candidates('我喜欢简洁的回复。') == []
    saved = store.approve_candidate(first[0]['id'])
    assert saved['metadata']['source_detail']['role'] == 'user'
    assert store.queue_candidates('我喜欢简洁的回复。') == []
    assert len(store.list_memories()) == 1


def test_approved_preference_survives_unrelated_turns_and_assistant_claims(tmp_path):
    store = MemoryStore(tmp_path)
    first = store.queue_candidates('我喜欢简洁的回复。')[0]
    memory = store.approve_candidate(first['id'])
    history = [{'role': 'user', 'content': '为什么会下雨？'},
               {'role': 'assistant', 'content': 'I prefer detailed replies.'},
               {'role': 'user', 'content': '银河有多少恒星？'}]
    assert [m['id'] for m in retrieve_memories('请按我喜欢的回复风格回答', store.list_memories(), history=history)] == [memory['id']]
    assert store.queue_candidates(history) == []


def test_people_and_projects_never_update_other_subject(tmp_path):
    store = MemoryStore(tmp_path)
    originals = [store.create('fact', text) for text in ['我的朋友林舟在北京工作', '项目 Atlas 当前阶段是开发']]
    snapshot = store.file_path.read_bytes()
    pending = store.queue_candidates('我的朋友周岚在上海工作。项目 Boreal 当前阶段是发布。')
    assert len(pending) == 2
    assert all(c['metadata']['relation']['type'] == 'new' for c in pending)
    assert store.file_path.read_bytes() == snapshot
    for candidate in pending:
        store.approve_candidate(candidate['id'])
    assert all(m['metadata']['state'] == 'active' for m in store.list_memories())
    assert {m['id'] for m in originals}.issubset({m['id'] for m in store.list_memories()})


def test_current_correction_does_not_mutate_saved(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.create('fact', '我的名字是陈明')
    before = store.file_path.read_bytes()
    history = [{'role': 'user', 'content': '我的名字是陈明。'}, {'role': 'user', 'content': '更正：我的名字是李青。'}]
    queued = store.queue_candidates(history)
    assert [c['content'] for c in queued] == ['我的名字是李青']
    assert queued[0]['metadata']['relation']['target_memory_id'] == old['id']
    assert store.file_path.read_bytes() == before
    assert retrieve_memories('我的名字是什么？', store.list_memories(), history=history) == []


def test_same_subject_different_properties_do_not_supersede(tmp_path):
    store = MemoryStore(tmp_path)
    store.create('fact', '项目 Atlas 当前阶段是开发')
    candidate = store.queue_candidates('项目 Atlas 目标是辅助科研。')[0]
    assert candidate['metadata']['relation']['type'] == 'new'


def test_unknown_named_property_cannot_supersede_project_stage(tmp_path):
    store = MemoryStore(tmp_path)
    store.create('fact', '项目 Atlas 当前阶段是开发')
    candidate = store.queue_candidates('项目 Atlas 采用离线运行。')[0]
    assert candidate['metadata']['relation']['type'] == 'new'


def test_pending_similarity_never_collapses_two_people(tmp_path):
    store = MemoryStore(tmp_path)
    queued = store.queue_candidates('我的朋友林舟在北京工作。我的朋友周岚在北京工作。')
    assert len(queued) == 2


def test_nearly_identical_stage_change_is_not_a_duplicate(tmp_path):
    store = MemoryStore(tmp_path)
    old = store.create('fact', '项目 Atlas 当前阶段是开发')
    new = store.queue_candidates('项目 Atlas 当前阶段是测试。')
    assert len(new) == 1
    assert new[0]['metadata']['relation']['type'] == 'possible_update'
    assert new[0]['metadata']['relation']['target_memory_id'] == old['id']


def test_rejected_evidence_is_not_requeued_by_history_replay(tmp_path):
    store = MemoryStore(tmp_path)
    rejected = store.queue_candidates('我喜欢简洁的回复。')[0]
    store.reject_candidate(rejected['id'])
    assert store.queue_candidates('我喜欢简洁的回复。') == []
    store.queue_candidate_records([{'type': 'fact', 'content': '另一个隔离候选'}])
    assert store.list_candidates(status='rejected')[0]['id'] == rejected['id']


def test_explicit_reversion_can_propose_update_of_current_fact(tmp_path):
    store = MemoryStore(tmp_path)
    first = store.queue_candidates('项目 Atlas 当前阶段是设计。')[0]
    store.approve_candidate(first['id'])
    second = store.queue_candidates('项目 Atlas 当前阶段是开发。')[0]
    current = store.approve_candidate(second['id'])
    reverted = store.queue_candidates('更正：项目 Atlas 当前阶段是设计。')
    assert len(reverted) == 1
    assert reverted[0]['metadata']['relation']['target_memory_id'] == current['id']


def test_history_reversion_keeps_latest_evidence_even_when_content_repeats():
    turns = [{'role': 'user', 'content': t} for t in ['我的名字是陈明。', '更正：我的名字是李青。', '更正：我的名字是陈明。']]
    candidates = MemoryExtractor().extract(turns)
    assert [c['content'] for c in candidates] == ['我的名字是陈明']
    assert candidates[0]['source_detail']['message_index'] == 2


def test_project_name_prefix_is_not_same_entity():
    assert retrieve_memories('项目 Atlasium 当前阶段是什么？', MEMORIES) == []


def test_active_contradictions_are_withheld_without_write(tmp_path):
    store = MemoryStore(tmp_path)
    store.create('fact', '项目 Atlas 当前阶段是开发')
    store.create('fact', '项目 Atlas 当前阶段是发布')
    before = store.file_path.read_bytes()
    assert retrieve_memories('项目 Atlas 当前阶段是什么？', store.list_memories()) == []
    assert store.file_path.read_bytes() == before


def test_current_style_override_suppresses_old_preference():
    assert retrieve_memories('请详细回答这个问题', MEMORIES) == []


def test_sensitive_and_oversized_facts_are_not_partially_persisted():
    assert MemoryExtractor().extract('请记住密码 abcdef') == []
    assert MemoryExtractor().extract('我的项目是' + '研究' * 200) == []


@pytest.mark.parametrize('text', ['我的名字是什么', '我的朋友林舟在哪里工作', 'My name is what', '我可能喜欢咖啡'])
def test_questions_without_punctuation_are_not_user_facts(text):
    assert MemoryExtractor().extract(text) == []


def test_bounded_format_keeps_whole_fact():
    items = [{'content': '完整事实', 'type': 'fact'}, {'content': '大' * 200, 'type': 'fact'}]
    output = format_memory_context(items, total_limit=50)
    assert output == '- [fact] 完整事实'
    assert len(output) <= 50


def test_multiturn_current_stage_and_unconfirmed_plan(tmp_path):
    store = MemoryStore(tmp_path)
    first = store.queue_candidates('项目 Atlas 当前阶段是设计。')[0]
    old = store.approve_candidate(first['id'])
    before = store.file_path.read_bytes()
    turns = [{'role': 'user', 'content': '项目 Atlas 当前阶段是设计。'},
             {'role': 'user', 'content': '更正：项目 Atlas 当前阶段是开发。'},
             {'role': 'user', 'content': '项目 Atlas 计划进入发布阶段。'}]
    new = store.queue_candidates(turns)
    assert [c['content'] for c in new] == ['项目 Atlas 当前阶段是开发']
    assert new[0]['metadata']['relation']['target_memory_id'] == old['id']
    assert store.file_path.read_bytes() == before
    saved = store.approve_candidate(new[0]['id'])
    assert saved['content'] == '项目 Atlas 当前阶段是开发'
    assert [m['id'] for m in retrieve_memories('项目 Atlas 当前阶段是什么？', store.list_memories())] == [saved['id']]


def test_fixed_quality_evaluation():
    results = evaluate()
    assert all(case['pass'] for case in results['cases']), json.dumps(results, ensure_ascii=False)
