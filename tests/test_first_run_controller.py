from modules.first_run import FirstRunController, empty_runtime_report


def _report(models=(), *, recommendation=None, status="Ready"):
    report = empty_runtime_report()
    report["status"] = status
    report["ollama"] = {
        "state": "Server Ready",
        "available": True,
        "executable_path": "ollama.exe",
        "models": {"all": list(models)},
    }
    if recommendation:
        report["recommendation"].update(recommendation)
    return report


def test_all_missing_can_be_skipped_and_completed():
    controller = FirstRunController(empty_runtime_report())

    controller.skip_model_setup()

    assert controller.completion_updates() == {"first_run.completed": True}
    assert controller.report["core_ready"] is True
    assert {item["status"] for item in controller.environment_items()} <= {
        "Ready", "Missing", "Offline", "Optional", "Degraded"
    }


def test_all_optional_skipped_does_not_persist_placeholder_or_embedding():
    controller = FirstRunController(_report())

    controller.skip_model_setup()
    updates = controller.completion_updates()

    assert updates == {"first_run.completed": True}
    assert "No models available" not in updates.values()
    assert "embedding_model" not in updates


def test_fully_configured_uses_existing_chat_and_embedding_models():
    report = _report(["qwen3:8b", "nomic-embed-text:latest"])
    controller = FirstRunController(
        report,
        configured_chat_model="qwen3:8b",
        configured_embedding_model="nomic-embed-text:latest",
    )

    controller.use_existing_model("qwen3:8b")

    assert controller.completion_updates() == {
        "first_run.completed": True,
        "chat_model_mode": "manual",
        "chat_model": "qwen3:8b",
        "resolved_chat_model": "",
        "chat_model_resolution_reason": "manual_selection",
        "last_successful_chat_model": "qwen3:8b",
        "embedding_model": "nomic-embed-text:latest",
    }


def test_embedding_only_model_never_appears_in_chat_choices():
    controller = FirstRunController(_report(["nomic-embed-text", "qwen3:4b"]))

    assert controller.existing_chat_names() == ["qwen3:4b"]
    assert controller.existing_embedding_names() == ["nomic-embed-text"]


def test_existing_suitable_model_is_preferred_over_download():
    controller = FirstRunController(
        _report(
            ["qwen3:8b"],
            recommendation={
                "model": "qwen3:8b",
                "existing_model": True,
                "download_required": False,
            },
        )
    )

    assert controller.selected_chat_model == "qwen3:8b"
    assert controller.accept_recommended_existing_or_skip() == "use_existing"
    assert controller.completion_updates()["chat_model"] == "qwen3:8b"


def test_first_run_single_existing_model_can_use_auto_without_download():
    report = _report(
        ["qwen3:4b"],
        recommendation={
            "model": "qwen3:4b",
            "existing_model": True,
            "download_required": False,
        },
    )
    report["model_resolution"] = {
        "chat": {
            "mode": "auto",
            "model": "qwen3:4b",
            "reason": "only_compatible_model",
        }
    }
    controller = FirstRunController(report)

    assert controller.use_automatically() == "qwen3:4b"
    updates = controller.completion_updates()
    assert updates["chat_model_mode"] == "auto"
    assert updates["resolved_chat_model"] == "qwen3:4b"
    assert updates["chat_model"] == "qwen3:4b"


def test_first_run_multiple_models_uses_resolved_existing_recommendation():
    report = _report(
        ["qwen3:4b", "qwen3:8b"],
        recommendation={
            "model": "qwen3:8b",
            "existing_model": True,
            "download_required": False,
        },
    )
    report["model_resolution"] = {
        "chat": {
            "mode": "auto",
            "model": "qwen3:8b",
            "reason": "hardware_recommendation",
        }
    }

    controller = FirstRunController(report)

    assert controller.selected_chat_model == "qwen3:8b"
    assert controller.recommendation()["download_required"] is False
    assert controller.accept_recommended_existing_or_skip() == "auto"


def test_download_success_is_the_only_download_state_that_persists_model():
    controller = FirstRunController(_report())
    controller.mark_download_started("qwen3:4b")
    controller.mark_download_result("cancelled", "cancelled")
    assert "chat_model" not in controller.completion_updates()

    controller.mark_download_started("qwen3:4b")
    controller.mark_download_result("success", "ready")
    assert controller.completion_updates()["chat_model"] == "qwen3:4b"


def test_navigation_is_bounded_and_completion_is_idempotent():
    controller = FirstRunController(empty_runtime_report())

    for _ in range(20):
        controller.next_step()
    first = controller.completion_updates()
    second = controller.completion_updates()

    assert controller.step == "complete"
    assert first == second == {"first_run.completed": True}


def test_unknown_vram_remains_unknown_in_first_run_view():
    report = empty_runtime_report()
    report["hardware"]["vram_gb"] = None
    report["hardware"]["vram_status"] = "known"

    hardware = FirstRunController(report).hardware()

    assert hardware["vram_gb"] is None
    assert hardware["vram_status"] == "unknown"
