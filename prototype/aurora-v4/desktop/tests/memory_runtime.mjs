// Opt-in real Release/WebView/Python/Rust smoke with isolated existing-schema fixtures.
// --native pauses for real Windows input; CDP alone is not human acceptance.
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {spawn,execFile} from "node:child_process";
import {promisify} from "node:util";
import {mkdir,mkdtemp,writeFile,readFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import {createServer} from "node:net";
import {once} from "node:events";
const {chromium}=createRequire(import.meta.url)("playwright");
const exec=promisify(execFile),repo=fileURLToPath(new URL("../../../..",import.meta.url));
const exe=fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe",import.meta.url));
assert.ok(process.env.AURORA_LIVE2D_CONFIG,"Existing audited private Live2D configuration required");
const ps=async code=>(await exec("powershell.exe",["-NoProfile","-Command",code],{windowsHide:true})).stdout.trim();
const inventory=async()=>JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
const critical=p=>["aurora-v4-desktop.exe","python.exe","llama-server.exe","aurora-local-voice-host.exe","aurora-live2d-host.exe"].includes(p.Name);
const initial=await inventory();
assert.equal(initial.filter(p=>critical(p)&&p.Name!=="python.exe").length,0,"Close existing Aurora; do not terminate user runtimes");
const root=repo+"/tests/output/v48b";await mkdir(root,{recursive:true});const directory=await mkdtemp(root+"/runtime-");
await mkdir(directory+"/app/config",{recursive:true});await mkdir(directory+"/app/memory",{recursive:true});
await writeFile(directory+"/app/config/settings.json",JSON.stringify({ollama:{host:"http://127.0.0.1:1"},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false},voice:{enabled:true,tts:{provider:"local_sherpa_melo"}},live2d:{enabled:true,visible:true,x:64,y:64}}));
const memoryFile=directory+"/app/memory/memories.json",candidateFile=directory+"/app/memory/memory_candidates.json";
const saved=JSON.stringify([{id:"v48b-fixture-memory",type:"preference",content:"V4-8B 测试记忆：喜欢在安静的地方阅读。",enabled:false,importance:"normal",created_time:"2026-10-08T00:00:00Z",metadata:{state:"active",confidence:.9,source_detail:{source:"isolated-smoke"}}}]);
const pending=JSON.stringify([{id:"v48b-fixture-candidate",type:"preference",content:"V4-8B 测试候选：尚未批准的阅读偏好。",status:"pending",importance:"normal",source:"isolated-smoke",created_time:"2026-10-08T00:00:00Z",risk:{level:"low"},explanation:"测试候选，不是正式记忆"},{id:"rejected-fixture",content:"Rejected item must not appear",status:"rejected"}]);
await writeFile(memoryFile,saved);await writeFile(candidateFile,pending);
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
try {
  child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});child.stderr.on("data",d=>stderr+=d);
  report.pid=child.pid; report.port=port; await collect(); await persist();
  browser=await wait(async()=>{try{return await chromium.connectOverCDP(`http://127.0.0.1:${port}`);}catch{return null;}},30000);
  page=browser.contexts()[0].pages()[0];page.setDefaultTimeout(20000);
  await page.waitForSelector("#window-hide");
  report.backend=await wait(async()=>{const s=await invoke("backend_snapshot");return s.state==="READY"&&s.info.diagnostics?.local_model?.state==="READY"?s:null;});
  await wait(async()=>(await invoke("local_voice_snapshot")).state==="READY");
  await wait(async()=>(await invoke("live2d_snapshot")).status==="ready");
  const before=await collect(),identities=before.filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort();
  await page.waitForSelector("#new-conversation:not([disabled])");await page.locator("#new-conversation").click();
  await page.waitForSelector("#prompt-input:not([disabled])");await page.locator("#prompt-input").fill("V4-8B 不发送的草稿");
  const conversation=await page.locator(".conversation.active").getAttribute("data-conversation-id");
  await page.locator("#open-settings").click();await page.locator("#memory-section summary").click();
  await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');await page.waitForSelector('#memory-pending[data-state="ready"] .memory-record');
  assert.equal(await page.locator("#memory-saved .memory-record").count(),1);assert.equal(await page.locator("#memory-pending .memory-record").count(),1);
  await page.locator("#memory-saved .memory-record").click();await page.waitForSelector("#memory-saved .memory-body");
  assert.match(await page.locator("#memory-saved .memory-body").textContent(),/喜欢在安静/);assert.match(await page.locator("#memory-saved .memory-metadata").textContent(),/0.9/);
  await page.locator("#memory-pending .memory-record").click();await page.waitForSelector("#memory-pending .memory-body");
  assert.match(await page.locator("#memory-pending .memory-metadata").textContent(),/测试候选，不是正式记忆/);
  report.checks.push("actual Release -> Rust -> authenticated Python -> existing MemoryStore: both lists/details and real metadata");
  assert.deepEqual({saved:await hash(memoryFile),pending:await hash(candidateFile)},beforeHashes);
  await writeFile(memoryFile,"[]");await page.locator("#memory-saved").getByRole("button",{name:"返回列表",exact:true}).click();await page.waitForSelector('#memory-saved[data-state="empty"]');
  await writeFile(memoryFile,"BROKEN ISOLATED FIXTURE");await page.locator("#memory-saved").getByRole("button",{name:"刷新列表",exact:true}).click();await page.waitForSelector('#memory-saved[data-state="error"]');
  assert.match(await page.locator("#memory-saved").textContent(),/读取失败/);
  await writeFile(memoryFile,saved);await page.locator("#memory-saved").getByRole("button",{name:"重试",exact:true}).click();await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');
  await page.locator("#memory-pending").getByRole("button",{name:"返回列表",exact:true}).click();await page.waitForSelector('#memory-pending[data-state="ready"] .memory-record');
  report.checks.push("isolated fixture empty/error/retry paths render correctly, production user data untouched");
  assert.deepEqual({saved:await hash(memoryFile),pending:await hash(candidateFile)},beforeHashes);
  await page.locator("#close-settings").click();assert.equal(await page.locator("#prompt-input").inputValue(),"V4-8B 不发送的草稿");
  await invoke("window_action",{action:"hide"});await invoke("window_action",{action:"show"});
  assert.equal(await page.locator("#prompt-input").inputValue(),"V4-8B 不发送的草稿");
  assert.equal(await page.locator(".conversation.active").getAttribute("data-conversation-id"),conversation);
  assert.deepEqual((await collect()).filter(critical).map(p=>`${p.ProcessId}:${p.Created}`).sort(),identities);
  report.checks.push("settings close and V4-8A hide/show retain conversation/draft and same runtime identities");
  await page.locator("#prompt-input").fill("请只回复：记忆查看检查完成，可以继续对话。");await page.locator("#send-button").click();
  await page.waitForSelector("#stop-button:not([disabled])");
  await page.locator("#open-settings").click();
  await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');
  await page.waitForSelector("#stop-button[disabled]",{state:"attached",timeout:90000});
  await wait(async()=>["preparing","speaking"].includes((await invoke("backend_snapshot")).voice?.state));
  const voice=await wait(async()=>{const s=await invoke("backend_snapshot");return s.voice?.state==="speaking"?s.voice:null;});
  report.voiceStarted={state:voice.state,provider:voice.provider};assert.equal(voice.provider,"local_sherpa_melo");
  await page.locator("#memory-saved .memory-record").click();await page.waitForSelector("#memory-saved .memory-body");
  await wait(async()=>(await invoke("backend_snapshot")).voice?.state==="idle");
  report.avatar=await wait(async()=>{const avatar=await invoke("live2d_snapshot");return avatar.state==="idle"&&avatar.mouth===0?avatar:null;});assert.equal(report.avatar.status,"ready");assert.equal(report.avatar.visible,true);
  await page.locator("#close-settings").click();assert.equal(await page.locator("#prompt-input").isDisabled(),false);
  await page.locator("#prompt-input").fill("V4-8B 下一次未发送草稿");assert.equal(await page.locator("#send-button").isDisabled(),false);
  const replies=await page.locator(".message.assistant .bubble").allTextContents();
  assert.ok(replies.some(text=>text.includes("记忆查看检查完成")));
  report.checks.push("one local LLM turn + Local Melo/Rust Audio playback completes while memory view opens; Avatar remains ready/visible and returns mouth=0");
  await page.locator("#open-settings").click();await page.waitForSelector('#memory-saved[data-state="ready"] .memory-record');
  report.afterInspectionHashes={saved:await hash(memoryFile),pending:await hash(candidateFile)};assert.deepEqual(report.afterInspectionHashes,beforeHashes);
  report.checks.push("memory/candidate bytes unchanged after inspection and ordinary smoke turn, no auto-approval/deletion");
  await page.screenshot({path:directory+"/memory-ready.png"});await persist();
  await writeFile(root+"/current-runtime.json",JSON.stringify({pid:child.pid,port,directory},null,2));
  if(process.argv.includes("--native")) {
    console.log("NATIVE_READY "+JSON.stringify({pid:child.pid,port,directory}));
    await wait(async()=>{try{report.native=JSON.parse(await readFile(directory+"/native-smoke.json","utf8"));return report.native.result==="PASS";}catch{return false;}},1800000);
  }
  await collect();await invoke("window_action",{action:"close"}).catch(()=>{});await wait(()=>child.exitCode!==null,20000);
  await wait(async()=>{report.remainingOwned=(await inventory()).filter(p=>owned.has(`${p.ProcessId}:${p.Created}`));return report.remainingOwned.length===0;},15000);
  report.checks.push("normal Desktop exit: zero owned process remnants");report.status="PASS";
} catch(error) {report.status="FAILED";report.error=String(error);throw error;}
finally {
  if(child?.exitCode===null&&page)await invoke("window_action",{action:"close"}).catch(()=>{});
  await browser?.close().catch(()=>{});await writeFile(directory+"/stderr.txt",stderr);await persist();
  console.log(JSON.stringify({status:report.status,checks:report.checks,native:report.native,directory}));
}
