# Remote CosyVoice Voice Node

## Scope

This phase adds one optional, blocking WAV path:

```text
Aurora -> TTSRouter -> RemoteCosyVoiceProvider -> HTTP
       -> Aurora Voice Node -> persistent cosyvoice-cli REPL -> WAV
       -> existing Aurora playback
```

The existing Edge TTS default and single-machine behavior are unchanged. SSH
may be used to copy files or start the service during development, but it is not
part of the runtime protocol.

## HTTP protocol

`GET /health` returns JSON and HTTP 200 whenever the HTTP service is alive. The
runtime must additionally report `runtime.available: true` before it is ready
to synthesize.

```json
{
  "service": "aurora-voice-node",
  "status": "ready",
  "runtime": {
    "available": true,
    "state": "ready",
    "process_running": true,
    "pid": 1234,
    "speed": 1.0,
    "restart_count": 0,
    "last_error": ""
  }
}
```

`POST /tts` accepts UTF-8 JSON:

```json
{"text":"你好","speed":1.0}
```

Success is HTTP 200 with `Content-Type: audio/wav` and a complete PCM WAV body.
This phase is deliberately non-streaming. Errors use JSON:

```json
{"error":{"code":"runtime_unavailable","message":"..."}}
```

Status mapping:

- 400: empty text, invalid JSON, or invalid speed
- 404: unknown endpoint
- 415: non-JSON request body
- 500: synthesis failure or invalid runtime WAV
- 503: cosyvoice.cpp is unavailable or exited
- 504: cosyvoice.cpp startup/generation timed out

## Runtime lifecycle

The Voice Node owns exactly one `cosyvoice-cli --interactive` child. Startup
waits for the REPL prompt, which occurs only after model and prompt
initialization. Requests are serialized because the REPL is single-input. For
each request the node submits one text line, reads the generated audio code,
uses `/save` to produce a temporary WAV, validates it, reads it into the HTTP
response, then removes both the file and the REPL cache entry.

The audited REPL accepts speed only as the process-level `--speed` argument; it
does not expose a `/speed` command. Consequently, requests at the current speed
reuse the loaded process, while a speed change performs a controlled stop and
one restart. A process crash is visible in `/health` with the exit code and
bounded output tail. A timeout terminates the wedged process. The next `/tts`
request attempts clean initialization again.

## Configuration and LAN preparation

Start the node with deployment-specific values; do not commit them:

```powershell
python -m aurora_voice_node --host 0.0.0.0 --port $VoiceNodePort `
  --cli $CosyVoiceCli --model $CosyVoiceModel `
  --prompt-speech $CosyVoicePrompt --backend $CosyVoiceBackend
```

Configure Aurora without changing the default provider:

```json
{
  "voice": {
    "tts": {
      "provider": "remote_cosyvoice",
      "timeout_seconds": 30.0,
      "remote_cosyvoice": {"url": "http://<voice-node-host>:<port>"}
    }
  }
}
```

From the Aurora machine, run the protocol smoke check with the actual URL:

```powershell
python scripts/smoke_voice_node.py --url $VoiceNodeUrl --text "Aurora voice node test"
```

The default server bind is loopback. LAN binding must be explicit. This phase
does not add TLS, authentication, discovery, service installation, or firewall
automation; use only a trusted LAN or an existing secured reverse proxy.

## Streaming upgrade boundary

A later streaming phase should replace only the transport response and playback
consumption boundary. `TTSRouter`, provider selection, Voice Node process
ownership, model/prompt configuration, and error JSON can remain. The current
`SpeechResult` file result and `POST /tts` full-body handling are the specific
non-streaming seams to extend; this phase does not implement that extension.
