// Opt-in real Release/WebView2 + Vulkan model smoke. Synthetic data only.
// Run after building, with Playwright in NODE_PATH. No LM Studio/Ollama allowed.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { spawn, execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdir, mkdtemp, writeFile, readFile, stat, readdir } from "node:fs/promises";
import { createServer } from "node:net";
import { once } from "node:events";
const { chromium } = createRequire(import.meta.url)("playwright");
const exec = promisify(execFile);
const repo = fileURLToPath(new URL("../../../..", import.meta.url));
const exe = fileURLToPath(new URL("../src-tauri/target/release/aurora-v4-desktop.exe", import.meta.url));
const output = `${repo}/tests/output/v46a-local`;
const killDesktop = process.argv.includes("--kill-desktop");
await mkdir(output, { recursive: true });
const sandbox = await mkdtemp(`${output}/run-`);
const ps = async code => (await exec("powershell.exe", ["-NoProfile", "-Command", code], { windowsHide: true })).stdout.trim();
const existing = JSON.parse(await ps("@(@(Get-Process -ErrorAction SilentlyContinue) | Where-Object { $_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop') } | Select-Object ProcessName,Id) | ConvertTo-Json -Compress -AsArray" ).catch(async () => {
  // Windows PowerShell 5 lacks -AsArray.
  return await ps("ConvertTo-Json -Compress -InputObject @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in @('LM Studio','ollama','llama-server','aurora-v4-desktop') } | Select-Object ProcessName,Id)");
}));
assert.equal(existing.length, 0, "Existing user process: close it before this isolated smoke.");
const cfg = JSON.parse(await readFile(`${process.env.USERPROFILE}/.lmstudio/settings.json`, "utf8"));
async function models(root, depth=0) {
  if (depth>4) return [];
  const found=[];
  for (const e of await readdir(root,{withFileTypes:true})) {
    if (e.isDirectory()) found.push(...await models(`${root}/${e.name}`,depth+1));
    else if (e.isFile() && e.name.endsWith(".gguf") && !e.name.startsWith("mmproj")) found.push(`${root}/${e.name}`);
  }
  return found;
}
const candidates=process.env.AURORA_LOCAL_MODEL_PATH ? [process.env.AURORA_LOCAL_MODEL_PATH] : await models(cfg.downloadsFolder);
assert.equal(candidates.length,1); const model=candidates[0]; const modelBefore=await stat(model);
await mkdir(`${sandbox}/app/config`, { recursive:true });
await mkdir(`${sandbox}/app/persona`, { recursive:true });
await mkdir(`${sandbox}/app/memory`, { recursive:true });
await mkdir(`${sandbox}/app/knowledge/files`, { recursive:true });
await writeFile(`${sandbox}/app/knowledge/files/fixture.md`,"黑白界面的文档说明");
await writeFile(`${sandbox}/app/knowledge/metadata.json`,JSON.stringify([{id:"knowledge-1",file_name:"design.md",file_type:"md",stored_name:"fixture.md",file_size:36,added_time:"2026-01-01 00:00:00",updated_time:"2026-01-01 00:00:00",enabled:true,content:"黑白界面的文档说明"}]));
await writeFile(`${sandbox}/app/config/settings.json`,JSON.stringify({ollama:{host:"http://127.0.0.1:1"},persona:{enabled:true},knowledge:{enabled:true},rag:{pipeline_enabled:true}}));
await writeFile(`${sandbox}/app/persona/persona.json`,JSON.stringify({name:"Aurora Test",description:"合成测试角色",style:"简洁",rules:["回答应简短。"],last_loaded_time:"never",last_updated_time:"never"}));
await writeFile(`${sandbox}/app/memory/memories.json`,JSON.stringify([{id:"memory-1",type:"preference",content:"用户偏好简洁的黑白界面",created_time:"2026-01-01T00:00:00Z",updated_time:"2026-01-01T00:00:00Z",importance:"high",enabled:true,metadata:{state:"active"}}]));
const portServer=createServer(); portServer.listen(0,"127.0.0.1"); await once(portServer,"listening");
const port=portServer.address().port; await new Promise(r=>portServer.close(r));
const env={...process.env,AURORA_USER_DATA_DIR:`${sandbox}/app`,WEBVIEW2_USER_DATA_FOLDER:`${sandbox}/webview`,WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${port}`};
// Exercise normal EXE defaults, not an opt-in production/provider override.
delete env.AURORA_V4_BACKEND;delete env.AURORA_V4_CHAT_PROVIDER;
const launched=performance.now();
const child=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:["ignore","pipe","pipe"]});
let stderr=""; child.stderr.on("data",d=>{stderr+=d.toString();});
let browser,page;
const report={native:true,modelFile:model.split(/[\\/]/).at(-1),modelBytes:modelBefore.size,externalServicesClosed:true,killDesktop,turns:[]};
const children=async()=>JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process -Filter "ParentProcessId = ${child.pid}" | Select-Object Name,ProcessId)`));
const snapshot=()=>page.evaluate(()=>window.__TAURI_INTERNALS__.invoke("backend_snapshot"));
const marks=()=>page.evaluate(()=>performance.getEntriesByName("aurora-terminal").map(x=>x.detail));
const runtime=async()=>{const owned=await children(); return owned.find(p=>p.Name.toLowerCase()==="llama-server.exe");};
async function waitSnapshot(predicate, timeoutMs=150000) {
  const until=Date.now()+timeoutMs;
  while(Date.now()<until) {const value=await snapshot();if(predicate(value))return value;await new Promise(r=>setTimeout(r,100));}
  throw new Error("Runtime snapshot deadline exceeded");
}
const waitReady=()=>waitSnapshot(s=>s.state==="READY"&&s.info.diagnostics?.local_model?.state==="READY");
async function begin(prompt) {
  const previous=(await marks()).at(-1)?.generationId ?? null;
  const sent=await page.evaluate(()=>performance.getEntriesByName("aurora-send").at(-1)?.startTime??-1);
  await page.locator("#prompt-input").fill(prompt); await page.locator("#send-button").click();
  try {await page.waitForFunction(old=>(performance.getEntriesByName("aurora-send").at(-1)?.startTime??-1)>old,sent,{timeout:5000});}
  catch(e){report.sendDebug=await page.evaluate(()=>({inputLength:document.querySelector('#prompt-input').value.length,disabled:document.querySelector('#send-button').disabled,hidden:document.querySelector('#send-button').hidden,active:document.querySelectorAll('.conversation.active').length,sendMarks:performance.getEntriesByName('aurora-send').map(x=>x.startTime)}));report.sendSnapshot=await snapshot();throw e;}
  return previous;
}
async function terminal(previous) {
  await page.waitForFunction(old=>{const m=performance.getEntriesByName("aurora-terminal").at(-1);return m&&m.detail.generationId!==old;},previous,{timeout:120000});
  return (await marks()).at(-1);
}
async function turn(prompt) { const n=await begin(prompt); const result=await terminal(n); assert.equal(result.status,"completed"); report.turns.push(result); return result; }
try {
  while(performance.now()-launched<30000) {
    try {browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);break;}catch{await new Promise(r=>setTimeout(r,200));}
  }
  assert.ok(browser); page=browser.contexts()[0].pages()[0]; await page.waitForSelector("#open-settings");
  report.initialState=(await snapshot()).state;
  await page.locator("#open-settings").click(); await page.locator("#close-settings").click();
  await waitReady(); report.launchToReadyMs=performance.now()-launched;
  const ready=await snapshot(); const publicData=JSON.stringify(ready);
  assert.ok(!publicData.includes("127.0.0.1:")&&!publicData.includes(process.env.USERPROFILE));
  report.localModel=ready.info.diagnostics.local_model;
  let owned=await children(); let active=await runtime(); assert.ok(active);
  const initialPid=active.ProcessId; const pythonPid=owned.find(p=>p.Name.toLowerCase()==="python.exe").ProcessId;
  report.runtimePid=initialPid;
  const second=spawn(exe,[],{cwd:repo,env,windowsHide:true,stdio:"ignore"});
  assert.equal((await once(second,"exit"))[0],0); assert.equal((await runtime()).ProcessId,initialPid);
  await page.locator("#new-conversation").click();
  await page.waitForFunction(()=>document.querySelectorAll(".conversation").length>0);
  const cold=await turn("黑白界面");
  assert.ok(cold.delta_count>1); assert.ok(cold.send_to_first_frontend_delta_ms<cold.send_to_terminal_ms);
  assert.ok(cold.production.memory_item_count>0); assert.equal(cold.production.persona_enabled,true); assert.equal(cold.production.rag_enabled,true);
  // Allow the existing post-turn idle gate/title to finish, without changing its policy.
  await page.waitForFunction(()=>{const t=document.querySelector(".conversation-title")?.textContent;return t&&t!=="New Conversation"&&t!=="新对话";},null,{timeout:30000});
  const deadline=Date.now()+35000;
  let files=[]; let saved;
  while(Date.now()<deadline){
    files=(await readdir(`${sandbox}/app/conversations`)).filter(n=>n.endsWith(".json"));
    if(files.length){saved=JSON.parse(await readFile(`${sandbox}/app/conversations/${files[0]}`,"utf8"));if(saved.title&&!['New Conversation','新对话'].includes(saved.title)&&saved.metadata?.conversation_intelligence)break;}
    await new Promise(r=>setTimeout(r,200));
  }
  assert.ok(saved?.metadata?.conversation_intelligence); report.postTurn=true;
  assert.equal(saved.metadata.conversation_intelligence.title_source,"llm");report.localTitle=true;
  for(const prompt of ["请记住本次会话的测试词是蓝鲸，只回复已记住。", "刚才的测试词是什么？只回复测试词。", "用一句简短中文问候。"]) await turn(prompt);
  const assistant=await page.locator(".message.assistant").allTextContents(); assert.ok(assistant.some(t=>t.includes("蓝鲸"))); report.history=true;
  assert.ok(report.turns[1].production.history_message_count>=2);
  assert.equal((await runtime()).ProcessId,initialPid); report.pidReused=true;
  const count=await begin("请详细写出一百条不同的日常生活建议，每条至少三句话，不要省略。");
  await page.waitForFunction(()=>performance.getEntriesByName("aurora-first-frontend-delta").length>0,null,{timeout:120000});
  await page.locator("#stop-button").click(); report.cancel=await terminal(count); assert.equal(report.cancel.status,"cancelled");
  assert.equal(report.cancel.production.worker_exited,true); assert.equal(report.cancel.production.active_response,false);
  await turn("只回复：恢复成功。");
  report.persistenceFiles=files.length;
  report.processMemory=JSON.parse(await ps(`Get-Process -Id ${initialPid} | Select-Object WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress`));
  report.gpuMemory=JSON.parse(await ps(`$g=@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | Where-Object { $_.Name -like 'pid_${initialPid}_*' }); [pscustomobject]@{available=($g.Count -gt 0);dedicatedBytes=($g | Measure-Object DedicatedUsage -Sum).Sum;sharedBytes=($g | Measure-Object SharedUsage -Sum).Sum} | ConvertTo-Json -Compress`));
  assert.equal((await runtime()).ProcessId,initialPid);
  const crashTurn=await begin("这一轮请详细回答，不要只回复确认：请列出一百个不同的科学主题，每个主题详细说明三句话。");
  await page.waitForFunction(()=>performance.getEntriesByName("aurora-first-frontend-delta").length>0,null,{timeout:120000});
  // PID ownership was rechecked immediately before this request. Do not launch a
  // slow CIM/PowerShell query after first content: a short answer could finish
  // during that query and stop being a generation-in-flight crash test.
  assert.equal((await marks()).length,0,"Crash injection must precede completion");
  process.kill(initialPid);
  await waitSnapshot(s=>s.state==="DEGRADED"&&!s.info.diagnostics?.local_model?.model_available,10000);
  report.crashTerminal=await terminal(crashTurn);assert.ok(["failed","backend_lost"].includes(report.crashTerminal.status));
  assert.ok((await children()).some(p=>p.ProcessId===pythonPid)); report.runtimeCrashPythonSurvived=true;
  await page.evaluate(()=>window.__TAURI_INTERNALS__.invoke("restart_backend")); await waitReady();
  active=await runtime(); assert.notEqual(active.ProcessId,initialPid); report.restartedPid=active.ProcessId;
  await page.reload(); await page.waitForSelector(".conversation"); await page.locator(".conversation").first().click();
  await page.waitForFunction(()=>document.querySelectorAll('.message.assistant').length>=4);
  report.persistedHistoryReloaded=true;
  await turn("只回复：重启恢复成功。");
  // A second foreground turn arrives before the first turn's title idle gate.
  const oldConversationCount=await page.locator('.conversation').count();
  await page.locator('#new-conversation').click();
  await page.waitForFunction(n=>document.querySelectorAll('.conversation').length>n,oldConversationCount);
  const postTurnLogStart=stderr.length;
  await turn("只回复你好。");await turn("请用一句话说明天空为什么是蓝色。");
  report.foregroundPriorityDeferred=stderr.slice(postTurnLogStart).includes('deferred_foreground');
  assert.equal(report.foregroundPriorityDeferred,true);
  // Close the application while a real generation is active.
  await begin("请详细讲述太阳系各个行星的特点，每个行星用十段文字说明。");
  await page.waitForFunction(()=>performance.getEntriesByName("aurora-first-frontend-delta").length>0,null,{timeout:120000});
  if (killDesktop) {child.kill(); await once(child,"exit"); report.forcedExitDuringGeneration=true;}
  report.status="passed";
} catch(error) {report.status="failed";report.error=String(error);throw error;}
finally {
  const alive=()=>child.exitCode===null&&child.signalCode===null;
  if(!report.forcedExitDuringGeneration&&page&&!page.isClosed()) await page.evaluate(()=>window.__TAURI_INTERNALS__.invoke("window_action",{action:"close"})).catch(()=>{});
  if(alive()) await Promise.race([once(child,"exit"),new Promise(r=>setTimeout(r,10000))]);
  if(alive()){child.kill();report.cleanup="forced";}else report.cleanup=report.forcedExitDuringGeneration?"forced-exit-test":"normal";
  await browser?.close().catch(()=>{});
  const after=await stat(model);report.modelUnchanged=after.size===modelBefore.size&&after.mtimeMs===modelBefore.mtimeMs;
  for(let n=0;n<100;n++) {report.remainingChildren=await children();if(!report.remainingChildren.length)break;await new Promise(r=>setTimeout(r,100));}
  const escapedModel=model.replaceAll("'","''");
  report.modelHandleReleased=(await ps(`$f=[IO.File]::Open('${escapedModel}',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None); $f.Dispose(); 'released'`))==="released";
  // Diagnostics only. Never save response text or raw prompt-bearing runtime output.
  report.runtimeEvents=stderr.split(/\r?\n/).filter(s=>s.startsWith("[aurora-local]"));
  if(!report.modelUnchanged||!report.modelHandleReleased||report.remainingChildren.length||report.cleanup==="forced")report.status="failed";
  await writeFile(`${output}/${killDesktop?'kill-report':'report'}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({status:report.status,error:report.error,launchToReadyMs:report.launchToReadyMs,turns:report.turns.length,cancelMs:report.cancel?.ui_cancel_to_terminal_ms,modelUnchanged:report.modelUnchanged,modelHandleReleased:report.modelHandleReleased,remainingChildren:report.remainingChildren}));
}
assert.equal(report.status,"passed");assert.equal(report.modelUnchanged,true);assert.equal(report.cleanup,killDesktop?"forced-exit-test":"normal");assert.equal(report.remainingChildren.length,0);
assert.equal(report.modelHandleReleased,true);
