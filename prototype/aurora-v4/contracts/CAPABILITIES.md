# IPC v1 capabilities

Capabilities are returned by `hello_ack` and `health.response`. They describe
the running sidecar build/configuration; Rust must not infer features from a
provider name or from files on disk.

```json
{
  "chat_streaming": true,
  "chat_cancel": true,
  "memory": true,
  "knowledge": true,
  "rag": true,
  "voice": {
    "ipc": false,
    "edge_tts": true,
    "cosyvoice_remote": true,
    "cosyvoice_local": false,
    "streaming_pcm": false
  }
}
```

Top-level booleans mean the feature is callable through the v1 gateway in the
current runtime. A false value may mean unsupported, disabled, or unavailable;
health details may later distinguish those cases.

`voice.ipc` gates all voice operations. The remaining voice booleans are an
inventory for migration planning until `voice.ipc` becomes true. They do not
make a v1 `voice.*` command legal. Stable Aurora implements Edge TTS and Remote
CosyVoice providers, so a compatible sidecar build may report those as true.
There is no LocalCosyVoiceProvider; `cosyvoice_local` must be false. The mere
existence of a reserved router name is not a capability.

`streaming_pcm` refers specifically to binary PCM across the v4 sidecar IPC,
not to Python's existing internal playback pipeline. It remains false in V4-1.

## Negotiated limits

`hello_ack` and health also return positive integer limits:

- `json_frame_max_bytes`
- `chat_input_max_bytes`
- `event_max_bytes`
- `binary_frame_max_bytes` (reserved for future voice transport)

Implementations must enforce bounded limits and use the lower applicable peer
limit. Exact defaults remain **TBD for V4-2 measurement**; V4-1 does not invent
numbers claimed to be production-safe. The handshake cannot become `READY`
unless concrete values are supplied by the implementation.

Unknown capability keys may be ignored for forward compatibility. Unknown
message types are not enabled merely because an unknown capability exists.
