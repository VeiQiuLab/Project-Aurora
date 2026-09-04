from modules.experience.voice.dependency_manager import install_dependencies


def test_runtime_pip_install_never_runs_without_confirmation(monkeypatch):
    monkeypatch.setattr(
        "modules.experience.voice.dependency_manager.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pip must not run")),
    )

    result = install_dependencies({}, confirmed=False)

    assert result["success"] is False
    assert result["confirmation_required"] is True
