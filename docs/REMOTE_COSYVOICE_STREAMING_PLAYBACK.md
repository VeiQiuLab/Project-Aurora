# Remote CosyVoice Streaming Playback

This phase adds an independent playback boundary. It does not connect streaming
TTS to `VoiceOrchestrator`, replace file-backed playback, or change the Voice
Node protocol.

```text
RemoteCosyVoiceProvider.synthesize_stream()
  -> StreamingSpeechResult blocking iterator
  -> producer thread
  -> bounded aligned PCM buffer
  -> sounddevice.RawOutputStream callback
  -> selected/default output device
```

## Audio backend

`sounddevice` is already a Project Aurora Voice dependency: version 0.5.6 is
locked in `requirements-voice.lock.txt`, included in Full packaging, and used by
existing microphone and device-discovery components. The playback module imports
it only when the real output factory is opened, so fake-backed tests do not need
an audio device or an installed PortAudio runtime.

The streaming path accepts interleaved PCM16 little-endian metadata. Unsupported
sample formats and widths are rejected rather than converted. The output device
is `None` by default, which preserves sounddevice's normal system-default output
selection. A sounddevice device index or name can be passed explicitly by the
smoke tool without adding another Aurora device configuration system.

## Buffering and completion

The default prebuffer is 250 ms and the maximum buffer is 2000 ms. Both byte
counts are derived from sample rate, channel count, and the two-byte PCM16 sample
width. At 24 kHz mono these are 12,000 and 96,000 bytes. A short completed stream
starts as soon as its available audio is known to be below the prebuffer target.

The producer is the only thread that reads the provider iterator. It combines
arbitrarily split bytes into complete `channels * 2` sample frames, blocks when
the one bounded buffer is full, and reports a dangling final byte as an error.
There is no second unbounded queue.

The audio callback only takes a short buffer lock, copies ready PCM, fills a
temporary shortage with zeroes, and updates counters. It never reads the network,
does disk I/O, parses JSON, or waits for producer data. Silence is inserted on an
underrun; previous PCM is never repeated.

After upstream END, all buffered PCM is submitted before the session completes.
The sounddevice adapter waits for its `finished_callback` after `CallbackStop`.
This establishes that the last callback buffer has drained through PortAudio; it
does not claim knowledge of the exact physical DAC or speaker completion time.

If upstream fails after audio begins, already buffered complete samples are
drained and the terminal report is `failed`. An output failure or user cancel
closes/cancels the `StreamingSpeechResult`, aborts the device, wakes the producer,
and joins both owned threads. `close()` and `cancel()` are idempotent.

Cancellation does not drain buffered audio. It marks the session cancelled,
discards queued PCM, wakes a producer waiting for buffer space, aborts the output
device before performing network cleanup, then shuts down and closes the provider
HTTP response. The smoke command catches `Ctrl+C`, waits for this cleanup, and
prints `status`, cancel latency, owned-thread state, provider closure, and audio
stream state before returning exit code 130 to PowerShell.

## Real two-machine smoke

The Voice Node and cosyvoice-server deployment from A-1 is unchanged. On the
Aurora machine, first verify that the locked dependency is available in the
Python environment used for the smoke test:

```powershell
python -c "import sounddevice; print(sounddevice.__version__)"
```

If that environment has not installed the formal Voice dependency yet:

```powershell
python -m pip install "sounddevice==0.5.6"
```

Run direct Provider-to-device playback without `VoiceOrchestrator`:

```powershell
python scripts/smoke_voice_node_stream_playback.py `
  --url $VoiceNodeUrl `
  --text "这是 Aurora Remote CosyVoice 实时流式播放测试。" `
  --speed 1.0 `
  --prebuffer-ms 250 `
  --max-buffer-ms 2000
```

Use `--device <index-or-name>` only when the system default is not the intended
output. The report includes provider metadata, first PCM, playback start, first
audio submission, upstream END and playback completion timing; PCM byte counts,
audio and wall duration, buffer peak/low watermark, underruns, producer/output
errors, and Voice Node health before and after playback.

## VoiceOrchestrator integration

Streaming orchestration is opt-in. It is selected only when
`voice.tts.streaming_enabled` is true, the provider selected by `TTSRouter`
implements `StreamingTTSProvider`, and a streaming playback controller is
available. Otherwise the existing `synthesize()` and file-backed playback path
is unchanged. The default remains false, including for Edge TTS.

```json
{
  "voice": {
    "tts": {
      "streaming_enabled": true
    },
    "playback": {
      "streaming": {
        "prebuffer_ms": 250.0,
        "max_buffer_ms": 2000.0,
        "device": ""
      }
    }
  }
}
```

The application composition boundary creates and reuses one
`StreamingPlaybackController`. `VoiceOrchestrator` owns only the current
`StreamingPlaybackSession`, clears that reference on every terminal path, and
cancels it through the existing runtime cancellation API. Streaming playback
always waits for upstream completion and audio drain before the voice run returns
to idle. Existing LLM sentence splitting and `TTSQueue` continue to use complete
TTS results; token-to-speech streaming is outside this phase.

Run the integration smoke through the real runtime, router, provider, and
orchestrator boundaries:

```powershell
python scripts/smoke_voice_orchestrator_stream_playback.py `
  --url $VoiceNodeUrl `
  --text "这是通过 VoiceOrchestrator 执行的流式语音测试。" `
  --repeat 2
```

The smoke uses deterministic fake recorder/STT inputs so it does not require the
GUI or microphone. Audio synthesis, transport, buffering, playback, cancellation,
and orchestration are real. Pressing Ctrl+C calls the runtime cancellation API.
