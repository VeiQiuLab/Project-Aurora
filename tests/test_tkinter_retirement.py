"""Entrypoint/data/import boundary tests; no Tk root, network or real audio."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from modules import desktop_launcher as launcher

ROOT = Path(__file__).resolve().parents[1]


def child(code, **env):
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          env={**os.environ, **env}, capture_output=True,
                          text=True, timeout=30, check=True)


def test_root_import_is_inert_and_does_not_import_legacy():
    child("import main, sys; assert not any(n.startswith(('tkinter','customtkinter','widgets','legacy','pygame','modules.settings','modules.app_paths')) for n in sys.modules)")


def test_missing_exe_never_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AURORA_DESKTOP_EXE", str(tmp_path / "missing.exe"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("No process allowed"))
    assert launcher.main([]) == 2
    assert "No legacy fallback" in capsys.readouterr().err


def test_path_check_does_not_launch(monkeypatch, tmp_path):
    exe = tmp_path / "Aurora v4.exe"
    exe.touch()
    monkeypatch.setenv("AURORA_DESKTOP_EXE", str(exe))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: pytest.fail("Check must not launch"))
    assert launcher.main(["--check"]) == 0
    monkeypatch.setenv("AURORA_DESKTOP_EXE", "relative.exe")
    assert launcher.main(["--check"]) == 2


def test_launch_only_selected_desktop_and_preserve_environment(monkeypatch, tmp_path):
    exe = tmp_path / "Aurora v4.exe"
    exe.touch()
    monkeypatch.setenv("AURORA_DESKTOP_EXE", str(exe))
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    assert launcher.main([]) == 0
    assert calls == [(([str(exe.resolve())],), {"cwd": ROOT, "creationflags": 0x08000000})]
    def fail(*a, **k):
        raise OSError("spawn failed")
    monkeypatch.setattr(launcher.subprocess, "Popen", fail)
    assert launcher.main([]) == 2


def test_legacy_isolated_before_settings_and_conversation_writes(tmp_path):
    prod = tmp_path / "production"
    (prod / "config").mkdir(parents=True)
    sentinel = prod / "config/settings.json"
    sentinel.write_text('{"sentinel":true}', encoding="utf-8")
    result = child('''
import json, os
from legacy.runtime_paths import activate_legacy_data
selected = activate_legacy_data()
from modules import app_paths
from modules.settings import Settings
store = Settings()
store.save()
assert app_paths.CONFIG_FILE.is_relative_to(selected)
assert app_paths.CONVERSATIONS_DIR.is_relative_to(selected)
assert app_paths.MEMORY_DIR.is_relative_to(selected)
print(json.dumps({"selected":str(selected)}))
''', APPDATA=str(tmp_path), AURORA_USER_DATA_DIR=str(prod))
    assert json.loads(result.stdout)["selected"] == str((tmp_path / "Aurora-Legacy").resolve())
    assert sentinel.read_text(encoding="utf-8") == '{"sentinel":true}'
    assert sorted(p.relative_to(prod).as_posix() for p in prod.rglob("*") if p.is_file()) == ["config/settings.json"]


def test_legacy_refuses_overlap_and_late_activation(tmp_path):
    code = '''
from legacy.runtime_paths import activate_legacy_data
try:
    activate_legacy_data()
except RuntimeError:
    pass
else:
    raise AssertionError("isolation should fail")
'''
    child(code, APPDATA=str(tmp_path), AURORA_USER_DATA_DIR=str(tmp_path / "Aurora-Legacy"))
    child("import modules.app_paths\n" + code, APPDATA=str(tmp_path), AURORA_USER_DATA_DIR=str(tmp_path / "prod"))


def test_legacy_guard_precedes_any_runtime_or_tk_import():
    tree = ast.parse((ROOT / "legacy/tk_desktop.py").read_text(encoding="utf-8"))
    guard = next(n.lineno for n in tree.body if isinstance(n, ast.Expr)
                 and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                 and n.value.func.id == "activate_legacy_data")
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(("modules", "widgets", "tkinter")):
            assert guard < node.lineno
        if isinstance(node, ast.Import) and any(a.name == "customtkinter" for a in node.names):
            assert guard < node.lineno


def test_real_shared_composition_and_tts_work_with_gui_imports_forbidden(tmp_path):
    # No sys.modules substitution: reject even attempted imports, including
    # optional-import exceptions which production might otherwise swallow.
    child('''
import importlib.abc, sys, os
from pathlib import Path
sys.path.insert(0, str(Path("prototype/aurora-v4/sidecar").resolve()))
attempted = []
class NoGui(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"tkinter","_tkinter","customtkinter","widgets","legacy","pygame","sounddevice"}:
            attempted.append(fullname)
            raise ImportError("Forbidden production dependency: " + fullname)
sys.meta_path.insert(0, NoGui())
from production_sidecar.composition import ProductionComposition
from production_sidecar.voice import create_router
from production_sidecar.rust_playback import RustPlayback
from production_sidecar.post_turn import PostTurnCoordinator
from production_sidecar.local_provider import BuiltInLlamaProvider
root = Path(os.environ["AURORA_USER_DATA_DIR"])
c = ProductionComposition(config_file=root/"config/settings.json", conversation_root=root/"conversations", context_root=root)
assert c.conversations.list_metadata() == []
c.context.prepare("hello")
router = create_router(c.settings.snapshot(), root/"audio")
assert type(router.provider_for()).__name__ == "EdgeTTSProvider"
c.close()
assert not attempted, attempted
assert not any(n.split(".")[0] in {"tkinter","_tkinter","customtkinter","widgets","legacy","pygame","sounddevice"} for n in sys.modules)
''', AURORA_USER_DATA_DIR=str(tmp_path), AURORA_V4_CHAT_PROVIDER="ollama")


def test_build_and_dependencies_have_explicit_legacy_boundary():
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name in ("customtkinter", "pyinstaller", "pygame", "faster-whisper", "sounddevice", "websocket-client"):
        assert name not in req.lower()
        assert name in (ROOT / "legacy/requirements.txt").read_text(encoding="utf-8")
    script = (ROOT / "build_exe.ps1").read_text(encoding="utf-8")
    assert script.index("if (-not $Legacy)") < script.index("import tkinter")
    assert "pnpm tauri build --no-bundle" in script
    for path in ("build_portable.ps1", "installer/build_installer.ps1"):
        assert "if (-not $Legacy) { throw" in (ROOT / path).read_text(encoding="utf-8")
    spec = (ROOT / "Project Aurora.spec").read_text(encoding="utf-8")
    assert 'AURORA_LEGACY_BUILD' in spec
    assert 'project_root / "legacy" / "tk_desktop.py"' in spec


@pytest.mark.skipif(sys.platform != "win32", reason="Windows packaging entrypoints")
@pytest.mark.parametrize("script,args", [
    ("build_portable.ps1", []),
    ("installer/build_installer.ps1", []),
    ("build_exe.ps1", ["-FullVoice"]),
])
def test_old_packaging_cannot_run_implicitly(script, args):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / script), *args],
                            cwd=ROOT, capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b"legacy" in result.stderr.lower()


def test_direct_spec_rejects_before_loading_pyinstaller():
    env = dict(os.environ)
    env.pop("AURORA_LEGACY_BUILD", None)
    result = subprocess.run([sys.executable, str(ROOT / "Project Aurora.spec")],
                            cwd=ROOT, env=env, capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b"Legacy-only PyInstaller recipe" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows legacy artifact guard")
@pytest.mark.parametrize("marker", ["missing", "stale", "matching"])
def test_legacy_package_requires_fresh_isolated_build(tmp_path, marker):
    payload = b"synthetic artifact; never executed"
    (tmp_path / "Aurora.exe").write_bytes(payload)
    if marker != "missing":
        (tmp_path / "legacy-build.json").write_text(json.dumps({
            "entrypoint": "legacy.tk_desktop", "data_directory": "Aurora-Legacy",
            "exe_sha256": hashlib.sha256(payload).hexdigest() if marker == "matching" else "old",
        }), encoding="utf-8")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", str(ROOT / "legacy/verify_build.ps1"), "-DistRoot", str(tmp_path)],
                            # Do not inherit a PowerShell 7-only module path
                            # when exercising Windows PowerShell 5.1.
                            env={k:v for k,v in os.environ.items() if k.upper() != "PSMODULEPATH"},
                            capture_output=True, timeout=15)
    assert (result.returncode == 0) == (marker == "matching"), result.stderr.decode("utf-8", errors="replace")
