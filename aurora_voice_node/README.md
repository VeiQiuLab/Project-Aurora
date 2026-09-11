# Aurora Voice Node

The Voice Node is Aurora's optional LAN boundary for a separately provisioned
CosyVoice runtime. Its recommended backend owns one persistent
`cosyvoice-server` process bound only to `127.0.0.1`; only the Python Voice Node
is exposed to the LAN. The legacy `cosyvoice-cli --interactive` backend remains
available through an explicit runtime selection, and one node process creates
only the selected backend.

Server-backend launch example (PowerShell placeholders):

```powershell
python -m aurora_voice_node --runtime-backend server `
  --host 0.0.0.0 --port $VoiceNodePort `
  --server $CosyVoiceServer --model $CosyVoiceModel `
  --prompt-speech $CosyVoicePrompt --backend cuda0 `
  --backend-path $CosyVoiceBin
```

`--internal-port 0` is the default and selects an available loopback port. The
internal endpoint is not returned by `/health`. The health response reports the
runtime backend, readiness, child PID, restart count, and streaming capability.

`POST /tts` remains the phase-two blocking API and returns a complete PCM16 WAV.
`POST /tts/stream` returns HTTP/1.1 chunked data with content type
`application/vnd.aurora.pcm-stream; version=1`. Each application frame is one
type byte, a four-byte unsigned big-endian payload length, and the payload. `M`
metadata is first, `A` contains aligned s16le PCM, `E` is the only normal end,
and `X` reports an error after the response starts. EOF without `E` is failure.

The server backend uses only Python's standard library. Closing the downstream
client response closes the loopback response so cosyvoice-server can cancel the
active generation and release the single runtime lease.

Legacy CLI launch remains compatible:

```powershell
python -m aurora_voice_node --runtime-backend cli `
  --host 0.0.0.0 --port $VoiceNodePort `
  --cli $CosyVoiceCli --model $CosyVoiceModel `
  --prompt-speech $CosyVoicePrompt --backend cuda0
```

The CLI backend advertises `streaming: false` and returns HTTP 501 for
`POST /tts/stream`; it never runs alongside the server backend in one node.
