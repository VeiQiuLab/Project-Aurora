//! Complete-artifact audio execution. No TTS, frontend paths, or PCM IPC.
use std::{fs::File, io::{Cursor, Read}, path::{Path, PathBuf},
    sync::{Arc, Condvar, Mutex, atomic::{AtomicBool, Ordering}},
    thread::{self, JoinHandle}, time::{Duration, Instant}};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message;
use rodio::{Decoder, OutputStream, OutputStreamBuilder, Sink};

pub const MAX_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Identity { pub generation_id: String, pub revision: u64 }

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Play { pub generation_id: String, pub revision: u64, pub file: String }
impl Play { fn identity(&self) -> Identity { Identity { generation_id: self.generation_id.clone(), revision: self.revision } } }

pub fn validate_identity(id: &Identity) -> Result<(), String> {
    if id.generation_id.is_empty() || id.generation_id.len() > 128 || id.revision > 9_007_199_254_740_991 {
        return Err("INVALID_AUDIO_IDENTITY".into());
    }
    Ok(())
}
pub fn validate_file(file: &str) -> Result<(), String> {
    let parts: Vec<_> = file.split('/').collect();
    let simple = |part: &str| !part.is_empty() && part.bytes().all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b));
    if file.len() > 256 || parts.len() != 2 || !simple(parts[0])
        || !parts[1].strip_suffix(".wav").or_else(|| parts[1].strip_suffix(".mp3")).is_some_and(simple) {
        return Err("INVALID_AUDIO_FILE".into());
    }
    Ok(())
}
pub fn validate_wire(value: &Value) -> Result<(), String> {
    let kind = value["type"].as_str().unwrap_or("");
    let keys = ["protocol", "version", "type", "payload"];
    if value.as_object().is_none_or(|o| o.len()!=4 || o.keys().any(|k| !keys.contains(&k.as_str()))) {
        return Err("INVALID_AUDIO_ENVELOPE".into());
    }
    match kind {
        "audio.play.request" => {
            let p: Play = serde_json::from_value(value["payload"].clone()).map_err(|_| "INVALID_AUDIO_PLAY")?;
            validate_identity(&p.identity())?; validate_file(&p.file)
        }
        "audio.stop.request" => {
            let id: Identity = serde_json::from_value(value["payload"].clone()).map_err(|_| "INVALID_AUDIO_STOP")?;
            validate_identity(&id)
        }
        _ => Err("INVALID_AUDIO_TYPE".into())
    }
}

fn read_artifact(root: &Path, relative: &str) -> Result<Vec<u8>, &'static str> {
    validate_file(relative).map_err(|_| "INVALID_AUDIO_FILE")?;
    let root = root.canonicalize().map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
    let path = root.join(relative);
    // Reject links/junctions at both levels; canonical containment is also required.
    for entry in [path.parent().ok_or("INVALID_AUDIO_FILE")?, path.as_path()] {
        let meta = std::fs::symlink_metadata(entry).map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
        if meta.file_type().is_symlink() { return Err("INVALID_AUDIO_FILE"); }
        #[cfg(windows)] {
            use std::os::windows::fs::MetadataExt;
            if meta.file_attributes() & 0x400 != 0 { return Err("INVALID_AUDIO_FILE"); }
        }
    }
    let resolved = path.canonicalize().map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
    if !resolved.starts_with(&root) { return Err("INVALID_AUDIO_FILE"); }
    let file = File::open(resolved).map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
    let metadata = file.metadata().map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
    if !metadata.is_file() || metadata.len()==0 || metadata.len()>MAX_BYTES { return Err("AUDIO_SIZE_LIMIT"); }
    let mut bytes = Vec::new();
    file.take(MAX_BYTES+1).read_to_end(&mut bytes).map_err(|_| "AUDIO_FILE_UNAVAILABLE")?;
    if bytes.len() as u64 > MAX_BYTES { return Err("AUDIO_SIZE_LIMIT"); }
    Ok(bytes) // file handle is closed before decoder/device ownership begins
}

trait Output {
    fn start(&mut self);
    fn finished(&self) -> bool;
    fn failed(&self) -> bool;
    fn stop(&mut self);
}
struct DeviceOutput { sink: Sink, _stream: OutputStream, failed: Arc<AtomicBool> }
impl Output for DeviceOutput {
    fn start(&mut self) { self.sink.play(); }
    fn finished(&self) -> bool { self.sink.empty() }
    fn failed(&self) -> bool { self.failed.load(Ordering::SeqCst) }
    fn stop(&mut self) { self.sink.stop(); }
}
type Factory = Box<dyn Fn(Vec<u8>) -> Result<Box<dyn Output>, &'static str> + Send>;
fn device(bytes: Vec<u8>) -> Result<Box<dyn Output>, &'static str> {
    let decoder = Decoder::try_from(Cursor::new(bytes)).map_err(|_| "AUDIO_DECODE_FAILED")?;
    let failed = Arc::new(AtomicBool::new(false));
    let errors = failed.clone();
    // Default device only; do not silently switch to another physical device.
    let mut stream = OutputStreamBuilder::from_default_device().map_err(|_| "AUDIO_DEVICE_UNAVAILABLE")?
        .with_error_callback(move |_| { errors.store(true, Ordering::SeqCst); })
        .open_stream().map_err(|_| "AUDIO_DEVICE_UNAVAILABLE")?;
    stream.log_on_drop(false);
    let sink = Sink::connect_new(stream.mixer());
    sink.pause(); sink.append(decoder);
    Ok(Box::new(DeviceOutput { sink, _stream: stream, failed }))
}

#[derive(Default)]
struct State {
    generation: Option<String>,
    closed: bool, allowed: Option<Identity>, consumed: Option<Identity>,
    pending: Option<(Play, Arc<AtomicBool>)>, cancel: Option<Arc<AtomicBool>>,
}
type Shared = Arc<(Mutex<State>, Condvar)>;
type Notify = Arc<dyn Fn(&Identity, &str, &str) -> bool + Send + Sync>;

pub struct AudioOwner {
    _root: tempfile::TempDir, shared: Shared, worker: Mutex<Option<JoinHandle<()>>>, notify: Notify,
}
impl std::fmt::Debug for AudioOwner {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("AudioOwner(private)") }
}
impl AudioOwner {
    pub fn new(root: tempfile::TempDir, writer: mpsc::Sender<Message>) -> Result<Self, String> {
        let notify: Notify = Arc::new(move |id, state, error| {
            // Bounded channel; never block resource release on an unresponsive peer.
            writer.try_send(Message::Text(json!({"protocol":"aurora-ipc","version":1,
                "type":"audio.event","payload":{"generation_id":id.generation_id,
                "revision":id.revision,"state":state,"error_code":error}}).to_string().into())).is_ok()
        });
        Self::with_factory(root, notify, Box::new(device))
    }
    fn with_factory(root: tempfile::TempDir, notify: Notify, factory: Factory) -> Result<Self, String> {
        let shared = Arc::new((Mutex::new(State::default()), Condvar::new()));
        let (state, emit, path) = (shared.clone(), notify.clone(), root.path().to_path_buf());
        let worker = thread::Builder::new().name("aurora-rust-audio".into())
            .spawn(move || run_worker(state, path, emit, factory)).map_err(|_| "AUDIO_WORKER_UNAVAILABLE")?;
        Ok(Self { _root: root, shared, worker: Mutex::new(Some(worker)), notify })
    }
    pub fn voice(&self, snapshot: &crate::voice::Snapshot) {
        let mut state = self.shared.0.lock().unwrap_or_else(|e| e.into_inner());
        if state.closed { return; }
        if state.generation.is_some() && state.generation != snapshot.generation_id { return; }
        if snapshot.state == "preparing" {
            let allowed = snapshot.generation_id.clone().map(|generation_id| Identity {generation_id, revision:snapshot.revision});
            if state.allowed != allowed {
                if let Some(cancel) = state.cancel.take() { cancel.store(true, Ordering::SeqCst); }
                state.allowed = allowed;
            }
        } else if snapshot.state != "speaking" {
            state.allowed = None;
            if let Some(cancel) = state.cancel.take() { cancel.store(true, Ordering::SeqCst); }
        }
        self.shared.1.notify_all();
    }
    pub fn play(&self, play: Play) {
        let id = play.identity();
        let mut state = self.shared.0.lock().unwrap_or_else(|e| e.into_inner());
        if state.consumed.as_ref() == Some(&id) { return; } // exactly once, even after terminal
        if state.closed || state.allowed.as_ref() != Some(&id) {
            drop(state); (self.notify)(&id, "stopped", ""); return;
        }
        if state.pending.is_some() {
            drop(state); (self.notify)(&id, "failed", "AUDIO_BUSY"); return;
        }
        let cancel = Arc::new(AtomicBool::new(false));
        state.cancel = Some(cancel.clone()); state.consumed = Some(id);
        state.pending = Some((play, cancel)); self.shared.1.notify_all();
    }
    pub fn stop(&self, id: &Identity) {
        let mut state = self.shared.0.lock().unwrap_or_else(|e| e.into_inner());
        if state.allowed.as_ref() == Some(id) {
            state.allowed = None;
            if let Some(cancel) = &state.cancel { cancel.store(true, Ordering::SeqCst); }
        }
        self.shared.1.notify_all();
    }
    pub fn stop_generation(&self, generation: &str) {
        let id = self.shared.0.lock().unwrap_or_else(|e| e.into_inner()).allowed.clone();
        if let Some(id) = id.filter(|id| id.generation_id == generation) { self.stop(&id); }
    }
    pub fn new_generation(&self, generation: &str) {
        let mut state = self.shared.0.lock().unwrap_or_else(|e| e.into_inner());
        state.generation = Some(generation.to_owned()); state.allowed = None;
        if let Some(cancel) = state.cancel.take() { cancel.store(true, Ordering::SeqCst); }
        self.shared.1.notify_all();
    }
    pub fn halt(&self) {
        let mut state = self.shared.0.lock().unwrap_or_else(|e| e.into_inner());
        state.closed = true; state.allowed = None;
        if let Some(cancel) = &state.cancel { cancel.store(true, Ordering::SeqCst); }
        self.shared.1.notify_all();
    }
    pub fn join(&self) {
        self.halt();
        if let Some(worker) = self.worker.lock().unwrap_or_else(|e| e.into_inner()).take() { let _ = worker.join(); }
    }
}
impl Drop for AudioOwner { fn drop(&mut self) { self.join(); } }

fn run_worker(shared: Shared, root: PathBuf, notify: Notify, factory: Factory) {
    eprintln!("[aurora-v4] event=rust_audio_worker_started");
    loop {
        let next = {
            let mut state = shared.0.lock().unwrap_or_else(|e| e.into_inner());
            while state.pending.is_none() && !state.closed {
                state = shared.1.wait(state).unwrap_or_else(|e| e.into_inner());
            }
            if state.pending.is_none() { eprintln!("[aurora-v4] event=rust_audio_worker_exited"); return; }
            state.pending.take()
        };
        let Some((play, cancel)) = next else { continue; };
        let id = play.identity();
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            if cancel.load(Ordering::SeqCst) { return Ok("stopped"); }
            let bytes = read_artifact(&root, &play.file)?;
            if cancel.load(Ordering::SeqCst) { return Ok("stopped"); }
            let mut output = factory(bytes)?; // paused, no audio before ownership recheck
            {
                let state = shared.0.lock().unwrap_or_else(|e| e.into_inner());
                if state.closed || state.allowed.as_ref()!=Some(&id) || cancel.load(Ordering::SeqCst) {
                    output.stop(); return Ok("stopped");
                }
                output.start();
            }
            eprintln!("[aurora-v4] event=rust_audio_started backend=rodio");
            if !notify(&id,"started","") { output.stop(); return Ok("stopped"); }
            let deadline = Instant::now()+Duration::from_secs(600);
            let mut eof = None;
            let result = loop {
                if cancel.load(Ordering::SeqCst) { break Ok("stopped"); }
                if output.failed() { break Err("AUDIO_DEVICE_FAILED"); }
                // Queue exhaustion means samples were submitted, not physically
                // drained. Keep the device alive briefly for its final buffer.
                // Explicit stop/device failure never waits for this tail grace.
                if output.finished() {
                    if eof.get_or_insert_with(Instant::now).elapsed() >= Duration::from_millis(100) { break Ok("completed"); }
                }
                if Instant::now() >= deadline { break Err("AUDIO_TIMEOUT"); }
                thread::sleep(Duration::from_millis(5));
            };
            output.stop(); drop(output); // device/decoder released before terminal
            result
        }));
        let (state,error) = if cancel.load(Ordering::SeqCst) { ("stopped","") } else {
            match outcome { Ok(Ok(state)) => (state,""), Ok(Err(error)) => ("failed",error), Err(_) => ("failed","AUDIO_INTERNAL_ERROR") }
        };
        eprintln!("[aurora-v4] event=rust_audio_terminal state={state} error_code={error}");
        notify(&id,state,error);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    type Events = Arc<Mutex<Vec<(Identity, String, String)>>>;
    struct FakeOutput { done: Arc<AtomicBool>, fail: Arc<AtomicBool>, started: Arc<AtomicUsize>, dropped: Arc<AtomicUsize> }
    impl Output for FakeOutput {
        fn start(&mut self) { self.started.fetch_add(1, Ordering::SeqCst); }
        fn finished(&self) -> bool { self.done.load(Ordering::SeqCst) }
        fn failed(&self) -> bool { self.fail.load(Ordering::SeqCst) }
        fn stop(&mut self) { self.done.store(true, Ordering::SeqCst); }
    }
    impl Drop for FakeOutput { fn drop(&mut self) { self.dropped.fetch_add(1, Ordering::SeqCst); } }
    fn wait(check: impl Fn() -> bool) {
        let deadline=Instant::now()+Duration::from_secs(3);
        while !check() { assert!(Instant::now()<deadline); thread::sleep(Duration::from_millis(2)); }
    }
    fn voice(g: &str, revision:u64) -> crate::voice::Snapshot {
        crate::voice::Snapshot { generation_id:Some(g.into()),revision,state:"preparing".into(),
            provider:"edge_tts".into(),enabled:true,error_code:String::new() }
    }
    fn play(g:&str, revision:u64) -> Play { Play {generation_id:g.into(),revision,file:"run/audio.wav".into()} }
    fn root() -> tempfile::TempDir {
        let root=tempfile::tempdir().unwrap();std::fs::create_dir(root.path().join("run")).unwrap();
        std::fs::write(root.path().join("run/audio.wav"),b"fixture").unwrap();root
    }
    fn notifier(events: &Events) -> Notify {
        let events=events.clone();Arc::new(move |id,state,error| {events.lock().unwrap().push((id.clone(),state.into(),error.into()));true})
    }
    #[test]
    fn path_boundary_missing_large_and_decoder_errors() {
        let root=root();
        for file in ["../secret.wav","C:/secret.wav","run/../secret.wav","run/a:stream.wav","run\\audio.wav","run/a.b.wav"] { assert!(read_artifact(root.path(),file).is_err()); }
        assert_eq!(read_artifact(root.path(),"run/missing.wav").unwrap_err(),"AUDIO_FILE_UNAVAILABLE");
        assert_eq!(device(b"not audio".to_vec()).err(),Some("AUDIO_DECODE_FAILED"));
        let f=File::create(root.path().join("run/large.wav")).unwrap(); f.set_len(MAX_BYTES+1).unwrap();
        assert_eq!(read_artifact(root.path(),"run/large.wav").unwrap_err(),"AUDIO_SIZE_LIMIT");
    }
    #[test]
    fn duplicate_stop_stale_and_resources_across_many_turns() {
        let events:Events=Default::default();let started=Arc::new(AtomicUsize::new(0));let dropped=Arc::new(AtomicUsize::new(0));
        let (s,d)=(started.clone(),dropped.clone());
        let owner=AudioOwner::with_factory(root(),notifier(&events),Box::new(move |_|Ok(Box::new(FakeOutput {
            done:Arc::new(AtomicBool::new(false)),fail:Arc::new(AtomicBool::new(false)),started:s.clone(),dropped:d.clone()})))).unwrap();
        let path=owner._root.path().to_path_buf();
        for n in 1..=40 {
            let g=format!("g{n}");owner.new_generation(&g);owner.voice(&voice(&g,n));
            owner.play(play(&g,n));owner.play(play(&g,n));
            wait(||started.load(Ordering::SeqCst)==n as usize);
            owner.stop(&play("old",0).identity());
            assert_eq!(dropped.load(Ordering::SeqCst),n as usize-1);
            owner.stop(&play(&g,n).identity());owner.stop(&play(&g,n).identity());
            wait(||events.lock().unwrap().iter().filter(|(_,s,_)|s=="stopped").count()==n as usize);
            assert_eq!(dropped.load(Ordering::SeqCst),n as usize); // before terminal
            owner.play(play(&g,n)); // completed duplicate must not resurrect
        }
        owner.join();owner.join();assert_eq!(started.load(Ordering::SeqCst),40);
        assert!(owner.worker.lock().unwrap().is_none());drop(owner);assert!(!path.exists());
    }
    #[test]
    fn completion_and_device_loss_are_distinct_and_release_before_event() {
        for fail in [false,true] {
            let events:Events=Default::default();let dropped=Arc::new(AtomicUsize::new(0));
            let d=dropped.clone();let owner=AudioOwner::with_factory(root(),notifier(&events),Box::new(move |_| Ok(Box::new(FakeOutput {
                done:Arc::new(AtomicBool::new(!fail)),fail:Arc::new(AtomicBool::new(fail)),
                started:Arc::new(AtomicUsize::new(0)),dropped:d.clone()})))).unwrap();
            owner.voice(&voice("g",1));owner.play(play("g",1));wait(||events.lock().unwrap().len()==2);
            assert_eq!(events.lock().unwrap()[1].1,if fail {"failed"} else {"completed"});
            assert_eq!(dropped.load(Ordering::SeqCst),1);owner.join();
        }
    }
    #[test]
    fn missing_device_and_factory_panic_are_audio_only_errors() {
        for panic in [false,true] {
            let events:Events=Default::default();
            let owner=AudioOwner::with_factory(root(),notifier(&events),Box::new(move |_| {
                if panic { panic!("synthetic audio failure"); }
                Err("AUDIO_DEVICE_UNAVAILABLE")
            })).unwrap();
            owner.voice(&voice("g",1));owner.play(play("g",1));wait(||!events.lock().unwrap().is_empty());
            assert_eq!(events.lock().unwrap()[0].1,"failed");owner.join();
        }
    }
    #[test]
    fn cancel_during_device_initialization_never_starts_late_output() {
        let events:Events=Default::default();let entered=Arc::new(AtomicBool::new(false));let release=Arc::new(AtomicBool::new(false));
        let started=Arc::new(AtomicUsize::new(0));let (e,r,s)=(entered.clone(),release.clone(),started.clone());
        let owner=AudioOwner::with_factory(root(),notifier(&events),Box::new(move |_| {
            e.store(true,Ordering::SeqCst);wait(||r.load(Ordering::SeqCst));
            Ok(Box::new(FakeOutput {done:Arc::new(AtomicBool::new(false)),fail:Arc::new(AtomicBool::new(false)),
                started:s.clone(),dropped:Arc::new(AtomicUsize::new(0))}))
        })).unwrap();
        owner.new_generation("g1");owner.voice(&voice("g1",1));owner.play(play("g1",1));wait(||entered.load(Ordering::SeqCst));
        owner.new_generation("g2");owner.voice(&voice("g1",5)); // delayed snapshot cannot authorize old audio
        release.store(true,Ordering::SeqCst);wait(||!events.lock().unwrap().is_empty());
        assert_eq!(started.load(Ordering::SeqCst),0);assert_eq!(events.lock().unwrap()[0].1,"stopped");
        owner.halt();owner.join();
    }
    #[test]
    fn shutdown_pending_or_active_and_transport_failure_are_bounded() {
        let owner=AudioOwner::with_factory(root(),Arc::new(|_,_,_|false),Box::new(|_|Ok(Box::new(FakeOutput {
            done:Arc::new(AtomicBool::new(false)),fail:Arc::new(AtomicBool::new(false)),started:Arc::new(AtomicUsize::new(0)),
            dropped:Arc::new(AtomicUsize::new(0))})))).unwrap();
        owner.voice(&voice("g",1));owner.play(play("g",1));owner.halt();owner.join();
        assert!(owner.worker.lock().unwrap().is_none());
    }
    #[test]
    fn private_wire_never_accepts_frontend_fields() {
        let mut value=json!({"protocol":"aurora-ipc","version":1,"type":"audio.play.request",
            "payload":{"generation_id":"g1","revision":1,"file":"run/audio.mp3"}});
        assert!(crate::protocol::validate_sidecar_event(&value).is_ok());
        value["payload"]["endpoint"]=json!("private");assert!(validate_wire(&value).is_err());
    }
    #[test]
    fn pcm16_wav_decodes_without_device_and_missing_file_reports_terminal() {
        use rodio::Source;
        let mut wav=b"RIFF".to_vec();wav.extend_from_slice(&516u32.to_le_bytes());wav.extend_from_slice(b"WAVEfmt ");
        wav.extend_from_slice(&16u32.to_le_bytes());wav.extend_from_slice(&1u16.to_le_bytes());wav.extend_from_slice(&1u16.to_le_bytes());
        wav.extend_from_slice(&24000u32.to_le_bytes());wav.extend_from_slice(&48000u32.to_le_bytes());
        wav.extend_from_slice(&2u16.to_le_bytes());wav.extend_from_slice(&16u16.to_le_bytes());wav.extend_from_slice(b"data");
        wav.extend_from_slice(&480u32.to_le_bytes());wav.extend_from_slice(&[0u8;480]);
        let decoder=Decoder::try_from(Cursor::new(wav)).unwrap();
        assert_eq!(decoder.sample_rate(),24000);assert_eq!(decoder.channels(),1);assert_eq!(decoder.count(),240);
        let events:Events=Default::default();let owner=AudioOwner::with_factory(root(),notifier(&events),Box::new(|_|panic!("must not open device"))).unwrap();
        owner.voice(&voice("g",1));let mut request=play("g",1);request.file="run/missing.wav".into();owner.play(request);
        wait(||!events.lock().unwrap().is_empty());assert_eq!(events.lock().unwrap()[0].2,"AUDIO_FILE_UNAVAILABLE");owner.join();
    }
}
