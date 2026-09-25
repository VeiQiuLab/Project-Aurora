use std::{
    path::PathBuf,
    process::Stdio,
    sync::{Arc, Mutex as StdMutex, atomic::{AtomicBool, Ordering}},
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tauri::ipc::Channel;
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, BufReader},
    process::{Child, Command},
    sync::{Mutex, mpsc},
    time::{Duration, timeout},
};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{
        Message,
        client::IntoClientRequest,
        http::{HeaderValue, header::AUTHORIZATION},
    },
};
use uuid::Uuid;

use crate::{
    protocol::{
        BOOTSTRAP_MAX_BYTES, BackendInfo, BackendSnapshot, BackendState, BootstrapReady,
        CancelTarget, ChatDiagnostics, ChatStartResult, ConversationDetail, ConversationSummary,
        FrontendEvent, PROTOCOL,
        ProductionDiagnostics, PrototypeMetrics, VERSION, chat_cancel, chat_request, health, hello,
        conversation_create, conversation_get, conversation_list, object, require_string,
        shutdown, validate_hello_ack_for_mode, validate_sidecar_event,
    },
    registry::{RequestOwner, RequestRegistry},
};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(10);
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(6);
const WRITER_CAPACITY: usize = 32;

#[derive(Debug)]
struct SidecarLaunch {
    python: PathBuf,
    script: PathBuf,
    working_directory: PathBuf,
    python_path: std::ffi::OsString,
}

#[derive(Debug)]
struct BackendData {
    state: BackendState,
    info: BackendInfo,
    voice: Option<crate::voice::Snapshot>,
    audio: Option<Arc<crate::audio::AudioOwner>>,
    epoch: u64,
    startup_cancel: Arc<AtomicBool>,
    child: Option<Arc<Mutex<Child>>>,
    job: Option<JobGuard>,
    writer: Option<mpsc::Sender<Message>>,
    sidecar_instance_id: Option<String>,
    registry: RequestRegistry,
    session_id: String,
    negotiated_chat_input_max_bytes: usize,
    metrics: PrototypeMetrics,
    request_started: std::collections::HashMap<(String, String), Instant>,
    cancel_started: std::collections::HashMap<(String, String), Instant>,
    crash_requested_at: Option<Instant>,
    restart_started_at: Option<Instant>,
    #[cfg(test)]
    launch_identity: Option<(u32, u16, String)>,
}

impl BackendData {
    fn new() -> Self {
        Self {
            state: BackendState::Stopped,
            info: BackendInfo::default(),
            voice: None,
            audio: None,
            epoch: 0,
            startup_cancel: Arc::new(AtomicBool::new(false)),
            child: None,
            job: None,
            writer: None,
            sidecar_instance_id: None,
            registry: RequestRegistry::default(),
            session_id: format!("session-{}", Uuid::new_v4().simple()),
            negotiated_chat_input_max_bytes: 0,
            metrics: PrototypeMetrics::default(),
            request_started: Default::default(),
            cancel_started: Default::default(),
            crash_requested_at: None,
            restart_started_at: None,
            #[cfg(test)]
            launch_identity: None,
        }
    }
}

#[derive(Clone)]
pub struct BackendManager {
    inner: Arc<Mutex<BackendData>>,
    frontend: Arc<StdMutex<Option<Channel<FrontendEvent>>>>,
    desktop_started: Instant,
    mode: String,
    local_model: Option<crate::local_model::LocalModelSupervisor>,
    pub live2d: Option<crate::live2d::Live2d>,
    #[cfg(test)]
    test_data_directory: Option<PathBuf>,
}

impl BackendManager {
    pub fn new() -> Self {
        // The desktop Settings page uses the existing production owner by default.
        // Mock transport remains an explicit test/development opt-in.
        let mut manager = Self::with_mode(std::env::var("AURORA_V4_BACKEND").unwrap_or_else(|_| "production".into()));
        manager.live2d = Some(Default::default());
        if manager.mode == "production" && std::env::var("AURORA_V4_CHAT_PROVIDER").as_deref() != Ok("ollama") {
            manager.local_model = Some(Default::default());
        }
        manager
    }

    fn with_mode(mode: String) -> Self {
        Self {
            inner: Arc::new(Mutex::new(BackendData::new())),
            frontend: Arc::new(StdMutex::new(None)),
            desktop_started: Instant::now(),
            mode,
            local_model: None,
            live2d: None,
            #[cfg(test)]
            test_data_directory: None,
        }
    }

    pub async fn register_channel(&self, channel: Channel<FrontendEvent>) -> BackendSnapshot {
        *self
            .frontend
            .lock()
            .expect("frontend channel lock poisoned") = Some(channel);
        let data = self.inner.lock().await;
        let snapshot = BackendSnapshot {
            state: data.state,
            metrics: data.metrics.clone(),
            info: data.info.clone(),
            voice: data.voice.clone(),
        };
        drop(data);
        self.emit(FrontendEvent::BackendState {
            state: snapshot.state,
            metrics: snapshot.metrics.clone(),
            info: snapshot.info.clone(),
        });
        snapshot
    }

    pub async fn snapshot(&self) -> BackendSnapshot {
        let data = self.inner.lock().await;
        BackendSnapshot {
            state: data.state,
            metrics: data.metrics.clone(),
            info: data.info.clone(),
            voice: data.voice.clone(),
        }
    }

    pub async fn start(&self, restarting: bool) -> Result<(), String> {
        let epoch;
        let startup_cancel;
        {
            let mut data = self.inner.lock().await;
            if matches!(
                data.state,
                BackendState::Starting
                    | BackendState::Restarting
                    | BackendState::Stopping
                    | BackendState::Handshaking
                    | BackendState::Ready
                    | BackendState::Degraded
            ) {
                return Ok(());
            }
            data.epoch += 1;
            data.voice = None;
            epoch = data.epoch;
            data.startup_cancel.store(true, Ordering::SeqCst);
            startup_cancel = Arc::new(AtomicBool::new(false));
            data.startup_cancel = startup_cancel.clone();
            data.info = BackendInfo {
                mode: if self.mode == "production" {
                    "production"
                } else {
                    "mock"
                }
                .into(),
                ..Default::default()
            };
            if restarting {
                data.restart_started_at = Some(Instant::now());
                data.state = BackendState::Restarting;
            } else {
                data.state = BackendState::Starting;
            }
        }
        self.emit_state().await;

        let result = self.start_once(epoch, startup_cancel).await;
        if let Err(error) = &result {
            eprintln!("[aurora-v4] event=sidecar_start_failed error={error}");
            let mut data = self.inner.lock().await;
            if data.epoch != epoch {
                return Err("Backend startup was superseded.".into());
            }
            data.state = BackendState::Disconnected;
            data.voice = None;
            data.info.error_code = Some("BACKEND_START_FAILED".into());
            data.writer = None;
            data.child = None;
            data.job = None;
            data.sidecar_instance_id = None;
            // A Python bootstrap/handshake failure must not leave a loaded model
            // behind. Keep the owner epoch locked until cleanup finishes so an
            // old startup cannot tear down a newer instance.
            if let Some(supervisor) = &self.local_model { supervisor.shutdown().await; }
            drop(data);
            self.emit_state().await;
        }
        result.map_err(|_| "Backend startup failed; see sidecar stderr diagnostics.".into())
    }

    async fn start_once(&self, epoch: u64, startup_cancel: Arc<AtomicBool>) -> Result<(), String> {
        if startup_cancel.load(Ordering::SeqCst) { return Err("STALE_STARTUP".into()); }
        let spawn_started = Instant::now();
        let launch = find_sidecar_launch(&self.mode)?;
        let handoff = if let Some(supervisor) = &self.local_model { Some(supervisor.start(startup_cancel).await?) } else { None };
        if self.inner.lock().await.epoch != epoch { return Err("STALE_STARTUP".into()); }
        let token = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
        let mut command = Command::new(&launch.python);
        let audio_root = if self.mode == "production" {
            tempfile::Builder::new().prefix("aurora-v4-audio-").tempdir().ok()
        } else { None };
        command.env_remove("AURORA_AUDIO_ROOT");
        if let Some(root) = &audio_root { command.env("AURORA_AUDIO_ROOT", root.path()); }
        command
            .arg("-u")
            .arg(&launch.script)
            .current_dir(&launch.working_directory)
            .env("AURORA_IPC_TOKEN", &token)
            .env("AURORA_IPC_PROTOCOL", PROTOCOL)
            .env("AURORA_IPC_SUPPORTED_VERSIONS", VERSION.to_string())
            .env("AURORA_MOCK_DELTA_DELAY_MS", "45")
            .env("PYTHONNOUSERSITE", "1")
            .env("PYTHONUTF8", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("PYTHONPATH", &launch.python_path)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        #[cfg(test)]
        if let Some(directory) = &self.test_data_directory {
            command.env("AURORA_USER_DATA_DIR", directory);
        }
        // Always clear inherited private values before selecting this instance's provider.
        for name in ["AURORA_LOCAL_ENDPOINT", "AURORA_LOCAL_TOKEN", "AURORA_LOCAL_MODEL"] { command.env_remove(name); }
        if let Some(private) = handoff {
            command.env("AURORA_V4_CHAT_PROVIDER", "builtin_local")
                .env("AURORA_LOCAL_ENDPOINT", private.endpoint).env("AURORA_LOCAL_TOKEN", private.token)
                .env("AURORA_LOCAL_MODEL", private.model);
        } else { command.env("AURORA_V4_CHAT_PROVIDER", "ollama"); }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.as_std_mut().creation_flags(0x0800_0000);
        }
        let mut child = command.spawn().map_err(|error| error.to_string())?;
        let child_pid = child
            .id()
            .ok_or_else(|| "sidecar child has no PID".to_string())?;
        let job = match JobGuard::assign(child_pid) {
            Ok(job) => job,
            Err(error) => {
                let _ = child.start_kill();
                return Err(error);
            }
        };
        eprintln!("[aurora-v4] event=sidecar_spawn pid={child_pid}");

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "sidecar stdout unavailable".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "sidecar stderr unavailable".to_string())?;
        tokio::spawn(drain_stderr(stderr));

        let mut bootstrap_bytes = Vec::new();
        let mut limited_stdout = BufReader::new(stdout).take(BOOTSTRAP_MAX_BYTES + 1);
        let bytes_read = timeout(
            STARTUP_TIMEOUT,
            limited_stdout.read_until(b'\n', &mut bootstrap_bytes),
        )
        .await
        .map_err(|_| "sidecar bootstrap timed out".to_string())?
        .map_err(|error| error.to_string())?;
        if bytes_read == 0
            || bytes_read as u64 > BOOTSTRAP_MAX_BYTES
            || !bootstrap_bytes.ends_with(b"\n")
        {
            return Err("sidecar bootstrap line is empty, too large, or incomplete".into());
        }
        let bootstrap: BootstrapReady =
            serde_json::from_slice(&bootstrap_bytes).map_err(|error| error.to_string())?;
        bootstrap.validate()?;
        if bootstrap.pid != child_pid {
            return Err("PYTHON_REDIRECTOR_NOT_SUPPORTED_USE_BASE_INTERPRETER".into());
        }
        eprintln!(
            "[aurora-v4] event=sidecar_bootstrap child_pid={} runtime_pid={}",
            child_pid, bootstrap.pid
        );
        let bootstrap_received = Instant::now();
        {
            let mut data = self.inner.lock().await;
            if data.epoch != epoch {
                return Err("STALE_STARTUP".into());
            }
            data.metrics.spawn_to_bootstrap_ms = Some(elapsed_ms(spawn_started));
            data.state = BackendState::Handshaking;
        }
        self.emit_state().await;

        let mut request = format!("ws://127.0.0.1:{}", bootstrap.port)
            .into_client_request()
            .map_err(|error| error.to_string())?;
        request.headers_mut().insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {token}")).map_err(|error| error.to_string())?,
        );
        let (mut socket, _) = timeout(HANDSHAKE_TIMEOUT, connect_async(request))
            .await
            .map_err(|_| "sidecar WebSocket connect timed out".to_string())?
            .map_err(|error| error.to_string())?;
        let hello_id = format!("hello-{}", Uuid::new_v4().simple());
        socket
            .send(Message::Text(hello(&hello_id).to_string().into()))
            .await
            .map_err(|error| error.to_string())?;
        let ack = timeout(HANDSHAKE_TIMEOUT, socket.next())
            .await
            .map_err(|_| "sidecar hello_ack timed out".to_string())?
            .ok_or_else(|| "sidecar closed during handshake".to_string())?
            .map_err(|error| error.to_string())?;
        let ack_text = ack
            .to_text()
            .map_err(|_| "sidecar hello_ack must be JSON text".to_string())?;
        let ack_value: Value = serde_json::from_str(ack_text).map_err(|error| error.to_string())?;
        let sidecar_instance_id =
            validate_hello_ack_for_mode(&ack_value, &hello_id, self.mode == "production")?;
        if sidecar_instance_id != bootstrap.sidecar_instance_id {
            return Err("sidecar_instance_id changed during handshake".into());
        }
        let negotiated_limit = object(&ack_value, "payload")?
            .get("limits")
            .and_then(Value::as_object)
            .and_then(|limits| limits.get("chat_input_max_bytes"))
            .and_then(Value::as_u64)
            .and_then(|limit| usize::try_from(limit).ok())
            .ok_or_else(|| "invalid chat_input_max_bytes".to_string())?;

        let (mut socket_writer, mut socket_reader) = socket.split();
        let (writer, mut messages) = mpsc::channel::<Message>(WRITER_CAPACITY);
        let audio = audio_root.and_then(|root| crate::audio::AudioOwner::new(root, writer.clone()).ok()).map(Arc::new);
        if self.mode == "production" && audio.is_none() { eprintln!("[aurora-v4] event=audio_unavailable"); }
        let child = Arc::new(Mutex::new(child));
        {
            let mut data = self.inner.lock().await;
            if data.epoch != epoch {
                return Err("STALE_STARTUP".into());
            }
            data.metrics.bootstrap_to_ready_ms = Some(elapsed_ms(bootstrap_received));
            if let Some(restart_started) = data.restart_started_at.take() {
                data.metrics.restart_to_ready_ms = Some(elapsed_ms(restart_started));
            }
            data.child = Some(child);
            data.job = Some(job);
            data.writer = Some(writer.clone());
            data.audio = audio;
            data.sidecar_instance_id = Some(sidecar_instance_id);
            data.negotiated_chat_input_max_bytes = negotiated_limit;
            data.state = if ack_value["payload"]["state"] == "DEGRADED" {
                BackendState::Degraded
            } else {
                BackendState::Ready
            };
            data.info.chat_enabled = true;
            if data.metrics.desktop_startup_ms == 0.0 {
                data.metrics.desktop_startup_ms = elapsed_ms(self.desktop_started);
            }
            #[cfg(test)]
            {
                data.launch_identity = Some((bootstrap.pid, bootstrap.port, token.clone()));
            }
        }
        self.emit_state().await;
        eprintln!("[aurora-v4] event=sidecar_ready");
        eprintln!(
            "[aurora-v4] event=backend_metrics json={}",
            serde_json::to_string(&self.snapshot().await).unwrap_or_default()
        );

        let writer_manager = self.clone();
        tokio::spawn(async move {
            while let Some(message) = messages.recv().await {
                let closing = message.is_close();
                if socket_writer.send(message).await.is_err() {
                    break;
                }
                if closing { break; }
            }
            let _ = socket_writer.close().await;
            writer_manager.connection_lost(epoch).await;
        });

        let reader_manager = self.clone();
        let close_writer = writer.clone();
        tokio::spawn(async move {
            while let Some(item) = socket_reader.next().await {
                match item {
                    Ok(Message::Text(text)) => {
                        if let Err(error) = reader_manager.handle_wire(epoch, text.as_str()).await {
                            if error == "STALE_CONNECTION" {
                                // Shutdown invalidates the epoch before Python
                                // finishes Voice cleanup. Drain (do not forward)
                                // these frames until its close handshake arrives.
                                continue;
                            }
                            eprintln!("[aurora-v4] event=protocol_warning code={error}");
                            reader_manager.emit(FrontendEvent::ProtocolWarning { code: error });
                        }
                    }
                    Ok(Message::Close(_)) => {
                        // Flush the close handshake even while Audio's reply
                        // sender is retained for orderly resource shutdown.
                        let _ = close_writer.try_send(Message::Close(None));
                        break;
                    }
                    Err(_) => {
                        let _ = close_writer.try_send(Message::Close(None));
                        break;
                    }
                    Ok(Message::Binary(_)) => {
                        reader_manager.emit(FrontendEvent::ProtocolWarning {
                            code: "UNEXPECTED_BINARY_FRAME".into(),
                        });
                    }
                    _ => {}
                }
            }
            reader_manager.connection_lost(epoch).await;
        });

        if let Some(supervisor) = self.local_model.clone() {
            let manager = self.clone();
            tokio::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                    if manager.inner.lock().await.epoch != epoch { break; }
                    if supervisor.exited().await {
                        let events = {
                            let mut data=manager.inner.lock().await;
                            if data.epoch != epoch { break; }
                            data.state=BackendState::Degraded; data.info.chat_enabled=false;
                            data.info.error_code=Some("LOCAL_MODEL_UNAVAILABLE".into());
                            data.request_started.clear(); data.cancel_started.clear();
                            data.registry.backend_lost()
                        };
                        for owner in events {
                            manager.emit(FrontendEvent::ChatTerminal { request_id:owner.request_id,
                                generation_id:owner.generation_id, terminal_state:"backend_lost".into(),
                                error_code:Some("BACKEND_LOST".into()), diagnostics:None });
                        }
                        manager.emit_state().await;
                    }
                    if manager.send_value(health(&format!("health-{}",Uuid::new_v4().simple()))).await.is_err() {break;}
                }
            });
        }
        if self.live2d.is_some() { self.settings_get().await?; }
        self.send_value(health(&format!("health-{}", Uuid::new_v4().simple())))
            .await
    }

    pub async fn chat_start(&self, input: String) -> Result<ChatStartResult, String> {
        self.chat_start_for_conversation(input, None).await
    }

    pub async fn chat_start_for_conversation(&self, input: String, conversation_id: Option<String>) -> Result<ChatStartResult, String> {
        let received = unix_ms();
        if let Some(id) = conversation_id.as_deref() {
            if id.is_empty() || id.len() > 128
                || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
            {
                return Err("Invalid conversation ID.".into());
            }
        }
        if input.trim().is_empty() {
            return Err("Message cannot be empty.".into());
        }
        let (result, writer) = {
            let mut data = self.inner.lock().await;
            if !matches!(data.state, BackendState::Ready | BackendState::Degraded) {
                return Err("Backend is not ready.".into());
            }
            if !data.info.chat_enabled {
                return Err("Chat capability is unavailable.".into());
            }
            if input.len() > data.negotiated_chat_input_max_bytes {
                return Err("Message exceeds the negotiated limit.".into());
            }
            let result = ChatStartResult {
                request_id: format!("request-{}", Uuid::new_v4().simple()),
                session_id: data.session_id.clone(),
                generation_id: format!("generation-{}", Uuid::new_v4().simple()),
                rust_received_unix_ms: received,
                rust_queued_unix_ms: unix_ms(),
            };
            let owner = RequestOwner {
                request_id: result.request_id.clone(),
                session_id: result.session_id.clone(),
                generation_id: result.generation_id.clone(),
            };
            data.registry.start(owner)?;
            if let Some(audio) = &data.audio { audio.new_generation(&result.generation_id); }
            data.request_started.insert(
                (result.session_id.clone(), result.generation_id.clone()),
                Instant::now(),
            );
            data.metrics.command_to_first_delta_ms = None;
            data.metrics.cancel_to_terminal_ms = None;
            let writer = data
                .writer
                .clone()
                .ok_or_else(|| "Backend transport unavailable.".to_string())?;
            (result, writer)
        };
        let message = chat_request(
            &result.request_id,
            &result.session_id,
            &result.generation_id,
            &input,
        );
        let mut message = message;
        message["payload"]["conversation_id"] = conversation_id.map(Value::String).unwrap_or(Value::Null);
        writer
            .send(Message::Text(message.to_string().into()))
            .await
            .map_err(|_| "Backend transport closed.".to_string())?;
        eprintln!(
            "[aurora-v4] event=chat_start request={} generation={}",
            short_id(&result.request_id),
            short_id(&result.generation_id)
        );
        Ok(result)
    }

    pub async fn conversation_list(&self) -> Result<(), String> {
        self.send_value(conversation_list(&format!("conversation-list-{}", Uuid::new_v4().simple()))).await
    }

    pub async fn voice_get(&self) -> Result<(), String> {
        if self.mode != "production" { return Err("VOICE_UNAVAILABLE".into()); }
        self.send_value(crate::voice::get(&format!("voice-get-{}", Uuid::new_v4().simple()))).await
    }

    pub async fn voice_stop(&self, generation_id: String) -> Result<(), String> {
        if self.mode != "production" { return Err("VOICE_UNAVAILABLE".into()); }
        if let Some(audio) = &self.inner.lock().await.audio { audio.stop_generation(&generation_id); }
        self.send_value(crate::voice::stop(&format!("voice-stop-{}", Uuid::new_v4().simple()), &generation_id)?).await
    }

    pub async fn settings_get(&self) -> Result<(), String> {
        self.send_value(crate::settings::get(&format!("settings-get-{}", Uuid::new_v4().simple()))).await
    }

    pub async fn settings_update(&self, expected_revision: u64, patch: Value) -> Result<(), String> {
        self.send_value(crate::settings::update(&format!("settings-update-{}", Uuid::new_v4().simple()), expected_revision, patch)?).await
    }

    pub async fn conversation_get(&self, conversation_id: String) -> Result<(), String> {
        if conversation_id.is_empty() || conversation_id.len() > 128 ||
            !conversation_id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
            return Err("Invalid conversation ID.".into());
        }
        self.send_value(conversation_get(&format!("conversation-get-{}", Uuid::new_v4().simple()), &conversation_id)).await
    }

    pub async fn conversation_create(&self) -> Result<(), String> {
        self.send_value(conversation_create(&format!("conversation-create-{}", Uuid::new_v4().simple()))).await
    }

    pub async fn chat_cancel(&self, target: CancelTarget) -> Result<bool, String> {
        let writer = {
            let mut data = self.inner.lock().await;
            let owner = RequestOwner {
                request_id: target.request_id.clone(),
                session_id: target.session_id.clone(),
                generation_id: target.generation_id.clone(),
            };
            if !data.registry.request_cancel(&owner)? {
                return Ok(false);
            }
            data.cancel_started.insert(
                (target.session_id.clone(), target.generation_id.clone()),
                Instant::now(),
            );
            data.metrics.cancel_to_terminal_ms = None;
            data.writer
                .clone()
                .ok_or_else(|| "Backend transport unavailable.".to_string())?
        };
        let request_id = format!("cancel-{}", Uuid::new_v4().simple());
        writer
            .send(Message::Text(
                chat_cancel(&request_id, &target).to_string().into(),
            ))
            .await
            .map_err(|_| "Backend transport closed.".to_string())?;
        eprintln!(
            "[aurora-v4] event=chat_cancel request={} generation={}",
            short_id(&target.request_id),
            short_id(&target.generation_id)
        );
        Ok(true)
    }

    pub async fn crash(&self) -> Result<(), String> {
        let child = {
            let mut data = self.inner.lock().await;
            if !matches!(data.state, BackendState::Ready | BackendState::Degraded) {
                return Err("Backend is not ready.".into());
            }
            data.crash_requested_at = Some(Instant::now());
            data.metrics.crash_to_disconnected_ms = None;
            data.child
                .clone()
                .ok_or_else(|| "Sidecar process unavailable.".to_string())?
        };
        child
            .lock()
            .await
            .start_kill()
            .map_err(|error| error.to_string())
    }

    pub async fn restart(&self) -> Result<(), String> {
        eprintln!("[aurora-v4] event=sidecar_restart_requested");
        self.shutdown().await?;
        self.start(true).await
    }

    pub async fn shutdown(&self) -> Result<(), String> {
        let (writer, child, job, audio, should_emit) = {
            let mut data = self.inner.lock().await;
            if matches!(data.state, BackendState::Stopped | BackendState::Stopping) {
                return Ok(());
            }
            data.startup_cancel.store(true, Ordering::SeqCst);
            data.state = BackendState::Stopping;
            data.epoch += 1;
            data.voice = None;
            let writer = data.writer.take();
            let child = data.child.take();
            let job = data.job.take();
            let audio = data.audio.take();
            if let Some(audio) = &audio { audio.halt(); }
            data.sidecar_instance_id = None;
            data.info.chat_enabled = false;
            (writer, child, job, audio, true)
        };
        if should_emit {
            self.emit_state().await;
        }
        if let Some(writer) = writer {
            let request_id = format!("shutdown-{}", Uuid::new_v4().simple());
            let _ = writer
                .send(Message::Text(shutdown(&request_id).to_string().into()))
                .await;
        }
        if let Some(child) = child {
            let mut child = child.lock().await;
            // Allow Python to stop audio and join request cleanup first.
            let _ = timeout(SHUTDOWN_GRACE, child.wait()).await;
            if child
                .try_wait()
                .map_err(|error| error.to_string())?
                .is_none()
            {
                eprintln!("[aurora-v4] event=sidecar_shutdown forced=true");
                let _ = child.start_kill();
                let _ = timeout(Duration::from_secs(3), child.wait()).await;
            } else {
                eprintln!("[aurora-v4] event=sidecar_shutdown forced=false");
            }
        }
        if let Some(supervisor) = &self.local_model { supervisor.shutdown().await; }
        drop(job);
        if let Some(audio) = audio {
            // Python has exited: now join and delete only this owned handoff root.
            let _ = tokio::task::spawn_blocking(move || { audio.join(); drop(audio); }).await;
        }
        let mut data = self.inner.lock().await;
        data.state = BackendState::Stopped;
        drop(data);
        self.emit_state().await;
        Ok(())
    }

    async fn send_value(&self, value: Value) -> Result<(), String> {
        let writer = self
            .inner
            .lock()
            .await
            .writer
            .clone()
            .ok_or_else(|| "Backend transport unavailable.".to_string())?;
        writer
            .send(Message::Text(value.to_string().into()))
            .await
            .map_err(|_| "Backend transport closed.".to_string())
    }

    async fn handle_wire(&self, epoch: u64, text: &str) -> Result<(), String> {
        let value: Value = serde_json::from_str(text).map_err(|_| "MALFORMED_JSON".to_string())?;
        let message_type = validate_sidecar_event(&value)?;
        let current_epoch = self.inner.lock().await.epoch;
        if epoch != current_epoch {
            return Err("STALE_CONNECTION".into());
        }
        match message_type {
            "audio.play.request" | "audio.stop.request" => {
                let data = self.inner.lock().await;
                if data.epoch != epoch { return Err("STALE_CONNECTION".into()); }
                if let Some(audio) = &data.audio {
                    if message_type == "audio.play.request" {
                        let play = serde_json::from_value(value["payload"].clone()).map_err(|_| "INVALID_AUDIO_PLAY")?;
                        audio.play(play);
                    } else {
                        let id = serde_json::from_value(value["payload"].clone()).map_err(|_| "INVALID_AUDIO_STOP")?;
                        audio.stop(&id);
                    }
                } else if let Some(writer) = &data.writer {
                    let _ = writer.try_send(Message::Text(serde_json::json!({"protocol":"aurora-ipc","version":1,
                        "type":"audio.event","payload":{"generation_id":value["payload"]["generation_id"],
                        "revision":value["payload"]["revision"],"state":"failed","error_code":"AUDIO_INTERNAL_ERROR"}}).to_string().into()));
                }
            }
            "voice.get.response" | "voice.stop.response" | "voice.changed" => {
                let snapshot = crate::voice::Snapshot::from_wire(value["payload"].clone())?;
                let mut data = self.inner.lock().await;
                if data.epoch != epoch { return Err("STALE_CONNECTION".into()); }
                if data.voice.as_ref().is_some_and(|old| old.revision >= snapshot.revision) { return Ok(()); }
                if let Some(audio) = &data.audio { audio.voice(&snapshot); }
                data.voice = Some(snapshot.clone());
                drop(data);
                self.emit(FrontendEvent::VoiceState { snapshot });
            }
            "settings.get.response" => {
                let request_id = require_string(&value, "request_id", None)?.to_owned();
                let snapshot = crate::settings::Snapshot::from_wire(value["payload"].clone())?;
                self.emit(FrontendEvent::SettingsSnapshot { request_id, snapshot });
            }
            "settings.update.response" => {
                let request_id = require_string(&value, "request_id", None)?.to_owned();
                let change = crate::settings::Change::from_wire(value["payload"].clone())?;
                self.emit(FrontendEvent::SettingsUpdated { request_id, change });
            }
            "settings.changed" => {
                let change = crate::settings::Change::from_wire(value["payload"].clone())?;
                let refresh_character = self.live2d.is_some() && change.changed_keys.iter().any(|key| key.starts_with("live2d."));
                self.emit(FrontendEvent::SettingsChanged { change });
                if refresh_character { self.settings_get().await?; }
            }
            "conversation.changed" => {
                let conversation: ConversationSummary = serde_json::from_value(
                    object(&value, "payload")?.get("conversation").cloned()
                        .ok_or_else(|| "INVALID_CONVERSATION".to_string())?,
                ).map_err(|_| "INVALID_CONVERSATION".to_string())?;
                conversation.validate()?;
                self.emit(FrontendEvent::ConversationChanged { conversation });
            }
            "conversation.list.response" => {
                let request_id = require_string(&value, "request_id", None)?.to_owned();
                let conversations: Vec<ConversationSummary> = serde_json::from_value(
                    object(&value, "payload")?.get("conversations").cloned()
                        .ok_or_else(|| "INVALID_CONVERSATION_LIST".to_string())?,
                ).map_err(|_| "INVALID_CONVERSATION_LIST".to_string())?;
                for conversation in &conversations {
                    conversation.validate()?;
                }
                self.emit(FrontendEvent::ConversationList { request_id, conversations });
            }
            "conversation.get.response" => {
                let request_id = require_string(&value, "request_id", None)?.to_owned();
                let conversation: ConversationDetail = serde_json::from_value(
                    object(&value, "payload")?.get("conversation").cloned()
                        .ok_or_else(|| "INVALID_CONVERSATION".to_string())?,
                ).map_err(|_| "INVALID_CONVERSATION".to_string())?;
                conversation.validate()?;
                self.emit(FrontendEvent::ConversationLoaded { request_id, conversation });
            }
            "conversation.create.response" => {
                let request_id = require_string(&value, "request_id", None)?.to_owned();
                let conversation: ConversationSummary = serde_json::from_value(
                    object(&value, "payload")?.get("conversation").cloned()
                        .ok_or_else(|| "INVALID_CONVERSATION".to_string())?,
                ).map_err(|_| "INVALID_CONVERSATION".to_string())?;
                conversation.validate()?;
                self.emit(FrontendEvent::ConversationCreated { request_id, conversation });
            }
            "health.response" => {
                let payload = object(&value, "payload")?;
                let mut data = self.inner.lock().await;
                if epoch != data.epoch {
                    return Err("STALE_CONNECTION".into());
                }
                if payload.get("sidecar_instance_id").and_then(Value::as_str)
                    != data.sidecar_instance_id.as_deref()
                {
                    return Err("STALE_CONNECTION".into());
                }
                let state = match payload.get("state").and_then(Value::as_str) {
                    Some("READY") => BackendState::Ready,
                    Some("DEGRADED") => BackendState::Degraded,
                    _ => return Err("INVALID_HEALTH_STATE".into()),
                };
                if self.mode == "production" {
                    data.info.diagnostics = Some(ProductionDiagnostics::from_wire(
                        payload
                            .get("diagnostics")
                            .cloned()
                            .ok_or("MISSING_DIAGNOSTICS")?,
                    )?);
                }
                data.state = state;
                drop(data);
                self.emit_state().await;
            }
            "chat.accepted" => {
                let owner = owner_from(&value)?;
                self.inner.lock().await.registry.accept(&owner)?;
                self.emit(FrontendEvent::ChatAccepted {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                    ipc_received_unix_ms: value["payload"]["ipc_received_unix_ms"].as_f64(),
                });
            }
            "chat.delta" => {
                let received = unix_ms();
                let owner = owner_from(&value)?;
                let seq = value
                    .get("seq")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| "INVALID_SEQUENCE".to_string())?;
                let delta = object(&value, "payload")?
                    .get("delta")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_DELTA".to_string())?
                    .to_owned();
                let mut data = self.inner.lock().await;
                data.registry.delta(&owner, seq)?;
                if data.metrics.command_to_first_delta_ms.is_none()
                    && let Some(started) = data
                        .request_started
                        .get(&(owner.session_id.clone(), owner.generation_id.clone()))
                {
                    data.metrics.command_to_first_delta_ms = Some(elapsed_ms(*started));
                }
                drop(data);
                self.emit(FrontendEvent::ChatDelta {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                    seq,
                    delta,
                    python_sent_unix_ms: value["payload"]["python_sent_unix_ms"].as_f64(),
                    rust_received_unix_ms: received,
                });
            }
            "chat.completed" => {
                let owner = owner_from(&value)?;
                let payload = object(&value, "payload")?;
                let terminal_state = payload
                    .get("terminal_state")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_TERMINAL_STATE".to_string())?
                    .to_owned();
                let error_code = payload
                    .get("error")
                    .and_then(Value::as_object)
                    .and_then(|error| error.get("code"))
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                let diagnostics = payload
                    .get("diagnostics")
                    .cloned()
                    .map(ChatDiagnostics::from_wire)
                    .transpose()?;
                let mut data = self.inner.lock().await;
                if !data.registry.terminal(&owner, &terminal_state)? {
                    return Err("DUPLICATE_TERMINAL".into());
                }
                if let Some(started) = data
                    .cancel_started
                    .remove(&(owner.session_id.clone(), owner.generation_id.clone()))
                {
                    if terminal_state == "cancelled" {
                        data.metrics.cancel_to_terminal_ms = Some(elapsed_ms(started));
                    }
                }
                data.request_started
                    .remove(&(owner.session_id.clone(), owner.generation_id.clone()));
                let cancel_latency = data.metrics.cancel_to_terminal_ms;
                drop(data);
                eprintln!(
                    "[aurora-v4] event=chat_terminal request={} generation={} state={} cancel_latency_ms={}",
                    short_id(&owner.request_id),
                    short_id(&owner.generation_id),
                    terminal_state,
                    cancel_latency
                        .map(|value| format!("{value:.1}"))
                        .unwrap_or_else(|| "none".into())
                );
                self.emit(FrontendEvent::ChatTerminal {
                    request_id: owner.request_id,
                    generation_id: owner.generation_id,
                    terminal_state,
                    error_code,
                    diagnostics,
                });
                self.emit_state().await;
            }
            "chat.cancel.ack" => {
                let generation_id = require_string(&value, "generation_id", None)?.to_owned();
                let outcome = object(&value, "payload")?
                    .get("outcome")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "INVALID_CANCEL_ACK".to_string())?
                    .to_owned();
                self.emit(FrontendEvent::CancelAck {
                    generation_id,
                    outcome,
                });
            }
            "error" | "backend.warning" => {
                let code = object(&value, "payload")?
                    .get("code")
                    .and_then(Value::as_str)
                    .unwrap_or("BACKEND_WARNING")
                    .to_owned();
                if message_type == "error" && crate::settings::ERRORS.contains(&code.as_str()) {
                    let request_id = require_string(&value, "request_id", None)?.to_owned();
                    self.emit(FrontendEvent::SettingsError { request_id, code });
                } else if message_type == "error"
                    && matches!(code.as_str(), "NOT_FOUND" | "INVALID_CONVERSATION" | "PERSISTENCE_FAILED")
                    && value.get("request_id").is_some()
                    && value.get("session_id").is_none()
                {
                    let request_id = require_string(&value, "request_id", None)?.to_owned();
                    self.emit(FrontendEvent::ConversationError { request_id, code });
                } else {
                    self.emit(FrontendEvent::ProtocolWarning { code });
                }
            }
            _ => {}
        }
        Ok(())
    }

    async fn connection_lost(&self, epoch: u64) {
        let terminal_events = {
            let mut data = self.inner.lock().await;
            if epoch != data.epoch
                || matches!(
                    data.state,
                    BackendState::Disconnected | BackendState::Stopping | BackendState::Stopped
                )
            {
                return;
            }
            if let Some(started) = data.crash_requested_at.take() {
                data.metrics.crash_to_disconnected_ms = Some(elapsed_ms(started));
            }
            data.state = BackendState::Disconnected;
            data.info.chat_enabled = false;
            data.voice = None;
            data.writer = None;
            if let Some(audio) = &data.audio { audio.halt(); }
            data.sidecar_instance_id = None;
            data.request_started.clear();
            data.cancel_started.clear();
            data.registry.backend_lost()
        };
        for owner in terminal_events {
            self.emit(FrontendEvent::ChatTerminal {
                request_id: owner.request_id,
                generation_id: owner.generation_id,
                terminal_state: "backend_lost".into(),
                error_code: Some("BACKEND_LOST".into()),
                diagnostics: None,
            });
        }
        self.emit_state().await;
        eprintln!("[aurora-v4] event=sidecar_disconnected");
    }

    async fn emit_state(&self) {
        let snapshot = self.snapshot().await;
        self.emit(FrontendEvent::BackendState {
            state: snapshot.state,
            metrics: snapshot.metrics,
            info: snapshot.info,
        });
    }

    fn emit(&self, event: FrontendEvent) {
        if let Some(character) = &self.live2d { character.observe(&event); }
        let channel = self
            .frontend
            .lock()
            .expect("frontend channel lock poisoned")
            .clone();
        if let Some(channel) = channel {
            let _ = channel.send(event);
        }
    }
}

fn owner_from(value: &Value) -> Result<RequestOwner, String> {
    Ok(RequestOwner {
        request_id: require_string(value, "request_id", None)?.to_owned(),
        session_id: require_string(value, "session_id", None)?.to_owned(),
        generation_id: require_string(value, "generation_id", None)?.to_owned(),
    })
}

async fn drain_stderr(stderr: tokio::process::ChildStderr) {
    let mut lines = BufReader::new(stderr).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        eprintln!("[aurora-v4-sidecar] {line}");
    }
}

fn find_sidecar_launch(mode: &str) -> Result<SidecarLaunch, String> {
    if !matches!(mode, "mock" | "production") {
        return Err("INVALID_BACKEND_MODE".into());
    }
    let sidecar_root = if let Some(path) = std::env::var_os("AURORA_V4_SIDECAR_DIR") {
        PathBuf::from(path)
    } else {
        let current = std::env::current_dir().map_err(|error| error.to_string())?;
        let executable = std::env::current_exe().map_err(|error| error.to_string())?;
        [
            current.as_path(),
            executable.parent().unwrap_or(executable.as_path()),
        ]
        .into_iter()
        .flat_map(|root| root.ancestors())
        .flat_map(|ancestor| {
            [
                ancestor.join("sidecar"),
                ancestor.join("prototype").join("aurora-v4").join("sidecar"),
            ]
        })
        .find(|candidate| candidate.join("mock_sidecar").join("server.py").is_file())
        .ok_or_else(|| "Aurora v4 mock sidecar directory was not found".to_string())?
    };
    let sidecar_root = sidecar_root
        .canonicalize()
        .map_err(|_| "SIDECAR_DIRECTORY_MISSING")?;
    let repo_root = sidecar_root
        .ancestors()
        .find(|p| {
            p.join("modules/app_paths.py").is_file()
                && p.join("config/default_settings.json").is_file()
        })
        .ok_or("AURORA_SOURCE_ROOT_NOT_FOUND")?;
    let script = sidecar_root
        .join(format!("{mode}_sidecar"))
        .join("server.py");
    let venv = if mode == "production" {
        repo_root.join(".venv")
    } else {
        sidecar_root.join(".venv")
    };
    // Launch the actual interpreter, not Windows' venv redirector: the process
    // assigned to the Job Object must be the process publishing bootstrap PID.
    let (python, packages) = if let Some(explicit) = std::env::var_os("AURORA_V4_PYTHON") {
        (PathBuf::from(explicit), None)
    } else if cfg!(windows) {
        let config =
            std::fs::read_to_string(venv.join("pyvenv.cfg")).map_err(|_| "PROJECT_VENV_MISSING")?;
        let home = config
            .lines()
            .find_map(|line| line.strip_prefix("home = "))
            .ok_or("INVALID_PYVENV_CONFIG")?;
        (
            PathBuf::from(home).join("python.exe"),
            Some(venv.join("Lib/site-packages")),
        )
    } else {
        (venv.join("bin/python"), None)
    };
    if !python.is_absolute() {
        return Err("AURORA_V4_PYTHON_MUST_BE_ABSOLUTE".into());
    }
    let mut paths = vec![repo_root.to_owned(), sidecar_root.clone()];
    if let Some(packages) = packages {
        if !packages.is_dir() {
            return Err("PROJECT_VENV_PACKAGES_MISSING".into());
        }
        paths.push(packages);
    }
    let python_path = std::env::join_paths(paths).map_err(|_| "INVALID_PYTHON_PATH")?;
    for required in [&script, &python] {
        if !required.exists() {
            return Err(format!(
                "Required sidecar path is missing: {}",
                required.display()
            ));
        }
    }
    Ok(SidecarLaunch {
        python,
        script,
        working_directory: sidecar_root,
        python_path,
    })
}

fn elapsed_ms(started: Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1000.0
}

fn unix_ms() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
        * 1000.0
}

fn short_id(value: &str) -> &str {
    value
        .rsplit('-')
        .next()
        .unwrap_or(value)
        .get(..8)
        .unwrap_or(value)
}

#[cfg(windows)]
#[derive(Debug)]
pub(crate) struct JobGuard(windows_sys::Win32::Foundation::HANDLE);

#[cfg(windows)]
unsafe impl Send for JobGuard {}
#[cfg(windows)]
unsafe impl Sync for JobGuard {}

#[cfg(windows)]
impl JobGuard {
    pub(crate) fn assign(pid: u32) -> Result<Self, String> {
        use std::{mem::size_of, ptr::null};
        use windows_sys::Win32::{
            Foundation::{CloseHandle, HANDLE},
            System::{
                JobObjects::{
                    AssignProcessToJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
                    SetInformationJobObject,
                },
                Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE},
            },
        };

        unsafe {
            let job: HANDLE =
                windows_sys::Win32::System::JobObjects::CreateJobObjectW(null(), null());
            if job.is_null() {
                return Err("CreateJobObjectW failed".into());
            }
            let mut information: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &information as *const _ as *const _,
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            ) == 0
            {
                CloseHandle(job);
                return Err("SetInformationJobObject failed".into());
            }
            let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
            if process.is_null() {
                CloseHandle(job);
                return Err("OpenProcess for sidecar failed".into());
            }
            let assigned = AssignProcessToJobObject(job, process);
            CloseHandle(process);
            if assigned == 0 {
                CloseHandle(job);
                return Err("AssignProcessToJobObject failed".into());
            }
            Ok(Self(job))
        }
    }
}

#[cfg(windows)]
impl Drop for JobGuard {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0);
        }
    }
}

#[cfg(not(windows))]
#[derive(Debug)]
pub(crate) struct JobGuard;

#[cfg(not(windows))]
impl JobGuard {
    pub(crate) fn assign(_pid: u32) -> Result<Self, String> {
        Ok(Self)
    }
}

#[cfg(test)]
mod tests {
    #[tokio::test]
    async fn voice_gateway_rejects_stale_revision_epoch_and_private_fields() {
        let manager = BackendManager::with_mode("production".into());
        let event = serde_json::json!({"protocol":"aurora-ipc", "version":1,
            "type":"voice.changed", "payload":{"revision":3,"state":"speaking",
            "enabled":true,"provider":"edge_tts","generation_id":"g2","error_code":""}});
        manager.handle_wire(0, &event.to_string()).await.unwrap();
        assert_eq!(manager.snapshot().await.voice.unwrap().generation_id.as_deref(), Some("g2"));
        let mut stale = event.clone();
        stale["payload"]["revision"] = serde_json::json!(2);
        stale["payload"]["generation_id"] = serde_json::json!("g1");
        manager.handle_wire(0, &stale.to_string()).await.unwrap();
        assert_eq!(manager.snapshot().await.voice.unwrap().revision, 3);
        assert!(manager.handle_wire(1, &event.to_string()).await.is_err());
        stale["payload"]["endpoint"] = serde_json::json!("private");
        assert!(manager.handle_wire(0, &stale.to_string()).await.is_err());
        manager.inner.lock().await.state = BackendState::Ready;
        manager.shutdown().await.unwrap();
        assert!(manager.snapshot().await.voice.is_none());
    }
    use super::*;
    use serde_json::json;

    async fn wait_for(
        manager: &BackendManager,
        predicate: impl Fn(&BackendSnapshot) -> bool,
    ) -> BackendSnapshot {
        timeout(Duration::from_secs(5), async {
            loop {
                let snapshot = manager.snapshot().await;
                if predicate(&snapshot) {
                    return snapshot;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("backend state transition timed out")
    }

    #[test]
    fn sidecar_discovery_uses_relative_prototype_paths() {
        let launch = find_sidecar_launch("mock").unwrap();
        assert!(
            launch
                .script
                .ends_with(std::path::Path::new("mock_sidecar/server.py"))
        );
        assert!(std::env::split_paths(&launch.python_path).count() >= 2);
        assert!(find_sidecar_launch("unknown").is_err());
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn settings_route_offline_persist_restart_and_backend_lost() {
        let directory = std::env::temp_dir().join(format!("aurora-settings-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(directory.join("config")).unwrap();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let file = directory.join("config/settings.json");
        std::fs::write(&file, json!({"ollama":{"host":format!("http://{}",listener.local_addr().unwrap())}}).to_string()).unwrap();
        let mut manager = BackendManager::with_mode("production".into());
        manager.test_data_directory = Some(directory.clone());
        assert!(manager.settings_get().await.is_err());
        manager.start(false).await.unwrap();
        wait_for(&manager, |s| s.info.diagnostics.is_some()).await;
        manager.settings_get().await.unwrap();
        manager.settings_update(0,json!({"ollama.thinking_mode":"on"})).await.unwrap();
        timeout(Duration::from_secs(4), async {
            loop {
                let raw: Value = serde_json::from_str(&std::fs::read_to_string(&file).unwrap()).unwrap();
                if raw["ollama"]["thinking_mode"] == "on" { break; }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        }).await.unwrap();
        let old_epoch = manager.inner.lock().await.epoch;
        manager.crash().await.unwrap();
        wait_for(&manager, |s| s.state == BackendState::Disconnected).await;
        assert!(manager.settings_update(1,json!({})).await.is_err());
        manager.restart().await.unwrap();
        wait_for(&manager, |s| s.info.diagnostics.as_ref().is_some_and(|d| d.ollama_think_mode == "on")).await;
        let examples: Vec<Value> = serde_json::from_str(include_str!("../../../contracts/ipc-v1.settings.examples.json")).unwrap();
        assert_eq!(manager.handle_wire(old_epoch,&examples[4].to_string()).await.unwrap_err(),"STALE_CONNECTION");
        manager.shutdown().await.unwrap();
        std::fs::remove_file(file).unwrap();
        std::fs::remove_dir(directory.join("config")).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }

    // Fully offline fixture; this test never consults the user's settings/Ollama.
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn production_gateway_degraded_crash_restart_health_and_ownership() {
        let directory = std::env::temp_dir().join(format!("aurora-v4-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(directory.join("config")).unwrap();
        // Bound listener without an HTTP handler: never reaches a live Ollama.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let host = format!("http://{}", listener.local_addr().unwrap());
        let settings = serde_json::json!({"ollama":{"host":host}, "chat_model":"fixture", "chat_model_mode":"manual"}).to_string();
        std::fs::write(directory.join("config/settings.json"), &settings).unwrap();
        let mut manager = BackendManager::with_mode("production".into());
        manager.test_data_directory = Some(directory.clone());
        manager.start(false).await.unwrap();
        let initial = wait_for(&manager, |s| s.info.diagnostics.is_some()).await;
        assert_eq!(initial.state, BackendState::Degraded);
        assert!(initial.info.chat_enabled);
        assert_eq!(
            initial.info.diagnostics.as_ref().unwrap().ollama.error_code,
            "OLLAMA_UNAVAILABLE"
        );
        assert!(
            manager
                .chat_start("must never generate".into())
                .await
                .is_ok()
        );
        let (old_epoch, old_instance, old_identity) = {
            let data = manager.inner.lock().await;
            (
                data.epoch,
                data.sidecar_instance_id.clone(),
                data.launch_identity.clone().unwrap(),
            )
        };
        manager.crash().await.unwrap();
        wait_for(&manager, |s| s.state == BackendState::Disconnected).await;
        manager.restart().await.unwrap();
        wait_for(&manager, |s| s.info.diagnostics.is_some()).await;
        let next_identity = manager.inner.lock().await.launch_identity.clone().unwrap();
        assert_ne!(old_identity.0, next_identity.0);
        assert_ne!(old_identity.1, next_identity.1);
        assert_ne!(old_identity.2, next_identity.2);
        assert_ne!(old_instance, manager.inner.lock().await.sidecar_instance_id);
        let stale = serde_json::json!({"protocol":PROTOCOL,"version":VERSION,"type":"health.response","request_id":"old",
            "payload":{"state":"READY","sidecar_instance_id":old_instance}});
        assert_eq!(
            manager
                .handle_wire(old_epoch, &stale.to_string())
                .await
                .unwrap_err(),
            "STALE_CONNECTION"
        );
        assert_eq!(manager.snapshot().await.state, BackendState::Degraded);
        manager.shutdown().await.unwrap();
        assert_eq!(manager.snapshot().await.state, BackendState::Stopped);
        assert!(std::net::TcpStream::connect(("127.0.0.1", next_identity.1)).is_err());
        assert_eq!(
            std::fs::read_to_string(directory.join("config/settings.json")).unwrap(),
            settings
        );
        std::fs::remove_file(directory.join("config/settings.json")).unwrap();
        std::fs::remove_dir(directory.join("config")).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }

    #[tokio::test]
    async fn invalid_backend_mode_is_safe_startup_failure() {
        let manager = BackendManager::with_mode("invalid".into());
        let error = manager.start(false).await.unwrap_err();
        assert_eq!(
            error,
            "Backend startup failed; see sidecar stderr diagnostics."
        );
        assert_eq!(manager.snapshot().await.state, BackendState::Disconnected);
        assert_eq!(
            manager.snapshot().await.info.error_code.as_deref(),
            Some("BACKEND_START_FAILED")
        );
        manager.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn python_start_failure_cleans_already_owned_model_runtime() {
        let supervisor=crate::local_model::LocalModelSupervisor::default();
        let config=crate::local_model::ModelConfig {executable:std::env::current_exe().unwrap(),
            model:std::path::PathBuf::from("fixture.gguf"),context:4096};
        let handoff=supervisor.start_config(Ok(config)).await.unwrap();
        let address=handoff.endpoint.strip_prefix("http://").unwrap();
        assert!(std::net::TcpStream::connect(address).is_ok());
        let mut manager=BackendManager::with_mode("invalid".into());
        manager.local_model=Some(supervisor);
        assert!(manager.start(false).await.is_err());
        assert!(std::net::TcpStream::connect(address).is_err());
        manager.shutdown().await.unwrap();
    }

    #[tokio::test]
    async fn shutdown_before_local_start_invalidates_owner_permanently() {
        let mut manager=BackendManager::with_mode("production".into());
        manager.local_model=Some(Default::default());
        let (epoch,owner)={let mut data=manager.inner.lock().await;
            data.state=BackendState::Starting;data.epoch+=1;
            (data.epoch,data.startup_cancel.clone())};
        manager.shutdown().await.unwrap();
        assert!(owner.load(Ordering::SeqCst));
        assert_eq!(manager.start_once(epoch,owner).await.unwrap_err(),"STALE_STARTUP");
        assert_eq!(manager.snapshot().await.state,BackendState::Stopped);
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn shutdown_during_startup_cannot_resurrect_an_old_epoch() {
        let manager = BackendManager::with_mode("mock".into());
        let starter = manager.clone();
        let task = tokio::spawn(async move { starter.start(false).await });
        wait_for(&manager, |s| s.state == BackendState::Starting).await;
        manager.shutdown().await.unwrap();
        assert!(task.await.unwrap().is_err());
        assert_eq!(manager.snapshot().await.state, BackendState::Stopped);
        assert!(manager.inner.lock().await.child.is_none());
        manager.start(false).await.unwrap();
        assert_eq!(manager.snapshot().await.state, BackendState::Ready);
        manager.shutdown().await.unwrap();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    #[ignore = "opt-in read-only real settings/Ollama smoke; no generation"]
    async fn production_real_read_only_smoke() {
        let manager = BackendManager::with_mode("production".into());
        manager.start(false).await.unwrap();
        let initial = wait_for(&manager, |s| s.info.diagnostics.is_some()).await;
        eprintln!(
            "PRODUCTION_INITIAL={}",
            serde_json::to_string(&initial).unwrap()
        );
        let identity = manager.inner.lock().await.launch_identity.clone().unwrap();
        eprintln!("PRODUCTION_PID={}", identity.0);
        assert!(initial.info.chat_enabled);
        manager.crash().await.unwrap();
        wait_for(&manager, |s| s.state == BackendState::Disconnected).await;
        manager.restart().await.unwrap();
        let restarted = wait_for(&manager, |s| s.info.diagnostics.is_some()).await;
        eprintln!(
            "PRODUCTION_RESTART={}",
            serde_json::to_string(&restarted).unwrap()
        );
        let next = manager.inner.lock().await.launch_identity.clone().unwrap();
        assert_ne!(identity.0, next.0);
        assert_ne!(identity.1, next.1);
        assert_ne!(identity.2, next.2);
        manager.shutdown().await.unwrap();
        assert!(std::net::TcpStream::connect(("127.0.0.1", next.1)).is_err());
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn real_gateway_stream_cancel_crash_restart_and_shutdown() {
        let manager = BackendManager::with_mode("mock".into());
        manager.start(false).await.unwrap();
        let initial = manager.snapshot().await;
        assert_eq!(initial.state, BackendState::Ready);

        let first = manager
            .chat_start("mock integration request".into())
            .await
            .unwrap();
        let first_delta = wait_for(&manager, |snapshot| {
            snapshot.metrics.command_to_first_delta_ms.is_some()
        })
        .await;
        assert!(
            manager
                .chat_cancel(CancelTarget {
                    request_id: first.request_id,
                    session_id: first.session_id,
                    generation_id: first.generation_id,
                })
                .await
                .unwrap()
        );
        let cancelled = wait_for(&manager, |snapshot| {
            snapshot.metrics.cancel_to_terminal_ms.is_some()
        })
        .await;

        manager
            .chat_start("mock crash isolation request".into())
            .await
            .unwrap();
        manager.crash().await.unwrap();
        let disconnected = wait_for(&manager, |snapshot| {
            snapshot.state == BackendState::Disconnected
        })
        .await;
        assert!(disconnected.metrics.crash_to_disconnected_ms.is_some());

        manager.restart().await.unwrap();
        let restarted = manager.snapshot().await;
        assert_eq!(restarted.state, BackendState::Ready);
        assert!(restarted.metrics.restart_to_ready_ms.is_some());

        eprintln!(
            "[aurora-v4-test] spawn_to_bootstrap_ms={:.1} bootstrap_to_ready_ms={:.1} command_to_first_delta_ms={:.1} cancel_to_terminal_ms={:.1} crash_to_disconnected_ms={:.1} restart_to_ready_ms={:.1}",
            initial.metrics.spawn_to_bootstrap_ms.unwrap(),
            initial.metrics.bootstrap_to_ready_ms.unwrap(),
            first_delta.metrics.command_to_first_delta_ms.unwrap(),
            cancelled.metrics.cancel_to_terminal_ms.unwrap(),
            disconnected.metrics.crash_to_disconnected_ms.unwrap(),
            restarted.metrics.restart_to_ready_ms.unwrap(),
        );

        manager.shutdown().await.unwrap();
        assert_eq!(manager.snapshot().await.state, BackendState::Stopped);
    }
}
