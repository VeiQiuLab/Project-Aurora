from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


CONTRACT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "aurora_ipc_v1_validation", CONTRACT_DIR / "validate_contracts.py"
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


def _example(message_type: str, *, occurrence: int = 0):
    matches = [item for item in contract.load_examples() if item["type"] == message_type]
    return copy.deepcopy(matches[occurrence])


def test_schema_and_all_examples_are_valid_json_and_contract_shapes():
    schema = json.loads((CONTRACT_DIR / "ipc-v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert contract.validate_files() == 19


def test_schema_covers_every_executable_message_rule():
    schema = json.loads((CONTRACT_DIR / "ipc-v1.schema.json").read_text(encoding="utf-8"))
    definition_names = {
        reference["$ref"].rsplit("/", 1)[-1] for reference in schema["oneOf"]
    }
    schema_types = {
        definition["allOf"][-1]["properties"]["type"]["const"]
        for name, definition in schema["$defs"].items()
        if name in definition_names and "allOf" in definition
    }
    assert schema_types == set(contract.MESSAGE_RULES)
    assert "bootstrapReady" in definition_names


def test_every_internal_schema_reference_resolves():
    schema = json.loads((CONTRACT_DIR / "ipc-v1.schema.json").read_text(encoding="utf-8"))
    definitions = schema["$defs"]

    def walk(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                assert reference.startswith("#/$defs/")
                assert reference.rsplit("/", 1)[-1] in definitions
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(schema)


def test_handshake_success_and_protocol_mismatch_are_explicit():
    contract.validate_message(_example("hello"))
    contract.validate_message(_example("hello_ack"))
    assert contract.negotiate_version([1], [1, 2]) == 1
    with pytest.raises(contract.ContractError, match="PROTOCOL_VERSION_MISMATCH"):
        contract.negotiate_version([1], [2])


def test_ordered_deltas_start_at_zero_and_advance_per_generation():
    validator = contract.StreamContractValidator()
    validator.accept(_example("chat.accepted"))
    for occurrence in range(3):
        validator.accept(_example("chat.delta", occurrence=occurrence))
    validator.accept(_example("chat.completed", occurrence=0))
    assert validator.terminal[("runtime-session-001", "generation-001")] == "completed"


def test_duplicate_gap_and_reverse_sequences_are_rejected():
    for invalid_seq in (1, 2):
        validator = contract.StreamContractValidator()
        validator.accept(_example("chat.accepted"))
        message = _example("chat.delta")
        message["seq"] = invalid_seq
        with pytest.raises(contract.ContractError, match="invalid sequence"):
            validator.accept(message)
    validator = contract.StreamContractValidator()
    validator.accept(_example("chat.accepted"))
    validator.accept(_example("chat.delta"))
    with pytest.raises(contract.ContractError, match="invalid sequence"):
        validator.accept(_example("chat.delta"))


def test_terminal_state_is_unique_and_completion_cancel_race_has_one_winner():
    validator = contract.StreamContractValidator()
    completed = _example("chat.completed", occurrence=0)
    validator.accept(completed)
    cancelled = copy.deepcopy(completed)
    cancelled["payload"] = {"terminal_state": "cancelled"}
    with pytest.raises(contract.ContractError, match="after terminal"):
        validator.accept(cancelled)
    assert validator.terminal[("runtime-session-001", "generation-001")] == "completed"


def test_cancel_ack_is_not_terminal_but_cancelled_completion_is_terminal():
    validator = contract.StreamContractValidator()
    validator.accept(_example("chat.accepted", occurrence=1))
    validator.accept(_example("chat.cancel.request"))
    validator.accept(_example("chat.cancel.ack"))
    owner = ("runtime-session-001", "generation-002")
    assert owner not in validator.terminal
    validator.accept(_example("chat.completed", occurrence=1))
    assert validator.terminal[owner] == "cancelled"


def test_stale_delta_after_terminal_is_rejected():
    validator = contract.StreamContractValidator()
    validator.accept(_example("chat.completed", occurrence=0))
    with pytest.raises(contract.ContractError, match="after terminal"):
        validator.accept(_example("chat.delta"))


def test_backend_lost_is_a_terminal_state_with_safe_error():
    message = _example("chat.completed", occurrence=3)
    contract.validate_message(message)
    validator = contract.StreamContractValidator()
    validator.accept(message)
    assert validator.terminal[("runtime-session-001", "generation-004")] == "backend_lost"
    assert message["payload"]["error"]["code"] == "BACKEND_LOST"


def test_malformed_and_unknown_messages_are_rejected():
    malformed = _example("chat.request")
    del malformed["generation_id"]
    with pytest.raises(contract.ContractError, match="missing fields"):
        contract.validate_message(malformed)
    unknown = _example("health.request")
    unknown["type"] = "future.unknown"
    with pytest.raises(contract.ContractError, match="unknown message type"):
        contract.validate_message(unknown)


def test_required_and_forbidden_identifier_contract_is_enforced():
    health = _example("health.request")
    health["generation_id"] = "not-allowed"
    with pytest.raises(contract.ContractError, match="forbidden fields"):
        contract.validate_message(health)
    delta = _example("chat.delta")
    del delta["request_id"]
    with pytest.raises(contract.ContractError, match="missing fields"):
        contract.validate_message(delta)


def test_local_cosyvoice_capability_can_never_be_advertised():
    hello_ack = _example("hello_ack")
    assert hello_ack["payload"]["capabilities"]["voice"]["cosyvoice_local"] is False
    hello_ack["payload"]["capabilities"]["voice"]["cosyvoice_local"] = True
    with pytest.raises(contract.ContractError, match="must be false"):
        contract.validate_message(hello_ack)


@pytest.mark.parametrize("capability", ["ipc", "streaming_pcm"])
def test_reserved_voice_ipc_capabilities_remain_false(capability):
    hello_ack = _example("hello_ack")
    hello_ack["payload"]["capabilities"]["voice"][capability] = True
    with pytest.raises(contract.ContractError, match="reserved in v1"):
        contract.validate_message(hello_ack)


def test_examples_do_not_contain_bootstrap_secrets_or_private_diagnostics():
    serialized = json.dumps(contract.load_examples()).lower()
    for forbidden in (
        "authorization",
        "bearer ",
        "session_token",
        "traceback",
        "reasoning_text",
        "message.thinking",
    ):
        assert forbidden not in serialized


def test_non_cancel_transport_error_remains_failed_and_requires_error_detail():
    failed = _example("chat.completed", occurrence=2)
    contract.validate_message(failed)
    missing_error = copy.deepcopy(failed)
    del missing_error["payload"]["error"]
    with pytest.raises(contract.ContractError, match="does not match state"):
        contract.validate_message(missing_error)


def test_bootstrap_is_bounded_machine_data_without_token():
    ready = _example("bootstrap.ready")
    contract.validate_bootstrap(ready)
    assert set(ready) == {
        "protocol",
        "version",
        "type",
        "port",
        "pid",
        "supported_versions",
        "sidecar_instance_id",
    }
