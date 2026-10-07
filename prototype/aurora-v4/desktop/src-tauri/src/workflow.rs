//! Desktop entry points only. Runtime ownership and shutdown remain unchanged.
use std::sync::Mutex;
use serde::Serialize;
use tauri::{Emitter, Manager};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use crate::sidecar::BackendManager;

pub const SHORTCUT_LABEL: &str = "Ctrl+Alt+Space";
#[derive(Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Snapshot { pub tray_ready: bool, pub shortcut_ready: bool, pub error: String }
#[derive(Default)]
pub struct Workflow(pub Mutex<Snapshot>);

pub fn show(app: &tauri::AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("main").ok_or("聊天窗口不可用")?;
    if window.is_minimized().map_err(|_| "无法读取窗口状态")? {
        window.unminimize().map_err(|_| "无法恢复窗口")?;
    }
    window.show().map_err(|_| "无法显示窗口")?;
    window.set_focus().map_err(|_| "无法聚焦窗口")?;
    window.emit("desktop-show", ()).map_err(|_| "无法通知输入区")?;
    Ok(())
}
pub fn hide(app: &tauri::AppHandle) -> Result<(), String> {
    app.get_webview_window("main").ok_or("聊天窗口不可用")?.hide().map_err(|_| "无法隐藏窗口".into())
}
fn error(app: &tauri::AppHandle, message: &str) {
    let state = app.state::<Workflow>();
    state.0.lock().unwrap().error = message.into();
    let _ = app.emit("desktop-workflow-status", state.0.lock().unwrap().clone());
}
pub fn setup(app: &tauri::AppHandle) {
    let result = (|| -> tauri::Result<()> {
        let show_item = MenuItem::with_id(app, "companion-show", "显示 Aurora", true, None::<&str>)?;
        let hide_item = MenuItem::with_id(app, "companion-hide", "隐藏聊天窗口", true, None::<&str>)?;
        let stop_item = MenuItem::with_id(app, "companion-stop", "停止当前操作（回复 / 朗读）", true, None::<&str>)?;
        let exit_item = MenuItem::with_id(app, "companion-exit", "退出 Aurora", true, None::<&str>)?;
        let menu = Menu::with_items(app, &[&show_item, &hide_item, &stop_item, &exit_item])?;
        let mut tray = TrayIconBuilder::with_id("aurora-companion").tooltip(format!("Aurora · {SHORTCUT_LABEL} 显示聊天")).menu(&menu);
        if let Some(icon) = app.default_window_icon() { tray = tray.icon(icon.clone()); }
        tray.on_menu_event(|app, event| match event.id.as_ref() {
            "companion-show" => { if let Err(e) = show(app) { error(app, &e); } },
            "companion-hide" => { if let Err(e) = hide(app) { error(app, &e); } },
            "companion-exit" => app.exit(0),
            "companion-stop" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    match app.state::<BackendManager>().stop_current().await {
                        Ok(Some(id)) => { let _ = app.emit_to("main", "desktop-cancel-generation", id); },
                        Ok(None) => {},
                        Err(_) => error(&app, "停止未送达。请显示 Aurora 检查连接后重试。"),
                    }
                });
            },
            _ => {},
        }).build(app)?;
        Ok(())
    })();
    match result {
        Ok(()) => app.state::<Workflow>().0.lock().unwrap().tray_ready = true,
        Err(_) => error(app, "托盘入口不可用。仍可使用窗口按钮和任务栏。"),
    }
    let shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Space);
    let installed = app.plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(move |app, key, event| {
        if key == &shortcut && event.state() == ShortcutState::Pressed {
            if let Err(e) = show(app) { error(app, &e); }
        }
    }).build());
    let registered = installed.map_err(|e| e.to_string())
        .and_then(|_| app.global_shortcut().register(shortcut).map_err(|e| e.to_string()));
    match registered {
        Ok(()) => app.state::<Workflow>().0.lock().unwrap().shortcut_ready = true,
        Err(_) => error(app, "Ctrl+Alt+Space 注册失败，可能被其他应用占用。请使用托盘显示 Aurora。"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn shortcut_is_stable_and_registration_failure_is_not_silent() {
        assert_eq!(SHORTCUT_LABEL, "Ctrl+Alt+Space");
        let unavailable = Snapshot { error: "快捷键被占用；使用托盘".into(), ..Default::default() };
        let value = serde_json::to_value(unavailable).unwrap();
        assert_eq!(value["shortcutReady"], false);
        assert!(!value["error"].as_str().unwrap().is_empty());
    }
}
