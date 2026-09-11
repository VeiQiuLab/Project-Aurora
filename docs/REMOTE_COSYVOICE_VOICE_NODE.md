# Remote CosyVoice Voice Node

## Architecture and compatibility

Remote CosyVoice remains an optional provider. Edge TTS and Aurora's
single-machine mode do not import, start, or require a CosyVoice process.

```text
Aurora RemoteCosyVoiceProvider
  -> Voice Node LAN HTTP
    -> selected runtime backend
      -> cosyvoice-server on 127.0.0.1 (recommended)
      -> cosyvoice-cli interactive (legacy complete-WAV mode)
```

One Voice Node selects exactly one backend. It never keeps the CLI and server
models resident together. SSH can deploy or start the node, but is not part of
the runtime protocol.

## Runtime lifecycle

The server adapter validates its executable, model, prompt, backend directory,
and working directory before launch. It selects an available internal port when
`--internal-port 0` is used, always supplies `--host 127.0.0.1`, captures a
bounded merged stdout/stderr tail, and waits for `/healthz` within the startup
timeout. It records the child PID and restart count.

Normal shutdown first terminates the child and waits for a bounded interval,
then kills a child that does not exit. Unexpected exit changes health to failed
and preserves the exit code and bounded log tail. A later request may perform a
clean restart. Requests share one serialized runtime lease. Speed is sent in
each cosyvoice-server request and never restarts the model.

The internal port is intentionally omitted from public health diagnostics.

## Launch

All deployment-specific paths and LAN addresses are launch parameters:

```powershell
$VoiceNodePort = 8765
$CosyVoiceServer = '<path-to-cosyvoice-server.exe>'
$CosyVoiceModel = '<path-to-CosyVoice3-Q8_0.gguf>'
$CosyVoicePrompt = '<path-to-prompt_speech.gguf>'
$CosyVoiceBin = '<directory-containing-runtime-DLLs>'

python -m aurora_voice_node --runtime-backend server `
  --host 0.0.0.0 --port $VoiceNodePort `
  --server $CosyVoiceServer --model $CosyVoiceModel `
  --prompt-speech $CosyVoicePrompt --backend cuda0 `
  --backend-path $CosyVoiceBin
```

The process working directory defaults to the directory containing
`cosyvoice-server.exe`, which lets Windows resolve its adjacent CUDA/GGML DLLs.
Use `--working-directory` only when the deployment requires an override.

Legacy complete-WAV mode remains available:

```powershell
python -m aurora_voice_node --runtime-backend cli `
  --host 0.0.0.0 --port $VoiceNodePort `
  --cli '<path-to-cosyvoice-cli.exe>' `
  --model $CosyVoiceModel --prompt-speech $CosyVoicePrompt `
  --backend cuda0 --backend-path $CosyVoiceBin
```

## HTTP protocol

`GET /health` returns HTTP 200 whenever the Voice Node HTTP service is alive.
`status` is `ready` only when the selected runtime is available. Runtime fields
include `backend`, `state`, `process_running`, `pid`, `restart_count`,
`streaming`, `sample_rate`, `channels`, `last_error`, and a bounded startup log
tail where applicable.

`POST /tts` accepts UTF-8 JSON:

```json
{"text":"你好","speed":1.0}
```

It calls cosyvoice-server's non-streaming API in server mode and returns a
complete, validated PCM16 RIFF/WAVE exactly as the phase-two API did.

`POST /tts/stream` accepts the same request and returns:

```text
Content-Type: application/vnd.aurora.pcm-stream; version=1
Transfer-Encoding: chunked
```

HTTP chunk boundaries are transport details. The application stream uses:

```text
1-byte type | 4-byte unsigned big-endian payload length | payload
```

Payloads are at most 64 KiB:

- `M` is first and contains UTF-8 JSON metadata for interleaved mono s16le PCM.
- `A` contains complete aligned PCM samples; current frames are about 85 ms at 24 kHz.
- `E` is the only normal terminal frame and reports `total_samples` and `audio_frames`.
- `X` is a terminal JSON error containing `code` and `message`; no `E` follows.

EOF without `E`, a truncated or oversized frame, duplicate metadata, invalid
ordering, unaligned audio, and zero-audio success are failures. If upstream
generation aborts after the LAN response starts, the node sends `X` when the
client connection still permits it. Client disconnect closes the loopback
response immediately and releases the runtime lease.

The legacy CLI backend reports `streaming: false` and returns HTTP 501 for the
streaming endpoint.

## Provider API and smoke test

`RemoteCosyVoiceProvider.synthesize()` remains unchanged and returns the
existing `SpeechResult`. `synthesize_stream()` is a separate synchronous
capability returning `StreamingSpeechResult` with metadata, a blocking iterator
of PCM chunks, `close()`/`cancel()`, and diagnostics. It does not alter
`TTSRouter`, Edge TTS, or playback.

From the Aurora machine, run two streaming requests and reconstruct PCM16 WAVs:

```powershell
python scripts/smoke_voice_node_stream.py --url $VoiceNodeUrl `
  --text "这是 Aurora 跨机流式语音测试。" `
  --speed 1.0 --second-speed 1.15 `
  --output .\aurora-stream-smoke.wav
```

The tool records response-header, metadata, first-audio, and END timings; PCM
bytes, samples, duration, frame count, maximum frame interval, runtime PID, and
restart count. With two requests it writes `aurora-stream-smoke-1.wav` and
`aurora-stream-smoke-2.wav`, and fails if the child PID changes.

This phase stops at transport and WAV reconstruction. `RealPlaybackController`,
sound-device streaming, playback queues, interruption, WebSocket, UI, and text
segmentation are outside this boundary.
