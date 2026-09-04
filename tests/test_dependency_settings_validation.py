from modules.settings_controller import SettingsController


class _Store:
    def update_many(self, values, save=True):
        self.values = dict(values)


def test_models_can_be_left_blank_when_optional_setup_is_skipped():
    valid, values, errors = SettingsController(_Store()).validate(
        {"chat_model": "", "embedding_model": ""}
    )

    assert valid is True
    assert errors == []
    assert values == {"chat_model": "", "embedding_model": ""}


def test_embedding_only_model_is_blocked_from_chat_setting():
    valid, _values, errors = SettingsController(_Store()).validate(
        {"chat_model": "nomic-embed-text"}
    )

    assert valid is False
    assert errors == ["Chat model must support chat."]


def test_chat_model_is_blocked_from_embedding_setting():
    valid, _values, errors = SettingsController(_Store()).validate(
        {"embedding_model": "qwen3:8b"}
    )

    assert valid is False
    assert errors == ["Embedding model must be embedding-only."]


def test_model_selection_modes_are_normalized_and_validated():
    controller = SettingsController(_Store())

    valid, values, errors = controller.validate(
        {"chat_model_mode": " Auto ", "embedding_model_mode": "MANUAL"}
    )

    assert valid is True
    assert errors == []
    assert values == {
        "chat_model_mode": "auto",
        "embedding_model_mode": "manual",
    }

    valid, _values, errors = controller.validate({"chat_model_mode": "random"})
    assert valid is False
    assert "Invalid model selection mode: chat_model_mode" in errors
