"""Long-history evidence regressions. Synthetic groups only; no live QQ sends."""
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
from unittest.mock import patch

import pytest

from test_controlled_qq import rig, event, connected, ready
from test_group_archive import enable
from test_production_sidecar import ROOT
from connectors.qq.group_archive import GroupArchive, ArchiveError


def discussion(archive):
    archive.configure('99', '40', True)
    rows = [
        (7, '备份方案先考虑网盘。'),
        (8, '网盘会上传私人文件，离线时也无法恢复。'),
        (7, '所以备份方案最后决定用离线硬盘，没有采用网盘。'),
    ]
    for i, (sender, text) in enumerate(rows):
        archive.ingest('99', event(sender=sender, group=40, message_id=10+i, time=100+i, text=text, mention=False))
    for i in range(180):
        archive.ingest('99', event(group=40, message_id=100+i, time=300+i, text=f'后来普通闲聊 {i}', mention=False))


def poke_discussion(archive):
    rows = [
        (7, '戳一戳功能有人建议加入，目前只是需求。'),
        (8, '这个版本还没有处理戳一戳事件，不能自动回应。'),
        (7, '因此戳一戳功能尚未实现，因为事件分发接口还没有接入。'),
    ]
    for i, (sender, text) in enumerate(rows):
        archive.ingest('99', event(sender=sender, group=40, message_id=30+i, time=150+i, text=text, mention=False))


def test_topic_requested_in_manual_failure_preserves_proposal_vs_implementation(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); discussion(archive); poke_discussion(archive)
    rows = archive.history_context('99', '40', '7', '戳一戳功能到底有没有实现？')
    text = json.dumps(rows, ensure_ascii=False)
    assert '只是需求' in text and '尚未实现' in text and '事件分发接口还没有接入' in text
    assert len(rows) <= 8 and sum(len(r['text']) for r in rows) <= 2000


def test_old_discussion_conclusion_and_other_speaker_reason_before_recency(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); discussion(archive)
    before = archive.query('99', '40', after=0, before=110)
    rows = archive.history_context('99', '40', '7', '之前备份方案最后怎么决定的？为什么？')
    text = json.dumps(rows, ensure_ascii=False)
    assert '决定用离线硬盘' in text and '上传私人文件' in text and '离线时也无法恢复' in text
    assert any(r['sender_id'] == '8' and '上传' in r['text'] for r in rows)
    assert [r['timestamp'] for r in rows] == sorted(r['timestamp'] for r in rows)
    assert archive.query('99', '40', after=0, before=110) == before
    assert len(rows) <= 8 and sum(len(r['text']) for r in rows) <= 2000


def test_named_missing_topic_no_unrelated_recent_fallback_and_group_account_boundary(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); discussion(archive)
    archive.configure('99', '41', True); archive.configure('100', '40', True)
    archive.ingest('99', event(group=41, text='备份方案决定使用云端：OTHER_GROUP_SECRET'))
    archive.ingest('100', event(group=40, self_id=100, text='备份方案决定使用远程：OTHER_ACCOUNT_SECRET'))
    rows = archive.history_context('99', '40', '7', '备份方案的结论是什么？')
    assert 'OTHER_' not in json.dumps(rows)
    assert archive.history_context('99', '40', '7', '火星旅行最后决定去哪？') == []
    with pytest.raises(ArchiveError, match='QQ_NOT_AUTHORIZED'):
        archive.history_context('99', '42', '7', '备份方案')


def test_personal_recall_never_borrows_other_speaker_identity(rig):
    async def run():
        qq, transport, adapter, _ = rig; await connected(qq); await enable(qq)
        qq.ingest(event(group=40, message_id=10, time=100, mention=False, text='我叫小林，周六计划去图书馆。'))
        qq.ingest(event(sender=8, group=40, message_id=11, time=101, mention=False, text='我叫小陈，周六计划去公园。'))
        await ready(qq, event(group=40, message_id=12, text='我刚才叫什么名字，周六计划去哪里？'))
        request, _, context = adapter.calls[-1]
        assert '小林' in context.system_context and '图书馆' in context.system_context
        assert '小陈' not in context.system_context and '公园' not in context.system_context
        assert not request.history and not transport.sent
        await qq.disconnect()
    asyncio.run(run())


def test_explicit_reply_relation_finds_reason_outside_neighbor_window(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); archive.configure('99', '40', True)
    archive.ingest('99', event(group=40, message_id=10, time=100, text='戳一戳功能暂不支持。'))
    for i in range(8): archive.ingest('99', event(group=40, message_id=20+i, time=101+i, text='插入闲聊'))
    reply = event(sender=8, group=40, message_id=30, time=120, text='因为桥接尚未处理对应事件。')
    reply['message'].insert(0, {'type': 'reply', 'data': {'id': '10'}})
    archive.ingest('99', reply)
    rows = archive.history_context('99', '40', '7', '戳一戳功能有没有实现，为什么？')
    assert '桥接尚未处理对应事件' in json.dumps(rows, ensure_ascii=False)


def test_search_full_original_and_excerpt_near_match_not_preview_head(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); archive.configure('99', '40', True)
    raw = '前面无关文字。' * 600 + '戳一戳功能尚未实现，因为事件接口未接入。' + '结尾无关文字。' * 600
    archive.ingest('99', event(group=40, message_id=10, text=raw))
    rows = archive.history_context('99', '40', '7', '戳一戳功能有没有实现？')
    assert len(rows) == 1 and rows[0]['excerpted']
    assert '事件接口未接入' in rows[0]['text'] and len(rows[0]['text']) <= 500
    with archive.database() as db: assert db.execute('SELECT text FROM messages').fetchone()[0] == raw


def test_separate_process_restart_same_evidence_and_original_integrity(tmp_path):
    archive = GroupArchive(tmp_path / 'archive.sqlite'); discussion(archive)
    expected = archive.history_context('99', '40', '7', '备份方案为什么这样决定？')
    code = "from connectors.qq.group_archive import GroupArchive;import sys,json;print(json.dumps(GroupArchive(sys.argv[1]).history_context('99','40','7','备份方案为什么这样决定？')))"
    result = subprocess.run([sys.executable, '-c', code, str(archive.path)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    with sqlite3.connect(archive.path) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 183


def test_archive_evidence_reaches_actual_llama_request_without_owner_context(rig):
    from test_local_provider import llama_fixture
    from production_sidecar.direct_chat import DirectChatAdapter
    async def run(provider, calls):
        qq, transport, _, post = rig; await connected(qq); await enable(qq)
        discussion(qq.archive)
        owner = qq.sidecar.composition.context_root / 'memory'; owner.mkdir()
        marker = owner / 'memories.json'; marker.write_text('[{"content":"PRIVATE_OWNER_MARKER"}]')
        before = marker.read_bytes()
        composition = qq.sidecar.composition
        composition.root, composition.local_provider = ROOT, provider
        qq.sidecar.chat.adapter = DirectChatAdapter(composition)
        question = '之前备份方案最后怎么决定的，为什么？'
        m = await ready(qq, event(group=40, message_id=900, text=question))
        wire = calls[-1][2]['messages']
        assert m['state'] == 'preview' and wire[-1]['content'] == question
        assert '决定用离线硬盘' in wire[0]['content'] and '上传私人文件' in wire[0]['content']
        assert 'PRIVATE_OWNER_MARKER' not in json.dumps(wire) and not post.completed.called
        assert marker.read_bytes() == before and not transport.sent
        assert not qq.histories and not qq.receipts.path.exists()
        await qq.disconnect()
    with llama_fixture() as (provider, calls): asyncio.run(run(provider, calls))


def test_storage_failure_and_pending_recall_do_not_generate_from_stale_evidence(rig):
    async def run():
        qq, transport, adapter, _ = rig; await connected(qq); await enable(qq); discussion(qq.archive)
        with patch.object(qq.archive, 'history_context', side_effect=ArchiveError()):
            m = await ready(qq, event(group=40, message_id=900, text='备份方案为什么这样决定？'))
        assert m['state'] == 'failed' and qq.archive_error == 'QQ_ARCHIVE_FAILED' and not adapter.calls
        qq.archive.remember_recall({'post_type': 'notice', 'notice_type': 'group_recall', 'self_id': 99, 'group_id': 40, 'message_id': 12})
        m = await ready(qq, event(group=40, message_id=901, text='备份方案为什么这样决定？'))
        assert m['state'] == 'failed' and not adapter.calls and not transport.sent
        await qq.disconnect()
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('AURORA_QQ_HISTORY_LIVE_SIDECAR_PID'),
                    reason='Opt-in: reuse an existing supervised 4B; never launch a second model')
def test_history_quality_with_actual_supervised_4b(rig):
    """Engineering answer-quality gate, NOT live QQ/manual acceptance.

    All archives/events/identities are fixtures. Private model handoff stays in
    memory; no token, actual group content or user-profile write is performed.
    """
    import psutil
    from production_sidecar.local_provider import BuiltInLlamaProvider
    from production_sidecar.direct_chat import DirectChatAdapter
    from production_sidecar.qq import ControlledQQ
    from test_controlled_qq import Transport
    environment = psutil.Process(int(os.environ['AURORA_QQ_HISTORY_LIVE_SIDECAR_PID'])).environ()
    assert environment.get('AURORA_V4_CHAT_PROVIDER') == 'builtin_local'
    provider = BuiltInLlamaProvider(environment['AURORA_LOCAL_ENDPOINT'], environment['AURORA_LOCAL_TOKEN'],
                                    environment['AURORA_LOCAL_MODEL'])
    assert provider.probe()['model_available']
    async def run():
        qq, transport, _, post = rig; await connected(qq); await enable(qq); discussion(qq.archive); poke_discussion(qq.archive)
        comp = qq.sidecar.composition
        comp.root, comp.local_provider = ROOT, provider
        qq.sidecar.chat.adapter = DirectChatAdapter(comp)
        questions = [
            ('之前备份方案最后决定用什么？', ('离线硬盘',)),
            ('为什么备份方案没有采用网盘？', ('私人文件', '离线')),
            ('大家最终决定火星旅行在哪天出发？', ()),
            ('戳一戳功能到底有没有实现？', ('未',)),
            ('为什么当时没有做戳一戳功能？', ('事件', '接口', '接入')),
            ('之前大家决定火星旅行由谁组织？', ()),
            ('当时火星旅行最终确定几月几日出发？', ()),
        ]
        for i, (text, required) in enumerate(questions):
            m = await ready(qq, event(group=40, message_id=900+i, text=text))
            assert m['state'] == 'preview'
            answer = m['reply']
            if required: assert all(term in answer for term in required), answer
            else:
                assert (any(term in answer for term in ('无法确认', '没有', '不知道', '未提供', '未找到'))
                        or re.search(r'未.{0,8}(?:讨论|提及|记录|确定)', answer)), answer
                assert not any(term in answer for term in ('周六', '周日', '2026', '已决定')), answer
                assert not re.search(r'\d+\s*[年月日号]', answer), answer
            assert not transport.sent and not qq.histories
        await qq.disconnect()
        fresh_transport = Transport(); fresh = ControlledQQ(qq.sidecar, lambda: fresh_transport)
        await connected(fresh)
        m = await ready(fresh, event(group=40, message_id=950, text='之前备份方案最后决定用什么，原因是什么？'))
        assert m['state'] == 'preview'
        assert all(term in m['reply'] for term in ('离线硬盘', '私人文件', '离线')), m['reply']
        assert not fresh_transport.sent and not post.completed.called
        assert not (comp.context_root / 'memory').exists()
        await fresh.disconnect()
    asyncio.run(run())
