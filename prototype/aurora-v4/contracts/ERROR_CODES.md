# IPC v1 error codes

Error codes are stable machine values. `message` is a short safe summary for
the UI; it is not a traceback. `retryable` describes whether retrying after an
appropriate state change may succeed, not whether Rust should retry
automatically.

| Code | Meaning | Normally retryable |
| --- | --- | --- |
| `PROTOCOL_ERROR` | Invalid ordering, duplicate terminal event, unknown type, or other protocol violation | No |
| `PROTOCOL_VERSION_MISMATCH` | No mutually supported IPC version | No, until components match |
| `AUTHENTICATION_FAILED` | WebSocket upgrade authentication failed | No |
| `INVALID_REQUEST` | Malformed JSON, missing/forbidden field, or invalid value | No |
| `PAYLOAD_TOO_LARGE` | A negotiated bounded limit was exceeded | No without reducing input |
| `BACKEND_NOT_READY` | Sidecar is alive but not ready for the command | Yes |
| `BACKEND_LOST` | Sidecar process/connection disappeared | Yes after restart |
| `PROVIDER_UNAVAILABLE` | Selected provider is unavailable | Yes after configuration/recovery |
| `MODEL_UNAVAILABLE` | Requested model cannot be used | Yes after model recovery |
| `REQUEST_TIMEOUT` | The operation exceeded its deadline | Yes |
| `REQUEST_CANCELLED` | Explicit cancellation won the terminal race | No |
| `INTERNAL_ERROR` | Unexpected backend failure, safely summarized | Possibly |

## Error delivery

The `error` envelope carries `code`, `message`, and `retryable`; applicable
request/session/generation IDs stay in the envelope. Authentication failures
may be rejected during the HTTP upgrade without a JSON frame.

For an accepted generation, `error` supplies safe detail but does not create a
second terminal state. Exactly one subsequent `chat.completed` sets
`terminal_state` to `failed`, `backend_lost`, or `rejected`. For a command that
never became an accepted generation, `error` alone ends that command.

Python traceback, prompt, memory/knowledge content, conversation text,
reasoning text, and credentials never appear in frontend error messages.
