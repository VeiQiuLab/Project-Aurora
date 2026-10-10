"""Isolated archive durability, privacy, boundaries and original QQ admission."""
import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from connectors.qq.group_archive import GroupArchive, ArchiveError
from connectors.qq.controlled_contract import validate_request,validate_snapshot
from test_controlled_qq import rig,event,connected,ready,ticket,auto_on,auto_idle
from production_sidecar.qq import ControlledQQ,QQError
from test_production_sidecar import ROOT,envelope
from validate_contracts import validate_message


async def enable(qq, group='40'):
    await qq.command({'action':'archive_enable','self_id':'99','group_id':group,'consent':True})
    assert not qq.archive_error


def query(qq, **filters):
    return qq.archive.query('99','40',**filters)


def test_default_off_then_nonmention_recording_does_not_reply(rig):
    async def run():
        qq,t,a,_=rig;await connected(qq);await auto_on(qq)
        qq.ingest(event(group=40,mention=False));assert not qq.archive.path.exists()
        await enable(qq)
        qq.ingest(event(group=40,message_id=2,mention=False,text='我叫小林，周六计划去图书馆。'))
        await asyncio.sleep(.02)
        assert len(query(qq))==1 and not qq.messages and not a.calls and not t.sent
        await qq.disconnect()
    asyncio.run(run())


def test_mention_and_self_reply_recorded_without_reply_loop(rig):
    async def run():
        qq,t,a,_=rig;await connected(qq);await enable(qq);await auto_on(qq)
        qq.ingest(event(group=40));await auto_idle(qq)
        assert len(query(qq))==2 and len(t.sent)==1
        own=event(sender=99,group=40,message_id=800,text='synthetic draft',post_type='message_sent')
        qq.ingest(own);qq.ingest(own);await asyncio.sleep(.02)
        assert len(query(qq))==2 and len(t.sent)==len(a.calls)==1
        assert {r['sender_id'] for r in query(qq)}=={'7','99'}
        await qq.disconnect()
    asyncio.run(run())


def test_duplicate_sender_names_and_account_group_isolation(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq);await enable(qq,'41')
        e=event(group=40,mention=False);e['sender']={'user_id':7,'nickname':'旧昵称'}
        qq.ingest(e);qq.ingest(e)
        e=event(group=40,message_id=2,mention=False);e['sender']={'user_id':7,'nickname':'新昵称'};qq.ingest(e)
        qq.ingest(event(sender=8,group=40,message_id=3,mention=False,text='另一位成员'))
        qq.ingest(event(group=41,message_id=4,mention=False,text='另一群'))
        qq.ingest(event(group=42,message_id=5,mention=False,text='未授权群'))
        qq.ingest(event(group=40,message_id=6,mention=False,self_id=100,text='另一账号'))
        rows=query(qq);assert len(rows)==3
        assert {r['display_name'] for r in rows if r['sender_id']=='7'}=={'旧昵称','新昵称'}
        epoch=qq.auto_epoch
        qq.ingest({'post_type':'notice','notice_type':'group_recall','self_id':99,'group_id':42,'message_id':1})
        assert qq.auto_epoch==epoch and not qq.archive.pending_recalls()
        assert len(qq.archive.query('99','41'))==1
        with pytest.raises(ArchiveError,match='QQ_NOT_AUTHORIZED'):qq.archive.query('100','40')
        await qq.disconnect()
    asyncio.run(run())


def test_raw_text_mentions_reply_and_media_metadata_without_download(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        e=event(group=40,mention=False,text='  原文\n不裁切  ')
        e['message'] += [{'type':'at','data':{'qq':'8'}},{'type':'reply','data':{'id':'20'}},
            {'type':'image','data':{'url':'PRIVATE_MEDIA_URL','file':'PRIVATE_MEDIA_PATH'}}]
        qq.ingest(e)
        file=Path(qq.archive.export('99','40'));rows=[json.loads(l) for l in file.read_text(encoding='utf-8').splitlines()]
        assert rows[0]['text']=='  原文\n不裁切  ' and rows[0]['message_type']=='mixed'
        assert {'type':'at','qq':'8'} in rows[0]['segments'] and {'type':'reply','id':'20'} in rows[0]['segments']
        assert {'type':'image'} in rows[0]['segments'] and 'PRIVATE_MEDIA' not in file.read_text(encoding='utf-8')
        assert not list(qq.archive.path.parent.glob('*.png'))
        await qq.disconnect()
    asyncio.run(run())


def test_persistent_old_messages_after_exit_and_separate_process_restart(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        qq.ingest(event(group=40,mention=False,time=100,text='小林 周六 图书馆 2026年10月'))
        await qq.disconnect();assert qq.archive.path.exists()
        code="from connectors.qq.group_archive import GroupArchive;import sys,json;a=GroupArchive(sys.argv[1]);r=a.query('99','40',text='图书馆');assert len(r)==1 and r[0]['timestamp']==100;print('restart retrieval PASS')"
        result=subprocess.run([sys.executable,'-c',code,str(qq.archive.path)],cwd=ROOT,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        assert 'PASS' in result.stdout
        fresh=ControlledQQ(qq.sidecar)
        r=await fresh.command({'action':'archive_query','self_id':'99','group_id':'40','sender_id':'7','query':'小林','after':0,'before':1000,'offset':0})
        assert len(r['archive']['rows'])==1 and r['archive']['policies'][0]['enabled']==1
    asyncio.run(run())


def test_chinese_literal_search_time_sender_pagination_and_context(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq);await enable(qq,'41')
        for i in range(25):qq.ingest(event(group=40,message_id=100+i,mention=False,time=100+i,text=f'小林 周六计划 图书馆 第{i}条'))
        assert len(query(qq,text='小林',after=110,before=120,sender='7'))==11
        assert len(query(qq))==20 and len(query(qq,offset=20))==5
        assert not query(qq,text='%') # SQL LIKE wildcards have no special meaning.
        key=query(qq,text='第12条')[0]['key'];around=qq.archive.around('99','40',key)
        assert len(around)==5 and around[2]['key']==key
        with pytest.raises(ArchiveError,match='QQ_NOT_FOUND'):qq.archive.around('99','41',key)
        await qq.disconnect()
    asyncio.run(run())


def test_large_history_retained_but_llm_input_small_and_current_sender_only(rig):
    async def run():
        qq,t,a,post=rig;await connected(qq);await enable(qq)
        qq.ingest(event(group=40,message_id=10,mention=False,time=100,text='我叫小林，周六计划去图书馆。'))
        for i in range(220):qq.ingest(event(group=40,message_id=100+i,mention=False,time=200+i,text='普通闲聊'+str(i)))
        qq.ingest(event(sender=8,group=40,message_id=500,mention=False,text='我叫小陈，准备去公园。'))
        await ready(qq,event(group=40,message_id=600,text='我刚才叫什么名字，周六计划去哪里？'))
        req,_,ctx=a.calls[-1]
        assert '小林' in ctx.system_context and '图书馆' in ctx.system_context
        assert '小陈' not in ctx.system_context and '公园' not in ctx.system_context
        assert len(ctx.system_context)<4000 and not req.history
        with qq.archive.database() as db:assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==223
        assert not post.completed.called and not (qq.sidecar.composition.context_root/'memory').exists()
        assert not t.sent;await qq.disconnect()
    asyncio.run(run())


def test_index_rebuild_does_not_remove_raw_records(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        for i in range(3):qq.ingest(event(group=40,message_id=i,mention=False,text=f'原文{i}'))
        before=query(qq)
        with qq.archive.database(write=True) as db:db.execute('REINDEX')
        assert query(qq)==before;await qq.disconnect()
    asyncio.run(run())


def test_storage_failure_visible_and_transaction_rollback(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        with qq.archive.database(write=True) as db:db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT,'fixture'); END")
        qq.ingest(event(group=40,mention=False))
        assert qq.snapshot()['archive']['error']=='QQ_ARCHIVE_FAILED' and not query(qq)
        with qq.archive.database() as db:assert db.execute('SELECT revision FROM groups').fetchone()[0]==0
        await qq.disconnect()
    asyncio.run(run())


def test_closed_archive_stops_new_records_but_keeps_old_records(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        qq.ingest(event(group=40,mention=False))
        await qq.command({'action':'archive_disable','self_id':'99','group_id':'40'})
        qq.ingest(event(group=40,message_id=2,mention=False))
        assert len(query(qq))==1 and qq.snapshot()['archive']['policies'][0]['enabled']==0
        await qq.disconnect()
    asyncio.run(run())


def test_permissions_confirmations_conflicts_and_duplicate_delete(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        bad={'action':'archive_enable','self_id':'99','group_id':'42','consent':True}
        assert (await qq.command(bad))['archive']['error']=='QQ_NOT_AUTHORIZED'
        qq.ingest(event(group=40,mention=False));key=query(qq)[0]['key']
        base={'self_id':'99','group_id':'40','scope':'message','target':key}
        s=await qq.command({'action':'archive_prepare_delete',**base});token=s['archive']['confirmation']
        s=await qq.command({'action':'archive_delete',**base,'target':'b'*64,'confirmation':token})
        assert s['archive']['error']=='QQ_NOT_AUTHORIZED' and len(query(qq))==1
        s=await qq.command({'action':'archive_prepare_delete',**base});token=s['archive']['confirmation']
        qq.ingest(event(group=40,message_id=2,mention=False))
        assert (await qq.command({'action':'archive_delete',**base,'confirmation':token}))['archive']['error']=='QQ_CONFLICT'
        s=await qq.command({'action':'archive_prepare_delete',**base});token=s['archive']['confirmation']
        assert not (await qq.command({'action':'archive_delete',**base,'confirmation':token}))['archive']['error']
        assert len(query(qq))==1
        assert (await qq.command({'action':'archive_delete',**base,'confirmation':token}))['archive']['error']=='QQ_NOT_AUTHORIZED'
        qq.ingest(event(group=40,mention=False));assert len(query(qq))==1 # tombstone blocks replay resurrection
        await qq.disconnect()
    asyncio.run(run())


def test_export_lossless_and_no_arbitrary_path_or_cross_group(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        text='中文原文'*1500;qq.ingest(event(group=40,mention=False,text=text))
        assert query(qq)[0]['truncated'] and len(query(qq)[0]['text'])==2048
        s=await qq.command({'action':'archive_export','self_id':'99','group_id':'40'})
        file=Path(s['archive']['export_file']);assert json.loads(file.read_text(encoding='utf-8'))['text']==text
        assert not list(file.parent.glob('*.partial'))
        s=await qq.command({'action':'archive_query','self_id':'99','group_id':'40','sender_id':'',
            'query':'中文','after':0,'before':9007199254740991,'offset':0})
        assert len(s['archive']['rows'])==1 and not s['archive']['export_file']
        with pytest.raises(QQError):await qq.command({'action':'archive_export','self_id':'99','group_id':'40','path':'outside'})
        s=await qq.command({'action':'archive_export','self_id':'99','group_id':'41'})
        assert s['archive']['error']=='QQ_NOT_AUTHORIZED'
        await qq.disconnect()
    asyncio.run(run())


def test_withdrawal_suppresses_source_and_known_reply_even_when_recording_off(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        m=await ready(qq,event(group=40,text='我叫小林'));await qq.command(await ticket(qq,m))
        assert len(query(qq))==2 and qq.histories
        await qq.command({'action':'archive_disable','self_id':'99','group_id':'40'})
        qq.ingest({'post_type':'notice','notice_type':'group_recall','self_id':99,'group_id':40,'message_id':1})
        assert not query(qq) and not qq.histories
        await enable(qq);qq.ingest(event(group=40,text='我叫小林'))
        assert not query(qq)
        exported=Path(qq.archive.export('99','40'));assert exported.read_text(encoding='utf-8')==''
        await qq.disconnect()
    asyncio.run(run())


def test_sender_and_whole_group_delete_do_not_touch_other_group_or_owner(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq);await enable(qq,'41')
        owner=qq.sidecar.composition.context_root/'owner-private-fixture';owner.write_text('private marker')
        for e in [event(group=40,mention=False),event(sender=8,group=40,message_id=2,mention=False),event(group=41,message_id=3,mention=False)]:qq.ingest(e)
        for scope,target in [('sender','7'),('group','')]:
            p={'self_id':'99','group_id':'40','scope':scope,'target':target}
            s=await qq.command({'action':'archive_prepare_delete',**p})
            s=await qq.command({'action':'archive_delete',**p,'confirmation':s['archive']['confirmation']})
            assert not s['archive']['error']
            assert len(query(qq))==(1 if scope=='sender' else 0)
        assert len(qq.archive.query('99','41'))==1 and owner.read_text()=='private marker'
        qq.ingest(event(group=40,message_id=4,mention=False));assert not query(qq)
        await qq.disconnect()
    asyncio.run(run())


def test_concurrent_duplicates_and_interrupted_transaction_integrity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    a=GroupArchive(tmp_path/'archive.sqlite');a.configure('99','40',True)
    e=event(group=40,mention=False)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:a.ingest('99',e),range(12)))
    assert len(a.query('99','40'))==1
    code="import sqlite3,sys,os;d=sqlite3.connect(sys.argv[1]);d.execute('BEGIN IMMEDIATE');d.execute('DELETE FROM messages');os._exit(0)"
    p=subprocess.run([sys.executable,'-c',code,str(a.path)]);assert p.returncode==0
    assert len(GroupArchive(a.path).query('99','40'))==1
    with a.database() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_archive_schema_and_errors_exclude_credentials_and_bad_ids(rig):
    qq,_,_,_=rig
    schema=json.loads((ROOT/'prototype/aurora-v4/contracts/ipc-v1.schema.json').read_text(encoding='utf-8'))
    for kind,p in [('qq.request',{'action':'archive_query','self_id':'99','group_id':'40','sender_id':'','after':0,'before':9007199254740991,'query':'中文','offset':0}),('qq.response',qq.snapshot())]:
        wire=envelope(kind,'qq-archive-test',**p);validate_message(wire);jsonschema.validate(wire,schema)
    for p in [{'action':'archive_enable','self_id':'99','group_id':'40','consent':False},
              {'action':'archive_prepare_delete','self_id':'99','group_id':'40','scope':'sender','target':'昵称'},
              {'action':'archive_export','self_id':'99','group_id':'40','token':'secret'}]:
        with pytest.raises(ValueError):validate_request(p)
    validate_snapshot(qq.snapshot())


def test_privacy_delete_cancels_inflight_output_and_history(rig):
    async def run():
        qq,t,a,_=rig;await connected(qq);await enable(qq)
        m=await ready(qq,event(group=40,text='我叫小林'));await qq.command(await ticket(qq,m))
        a.wait=True;qq.ingest(event(group=40,message_id=2,text='继续追问'))
        key=list(qq.messages.values())[-1]['key'];await qq.command({'action':'generate','message_key':key})
        while len(a.calls)<2:await asyncio.sleep(.001)
        p={'self_id':'99','group_id':'40','scope':'sender','target':'7'}
        s=await qq.command({'action':'archive_prepare_delete',**p})
        s=await qq.command({'action':'archive_delete',**p,'confirmation':s['archive']['confirmation']})
        assert not s['archive']['error'] and not qq.generation_task and not qq.histories
        assert not query(qq) and len(t.sent)==1;await qq.disconnect()
    asyncio.run(run())


def test_recall_during_already_admitted_send_does_not_reintroduce_facts(rig):
    async def run():
        qq,t,_,_=rig;await connected(qq);await enable(qq)
        m=await ready(qq,event(group=40,text='我叫小林'))
        entered,release=asyncio.Event(),asyncio.Event()
        async def sending(source,text):entered.set();await release.wait();return '800'
        t.send_text=sending
        task=asyncio.create_task(qq.command(await ticket(qq,m)));await entered.wait()
        qq.ingest(event(sender=99,group=40,message_id=800,text='synthetic draft',post_type='message_sent'))
        qq.ingest({'post_type':'notice','notice_type':'group_recall','self_id':99,'group_id':40,'message_id':1})
        release.set();await task
        assert not query(qq) and not qq.histories
        qq.ingest(event(sender=99,group=40,message_id=800,text='synthetic draft',post_type='message_sent'))
        assert not query(qq);await qq.disconnect()
    asyncio.run(run())


def test_failed_recall_blocks_retrieval_until_explicit_retry_succeeds(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        qq.ingest(event(group=40,mention=False,text='应撤回的内容'))
        with patch.object(qq.archive,'ingest',side_effect=ArchiveError()):
            qq.ingest({'post_type':'notice','notice_type':'group_recall','self_id':99,'group_id':40,'message_id':1})
        assert qq.archive_error=='QQ_ARCHIVE_FAILED' and qq.archive_pending_recalls
        s=await qq.command({'action':'archive_query','self_id':'99','group_id':'40','sender_id':'','query':'','after':0,'before':9007199254740991,'offset':0})
        assert not s['archive']['error'] and not s['archive']['rows'] and not qq.archive_pending_recalls
        await qq.disconnect()
    asyncio.run(run())


def test_bounded_transport_backpressure_preserves_all_delivered_events(tmp_path):
    from qq_fixture import OneBotFixture
    from connectors.qq.controlled_transport import ControlledTransport
    async def run():
        a=GroupArchive(tmp_path/'archive.sqlite');a.configure('99','40',True)
        async with OneBotFixture() as f:
            transport=ControlledTransport('',f.token,f.ws_url);await transport.open()
            for i in range(180):await f.publish(group=40,message_id=i,text=f'普通消息{i}')
            await asyncio.sleep(.03);assert transport.incoming.qsize()<=128
            received=0
            async for e in transport.events():
                a.ingest('99',e);received+=1
                if received==180:break
            assert received==180
            with a.database() as db:assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==180
            assert not f.sends;await transport.close()
    asyncio.run(run())


def test_disconnect_drains_received_archive_events_without_reply(rig):
    async def run():
        qq,t,a,_=rig;await connected(qq);await enable(qq);await auto_on(qq)
        t.incoming=asyncio.Queue(maxsize=128)
        for i in range(12):t.incoming.put_nowait(event(group=40,message_id=50+i,text='退出前已经接收到的消息'))
        await qq.disconnect()
        assert len(query(qq))==12 and not t.sent and not a.calls and t.incoming.empty()
        assert not qq.automatic and qq.status=='disabled'
    asyncio.run(run())


def test_privacy_intent_survives_process_interruption_and_recovery_before_query(rig):
    async def run():
        qq,_,_,_=rig;await connected(qq);await enable(qq)
        qq.ingest(event(group=40,mention=False,text='必须撤回的中文内容'))
        code="from connectors.qq.group_archive import GroupArchive;import sys,os;a=GroupArchive(sys.argv[1]);a.remember_recall({'post_type':'notice','notice_type':'group_recall','self_id':99,'group_id':40,'message_id':1});os._exit(0)"
        result=subprocess.run([sys.executable,'-c',code,str(qq.archive.path)],cwd=ROOT)
        assert result.returncode==0 and len(qq.archive.pending_recalls())==1
        fresh=ControlledQQ(qq.sidecar)
        with patch.object(fresh.archive,'ingest',side_effect=ArchiveError()):
            s=await fresh.command({'action':'archive_query','self_id':'99','group_id':'40','sender_id':'','query':'','after':0,'before':9007199254740991,'offset':0})
        assert s['archive']['error']=='QQ_ARCHIVE_FAILED' and not s['archive']['rows']
        s=await fresh.command({'action':'archive_query','self_id':'99','group_id':'40','sender_id':'','query':'','after':0,'before':9007199254740991,'offset':0})
        assert not s['archive']['error'] and not s['archive']['rows'] and not fresh.archive.pending_recalls()
        qq.ingest(event(group=40,mention=False,text='必须撤回的中文内容'));assert not query(qq)
        assert '必须撤回' not in qq.archive.path.with_suffix('.privacy.json').read_text(encoding='utf-8')
        await qq.disconnect()
    asyncio.run(run())
