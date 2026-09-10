# Aurora Voice Node

This is the minimal, non-streaming HTTP bridge for a separately provisioned
`cosyvoice-cli` runtime. It uses only Python's standard library. Model, prompt,
backend, listen address, and all paths are supplied at launch; none are embedded
in Aurora.

Example (PowerShell placeholders):

```powershell
$Cli = '<path-to-cosyvoice-cli>'
$Model = '<path-to-cosyvoice3-model.gguf>'
$Prompt = '<path-to-prompt_speech.gguf>'
python -m aurora_voice_node --host 0.0.0.0 --port 8765 `
  --cli $Cli --model $Model --prompt-speech $Prompt --backend cuda0
```

For extra CLI tuning, repeat `--runtime-arg`. An extra option beginning with a
dash must use the equals form, such as
`--runtime-arg=--llm-kv-cache-type --runtime-arg=f32`.

The node starts `cosyvoice-cli --interactive` before accepting normal work.
`GET /health` remains available if initialization fails so the reason is
diagnosable. Requests are serialized through the single REPL. The model and
prompt stay loaded while speed is unchanged. Because the current REPL has no
speed command, changing speed performs one controlled process restart. A crash
or generation timeout marks the runtime unavailable; the next request attempts
a clean restart.

The default bind address is loopback. Binding to a LAN interface is an explicit
deployment choice. This phase does not include authentication or TLS, so expose
the port only on a trusted network or place it behind an existing secured
reverse proxy.
