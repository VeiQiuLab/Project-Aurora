// Opt-in real Release/WebView/Python/Rust smoke with isolated existing-schema fixtures.
// --native pauses for real Windows input; CDP alone is not human acceptance.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile} from "node:fs/promises";
import {createHash,randomUUID} from "node:crypto";
import {createServer} from "node:net";
import {once} from "node:events";
import {resolve,relative,isAbsolute} from "node:path";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile),repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
assert.ok(process.env.AURORA_LIVE2D_CONFIG,"Existing audited private Live2D configuration required");
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
const inventory=async()=>JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
const critical=p=>["aurora-v4-desktop.exe","python.exe","llama-server.exe","aurora-local-voice-host.exe","aurora-live2d-host.exe"].includes(p.Name);
const initial=await inventory();
assert.equal(initial.filter(p=>critical(p)&&p.Name!=="python.exe").length,0,"Close existing Aurora; do not terminate user runtimes");
const root=resolve(repo,"tests/output/v48c");await mkdir(root,{recursive:true});const resumeArg=process.argv.includes("--resume")?process.argv[process.argv.indexOf("--resume")+1]:null;const resume=resumeArg?resolve(resumeArg):null;const resumeRelative=resume?relative(root,resume):null;assert.ok(!resume||(resumeRelative&&!resumeRelative.startsWith("..")&&!isAbsolute(resumeRelative)),"Resume must be an isolated stage fixture");const directory=resume||await mkdtemp(root+"/runtime-");
await mkdir(directory+"/app/config",{recursive:true});await mkdir(directory+"/app/memory",{recursive:true});
if(!resume)await writeFile(directory+"/app/config/settings.json",JSON.stringify({ollama:{host:"http://127.0.0.1:1"},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false},voice:{enabled:true,tts:{provider:"local_sherpa_melo"}},live2d:{enabled:true,visible:true,x:64,y:64}}));
const memoryFile=directory+"/app/memory/memories.json",candidateFile=directory+"/app/memory/memory_candidates.json";
const saved=JSON.stringify([{id:"v48c-fixture-memory",type:"preference",content:"V4-8C 测试记忆：喜欢在安静的地方阅读。",enabled:false,importance:"normal",created_time:"2026-10-08T00:00:00Z",metadata:{state:"active",confidence:.9,source_detail:{source:"isolated-smoke"}}}]);
const pending=JSON.stringify([{id:"v48c-approve-fixture",type:"preference",content:"V4-8C 批准候选：喜欢安静阅读。",status:"pending",score:.9,importance:"normal",source:"isolated-smoke",metadata:{}},{id:"v48c-reject-fixture",type:"instruction",content:"V4-8C 拒绝候选：这条不进入记忆库。",status:"pending",score:.9,importance:"normal",source:"isolated-smoke",metadata:{}}]);
if(!resume){await writeFile(memoryFile,saved);await writeFile(candidateFile,pending);}
const hash=async path=>createHash("sha256").update(await readFile(path)).digest("hex");
const beforeHashes={saved:await hash(memoryFile),pending:await hash(candidateFile)};
const listener=createServer();listener.listen(0,"127.0.0.1");await once(listener,"listening");const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:directory+"/app",WEBVIEW2_USER_DATA_FOLDER:directory+"/webview",WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
const report={status:"RUNNING",mode:"real-release-isolated-fixture",checks:[],owned:[],remainingOwned:[],native:"NOT YET OBSERVED",beforeHashes};
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=90000){const end=Date.now()+ms;while(Date.now()<end){const value=await fn();if(value)return value;await delay(100);}throw Error("memory runtime timeout");}
let child,browser,page,stderr="";const owned=new Map();
async function collect(){const rows=await inventory(),ids=new Set([child.pid]);let changed=true;while(changed){changed=false;for(const p of rows)if(ids.has(p.ParentProcessId)&&!ids.has(p.ProcessId)){ids.add(p.ProcessId);changed=true;}}const result=rows.filter(p=>ids.has(p.ProcessId));for(const p of result)owned.set(`${p.ProcessId}:${p.Created}`,p);report.owned=[...owned.values()];return result;}
const persist=()=>writeFile(directory+"/report.json",JSON.stringify(report,null,2));
const invoke=(cmd,args)=>page.evaluate(({cmd,args})=>window.__TAURI_INTERNALS__.invoke(cmd,args),{cmd,args});

async function startDesktop() {
  child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});child.stderr.on("data",d=>stderr+=d);
  report.pid=child.pid;report.port=port;await collect();await persist();
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(20000);
  await page.waitForSelector("#window-hide");
  report.backend=await wait(async()=>{const s=await invoke("backend_snapshot");return s.state==="READY"&&s.info.diagnostics?.local_model?.state==="READY"?s:null;});
  await wait(async()=>(await invoke("local_voice_snapshot")).state==="READY");
  await wait(async()=>(await invoke("live2d_snapshot")).status==="ready");
}
async function stopDesktop() {
  await collect();await invoke("window_action",{action:"close"}).catch(()=>{});
  await wait(()=>child.exitCode!==null,20000);await browser?.close().catch(()=>{});
  await wait(async()=>{report.remainingOwned=(await inventory()).filter(p=>owned.has(`${p.ProcessId}:${p.Created}`));return report.remainingOwned.length===0;},15000);
}
const savedPanel=()=>page.locator("#memory-saved");
async function openMemory(){await page.locator("#open-settings").click();if(!(await page.locator("#memory-section").evaluate(e=>e.open)))await page.locator("#memory-section summary").click();await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');}
async function savedDetail(){await savedPanel().locator(".memory-record").first().click();await page.waitForSelector("#memory-saved .memory-body");}
try {
  await startDesktop();await openMemory();
  if(!resume){await page.waitForSelector('#memory-pending[data-state="ready"] .memory-record');assert.equal(await savedPanel().locator(".memory-record").count(),1);assert.equal(await page.locator("#memory-pending .memory-record").count(),2);}
  await collect();await writeFile(root+"/current-governance-runtime.json",JSON.stringify({pid:child.pid,port,directory},null,2));
  console.log("NATIVE_READY "+JSON.stringify({pid:child.pid,port,directory}));
  await wait(async()=>{try{report.native=JSON.parse(await readFile(directory+"/native-smoke.json","utf8"));return report.native.result==="PASS";}catch{return false;}},1800000);
  let actual=JSON.parse(await readFile(memoryFile,"utf8")),candidates=JSON.parse(await readFile(candidateFile,"utf8"));
  assert.equal(actual.length,1);assert.ok(["V4-8C 隔离编辑验收通过。","V4-8C 失败重试后正确保存。"].includes(actual[0].content));
  assert.ok(!actual.some(item=>item.id==="v48c-fixture-memory"));
  assert.equal(candidates.find(item=>item.id==="v48c-approve-fixture").status,"approved");assert.equal(candidates.find(item=>item.id==="v48c-reject-fixture").status,"rejected");
  report.checks.push("native approve/reject/edit/delete cancel/delete confirm persisted exact isolated targets");
  // Concurrent editor changes only this fixture through the same production Store.
  await savedPanel().getByRole("button",{name:"返回列表",exact:true}).click().catch(()=>{});
  await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');await savedDetail();
  await savedPanel().getByRole("button",{name:"编辑 / Edit",exact:true}).click();await savedPanel().getByRole("textbox",{name:"编辑记忆内容",exact:true}).fill("V4-8C 保留的冲突草稿");
  const pythonCode="import sys; from modules.memory import MemoryStore; from modules.memory_coordination import fingerprint; s=MemoryStore(sys.argv[1],read_only=True); r=s.inspect_records('saved')[0][0]; s.govern(dict(operation_id=sys.argv[2],action='edit',id=r['id'],expected_version=fingerprint(r),content='V4-8C 并发编辑后的最新内容',confirmed=False))";
  await exec(repo+"/.venv/Scripts/python.exe",["-c",pythonCode,memoryFile,"fixture-concurrent-"+randomUUID()],{cwd:repo,windowsHide:true});
  await savedPanel().getByRole("button",{name:"保存 / Save",exact:true}).click();
  await wait(async()=>(await savedPanel().textContent()).includes("记录已被修改"));
  assert.equal(await savedPanel().getByRole("textbox",{name:"编辑记忆内容",exact:true}).inputValue(),"V4-8C 保留的冲突草稿");
  actual=JSON.parse(await readFile(memoryFile,"utf8"));assert.equal(actual[0].content,"V4-8C 并发编辑后的最新内容");
  await savedPanel().getByRole("button",{name:"取消编辑",exact:true}).click();
  await savedPanel().getByRole("button",{name:"返回列表",exact:true}).click();await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');await savedDetail();
  await savedPanel().getByRole("button",{name:"编辑 / Edit",exact:true}).click();await savedPanel().getByRole("textbox",{name:"编辑记忆内容",exact:true}).fill("V4-8C 失败重试后正确保存。");
  const receiptFile=directory+"/app/memory/memory_operations.json",receipt=await readFile(receiptFile),receiptBackup=await readFile(receiptFile+".bak");
  const beforeFailure=await readFile(memoryFile);
  await writeFile(receiptFile,"BROKEN ISOLATED RECEIPT FIXTURE");await writeFile(receiptFile+".bak","BROKEN ISOLATED RECEIPT BACKUP");
  await savedPanel().getByRole("button",{name:"保存 / Save",exact:true}).click();
  await page.waitForSelector('#memory-saved button:has-text("重试操作")');
  assert.deepEqual(await readFile(memoryFile),beforeFailure);assert.equal(await savedPanel().getByRole("textbox",{name:"编辑记忆内容",exact:true}).inputValue(),"V4-8C 失败重试后正确保存。");
  await writeFile(receiptFile,receipt);await writeFile(receiptFile+".bak",receiptBackup);await savedPanel().getByRole("button",{name:"重试操作",exact:true}).click();await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');
  actual=JSON.parse(await readFile(memoryFile,"utf8"));assert.equal(actual[0].content,"V4-8C 失败重试后正确保存。");
  report.checks.push("real Rust/Python conflict preserves draft and latest content; isolated write failure preserves data and idempotent retry succeeds");
  await page.locator("#close-settings").click();await page.waitForSelector("#new-conversation:not([disabled])");await page.locator("#new-conversation").click();await page.waitForSelector("#prompt-input:not([disabled])");
  await page.locator("#prompt-input").fill("V4-8C 不发送的草稿");const cid=await page.locator(".conversation.active").getAttribute("data-conversation-id");
  const ids=(await collect()).filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort();
  await invoke("window_action",{action:"hide"});await invoke("window_action",{action:"show"});
  assert.equal(await page.locator("#prompt-input").inputValue(),"V4-8C 不发送的草稿");assert.equal(await page.locator(".conversation.active").getAttribute("data-conversation-id"),cid);
  assert.deepEqual((await collect()).filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort(),ids);
  report.checks.push("V4-8A hide/show preserves draft/conversation and runtime identities");
  report.persisted=actual;await stopDesktop();await startDesktop();await openMemory();await savedDetail();
  assert.equal(await savedPanel().locator(".memory-body").textContent(),"V4-8C 失败重试后正确保存。");
  await page.waitForSelector('#memory-pending[data-state="empty"]');report.checks.push("normal restart preserves governance and no pending decisions reappear");
  await page.locator("#close-settings").click();if(await page.locator("#prompt-input").isDisabled()){if(await page.locator(".conversation").count())await page.locator(".conversation").first().click();else await page.locator("#new-conversation").click();}await page.waitForSelector("#prompt-input:not([disabled])");await page.locator("#prompt-input").fill("请只回复：记忆管理验收完成，可以继续对话。");await page.locator("#send-button").click();
  await page.waitForSelector("#stop-button:not([disabled])");await page.waitForSelector("#stop-button[disabled]",{state:"attached",timeout:90000});
  report.voice=await wait(async()=>{const s=await invoke("backend_snapshot");return s.voice?.state==="speaking"?s.voice:null;});assert.equal(report.voice.provider,"local_sherpa_melo");
  await openMemory();await savedDetail();assert.match(await savedPanel().locator(".memory-body").textContent(),/失败重试后正确保存/);
  await wait(async()=>(await invoke("backend_snapshot")).voice?.state==="idle");
  report.avatar=await wait(async()=>{const a=await invoke("live2d_snapshot");return a.state==="idle"&&a.mouth===0?a:null;});assert.equal(report.avatar.status,"ready");assert.equal(report.avatar.visible,true);
  report.checks.push("local chat + Local Melo/Rust Audio completes with Memory open; Avatar remains ready/visible and returns mouth=0");
  await page.screenshot({path:directory+"/governance-final.png"});await stopDesktop();report.checks.push("normal exit twice: zero owned process remnants");report.status="PASS";
} catch(error){report.status="FAILED";report.error=String(error);throw error;}
finally {
  if(child?.exitCode===null&&page)await invoke("window_action",{action:"close"}).catch(()=>{});
  await browser?.close().catch(()=>{});await writeFile(directory+"/stderr.txt",stderr);await persist();
  console.log(JSON.stringify({status:report.status,checks:report.checks,native:report.native,directory}));
}
