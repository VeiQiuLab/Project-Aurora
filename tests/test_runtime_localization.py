import json
from pathlib import Path

from modules.i18n import set_language, t
from modules.runtime_display import localized_runtime_item, runtime_status_text


ROOT = Path(__file__).resolve().parents[1]


def _locale(name):
    return json.loads((ROOT / "locales" / name).read_text(encoding="utf-8"))


def test_localization_key_parity():
    assert set(_locale("zh_CN.json")) == set(_locale("en_US.json"))


def test_runtime_status_and_details_are_natural_in_chinese():
    set_language("zh_CN")
    assert runtime_status_text("Ready") == "就绪"
    assert runtime_status_text("Missing") == "缺失"
    assert runtime_status_text("Optional") == "未启用"
    item = {
        "key": "chat_model",
        "name": "Chat Model",
        "status": "Ready",
        "data": {"configured": "qwen3:4b", "mode": "auto"},
    }
    assert localized_runtime_item(item)["detail"] == "qwen3:4b · 自动选择"


def test_critical_chinese_runtime_strings_do_not_fall_back_to_english():
    zh = _locale("zh_CN.json")
    critical = {
        "runtime_title",
        "runtime_status_ready",
        "runtime_status_missing",
        "runtime_status_optional",
        "runtime_check_again",
        "runtime_reevaluate",
        "runtime_install_download",
        "runtime_configure",
        "runtime_repair",
        "runtime_diagnostics",
        "runtime_optional_features",
        "runtime_download_embedding",
        "runtime_download_whisper",
        "first_run_existing_chat_model",
        "first_run_choose_model",
        "ai_model_rerecommend",
        "voice_environment_hint",
    }
    forbidden = (
        "Runtime / Dependencies",
        "Ready",
        "Missing",
        "Optional",
        "Check Again",
        "Re-evaluate",
        "Install / Download",
        "Configure",
        "Repair",
        "Diagnostics",
        "Download Whisper Model",
    )
    assert all(key in zh for key in critical)
    for key in critical:
        assert not any(text in zh[key] for text in forbidden)


def test_target_screens_do_not_contain_legacy_user_facing_english_literals():
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "widgets/components/dependency_center.py",
            "widgets/first_run_wizard.py",
            "widgets/pages/settings_page.py",
            "widgets/settings_window.py",
        )
    )
    forbidden_literals = (
        'text="Runtime / Dependencies"',
        'text="Check Again"',
        'text="Re-evaluate"',
        'text="Install / Download"',
        'text="Download Embedding',
        'text="Download Whisper Model"',
        'text="Voice Enabled"',
        'text="Reload Models"',
        'text="Re-run Recommendation"',
    )
    assert not any(literal in sources for literal in forbidden_literals)
