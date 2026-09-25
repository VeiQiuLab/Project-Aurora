//! Optional presentation child. Never owns AI, Voice, audio or persisted settings.
use crate::{
    protocol::{BackendState, FrontendEvent},
    sidecar::JobGuard,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    path::PathBuf,
    process::Stdio,
    sync::{Arc, Mutex},
    time::Instant,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt, BufReader},
    process::{Child, ChildStdin, Command},
    sync::watch,
    time::{Duration, timeout},
};

#[derive(Clone, Debug, Default, Serialize)]
pub struct Snapshot {
    pub status: String,
    pub state: String,
    pub visible: bool,
    pub fps: f64,
    pub error_code: String,
}
#[derive(Clone, Debug, PartialEq, Serialize)]
struct Input {
    revision: u64,
    state: String,
    visible: bool,
    x: Option<i32>,
    y: Option<i32>,
    shutdown: bool,
}
#[derive(Clone, Debug, PartialEq)]
struct Desired {
    enabled: bool,
    input: Input,
}
struct Projection {
    desired: Desired,
    generation: Option<String>,
    voice_revision: u64,
    settings_revision: Option<u64>,
    cancelled: bool,
    chat_active: bool,
    voice_state: String,
}
impl Default for Projection {
    fn default() -> Self {
        Self {
            desired: Desired {
                enabled: false,
                input: Input {
                    revision: 0,
                    state: "idle".into(),
                    visible: true,
                    x: None,
                    y: None,
                    shutdown: false,
                },
            },
            generation: None,
            voice_revision: 0,
            settings_revision: None,
            cancelled: false,
            chat_active: false,
            voice_state: "idle".into(),
        }
    }
}
impl Projection {
    fn accept(&mut self, event: &FrontendEvent) -> bool {
        let old = self.desired.clone();
        match event {
            FrontendEvent::SettingsSnapshot { snapshot, .. } => {
                if self
                    .settings_revision
                    .is_some_and(|r| r >= snapshot.revision)
                {
                    return false;
                }
                self.settings_revision = Some(snapshot.revision);
                for d in &snapshot.descriptors {
                    match d.key.as_str() {
                        "live2d.enabled" => {
                            self.desired.enabled = d.value.as_bool().unwrap_or(false)
                        }
                        "live2d.visible" => {
                            self.desired.input.visible = d.value.as_bool().unwrap_or(false)
                        }
                        "live2d.x" => {
                            self.desired.input.x =
                                d.value.as_i64().and_then(|v| i32::try_from(v).ok())
                        }
                        "live2d.y" => {
                            self.desired.input.y =
                                d.value.as_i64().and_then(|v| i32::try_from(v).ok())
                        }
                        _ => {}
                    }
                }
            }
            FrontendEvent::ChatAccepted { generation_id, .. } => {
                if self.generation.as_ref() == Some(generation_id) {
                    return false;
                }
                self.generation = Some(generation_id.clone());
                self.cancelled = false;
                self.chat_active = true;
                self.voice_state = "idle".into();
                self.desired.input.state = "thinking".into();
            }
            FrontendEvent::ChatTerminal {
                generation_id,
                terminal_state,
                ..
            } if self.generation.as_ref() == Some(generation_id) => {
                self.chat_active = false;
                self.cancelled = terminal_state != "completed";
                self.desired.input.state = if matches!(
                    terminal_state.as_str(),
                    "failed" | "rejected" | "backend_lost"
                ) {
                    "error"
                } else if !self.cancelled && self.voice_state == "speaking" {
                    "speaking"
                } else if !self.cancelled && self.voice_state == "preparing" {
                    "thinking"
                } else {
                    "idle"
                }
                .into();
            }
            FrontendEvent::VoiceState { snapshot } if snapshot.revision > self.voice_revision => {
                self.voice_revision = snapshot.revision;
                if self.generation == snapshot.generation_id && !self.cancelled {
                    self.voice_state = snapshot.state.clone();
                    self.desired.input.state = match snapshot.state.as_str() {
                        "speaking" => "speaking",
                        "preparing" => "thinking",
                        "error" => "error",
                        _ if self.chat_active => "thinking",
                        _ => "idle",
                    }
                    .into();
                }
            }
            FrontendEvent::BackendState { state, .. }
                if matches!(
                    state,
                    BackendState::Disconnected | BackendState::Stopped | BackendState::Stopping
                ) =>
            {
                self.generation = None;
                self.voice_revision = 0;
                self.settings_revision = None;
                self.cancelled = true;
                self.chat_active = false;
                self.voice_state = "idle".into();
                self.desired.input.state = "idle".into();
            }
            _ => {}
        }
        if old != self.desired {
            self.desired.input.revision += 1;
            true
        } else {
            false
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    executable: PathBuf,
    model: PathBuf,
    shaders: PathBuf,
}
impl Config {
    fn load() -> Result<Self, &'static str> {
        // Explicit private developer/runtime configuration. No machine paths in source.
        let path = std::env::var_os("AURORA_LIVE2D_CONFIG").ok_or("LIVE2D_UNCONFIGURED")?;
        use std::io::Read;
        let mut bytes = Vec::new();
        std::fs::File::open(path)
            .map_err(|_| "LIVE2D_UNCONFIGURED")?
            .take(16385)
            .read_to_end(&mut bytes)
            .map_err(|_| "LIVE2D_CONFIG_INVALID")?;
        if bytes.len() > 16384 {
            return Err("LIVE2D_CONFIG_INVALID");
        }
        let cfg: Self = serde_json::from_slice(&bytes).map_err(|_| "LIVE2D_CONFIG_INVALID")?;
        if !cfg.executable.is_absolute()
            || !cfg.model.is_absolute()
            || !cfg.shaders.is_absolute()
            || !cfg.executable.is_file()
            || !cfg.model.is_file()
            || !cfg.shaders.is_dir()
        {
            return Err("LIVE2D_FILES_UNAVAILABLE");
        }
        Ok(cfg)
    }
}
type Notify = Arc<dyn Fn(Snapshot) + Send + Sync>;
#[derive(Clone)]
pub struct Live2d {
    projection: Arc<Mutex<Projection>>,
    tx: watch::Sender<Desired>,
    snapshot: Arc<Mutex<Snapshot>>,
    notify: Arc<Mutex<Option<Notify>>>,
    task: Arc<Mutex<Option<tauri::async_runtime::JoinHandle<()>>>>,
}
impl Default for Live2d {
    fn default() -> Self {
        let projection = Projection::default();
        let (tx, _) = watch::channel(projection.desired.clone());
        Self {
            projection: Arc::new(Mutex::new(projection)),
            tx,
            snapshot: Arc::new(Mutex::new(Snapshot {
                status: "disabled".into(),
                state: "idle".into(),
                ..Default::default()
            })),
            notify: Default::default(),
            task: Default::default(),
        }
    }
}
impl Live2d {
    pub fn start(&self, notify: impl Fn(Snapshot) + Send + Sync + 'static) {
        let mut task = self.task.lock().unwrap_or_else(|e| e.into_inner());
        if task.is_some() {
            return;
        }
        *self.notify.lock().unwrap_or_else(|e| e.into_inner()) = Some(Arc::new(notify));
        let own = self.clone();
        let rx = self.tx.subscribe();
        *task = Some(tauri::async_runtime::spawn(async move {
            own.run(rx).await;
        }));
    }
    pub fn snapshot(&self) -> Snapshot {
        self.snapshot
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }
    pub fn observe(&self, event: &FrontendEvent) {
        let mut p = self.projection.lock().unwrap_or_else(|e| e.into_inner());
        if p.accept(event) {
            self.tx.send_replace(p.desired.clone());
        }
    }
    fn publish(&self, status: &str, input: &Input, fps: f64, error: &str) {
        let value = Snapshot {
            status: status.into(),
            state: input.state.clone(),
            visible: status == "ready" && input.visible,
            fps,
            error_code: error.into(),
        };
        *self.snapshot.lock().unwrap_or_else(|e| e.into_inner()) = value.clone();
        let notify = self
            .notify
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone();
        if let Some(notify) = notify {
            notify(value);
        }
    }
    pub async fn shutdown(&self) {
        {
            let mut p = self.projection.lock().unwrap_or_else(|e| e.into_inner());
            p.desired.enabled = false;
            p.desired.input.shutdown = true;
            p.desired.input.revision += 1;
            self.tx.send_replace(p.desired.clone());
        }
        let task = self.task.lock().unwrap_or_else(|e| e.into_inner()).take();
        if let Some(task) = task {
            let _ = task.await;
        }
    }
    async fn run(&self, mut rx: watch::Receiver<Desired>) {
        loop {
            let desired = rx.borrow_and_update().clone();
            if desired.input.shutdown {
                break;
            }
            if !desired.enabled {
                self.publish("disabled", &desired.input, 0.0, "");
                if rx.changed().await.is_err() {
                    break;
                }
                continue;
            }
            self.publish("starting", &desired.input, 0.0, "");
            let result = match Config::load() {
                Ok(config) => self.session(&config, &mut rx).await,
                Err(code) => Err(code),
            };
            if let Err(code) = result {
                let latest = rx.borrow().clone();
                if latest.enabled && !latest.input.shutdown {
                    self.publish("error", &latest.input, 0.0, code);
                }
                // No restart loop. Explicit disable then enable is required.
                while rx.borrow().enabled && !rx.borrow().input.shutdown {
                    if rx.changed().await.is_err() {
                        return;
                    }
                }
            }
        }
        self.publish("stopped", &rx.borrow().input, 0.0, "");
    }
    async fn session(
        &self,
        config: &Config,
        rx: &mut watch::Receiver<Desired>,
    ) -> Result<(), &'static str> {
        let mut command = Command::new(&config.executable);
        command
            .env("AURORA_LIVE2D_MODEL", &config.model)
            .env("AURORA_LIVE2D_SHADERS", &config.shaders)
            .env_remove("AURORA_LIVE2D_CAPTURE_PATH");
        self.run_child(command, rx).await
    }

    async fn run_child(
        &self,
        mut command: Command,
        rx: &mut watch::Receiver<Desired>,
    ) -> Result<(), &'static str> {
        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);
        #[cfg(windows)]
        command.creation_flags(0x08000000);
        let mut child = command.spawn().map_err(|_| "LIVE2D_START_FAILED")?;
        let _job = JobGuard::assign(child.id().ok_or("LIVE2D_START_FAILED")?)
            .map_err(|_| "LIVE2D_OWNERSHIP_FAILED")?;
        let mut writer = child.stdin.take().ok_or("LIVE2D_TRANSPORT_FAILED")?;
        let stdout = child.stdout.take().ok_or("LIVE2D_TRANSPORT_FAILED")?;
        let mut reader = BufReader::new(stdout);
        let mut ready = false;
        let started = Instant::now();
        let mut sent = 0;
        let mut line = Vec::new();
        let mut bytes = [0u8; 1024];
        let outcome = loop {
            let desired = rx.borrow_and_update().clone();
            if desired.input.shutdown || !desired.enabled {
                break Ok(());
            }
            if ready && sent != desired.input.revision {
                if send(&mut writer, &desired.input).await.is_err() {
                    break Err("LIVE2D_TRANSPORT_FAILED");
                }
                sent = desired.input.revision;
            }
            if !ready && started.elapsed() > Duration::from_secs(20) {
                break Err("LIVE2D_START_TIMEOUT");
            }
            tokio::select! {
                changed=rx.changed()=>{if changed.is_err(){break Ok(())}},
                n=reader.read(&mut bytes)=>{
                    let Ok(n)=n else{break Err("LIVE2D_TRANSPORT_FAILED")};if n==0{break Err("LIVE2D_EXITED")}
                    line.extend_from_slice(&bytes[..n]);if line.len()>4096{break Err("LIVE2D_PROTOCOL_FAILED")}
                    let mut error=None;
                    while let Some(end)=line.iter().position(|b|*b==b'\n'){
                        let raw:Vec<_>=line.drain(..=end).collect();
                        let Ok(value)=serde_json::from_slice::<Value>(&raw)else{error=Some("LIVE2D_PROTOCOL_FAILED");break};
                        match value["type"].as_str(){
                            Some("ready") if value["protocol"]==1=>{ready=true;self.publish("ready",&desired.input,0.0,"");}
                            Some("applied") if ready=>{
                                if value["revision"].as_u64()==Some(desired.input.revision)
                                    && value["state"].as_str()==Some(desired.input.state.as_str())
                                    && value["visible"].as_bool()==Some(desired.input.visible) {
                                    self.publish("ready",&desired.input,self.snapshot().fps,"");
                                }
                            }
                            Some("metrics") if ready=>{
                                if value["revision"].as_u64()==Some(desired.input.revision){
                                    let fps=value["frames"].as_f64().unwrap_or(0.0)/value["seconds"].as_f64().unwrap_or(1.0).max(0.001);
                                    self.publish("ready",&desired.input,if fps.is_finite(){fps.min(1000.0)}else{0.0},"");
                                }
                            }
                            Some("error")=>{error=Some("LIVE2D_RENDER_FAILED");break},
                            Some("closed")=>{error=Some("LIVE2D_CLOSED");break},
                            _=>{error=Some("LIVE2D_PROTOCOL_FAILED");break}
                        }
                    }
                    if let Some(code)=error{break Err(code)}
                },
                _=tokio::time::sleep(Duration::from_millis(100))=>{}
            }
        };
        let mut stop = rx.borrow().input.clone();
        stop.revision = stop.revision.saturating_add(1);
        stop.shutdown = true;
        let _ = send(&mut writer, &stop).await;
        drop(writer);
        close_child(&mut child).await;
        eprintln!("[aurora-live2d] event=host_released");
        outcome
    }
}
async fn send(writer: &mut ChildStdin, input: &Input) -> Result<(), ()> {
    let mut bytes = serde_json::to_vec(input).map_err(|_| ())?;
    bytes.push(b'\n');
    timeout(Duration::from_millis(500), writer.write_all(&bytes))
        .await
        .map_err(|_| ())?
        .map_err(|_| ())
}
async fn close_child(child: &mut Child) {
    if timeout(Duration::from_secs(3), child.wait()).await.is_err() {
        let _ = child.start_kill();
        let _ = timeout(Duration::from_secs(2), child.wait()).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn accepted(g: &str) -> FrontendEvent {
        FrontendEvent::ChatAccepted {
            request_id: "r".into(),
            generation_id: g.into(),
            ipc_received_unix_ms: None,
        }
    }
    fn voice(g: &str, r: u64, s: &str) -> FrontendEvent {
        FrontendEvent::VoiceState {
            snapshot: crate::voice::Snapshot {
                revision: r,
                state: s.into(),
                enabled: true,
                provider: "edge_tts".into(),
                generation_id: Some(g.into()),
                error_code: "".into(),
            },
        }
    }
    #[test]
    fn state_and_stale() {
        let mut p = Projection::default();
        assert!(!p.desired.enabled);
        p.accept(&accepted("a"));
        assert_eq!(p.desired.input.state, "thinking");
        p.accept(&voice("a", 1, "speaking"));
        assert_eq!(p.desired.input.state, "speaking");
        assert!(!p.accept(&voice("a", 1, "idle")));
        p.accept(&accepted("b"));
        p.accept(&voice("a", 2, "idle"));
        assert_eq!(p.desired.input.state, "thinking");
        p.accept(&voice("b", 3, "speaking"));
        p.accept(&FrontendEvent::ChatTerminal {
            request_id: "r".into(),
            generation_id: "b".into(),
            terminal_state: "completed".into(),
            error_code: None,
            diagnostics: None,
        });
        assert_eq!(p.desired.input.state, "speaking");
        p.accept(&voice("b", 4, "stopping"));
        assert_eq!(p.desired.input.state, "idle");
    }
    #[test]
    fn cancelled_cannot_respeak() {
        let mut p = Projection::default();
        p.accept(&accepted("a"));
        p.accept(&FrontendEvent::ChatTerminal {
            request_id: "r".into(),
            generation_id: "a".into(),
            terminal_state: "cancelled".into(),
            error_code: None,
            diagnostics: None,
        });
        p.accept(&voice("a", 2, "speaking"));
        assert_eq!(p.desired.input.state, "idle");
        assert!(!p.accept(&accepted("a")));
        assert_eq!(p.desired.input.state, "idle");
    }
    #[test]
    fn initial_voice_idle_cannot_erase_active_chat_thinking() {
        let mut p = Projection::default();
        p.accept(&accepted("a"));
        p.accept(&voice("a", 1, "idle"));
        assert_eq!(p.desired.input.state, "thinking");
    }
    #[tokio::test]
    async fn disabled_shutdown_no_renderer() {
        let owner = Live2d::default();
        owner.start(|_| {});
        owner.shutdown().await;
        assert_eq!(owner.snapshot().status, "stopped");
    }
    fn settings(revision: u64, enabled: bool) -> FrontendEvent {
        let examples: Value = serde_json::from_str(include_str!(
            "../../../contracts/ipc-v1.settings.examples.json"
        ))
        .unwrap();
        let mut snapshot = crate::settings::Snapshot::from_wire(examples[1]["payload"].clone())
            .or_else(|_| crate::settings::Snapshot::from_wire(examples[0]["payload"].clone()))
            .unwrap();
        snapshot.revision = revision;
        for d in &mut snapshot.descriptors {
            if d.key == "live2d.enabled" {
                d.value = Value::Bool(enabled);
            }
        }
        FrontendEvent::SettingsSnapshot {
            request_id: "s".into(),
            snapshot,
        }
    }
    #[test]
    fn settings_revision_and_disconnect() {
        let mut p = Projection::default();
        p.accept(&settings(3, true));
        assert!(p.desired.enabled);
        p.accept(&settings(2, false));
        assert!(p.desired.enabled);
        p.accept(&FrontendEvent::BackendState {
            state: BackendState::Disconnected,
            metrics: Default::default(),
            info: Default::default(),
        });
        p.accept(&settings(0, false));
        assert!(!p.desired.enabled);
        assert_eq!(p.desired.input.state, "idle");
    }
    #[test]
    fn terminal_from_old_generation_does_not_reset_new() {
        let mut p = Projection::default();
        p.accept(&accepted("a"));
        p.accept(&accepted("b"));
        p.accept(&FrontendEvent::ChatTerminal {
            request_id: "r".into(),
            generation_id: "a".into(),
            terminal_state: "failed".into(),
            error_code: None,
            diagnostics: None,
        });
        assert_eq!(p.desired.input.state, "thinking");
    }
    #[tokio::test]
    async fn missing_executable_fails_only_optional_session() {
        let host = Live2d::default();
        let mut desired = host.tx.borrow().clone();
        desired.enabled = true;
        desired.input.revision = 1;
        let (_tx, mut rx) = watch::channel(desired);
        let config = Config {
            executable: PathBuf::from("aurora-missing-test-host.exe"),
            model: PathBuf::new(),
            shaders: PathBuf::new(),
        };
        assert_eq!(
            host.session(&config, &mut rx).await,
            Err("LIVE2D_START_FAILED")
        );
        assert_eq!(host.snapshot().status, "disabled");
    }

    fn fixture(mode: &str) -> Command {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(4)
            .unwrap()
            .to_path_buf();
        let mut cmd = Command::new(root.join(".venv/Scripts/python.exe"));
        cmd.args(["-u", "-c", r#"
import json, sys, time
mode = sys.argv[1]
if mode == 'failure':
    print('{"type":"error","code":"RENDERER_INIT_FAILED"}', flush=True)
    sys.exit(1)
if mode == 'malformed':
    print('x' * 5000, flush=True)
    sys.exit(1)
if mode == 'early':
    sys.exit(1)
if mode == 'hang':
    time.sleep(30)
print('{"type":"ready","protocol":1}', flush=True)
for raw in sys.stdin:
    v = json.loads(raw)
    if v['shutdown']:
        print('{"type":"closed"}', flush=True)
        break
    print(json.dumps(dict(type='metrics', revision=v['revision'], state=v['state'], visible=v['visible'], frames=58 if v['visible'] else 0, seconds=1)), flush=True)
"#, mode]);
        cmd
    }
    fn enabled() -> Desired {
        let mut d = Projection::default().desired;
        d.enabled = true;
        d.input.revision = 1;
        d
    }
    #[tokio::test]
    async fn child_success_hide_and_shutdown_join() {
        let owner = Live2d::default();
        let child_owner = owner.clone();
        let (tx, mut rx) = watch::channel(enabled());
        let task =
            tokio::spawn(async move { child_owner.run_child(fixture("normal"), &mut rx).await });
        timeout(Duration::from_secs(5), async {
            while owner.snapshot().fps == 0.0 {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        let mut d = enabled();
        d.input.revision = 2;
        d.input.visible = false;
        tx.send_replace(d.clone());
        timeout(Duration::from_secs(5), async {
            while owner.snapshot().visible {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        assert_eq!(owner.snapshot().fps, 0.0);
        d.input.revision = 3;
        d.input.shutdown = true;
        tx.send_replace(d);
        assert_eq!(
            timeout(Duration::from_secs(5), task)
                .await
                .unwrap()
                .unwrap(),
            Ok(())
        );
    }
    #[tokio::test]
    async fn child_error_crash_and_protocol_failure_release() {
        for (mode, expected) in [
            ("failure", "LIVE2D_RENDER_FAILED"),
            ("early", "LIVE2D_EXITED"),
            ("malformed", "LIVE2D_PROTOCOL_FAILED"),
        ] {
            let owner = Live2d::default();
            let (_tx, mut rx) = watch::channel(enabled());
            assert_eq!(
                timeout(
                    Duration::from_secs(5),
                    owner.run_child(fixture(mode), &mut rx)
                )
                .await
                .unwrap(),
                Err(expected)
            );
        }
    }
    #[tokio::test]
    async fn shutdown_while_initializing_is_bounded() {
        let owner = Live2d::default();
        let (tx, mut rx) = watch::channel(enabled());
        let task = tokio::spawn(async move { owner.run_child(fixture("hang"), &mut rx).await });
        tokio::time::sleep(Duration::from_millis(100)).await;
        let mut d = enabled();
        d.input.shutdown = true;
        d.input.revision = 2;
        tx.send_replace(d);
        assert_eq!(
            timeout(Duration::from_secs(6), task)
                .await
                .unwrap()
                .unwrap(),
            Ok(())
        );
    }
}
