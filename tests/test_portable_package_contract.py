import importlib.util
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = PROJECT_ROOT / "scripts" / "validate_portable_package.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("aurora_portable_validator", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


class PortablePackageValidatorTests(unittest.TestCase):
    def test_clean_runtime_layout_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Aurora.exe").write_bytes(b"portable-runtime")
            config = root / "_internal" / "config"
            config.mkdir(parents=True)
            (config / "default_settings.json").write_text("{}", encoding="utf-8")

            self.assertEqual(validator.validate_package(root), [])

    def test_private_runtime_paths_and_ffmpeg_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory").mkdir()
            (root / "memory" / "memories.json").write_text("[]", encoding="utf-8")
            (root / "settings.json").write_text("{}", encoding="utf-8")
            (root / "ffmpeg.exe").write_bytes(b"binary")

            violations = "\n".join(validator.validate_package(root))

            self.assertIn("forbidden user-data directory", violations)
            self.assertIn("settings.json", violations)
            self.assertIn("ffmpeg.exe", violations)

    def test_pyav_ffmpeg_libraries_and_optional_voice_runtime_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            libraries = root / "_internal" / "av.libs"
            libraries.mkdir(parents=True)
            (libraries / "avcodec-62-test.dll").write_bytes(b"binary")
            (root / "_internal" / "faster_whisper").mkdir()

            violations = "\n".join(validator.validate_package(root))

            self.assertIn("forbidden optional runtime directory", violations)
            self.assertIn("forbidden FFmpeg codec library", violations)

    def test_utf8_and_utf16_developer_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            developer_path = r"C:\Users\Developer\Project-Aurora"
            (root / "utf8.bin").write_bytes(b"prefix" + developer_path.encode("utf-8") + b"suffix")
            (root / "utf16.bin").write_bytes(developer_path.encode("utf-16-le"))

            violations = validator.validate_package(root, [developer_path])

            self.assertEqual(len(violations), 2)


class PortableBuildContractTests(unittest.TestCase):
    def test_spec_collects_customtkinter_data_and_excludes_optional_voice_runtime(self):
        content = (PROJECT_ROOT / "Project Aurora.spec").read_text(encoding="utf-8")

        self.assertIn('collect_data_files("customtkinter")', content)
        self.assertNotIn("ffmpeg.exe", content.casefold())
        self.assertNotIn('(str(tools_dir), "tools")', content)
        self.assertIn("optional_voice_excludes", content)
        for package in ("av", "ctranslate2", "edge_tts", "faster_whisper", "pygame", "sounddevice"):
            self.assertIn(f'"{package}"', content)
        self.assertIn("excludes=optional_voice_excludes", content)

    def test_build_scripts_do_not_require_or_bundle_ffmpeg(self):
        executable_build = (PROJECT_ROOT / "build_exe.ps1").read_text(encoding="utf-8")
        installer_build = (PROJECT_ROOT / "installer" / "build_installer.ps1").read_text(encoding="utf-8")

        self.assertNotIn("tools\\ffmpeg.exe", executable_build.casefold())
        self.assertNotIn("tools\\ffmpeg.exe", installer_build.casefold())
        self.assertIn("_internal\\customtkinter\\assets", executable_build)
        self.assertIn("_internal\\customtkinter\\assets", installer_build)

    def test_portable_script_has_privacy_scan_and_hash(self):
        content = (PROJECT_ROOT / "build_portable.ps1").read_text(encoding="utf-8")

        self.assertIn("Aurora-Windows-Test.zip", content)
        self.assertIn("validate_portable_package.py", content)
        self.assertIn("Get-FileHash", content)
        self.assertIn("SHA256", content)


if __name__ == "__main__":
    unittest.main()
