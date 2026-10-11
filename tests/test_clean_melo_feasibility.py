"""CPU-independent tests of experimental evidence tooling; not listening QA."""
import importlib.util
from pathlib import Path
import struct
import wave

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("clean_melo_probe", REPO / "scripts/probe_clean_melo.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_golden_corpus_is_fixed_and_covers_languages():
    assert len(probe.CORPUS) == 9
    assert "hello world" in probe.CORPUS
    assert any("2026" in text for text in probe.CORPUS)
    assert any("25.5" in text for text in probe.CORPUS)


def test_empty_capture_cannot_be_identical():
    assert probe.compare_inputs([], []) == "INVALID"


def test_actual_tensor_capture_identical():
    tensor = [{"inputs": [{"name": "x", "dtype": 7, "shape": [1, 3], "values": [0, 3, 0]}]}]
    assert probe.compare_inputs(tensor, tensor) == "IDENTICAL"


@pytest.mark.parametrize("field,value", [("name", "tones"), ("dtype", 1), ("shape", [3]), ("values", [0, 4, 0])])
def test_mismatch_not_upgraded_to_audio_equivalence(field, value):
    old = {"name": "x", "dtype": 7, "shape": [1, 3], "values": [0, 3, 0]}
    assert probe.compare_inputs([old], [{**old, field: value}]) == "INVALID"


def test_pcm_stats(tmp_path):
    path = tmp_path / "speech.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(struct.pack("<hhhh", 0, 16000, -16000, 0))
    stats = probe.pcm_stats(path)
    assert stats["sample_rate"] == 44100 and stats["channels"] == 1
    assert stats["samples"] == 4 and stats["rms"] > 0
    assert len(stats["sha256"]) == 64


def test_silent_audio_not_accepted(tmp_path):
    path = tmp_path / "silent.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\0" * 16)
    with pytest.raises(AssertionError):
        probe.pcm_stats(path)


def test_no_upstream_root_or_gpl_targets_in_clean_build():
    cmake = (REPO / "scripts/sherpa_melo_clean/CMakeLists.txt").read_text()
    assert 'add_subdirectory("${SHERPA_SOURCE}"' not in cmake
    assert 'EXCLUDE_FROM_ALL "${CMAKE_BINARY_DIR}/oracle-main.cpp"' in cmake
    assert "Forbidden broad/GPL target" in cmake
    assert "piper-phonemize-lexicon.cc" not in cmake


def test_oracle_not_linked_into_performance_host():
    cmake = (REPO / "scripts/sherpa_melo_clean/CMakeLists.txt").read_text()
    host = cmake.split("add_executable(benchmark_sherpa_melo", 1)[1].split("foreach(dll", 1)[0]
    assert "oracle_trace" not in host


def test_prior_fixture_preserved_in_memory_reuse():
    script = (REPO / "prototype/aurora-v4/desktop/tests/clean_melo_feasibility.mjs").read_text()
    assert "898b90e8d31b0c0f6628535c1353a948d0543640545bc63d2e68f2b1ceca228e" in script
    assert "writeFile" not in script
    assert "for(const threads of [4])" in script
