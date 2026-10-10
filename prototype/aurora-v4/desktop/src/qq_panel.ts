import { QQState, authorizedIds, automaticCommand, sourceLabel, type QQEvent, type QQCommand } from "./qq_state";
const errors:Record<string,string>={QQ_NOT_CONFIGURED:"请先在本机配置 Aurora 独立接口和认证，再重试。",QQ_UNAVAILABLE:"QQ 接口不可用，正在尝试恢复或需要重新连接。",QQ_AUTH_FAILED:"QQ 接口认证失败，请检查本机配置。",QQ_IDENTITY_INVALID:"无法验证 QQ 账号身份。",QQ_REJECTED:"QQ 明确拒绝了发送。检查后可重新确认重试。",QQ_SEND_UNKNOWN:"发送结果未知。为避免重复发送，已禁止重试，请在 QQ 中核实。",QQ_INVALID_REQUEST:"请求无效，请检查授权号码和预览。",QQ_NOT_CONNECTED:"请先连接 QQ。",QQ_NOT_FOUND:"消息已过期，请选择当前消息。",QQ_CONFLICT:"回复版本已改变，请重新检查预览。",QQ_NOT_AUTHORIZED:"发送授权已失效。",QQ_BUSY:"已有回复正在生成，请等待或取消。",QQ_GENERATION_FAILED:"回复生成失败，可重试。",QQ_PERSISTENCE_FAILED:"无法保存发送记录，未开始发送。",QQ_ALREADY_SENT:"这条消息已经发送，已阻止重复发送。"};
const status:Record<string,string>={disabled:"外部交互已关闭",connecting:"正在连接",connected:"已连接",reconnecting:"连接中断，正在恢复",error:"连接失败"};
const messageStates:Record<string,string>={received:"待处理",queued:"自动回复排队中",generating:"正在生成（尚未发送）",preview:"草稿（尚未发送）",cancelled:"已取消",sending:"正在发送",sent:"已发送",failed:"操作失败",unknown:"发送结果未知，禁止重试"};
export class QQPanel {
  private state=new QQState();
  private connected=false;
  private visible=false;
  private pending:string|null=null;
  private submitted:QQCommand|null=null;
  private timer:ReturnType<typeof setTimeout>|null=null;
  private poll:ReturnType<typeof setInterval>|null=null;
  private section=document.getElementById("qq-section") as HTMLDetailsElement;
  private label=document.getElementById("qq-status")!;
  private body=document.getElementById("qq-messages")!;
  private view=document.getElementById("qq-preview")!;
  private confirmation=document.getElementById("qq-confirmation")!;
  private privateIds=document.getElementById("qq-private-ids") as HTMLInputElement;
  private groupIds=document.getElementById("qq-group-ids") as HTMLInputElement;
  private trigger=document.getElementById("qq-trigger") as HTMLInputElement;
  private text=document.getElementById("qq-reply") as HTMLTextAreaElement;
  private dirty=false;
  private autoGroups=document.getElementById("qq-auto-groups") as HTMLInputElement;
  private autoConsent=document.getElementById("qq-auto-consent") as HTMLInputElement;
  private naturalConsent=document.getElementById("qq-natural-consent") as HTMLInputElement;
  private archiveDelete:QQCommand|null=null;
  private archiveOffset=0;
  constructor(private invoke:(command:string,args?:Record<string,unknown>)=>Promise<unknown>) {
    this.section.querySelectorAll("button").forEach(b=>b.classList.add("ghost-button"));
    this.section.querySelectorAll("input,textarea").forEach(e=>e.classList.add("setting-input"));
    this.section.addEventListener("toggle",()=>{if(this.section.open)void this.request({action:"snapshot"});});
    document.getElementById("qq-connect")!.addEventListener("click",()=>{
      try{void this.request({action:"connect",private_ids:authorizedIds(this.privateIds.value),group_ids:authorizedIds(this.groupIds.value),trigger:this.trigger.value});}catch(e){this.label.textContent=String(e);}
    });
    document.getElementById("qq-disconnect")!.addEventListener("click",()=>{
      // Disconnect remains available during a pending operation. Late replies
      // cannot restore the old authorization or sending confirmation.
      this.finish();this.autoConsent.checked=false;this.naturalConsent.checked=false;this.state.confirmation=null;
      this.confirmation.hidden=true;this.archiveDelete=null;
      void this.request({action:"disconnect"});
    });
    document.getElementById("qq-refresh")!.addEventListener("click",()=>void this.request({action:"snapshot"}));
    document.getElementById("qq-enable-auto")!.addEventListener("click",()=>{
      try{if(!this.autoConsent.checked)throw Error("请先明确确认测试群自动发送授权。");void this.request(automaticCommand(this.state.snapshot,this.autoGroups.value));}catch(e){this.label.textContent=String(e);}
    });
    this.autoConsent.addEventListener("change",()=>this.render());
    this.naturalConsent.addEventListener("change",()=>this.render());
    document.getElementById("qq-enable-natural")!.addEventListener("click",()=>{
      const s=this.state.snapshot;
      if(!s?.automatic||!this.naturalConsent.checked){this.label.textContent="请先启用自动回复，并确认允许偶尔接话。";return;}
      void this.request({action:"enable_natural",self_id:s.self_id,group_ids:s.auto_group_ids});
    });
    document.getElementById("qq-disable-natural")!.addEventListener("click",()=>{
      this.finish();this.naturalConsent.checked=false;void this.request({action:"disable_natural"});
    });
    document.getElementById("qq-disable-auto")!.addEventListener("click",()=>{
      // Emergency disable may supersede a poll/slow manual command.
      this.finish();this.autoConsent.checked=false;this.naturalConsent.checked=false;void this.request({action:"disable_auto"});
    });
    this.text.addEventListener("input",()=>{this.dirty=true;this.state.confirmation=null;this.confirmation.hidden=true;});
    for(const action of ["generate","cancel","edit","prepare"]){document.getElementById("qq-"+action)!.addEventListener("click",()=>void this.act(action));}
    document.getElementById("qq-confirm-send")!.addEventListener("click",()=>{
      try{void this.request(this.state.send());this.confirmation.hidden=true;}catch(e){this.label.textContent=String(e);}
    });
    document.getElementById("qq-confirm-cancel")!.addEventListener("click",()=>{this.state.confirmation=null;this.confirmation.hidden=true;});
    this.setupArchive();
    this.render();
  }
  open(){this.visible=true;if(this.connected&&this.section.open)void this.request({action:"snapshot"});this.startPoll();}
  close(){this.visible=false;this.state.confirmation=null;this.confirmation.hidden=true;this.archiveDelete=null;document.getElementById("qq-archive-confirmation")!.hidden=true;if(this.poll)clearInterval(this.poll);this.poll=null;}
  backend(available:boolean){this.connected=available;if(!available){this.finish();this.state.reset();this.dirty=false;this.archiveDelete=null;this.render();}else if(this.visible&&this.section.open)void this.request({action:"snapshot"});this.startPoll();}
  private startPoll(){if(!this.poll&&this.visible&&this.connected)this.poll=setInterval(()=>{if(this.section.open&&!this.pending)void this.request({action:"snapshot"});},1000);}
  private finish(){if(this.timer)clearTimeout(this.timer);this.timer=null;this.pending=null;this.submitted=null;}
  private async request(command:QQCommand) {
    if(!this.connected)return;
    if(this.pending){
      if(this.submitted?.action!=="snapshot"||command.action==="snapshot")return;
      // A user operation supersedes a background read. Its late response is
      // ignored by request ID; a poll must never swallow a click or keystroke.
      this.finish();
    }
    const id="qq-"+crypto.randomUUID();this.pending=id;this.submitted=command;
    this.render();
    this.timer=setTimeout(()=>{this.finish();this.state.reset();this.render();this.label.textContent="请求超时。发送结果需重新读取核实；不会自动重发。";},12000);
    try{await this.invoke("qq_command",{requestId:id,command});}catch{if(this.pending!==id)return;this.finish();this.render();this.label.textContent="QQ 功能未连接，请重试。";}
  }
  accept(event:QQEvent){
    if(event.requestId!==this.pending)return;
    const command=this.submitted;
    if(command?.action==="edit" && !event.snapshot.error && event.snapshot.messages.some(m=>m.key===command.message_key&&m.reply===command.text))this.dirty=false;
    this.finish();this.state.accept(event.snapshot);this.render();
    if(command?.action==="archive_prepare_delete" && !event.snapshot.archive?.error && event.snapshot.archive?.confirmation && this.visible){
      this.archiveDelete={...command,action:"archive_delete",confirmation:event.snapshot.archive.confirmation};
      document.getElementById("qq-archive-delete-description")!.textContent=`确认删除群 ${command.group_id} 的 ${command.scope==="group"?"全部档案并关闭记录":command.scope==="sender"?"发言者 "+command.target+" 的档案":"指定消息"}及其已知关联回复？此操作不能撤销。`;
      document.getElementById("qq-archive-confirmation")!.hidden=false;
    }
  }
  private async act(action:string){
    const m=this.state.current;if(!m||(this.pending&&this.submitted?.action!=="snapshot"))return;
    if(action==="prepare"&&this.dirty){this.label.textContent="请先保存预览，再确认发送。";return;}
    const args:QQCommand={action,message_key:m.key};
    if(action==="edit"||action==="prepare")args.revision=m.revision;
    if(action==="edit")args.text=this.text.value;
    if(action==="cancel"||action==="generate")this.dirty=false;
    await this.request(args);
    // IPC returns asynchronously. Confirmation is opened only from a response
    // carrying a fresh server-issued token for this exact message and revision.
    if(action==="prepare")this.awaitConfirmation(m.key,m.revision);
  }
  private awaitConfirmation(key:string,revision:number){
    const id=this.pending;
    const tick=()=>{
      if(this.pending===id&&id){setTimeout(tick,30);return;}
      const m=this.state.current;
      if(m?.key!==key||m.revision!==revision||!m.confirmation||this.dirty||!this.visible||this.state.snapshot?.error)return;
      this.state.confirm();this.render();document.getElementById("qq-confirm-target")!.textContent=sourceLabel(m);
      document.getElementById("qq-confirm-text")!.textContent=m.reply;this.confirmation.hidden=false;
    };tick();
  }
  private archiveInput(id:string){return document.getElementById("qq-archive-"+id) as HTMLInputElement;}
  private archiveSource(){
    const value=(document.getElementById("qq-archive-source") as HTMLSelectElement).value;
    const [self_id,group_id]=value.split("/");
    if(!this.state.snapshot?.archive?.policies.some(p=>p.account_id===self_id&&p.group_id===group_id))throw Error("请选择已授权档案。");
    return {self_id,group_id};
  }
  private setupArchive(){
    const run=(action:string,extra:Record<string,unknown>={})=>{
      try{this.archiveDelete=null;void this.request({action,...this.archiveSource(),...extra});}
      catch(e){document.getElementById("qq-archive-status")!.textContent=String(e);}
    };
    const search=(next=false)=>{
      this.archiveOffset=next?this.archiveOffset+20:0;
      const date=(id:string,fallback:number)=>this.archiveInput(id).value?Math.floor(new Date(this.archiveInput(id).value).getTime()/1000):fallback;
      run("archive_query",{sender_id:this.archiveInput("sender").value.trim(),query:this.archiveInput("query").value,
        after:date("after",0),before:date("before",9007199254740991),offset:this.archiveOffset});
    };
    document.getElementById("qq-archive-enable")!.addEventListener("click",()=>{
      try{
        const s=this.state.snapshot,group_id=this.archiveInput("group").value.trim();
        if(!s?.self_id||s.status!=="connected"||!s.group_ids.includes(group_id)||!this.archiveInput("consent").checked)throw Error("请核实此群授权，并确认群成员记录提示。");
        void this.request({action:"archive_enable",self_id:s.self_id,group_id,consent:true});
      }catch(e){document.getElementById("qq-archive-status")!.textContent=String(e);}
    });
    this.archiveInput("consent").addEventListener("change",()=>this.renderArchive());
    this.archiveInput("group").addEventListener("input",()=>{this.archiveInput("consent").checked=false;this.renderArchive();});
    document.getElementById("qq-archive-source")!.addEventListener("change",()=>{this.archiveDelete=null;this.renderArchive();});
    document.getElementById("qq-archive-disable")!.addEventListener("click",()=>run("archive_disable"));
    document.getElementById("qq-archive-search")!.addEventListener("click",()=>search());
    document.getElementById("qq-archive-next")!.addEventListener("click",()=>search(true));
    document.getElementById("qq-archive-export")!.addEventListener("click",()=>run("archive_export"));
    document.getElementById("qq-archive-delete-sender")!.addEventListener("click",()=>run("archive_prepare_delete",{scope:"sender",target:this.archiveInput("sender").value.trim()}));
    document.getElementById("qq-archive-delete-group")!.addEventListener("click",()=>run("archive_prepare_delete",{scope:"group",target:""}));
    document.getElementById("qq-archive-confirm-delete")!.addEventListener("click",()=>{const c=this.archiveDelete;this.archiveDelete=null;if(c)void this.request(c);});
    document.getElementById("qq-archive-cancel-delete")!.addEventListener("click",()=>{this.archiveDelete=null;this.renderArchive();});
  }
  private renderArchive(){
    const a=this.state.snapshot?.archive,s=this.state.snapshot,busy=!!this.pending&&this.submitted?.action!=="snapshot";
    const select=document.getElementById("qq-archive-source") as HTMLSelectElement,value=select.value;
    const options=(a?.policies??[]).map(p=>({value:p.account_id+"/"+p.group_id,label:`群 ${p.group_id} · QQ ${p.account_id} · ${p.enabled?"记录已开启":"新记录已关闭"}`}));
    if(options.length!==select.options.length||options.some((o,i)=>o.value!==select.options[i].value||o.label!==select.options[i].textContent)){
      select.replaceChildren();
      for(const o of options){const option=document.createElement("option");option.value=o.value;option.textContent=o.label;select.append(option);}
      if([...select.options].some(o=>o.value===value))select.value=value;
    }
    const matchesSource=select.value===`${a?.account_id}/${a?.group_id}`;
    document.getElementById("qq-archive-status")!.textContent=!this.connected?"档案服务未连接，可恢复后重试":this.submitted?.action.startsWith("archive_")?"正在处理档案…":a?.error?`${a.error==="QQ_ARCHIVE_FAILED"?"档案存储 / 查询失败；不能确认已记录。请检查磁盘后重试":a.error==="QQ_CONFLICT"?"档案已发生变化，请重新检查并确认删除":a.error==="QQ_NOT_AUTHORIZED"?"此档案操作未获授权":"档案记录不可用"}`:a?.export_file?`导出已完成：${a.export_file}`:a?.group_id?`群 ${a.group_id} · 本页 ${a.rows.length} 条（每页最多 20 条）`:"尚未开启群聊记录，默认不记录任何群。";
    const rows=document.getElementById("qq-archive-rows")!;rows.replaceChildren();
    for(const r of matchesSource?a?.rows??[]:[]){
      const box=document.createElement("div");box.className="memory-record";
      const text=document.createElement("p");text.className="qq-text";text.textContent=`${r.display_name||"未提供昵称"}（QQ ${r.sender_id}） · ${new Date(r.timestamp*1000).toLocaleString()} · ${r.message_type}\n${r.text}${r.truncated?"\n[界面节选，完整原文保存在档案 / 导出中]":""}`;box.append(text);
      for(const action of ["archive_around","archive_prepare_delete"]){const button=document.createElement("button");button.type="button";button.className="ghost-button";button.textContent=action==="archive_around"?"查看前后文":"删除此条…";button.disabled=busy||!this.connected;
        button.addEventListener("click",()=>void this.request({action,self_id:r.account_id,group_id:r.group_id,...(action==="archive_around"?{key:r.key}:{scope:"message",target:r.key})}));box.append(button);}
      rows.append(box);
    }
    if(!matchesSource||!a?.rows.length)rows.textContent=a?.error?"读取失败，请重试。":matchesSource&&a?.group_id?"没有符合条件的记录。":"请选择档案并查询。";
    for(const id of ["disable","search","next","export","delete-sender","delete-group"])(document.getElementById("qq-archive-"+id) as HTMLButtonElement).disabled=!this.connected||busy||!select.options.length;
    (document.getElementById("qq-archive-next") as HTMLButtonElement).disabled=!this.connected||busy||(a?.rows.length??0)<20;
    (document.getElementById("qq-archive-enable") as HTMLButtonElement).disabled=!this.connected||busy||s?.status!=="connected"||!this.archiveInput("consent").checked;
    document.getElementById("qq-archive-confirmation")!.hidden=!this.archiveDelete;
    (document.getElementById("qq-archive-confirm-delete") as HTMLButtonElement).disabled=busy||!this.connected;
  }
  private render(){
    const s=this.state.snapshot,m=this.state.current,busy=!!this.pending&&this.submitted?.action!=="snapshot";
    this.renderArchive();
    const modes:Record<string,string>={ready:"持续可用",busy:"排队 / 回复中",paused:"模型不可用，安全暂停；仅新消息可重试",reconnecting:"断线暂停，受控恢复中",off:"已关闭"};
    document.getElementById("qq-auto-status")!.textContent=s?.automatic?`Automatic · ${modes[s.auto_status]} · 测试群 ${s.auto_group_ids.join("、")} · 排队 ${s.queued}`:"Manual · 自动回复已关闭";
    document.getElementById("qq-natural-status")!.textContent=s?.natural?`偶尔接话已开启 · ${modes[s.auto_status]} · 群 ${s.auto_group_ids.join("、")}`:"偶尔接话已关闭 · 只回应 @ / 触发词";
    (document.getElementById("qq-enable-natural") as HTMLButtonElement).disabled=busy||s?.status!=="connected"||!s?.automatic||!!s?.natural||!this.naturalConsent.checked;
    (document.getElementById("qq-disable-natural") as HTMLButtonElement).disabled=!this.connected;
    this.naturalConsent.disabled=busy||!!s?.natural;
    this.label.textContent=!this.connected?"QQ 功能未连接":this.submitted?.action==="disconnect"?"正在断开 QQ，等待确认后可修改授权。":s?(errors[s.error]||`${status[s.status]}${s.self_id?" · QQ "+s.self_id:""}${!s.configured?" · 本机独立接口未配置":""}`):"正在读取…";
    document.getElementById("qq-authorization-note")!.textContent=!this.connected?"本地服务恢复后可连接 QQ。":s?.status==="connected"||s?.status==="connecting"||s?.status==="reconnecting"||busy?"连接期间授权输入已锁定。要增加或移除群号，先点“断开 QQ / 修改群号”；断开会关闭自动回复，不删除群聊档案。":"现在可修改授权号码，多个号码用逗号分隔。填写后点“连接 QQ”；自动回复需单独启用。";
    this.body.replaceChildren();
    for(const item of s?.messages??[]){
      const b=document.createElement("button");b.type="button";b.className="ghost-button memory-record";b.disabled=busy;b.textContent=sourceLabel(item)+" · "+(item.supported?messageStates[item.state]:"Unsupported：仅支持普通文本");b.addEventListener("click",()=>{this.state.select(item.key);this.dirty=false;this.render();});this.body.append(b);
    }
    if(!s?.messages.length)this.body.textContent="暂无待回复消息。@ / 触发词会进入回复列表；开启偶尔接话后也可能补充一两句。群聊档案独立记录。";
    this.view.hidden=!m;
    this.confirmation.hidden=!this.state.confirmation;
    if(m){document.getElementById("qq-source")!.textContent=sourceLabel(m);document.getElementById("qq-original")!.textContent=m.text;document.getElementById("qq-message-state")!.textContent=messageStates[m.state];if(!this.dirty)this.text.value=m.reply;}
    const active=s?.status==="connected",done=m&&["sent","sending","unknown"].includes(m.state);
    (document.getElementById("qq-enable-auto") as HTMLButtonElement).disabled=busy||!active||!!s?.automatic||!this.autoConsent.checked;
    (document.getElementById("qq-disable-auto") as HTMLButtonElement).disabled=!this.connected;
    this.autoGroups.disabled=busy||!!s?.automatic;this.autoConsent.disabled=busy||!!s?.automatic;
    (document.getElementById("qq-connect") as HTMLButtonElement).disabled=busy||!this.connected||!s?.configured||s.status==="connecting"||active;
    (document.getElementById("qq-disconnect") as HTMLButtonElement).disabled=!this.connected||this.submitted?.action==="disconnect"||(!s||s.status==="disabled")&&this.submitted?.action!=="connect";
    (document.getElementById("qq-refresh") as HTMLButtonElement).disabled=busy||!this.connected;
    (document.getElementById("qq-confirm-send") as HTMLButtonElement).disabled=busy||!this.state.confirmation;
    for(const input of [this.privateIds,this.groupIds,this.trigger]) input.disabled=busy||active||s?.status==="connecting"||s?.status==="reconnecting";
    const autoOwned=m&&(m.state==="queued"||(s?.automatic&&m.source==="group"&&s.auto_group_ids.includes(m.conversation_id.split(":")[3])&&["generating","preview"].includes(m.state)));
    for(const action of ["generate","cancel","edit","prepare"]){(document.getElementById("qq-"+action) as HTMLButtonElement).disabled=busy||!active||!m?.supported||!!done||!!autoOwned||(action!=="cancel"&&m.state==="generating")||((action==="prepare"||action==="edit")&&!m.revision);}
    this.text.disabled=busy||!active||!m?.supported||!!done||!!autoOwned||m.state==="generating";
  }
}
