mod protocol;
mod registry;
mod sidecar;
mod settings;
mod local_model;
mod voice;
mod audio;

use protocol::{BackendSnapshot, CancelTarget, ChatStartResult, FrontendEvent};
use serde::{Deserialize, Serialize};
use sidecar::BackendManager;
use tauri::ipc::Channel;
use tauri::window::{Effect, EffectsBuilder};
use tauri::Manager;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum WindowAction {
    Minimize,
    ToggleMaximize,
    Close,
}

#[tauri::command]
async fn window_action(window: tauri::WebviewWindow, action: WindowAction) -> Result<bool, String> {
    match action {
        WindowAction::Minimize => window.minimize(),
        WindowAction::ToggleMaximize => {
            if window.is_maximized().map_err(|error| error.to_string())? {
                window.unmaximize()
            } else {
                window.maximize()
            }
        }
        WindowAction::Close => window.close(),
    }
    .map_err(|error| error.to_string())?;

    window.is_maximized().map_err(|error| error.to_string())
}

#[tauri::command]
fn set_reduced_effects(window: tauri::WebviewWindow, enabled: bool) -> Result<(), String> {
    if enabled {
        window.set_effects(None)
    } else {
        window.set_effects(EffectsBuilder::new().effect(Effect::MicaDark).build())
    }
    .map_err(|error| error.to_string())
}

#[tauri::command]
async fn backend_subscribe(
    manager: tauri::State<'_, BackendManager>,
    channel: Channel<FrontendEvent>,
) -> Result<BackendSnapshot, String> {
    Ok(manager.register_channel(channel).await)
}

#[tauri::command]
async fn backend_snapshot(
    manager: tauri::State<'_, BackendManager>,
) -> Result<BackendSnapshot, String> {
    Ok(manager.snapshot().await)
}

#[tauri::command]
async fn chat_start(
    manager: tauri::State<'_, BackendManager>,
    input: String,
    conversation_id: Option<String>,
) -> Result<ChatStartResult, String> {
    manager.chat_start_for_conversation(input, conversation_id).await
}

#[tauri::command]
async fn conversation_list(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.conversation_list().await
}

#[tauri::command]
async fn settings_get(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.settings_get().await
}

#[tauri::command]
async fn settings_update(manager: tauri::State<'_, BackendManager>, expected_revision: u64, patch: serde_json::Value) -> Result<(), String> {
    manager.settings_update(expected_revision, patch).await
}

#[tauri::command]
async fn voice_get(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.voice_get().await
}

#[tauri::command]
async fn voice_stop(manager: tauri::State<'_, BackendManager>, generation_id: String) -> Result<(), String> {
    manager.voice_stop(generation_id).await
}

#[tauri::command]
async fn conversation_get(
    manager: tauri::State<'_, BackendManager>,
    conversation_id: String,
) -> Result<(), String> {
    manager.conversation_get(conversation_id).await
}

#[tauri::command]
async fn conversation_create(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.conversation_create().await
}

#[tauri::command]
async fn chat_cancel(
    manager: tauri::State<'_, BackendManager>,
    target: CancelTarget,
) -> Result<bool, String> {
    manager.chat_cancel(target).await
}

#[tauri::command]
async fn crash_backend(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.crash().await
}

#[tauri::command]
async fn restart_backend(manager: tauri::State<'_, BackendManager>) -> Result<(), String> {
    manager.restart().await
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let manager = BackendManager::new();
    let startup_manager = manager.clone();
    let cleanup_manager = manager.clone();
    let app = tauri::Builder::default()
        // Must precede setup: a secondary process never starts another sidecar.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                // Attempt every step even if one fails; retain maximized state.
                if window.is_minimized().unwrap_or(false) {
                    let _ = window.unminimize();
                }
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .manage(manager)
        .setup(move |_| {
            tauri::async_runtime::spawn(async move {
                let _ = startup_manager.start(false).await;
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            window_action,
            set_reduced_effects,
            backend_subscribe,
            backend_snapshot,
            chat_start,
            conversation_list,
            settings_get,
            voice_get,
            voice_stop,
            settings_update,
            conversation_get,
            conversation_create,
            chat_cancel,
            crash_backend,
            restart_backend,
        ])
        .build(tauri::generate_context!())
        .expect("Aurora v4 desktop prototype failed to build");

    app.run(move |_app_handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            let _ = tauri::async_runtime::block_on(cleanup_manager.shutdown());
        }
    });
}
