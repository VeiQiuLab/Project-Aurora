// Test helper only: occupy the official hotkey, then release on stdin/EOF.
#[cfg(windows)]
fn main() {
    use global_hotkey::{GlobalHotKeyManager, hotkey::{HotKey, Modifiers, Code}};
    let manager = GlobalHotKeyManager::new().unwrap();
    let key = HotKey::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Space);
    manager.register(key).expect("fixture could not register hotkey");
    println!("HOTKEY_HELD");
    let mut line = String::new();
    let _ = std::io::stdin().read_line(&mut line);
    manager.unregister(key).unwrap();
    println!("HOTKEY_RELEASED");
}
#[cfg(not(windows))]
fn main() { panic!("Windows acceptance fixture"); }
