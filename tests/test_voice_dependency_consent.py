from modules.experience.voice.dependency_manager import install_dependencies


def test_runtime_pip_install_never_runs_without_confirmation(monkeypatch):
    result = install_dependencies({}, confirmed=False)

    assert result["success"] is False
    assert result["confirmation_required"] is True


def test_runtime_package_install_is_refused_even_after_confirmation(monkeypatch):
    monkeypatch.setattr(
        "modules.experience.voice.dependency_manager.check_dependencies",
        lambda _settings: {
            "ready": False,
            "missing": [{"name": "STT"}],
        },
    )

    result = install_dependencies({}, confirmed=True)

    assert result["success"] is False
    assert result["installed"] == []
    assert "does not install Python packages" in result["stderr"]
