// Real Release + real built-in model, isolated data. No QQ or private Memory.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdir,mkdtemp,writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {once} from 'node:events';

const repo=fileURLToPath(new URL('../../../../',import.meta.url));
const exe=resolve(repo,'prototype/aurora-v4/desktop/src-tauri/target/release/aurora-v4-desktop.exe');
const {chromium}=createRequire(import.meta.url)('playwright');
const exec=promisify(execFile);
const ps=async code=>(await exec('powershell.exe',['-NoProfile','-Command',code],{windowsHide:true,maxBuffer:8*1024*1024})).stdout.trim();
const inventory=async()=>JSON.parse(await ps("ConvertTo-Json -Compress -InputObject @(Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}})"));
const core=['aurora-v4-desktop.exe','llama-server.exe','aurora-local-voice-host.exe','aurora-live2d-host.exe'];
assert.equal((await inventory()).filter(p=>core.includes(p.Name)).length,0,'Exit only Aurora before this isolated smoke');
await mkdir(resolve(repo,'tests/output/connection-repair'),{recursive:true});
const directory=await mkdtemp(resolve(repo,'tests/output/connection-repair/release-'));
await mkdir(directory+'/app/config',{recursive:true});
await writeFile(directory+'/app/config/settings.json',JSON.stringify({voice:{enabled:false},live2d:{enabled:false},persona:{enabled:false},knowledge:{enabled:false},rag:{pipeline_enabled:false}}));
const report={status:'RUNNING',directory,checks:[],started:new Date().toISOString(),realModel:true,liveQQ:'NOT TESTED'};
const owned=new Map();
let child,browser,page,stderr='',run=0;
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(fn,ms=90000){const end=Date.now()+ms;while(Date.now()<end){const v=await fn();if(v)return v;await delay(100);}throw Error('Timeout: '+report.phase);}
const invoke=(command,args={})=>page.evaluate(({command,args})=>window.__TAURI_INTERNALS__.invoke(command,args),{command,args});
const snapshot=()=>invoke('backend_snapshot');
async function collect(){const all=await inventory();if(child){owned.set(`${child.pid}:${all.find(p=>p.ProcessId===child.pid)?.Created}`,all.find(p=>p.ProcessId===child.pid));}let changed=true;while(changed){changed=false;for(const p of all){if([...owned.values()].some(o=>o&&o.ProcessId===p.ParentProcessId)&&!owned.has(`${p.ProcessId}:${p.Created}`)){owned.set(`${p.ProcessId}:${p.Created}`,p);changed=true;}}}return all;}
async function check(name,fn){report.phase=name;await fn();report.checks.push({name,result:'PASS'});console.log('PASS '+name);await writeFile(directory+'/report.json',JSON.stringify(report,null,2));}
async function launch(){
  run++;
  const listener=createServer();listener.listen(0,'127.0.0.1');await once(listener,'listening');const port=listener.address().port;await new Promise(r=>listener.close(r));
  const env={...process.env,AURORA_USER_DATA_DIR:directory+'/app',AURORA_LOCAL_VOICE_DISABLE:'1',WEBVIEW2_USER_DATA_FOLDER:directory+'/webview',WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-address=127.0.0.1 --remote-debugging-port=${port}`};
  for(const k of ['AURORA_V4_BACKEND','AURORA_V4_CHAT_PROVIDER','AURORA_LOCAL_ENDPOINT','AURORA_LOCAL_TOKEN','AURORA_LOCAL_MODEL','AURORA_QQ_TOKEN','AURORA_QQ_HTTP_URL','AURORA_QQ_WS_URL'])delete env[k];
  // Exercise EXE-relative source discovery, independent of repository cwd.
  child=spawn(exe,[],{cwd:process.env.SystemRoot,env,windowsHide:true,stdio:['ignore','pipe','pipe']});
  child.stderr.on('data',b=>{stderr+=b.toString('utf8');});child.on('error',e=>{report.launchError=String(e);});
  await wait(async()=>{try{return(await fetch(`http://127.0.0.1:${port}/json/version`)).ok;}catch{return false;}});
  browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);page=browser.contexts()[0].pages()[0];
  await page.waitForFunction(()=>!!window.__TAURI_INTERNALS__);
  await wait(async()=>{const s=await snapshot();return s.state==='READY'&&s.info.diagnostics?.local_model?.model_available;});
  await collect();
}
async function close(){
  await collect();const current=child;
  await invoke('window_action',{action:'close'}).catch(()=>{});
  await wait(()=>current.exitCode!==null,20000);assert.equal(current.exitCode,0);
  await browser.close();browser=null;page=null;
  await wait(async()=>{const all=await inventory();report.remainingOwned=all.filter(p=>owned.has(`${p.ProcessId}:${p.Created}`));return report.remainingOwned.length===0;},20000);
}
async function send(text,expected){
  const before=await page.evaluate(()=>performance.getEntriesByName('aurora-terminal').at(-1)?.detail.generationId);
  await page.locator('#prompt-input').fill(text);await page.locator('#send-button').click();
  await wait(()=>page.evaluate(id=>{const entry=performance.getEntriesByName('aurora-terminal').at(-1);return entry&&entry.detail.generationId!==id;},before));
  const terminal=await page.evaluate(()=>performance.getEntriesByName('aurora-terminal').at(-1).detail);
  assert.equal(terminal.status,'completed');
  const reply=(await page.locator('#messages .message.assistant').last().textContent()).trim();
  assert.match(reply,expected);return {reply,status:terminal.status};
}
async function recoverFromCrash(){
  await invoke('crash_backend');
  await wait(async()=>(await snapshot()).state==='DISCONNECTED');
  const lost=await snapshot();assert.equal(lost.info.chat_enabled,false);assert.equal(lost.info.diagnostics,null);
  await wait(async()=>{const s=await snapshot();return s.state==='READY'&&s.info.diagnostics?.local_model?.model_available;});
  const all=await collect(),desc=[...owned.values()].filter(Boolean).filter(p=>all.some(n=>n.ProcessId===p.ProcessId&&n.Created===p.Created));
  assert.equal(desc.filter(p=>p.Name==='llama-server.exe').length,1);
  assert.equal(desc.filter(p=>p.Name==='python.exe').length,1);
}
try{
  if(process.env.AURORA_NATIVE_ACCEPTANCE==='1'){
    await check('unpackaged-windows-launch-context',async()=>{
      const code=Number(await ps(`Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class PackageProbe { [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern int GetCurrentPackageFullName(ref uint length, IntPtr name); }'; [uint32]$length=0; [PackageProbe]::GetCurrentPackageFullName([ref]$length,[IntPtr]::Zero)`));
      assert.equal(code,15700,'Native acceptance must run outside an MSIX package file-system view');
      report.windowsPackageContext='UNPACKAGED';
    });
  }
  await check('startup-authenticated-ready-and-real-vulkan-model',async()=>{await launch();report.initial=await snapshot();assert.equal(report.initial.info.mode,'production');assert.match(report.initial.info.diagnostics.local_model.configured_model,/Qwen3\.5-4B/);assert.equal(report.initial.info.diagnostics.local_model.backend,'vulkan');});
  await check('unauthenticated-sidecar-still-rejected',async()=>{const all=await inventory(),pid=all.find(p=>p.ParentProcessId===child.pid&&p.Name==='python.exe').ProcessId;const ports=JSON.parse(await ps(`ConvertTo-Json -Compress -InputObject @(Get-NetTCPConnection -OwningProcess ${pid} -State Listen | Select-Object LocalPort)`));assert.equal(ports.length,1);assert.equal((await fetch('http://127.0.0.1:'+ports[0].LocalPort)).status,401);});
  await check('factual-frontend-readiness-and-qq-page',async()=>{await page.locator('#open-settings').click();assert.match(await page.locator('#settings-model-status').textContent(),/已就绪/);await page.locator('#qq-section summary').click();await page.waitForFunction(()=>document.querySelector('#qq-status').textContent.includes('已关闭'));await page.locator('#close-settings').click();});
  await check('real-chat-inference',async()=>{await page.locator('#new-conversation').click();await page.waitForSelector('#prompt-input:not([disabled])');report.firstChat=await send('请只回答：启动验证成功。',/启动验证成功/);});
  await check('crash-active-generation-automatic-recovery-no-replay',async()=>{
    await page.locator('#prompt-input').fill('请逐条列出一百项整理工作台的具体建议，每项写两句话。');await page.locator('#send-button').click();
    await wait(()=>page.evaluate(()=>performance.getEntriesByName('aurora-first-frontend-delta').length>0));
    await recoverFromCrash();
    const terminal=await page.evaluate(()=>performance.getEntriesByName('aurora-terminal').at(-1).detail);assert.equal(terminal.status,'backend_lost');
    const count=await page.evaluate(()=>performance.getEntriesByName('aurora-terminal').length);await delay(600);assert.equal(await page.evaluate(()=>performance.getEntriesByName('aurora-terminal').length),count);
    report.recoveredChat=await send('请只回答：恢复验证成功。',/恢复验证成功/);
  });
  await check('second-automatic-recovery',recoverFromCrash);
  await check('retry-exhaustion-is-visible-and-manual-recovery-works',async()=>{
    await invoke('crash_backend');await wait(async()=>(await snapshot()).info.error_code==='BACKEND_RECOVERY_EXHAUSTED');
    assert.equal((await snapshot()).state,'DISCONNECTED');
    assert.match(await page.locator('#backend-diagnostics').textContent(),/自动恢复未成功/);
    await invoke('restart_backend');await wait(async()=>{const s=await snapshot();return s.state==='READY'&&s.info.diagnostics?.local_model?.model_available;});await collect();
  });
  await check('normal-exit-no-owned-residue',close);
  await check('full-application-restart-and-real-inference',async()=>{await launch();await page.waitForSelector('#prompt-input:not([disabled])');report.restartChat=await send('请只回答：重启验证成功。',/重启验证成功/);});
  await check('exit-during-recovery-never-resurrects-runtime',async()=>{await invoke('crash_backend');await wait(async()=>(await snapshot()).state==='DISCONNECTED');await close();await delay(3500);assert.equal((await inventory()).filter(p=>core.includes(p.Name)).length,0);});
  report.status='PASS';
}catch(e){report.status='FAILED';report.error=String(e);await page?.screenshot({path:directory+'/failure.png'}).catch(()=>{});throw e;}
finally{
  if(child?.exitCode===null&&page)await close().catch(()=>{});
  await writeFile(directory+'/stderr.txt',stderr);
  await writeFile(directory+'/report.json',JSON.stringify({...report,finished:new Date().toISOString()},null,2));
  console.log(JSON.stringify({status:report.status,directory,checks:report.checks.length,error:report.error}));
}
