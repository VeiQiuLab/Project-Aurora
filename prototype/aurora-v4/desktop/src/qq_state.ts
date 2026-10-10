export type QQMessage = {key:string;source:"private"|"group";conversation_id:string;sender_id:string;message_id:string;timestamp:number;text:string;supported:boolean;state:string;reply:string;revision:number;confirmation:string;sent_message_id:string};
export type ArchiveRow={key:string;platform:string;account_id:string;group_id:string;sender_id:string;display_name:string;message_id:string;timestamp:number;message_type:string;text:string;ingested_at:number;truncated:boolean};
export type ArchiveSnapshot={policies:{account_id:string;group_id:string;enabled:number}[];error:string;rows:ArchiveRow[];account_id:string;group_id:string;export_file:string;confirmation:string};
export type QQSnapshot = {status:string;error:string;configured:boolean;self_id:string;private_ids:string[];group_ids:string[];trigger:string;messages:QQMessage[];automatic:boolean;auto_group_ids:string[];auto_status:string;queued:number;natural?:boolean;archive?:ArchiveSnapshot};
export function automaticCommand(snapshot:QQSnapshot|null, groups:string):QQCommand {
  const group_ids=authorizedIds(groups);
  if(!snapshot || snapshot.status!=="connected" || !snapshot.self_id || !group_ids.length || group_ids.some(g=>!snapshot.group_ids.includes(g)))throw Error("自动回复仅限当前已授权的测试群，请先核实账号和群号。");
  return {action:"enable_auto",self_id:snapshot.self_id,group_ids};
}
export type QQEvent = {type:"qq_snapshot";requestId:string;snapshot:QQSnapshot};
export type QQCommand = {action:string;[key:string]:unknown};
export function authorizedIds(text:string):string[] {
  const ids=text.split(/[\s,，]+/).filter(Boolean);
  if(ids.length>20 || new Set(ids).size!==ids.length || ids.some(id=>!/^[1-9][0-9]{0,18}$/.test(id) || BigInt(id)>=2n**63n)) throw Error("请填写有效且不重复的 QQ / 群号，最多 20 项。");
  return ids;
}
export function sourceLabel(m:QQMessage):string {
  return `${m.source==="group"?"群 "+m.conversation_id.split(":")[3]:"私聊 "+m.sender_id} · 发送者 ${m.sender_id} · 消息 ${m.message_id}`;
}
export class QQState {
  snapshot:QQSnapshot|null=null;
  selected="";
  confirmation:{key:string;revision:number;token:string;text:string}|null=null;
  accept(snapshot:QQSnapshot) {
    this.snapshot=snapshot;
    if(!snapshot.messages.some(m=>m.key===this.selected)) this.selected="";
    const m=this.current;
    if(this.confirmation && (!m || m.key!==this.confirmation.key || m.revision!==this.confirmation.revision || m.reply!==this.confirmation.text || m.confirmation!==this.confirmation.token || snapshot.status!=="connected")) this.confirmation=null;
  }
  select(key:string) {this.selected=key;this.confirmation=null;}
  get current() {return this.snapshot?.messages.find(m=>m.key===this.selected)??null;}
  confirm() {
    const m=this.current;
    if(!m || !m.confirmation || this.snapshot?.status!=="connected") throw Error("预览已失效，请重新检查。");
    this.confirmation={key:m.key,revision:m.revision,token:m.confirmation,text:m.reply};
  }
  send():QQCommand {
    const c=this.confirmation,m=this.current;
    if(!c || !m || c.key!==m.key || c.revision!==m.revision || c.text!==m.reply || c.token!==m.confirmation || this.snapshot?.status!=="connected") throw Error("预览已失效，请重新检查。");
    this.confirmation=null;
    return {action:"send",message_key:c.key,revision:c.revision,confirmation:c.token};
  }
  reset() {this.snapshot=null;this.selected="";this.confirmation=null;}
}
