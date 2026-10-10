import test from 'node:test';
import assert from 'node:assert/strict';
import {QQState,authorizedIds,automaticCommand,sourceLabel} from './qq_state.ts';
const m={key:'a'.repeat(64),source:'group',conversation_id:'qq:99:group:40:7',sender_id:'7',message_id:'1',text:'fixture',reply:'draft',revision:1,confirmation:'b'.repeat(64),state:'preview',supported:true};
const snapshot=(messages=[m])=>({status:'connected',error:'',configured:true,self_id:'99',private_ids:[],group_ids:['40'],trigger:'',messages});
test('authorization rejects names, duplicates and overflowing identities',()=>{assert.deepEqual(authorizedIds('7，8'),['7','8']);for(const s of ['name','7,7','9223372036854775808','0'])assert.throws(()=>authorizedIds(s));});
test('confirmation binds exact message, source and reply revision',()=>{const s=new QQState();s.accept(snapshot());s.select(m.key);s.confirm();assert.equal(s.send().confirmation,m.confirmation);assert.throws(()=>s.send());s.confirm();s.accept(snapshot([{...m,revision:2,reply:'changed'}]));assert.throws(()=>s.send());assert.equal(s.confirmation,null);});
test('selection, disconnect and backend loss invalidate confirmation',()=>{const s=new QQState();s.accept(snapshot());s.select(m.key);s.confirm();s.select('other');assert.throws(()=>s.send());s.select(m.key);s.confirm();s.accept({...snapshot(),status:'reconnecting',messages:[]});assert.equal(s.current,null);s.reset();assert.equal(s.snapshot,null);});
test('protocol IDs distinguish group and sender, no nickname recipient',()=>{assert.equal(sourceLabel(m),'群 40 · 发送者 7 · 消息 1');assert.match(sourceLabel({...m,source:'private'}),/私聊 7/);});
test('automatic authorization binds verified account and authorized groups only',()=>{
 assert.deepEqual(automaticCommand(snapshot(),'40'),{action:'enable_auto',self_id:'99',group_ids:['40']});
 for(const [s,g] of [[null,'40'],[snapshot(),''],[snapshot(),'41'],[{...snapshot(),status:'reconnecting'},'40'],[{...snapshot(),self_id:''},'40']])assert.throws(()=>automaticCommand(s,g));
});
