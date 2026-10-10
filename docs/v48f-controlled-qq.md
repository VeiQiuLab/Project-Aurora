# V4-8F — Controlled QQ messaging

Starting revision: `6c9cf64d7b29f9069fd2b41b5154dad0af101462` on `refactor/aurora-v4`.

**V4-8F STATUS: HOLD**

This is an authorized WIP development checkpoint, not a Final PASS. It preserves
the existing QQ integration, Authorized Automatic, short-term context repair,
Group Archive Step 1, connection/input fixes, and opt-in balanced participation.
The checkpoint adds no functionality and does not enter Step 2 or V4-8G.

## Acceptance summary

| Evidence | Current result and boundary |
|---|---|
| Manual real QQ reply | Delivery verified; preview and explicit confirmation used |
| Authorized Automatic real QQ reply | Delivery verified in the authorized test group |
| Native @mooncell recognition | Verified against authenticated numeric self_id; nickname is only display/optional text trigger |
| Short-term QQ context isolation regression | PASS for sender/group/source isolation and actual LLM request history |
| QQ Group Archive Step 1 isolated tests | PASS; not whole-stage or real archive acceptance |
| Local Chinese history retrieval | PASS with isolated records |
| Release restart retrieval | PASS with isolated persisted records |
| Owner private Memory isolation | PASS in isolated tests |
| Repaired real QQ continuous followups | NOT FULLY VERIFIED |
| Real QQ non-@ archive reception | NOT VERIFIED |
| Complete real QQ safety acceptance | NOT COMPLETED, including multi-speaker live evidence |
| Balanced participation | Isolated engineering evidence; real group quality NOT VERIFIED |

Detailed run logs, private live evidence and runtime artifacts remain local under
the ignored `tests/output/v48f/` directory. They are not public release artifacts.
Automated and isolated results cannot substitute for outstanding real QQ gates.

Checkpoint quick regression (2026-10-10): Python QQ/archive/IPC contracts **113
passed**, existing QQ/production/context/post-turn regression **76 passed**,
Rust Desktop **76 passed / 2 existing ignored**, frontend **47 passed**, TypeScript
type check passed, and QQ browser UI **41 checks passed**. The browser checks
include polling while typing, disconnect/reconnect controls, Manual confirmation,
Automatic/natural toggles and archive operations. All test identities and message
bodies are synthetic; realistic-length typing fixtures were sanitized before
publication. No real QQ acceptance, Release rebuild, voice soak or manual matrix
was repeated for this checkpoint.

Public checkpoint contents are limited to source, tests and this maintained stage
document. Runtime databases, exports, personal configuration, credentials, login
artifacts and raw reports remain excluded by the existing ignore rules. The shared
IPC coverage assertion includes the existing Memory Write definitions so that its
all-message coverage remains valid when checking the added QQ contracts; this
does not change Memory behavior.

The Desktop settings entry **Integrations / QQ** owns an explicitly enabled
session. It never starts the legacy automatic-reply connector. Rust forwards
validated typed commands over its existing authenticated Sidecar channel;
Python owns the protocol adapter, bounded external histories and reply drafts.
The existing Rust-supervised local model is reused. No additional model process,
Memory store, voice route or Avatar operation is introduced.

## Local configuration and ownership

Configure these environment variables before launching Aurora:

- `AURORA_QQ_HTTP_URL`: optional independent OneBot HTTP endpoint. Leave unset for WS-only APIs.
- `AURORA_QQ_WS_URL`: authenticated OneBot forward WebSocket endpoint (events and optional API calls).
- `AURORA_QQ_TOKEN`: nonempty bearer token configured on the configured bridge.

Only explicit numeric loopback hosts `127.0.0.1` or `::1` are accepted. Proxy
use and HTTP/WebSocket redirects are disabled. Token and endpoint values do not
cross the Rust-to-WebView interface or appear in ordinary diagnostics. There
are no fallback addresses or connections to QQSuggestionBot. Aurora neither
reads its credentials nor changes its files, database, configuration or service.

The protocol boundary reuses existing event adaptation and the OneBot client
class, with strict action response handling and the already installed asynchronous
WebSocket runtime. It checks the authenticated API account identity against each
event's `self_id`, validates top-level sender/group/message/time fields, and
rejects inconsistent nested sender identities. Nicknames never determine targets.

Authorized groups also accept a plain-text `@` followed by the authenticated
account's current display name (case insensitive, with ASCII word boundaries).
The login API supplies this trigger name again on reconnect. It grants no new
source permission: numeric account/group/sender checks, Automatic consent,
queues, rate limits and duplicate protection still apply. A display name without
`@`, another name, an email address or a longer handle is not this trigger.
Quote-reply reference metadata may accompany text; it never loads quoted content
or grants mention/authorization by itself. Original archive events are retained.

## Optional balanced participation

The independent **偶尔接话** control defaults off and requires an active
Automatic session, the same verified identity and its exact group allowlist.
Five fresh ordinary text events from at least two members within two minutes,
with a substantive question/planning topic, may initiate one silent-or-reply
decision using the existing model. Busy work/queued replies take priority.
Only the latest six short snippets of that group are supplied, with speaker QQ
IDs; no private Memory or other group/archive is queried for this decision.
Strict JSON with an empty reply means silence. Invalid output, mentions and
overlong/more-than-two-sentence output are never sent. Public supplements are
at most 180 characters, one per group per ten minutes, at most two per hour
across all groups; even silent decisions wait two minutes before reconsidering.
Explicit replies also start the natural-participation group cooldown.
Disconnect/Automatic disable revoke participation; its own disable cancels
pending automatic work while keeping future explicit @ replies enabled.
Reconnect retains cooldowns but drops the recent activity and old jobs.
Restart defaults off. These are frequency/format guarantees, not a guarantee
that every model-selected contribution is socially appropriate; real group
quality remains an acceptance item. No intentional replay or random timer posts.

Protocol references: [OneBot HTTP API](https://github.com/botuniverse/onebot-11/blob/master/communication/http.md),
[forward WebSocket](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md),
[send actions](https://github.com/botuniverse/onebot-11/blob/master/api/public.md).

## Reception and context

External messaging is disabled on every process start. Explicit private/group
allowlists exist for the enabled session only. Explicit group replies require an
@mention of the verified account, its current display-name text trigger, or a
configured prefix. Optional balanced participation is separately authorized as
described above. Unauthorized reply bodies are discarded before parsing or
retaining reply content; self messages and message-sent events cannot trigger
replies. Separately authorized archive reception runs before these reply filters.
Only segment-array plain text is supported. Authorized triggered media is shown
as Unsupported, without keeping its media data. String/CQ events are rejected
because their media/mention semantics are not unambiguous for this boundary.

The external context key includes account, source type, conversation ID and sender
ID. Local, private, different-group and same-group different-sender histories
cannot mix. External generation shares the existing model ownership gate and
uses `DirectChatAdapter`, streaming handles and transport cancellation. It uses
a fixed minimal public system instruction with trusted numeric source/sender attribution; it does not call owner Context/RAG,
ConversationPersistence or Post-Turn extraction. Third-party content is neither
owner Memory nor a Memory Candidate. Local Memory features remain enabled.

The QQ public instruction explicitly permits factual followups from the supplied
same-source, same-sender user/assistant history. This is short-term conversation
context, not owner long-term Memory. Missing or expired facts are unknown; external
history remains untrusted data and cannot grant permissions or change instructions.
The recovery regression exercises event parsing through DirectChatAdapter and the
actual llama HTTP request body, including sent-only history, bounded eviction,
other senders/groups/private sources and unsent/cancelled drafts. A separate
isolated supervised 4B corpus checks answer quality; a mocked SSE reply alone
does not prove factual recall.

Only successfully sent user/assistant pairs enter RAM history. Cancelled and
unsent drafts do not become past replies. There are at most eight current message
records, eight external histories of eight messages (four completed pairs), 2,048 input characters and 4,096
preview characters per record. Generation previews above the bound are truncated.
The 4,096-entry receive dedup window survives reconnect within the process.
Reconnect discards drafts and queued jobs and accepts only events from its new
connection time onward. Sent RAM history survives transient reconnect with the same
verified account. Backoff is 1/2/4/8/16/30 seconds, capped at 30 seconds, with no
artificial retry-count cutoff; authentication failure requires explicit retry.
An account change revokes Automatic and clears histories. Disconnect and Sidecar shutdown join generation,
close the event socket and clear external session state.

## Explicit send boundary

In Manual mode, selecting a received message and generating a reply never invokes a send action.
The user can edit, save or cancel the preview. **Check and send…** obtains a fresh
backend-issued confirmation bound to the immutable received source and exact
reply revision. The confirmation shows target, sender, original message ID and
reply text. **Confirm this one message** consumes the token. A changed reply,
selected source, disconnect or cancelled preview invalidates its UI confirmation.
The backend independently checks connection, source authorization, current
revision, confirmation and single-send receipt. It accepts no arbitrary recipient
field from the frontend or model. Explicit OneBot text segments keep generated
CQ strings literal and cannot become media or @all operations.

`qq/send_receipts.sqlite` in Aurora's user-data root retains only a hashed source
key and attempt state, never QQ bodies, drafts, token or endpoint. SQLite
`BEGIN IMMEDIATE` plus a FULL-synchronous committed attempt reserves the send
before the network action, including competing processes. A successful result
must include a valid protocol message ID. Duplicate successes are blocked.
Explicit protocol rejection permits a new user confirmation and retry; it never
retries automatically. Timeout, malformed response, interrupted process or
failure to persist the outcome is ambiguous and blocks further sends for that
source message. Recovery fails closed on an `attempting` tombstone. There is no
claim of exactly-once delivery: OneBot 11 has no transactional send receipt or
idempotency key. The user must check QQ after an unknown outcome.

## Authorized Automatic continuation

Manual remains the default, including all private chats. A separate explicit
consent control and **Enable Authorized Automatic** command bind the currently
verified account to a nonempty subset of explicitly authorized controlled test
groups. Enabling never schedules already received messages. New @account,
display-name text triggers or configured-prefix messages in those groups enter
the auto worker; separately enabled balanced participation may also enqueue a
bounded decision. Changing
accounts, explicit disconnect, or process restart revoke Automatic. No schedule,
sleep/fatigue personality, additional Sidecar/model, or Windows power change exists.

The Sidecar owns the worker while settings/chat are closed or hidden. One shared
model reservation serializes all external generation; a busy local model makes
the auto worker wait. A runtime/generation failure drops old queued jobs and
pauses processing; a new triggered event can check recovery. No old backlog is
resent after reconnect or runtime recovery. Group round-robin scheduling keeps
FIFO within groups and senders, with at most six queued jobs and two jobs per
group including an active job. Explicit-reply queue lifetime is 180 seconds;
balanced-participation jobs expire after 30 seconds. Visible source
records owned by queued/generating/sending operations cannot be evicted.

Send attempts are limited to one per three seconds globally and one per ten
seconds per group, plus at most three replies per sender conversation per minute.
The worker emits only literal text, without mentions, and ignores self events,
message_sent events, duplicates, and exact echoes of retained same-group sent replies.
These gates prevent self-reply and bounded reply storms; arbitrary other bots
cannot be identified from ordinary text alone. Flood overflow stays Manual or is
dropped from the bounded recent list; it is never silently queued for later.

**Immediately disable Automatic** synchronously revokes admission before waiting
for command locks, invalidates queued/in-flight generation epochs and joins the
worker. An already-admitted network send cannot be recalled; its outcome is
settled before disable acknowledgement, and no following job is sent. Unknown
outcomes are never automatically retried. Manual drafts outside auto jobs remain
usable. Auto replies use the same durable receipt and source-bound send boundary,
with explicit backend authorization replacing the one-message Manual nonce.

## Targeted reuse comparison

Read-only source inspected: QQSuggestionBot's `index.js` and installed
NapCat's `napcat.mjs` (no SuggestionBot configuration, database or
credentials read). SuggestionBot uses authenticated forward WS, per-connection
echo-correlated API requests, group/sender/message identity, bounded in-memory
dedup/history, self filtering, timeout/unknown-send handling, and closes its store
on disconnect. Its source does not implement a long-lived reconnect loop.

| Capability | Reuse / ownership |
|---|---|
| NapCat login and OneBot protocol | Reuse existing bridge; no new QQ login protocol |
| Event parsing and protocol data | Reuse Aurora's existing message_adapter and OneBotClient boundary |
| WS receive + API correlation | Same standard protocol; owned asyncio transport required for Sidecar lifecycle |
| Suggestion commands / SQLite suggestion records | Independent bot responsibility; never imported or modified |
| Aurora preview, authorization, external context, model queue, receipts | Aurora responsibility; cannot safely delegate to suggestion bot |
| Shared source framework | Unnecessary; no cross-project imports or framework introduced |

Installed NapCat's `gO.createServer` maintains independent clients; `onEvent`
broadcasts to every event client and `handleMessage` sends API responses back to
the requesting socket with echo. Closing a client removes only that client. This
source supports independent consumers, not stealing one event connection. Two
independent simulated authenticated clients also receive the same event and
closing one does not affect the other. Each consumer must still filter its own
triggers and identity; real runtime coexistence remains a separate acceptance gate.

User authorized a second consumer and identified a controlled test target in the
current session. Actual account/group availability must be verified against the
running bridge, not inferred from its config file. The tested bridge uses WS-only
APIs. Local bridge setup and phone authentication were completed separately;
credentials, QR sessions and machine-specific diagnostics remain local. Real authenticated API checks
verified the account, controlled group, and bot membership. Aurora and an
independent read-only receiver received the same authorized event. Real Manual
delivery and three Automatic deliveries were subsequently observed in the native
QQ client. The initial live recall answers were inconsistent, so those successful
deliveries did not close acceptance. Current recovery evidence and any outstanding
live gates are recorded in the final report; old no-event checkpoints are historical.
Bridge authentication must be verified anew before each live run. No SuggestionBot connection/service
was changed. Official protocol guidance: [NapCat integration](https://napneko.github.io/use/integration),
[OneBot WS](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md).

## Evidence and limits

Formal evidence: `tests/output/v48f/v48f-final-report.md`. Synthetic protocol and
isolated Desktop checks prove engineering behavior, not live QQ delivery.
Live delivery, continuous factual followups and safety acceptance must all close
before the stage is PASS. If a second real test speaker is unavailable, isolated
sender-separation checks remain engineering evidence and do not count as a
completed multi-speaker live test. Preserve HOLD for any missing required gate;
do not commit or push a PASS closeout until those gates are satisfied.

No unrestricted auto-reply, mass send, group administration, login protocol, multi-account
management, external Memory extraction, packaging or first-run setup is included.
Voice Full Manual Matrix remains NOT COMPLETED; G01 percent pronunciation remains
Major; LEGAL REVIEW RECOMMENDED and Packaging / First-run NOT COMPLETED remain.


## Memory extension Step 1: persistent QQ group archive

This extension is independent of the outstanding V4-8F live QQ acceptance gate.
No group is recorded by default. Settings > QQ > 本地群聊档案 displays the
recording/retention/privacy notice and requires a fresh explicit consent check
for the selected group. Initial use is limited to the owner-authorized test group;
the operator must notify its members before enabling. Recording and Authorized
Automatic are separate authorizations. Enabling one never enables the other.

The existing Sidecar stores `<user-data>/qq/group_archive.sqlite`, separate from
private Memory, Memory Candidates and local chat storage. It uses SQLite WAL,
FULL synchronous commits, BEGIN IMMEDIATE writes, foreign keys and group/sender
chronological indexes. No other runtime or database service is introduced.

| Table | Stored fields and purpose |
|---|---|
| groups | account_id + group_id primary key, enabled recording policy, revision, authorization time |
| messages | hash key; platform, account/group/sender QQ IDs; display-name snapshot; original message ID/time/type/text; selected message segments; ingestion time; account/group/message unique constraint |
| relations | hashed parent/child message keys for explicit replies and runtime reply provenance |
| suppressed | hashed message keys only, preventing deleted/withdrawn records from reappearing on replay |

Authorized delivered group events enter the archive before mention filtering,
self filtering, LLM text limits, reply freshness or automatic admission. Non-@
messages and the account's own replies are retained without generating another
reply. Runtime successful-send acknowledgement records its returned message ID;
bridge echo deduplicates to the same record. Existing raw text, whitespace and
text segments are preserved. Mention/reply IDs are retained. Unsupported media
stores its segment type only; no asset download, URL/file secret metadata or
bridge credentials are retained. Mixed media/text is visibly distinct from text.
Bounded receive backpressure replaces silent queue overflow; controlled disconnect
drains already-queued events for archive-only processing, never generation/send.

There is no TTL, relevance filter, automatic history deletion, summary substitution
or automatic compression. The short reply window does not remove disk records.
SQLite index rebuild leaves originals intact. Lossless export streams full records
and selected segments into an exclusively-created profile-local JSONL, flushed
before completion rename; partial failure is not reported as completed. Export
path is generated by the backend; arbitrary file paths are not accepted by IPC.

Query authorization always binds both account and group. Optional sender QQ ID,
inclusive epoch-second interval and literal Unicode substring filters support
Chinese short names/words without relying on English tokenization. UI pages hold
at most 20 rows, with explicit 2048-character previews; full raw text remains on
disk/export. Neighbor lookup returns at most two records before and after the
selected record within the same group. There is no vector database or semantic
search in this step.

Public QQ Context Assembly may use at most four 500-character excerpts from the
currently authorized account/group/current sender, plus its existing bounded QQ
conversation history. Name/plan cues prefer matching recent records, then a few
recent records. Excerpts are explicitly untrusted data, never tool/authorization
instructions. No private owner Memory or other speaker/group is read. This is a
minimal factual-history aid, not complete long-history reasoning or a guarantee
that the 4B model will phrase every answer accurately.

The trusted local settings UI alone can export and request deletion. Delete is
prepare -> explicit confirmation -> one-use source/scope/revision-bound token;
stale/conflicting requests safely reject. Scopes are one message, one sender QQ
ID, or the whole group (also disables new recording). An AI/group message cannot
approve deletion. Member privacy requests must be explicitly handled by the
operator through the sender control; free-text requests are not automatic commands.
Received OneBot group_recall notices remove the source and known related replies,
clear that group's RAM context/cancel pending output, and install replay tombstones.
The normal privacy deletion path does the same. Already-admitted network sends,
existing backups and exported files cannot be erased by this operation and need
separate explicit handling. Disabling recording alone keeps the existing authorized
archive readable; it stops new records, not past authorized retrieval.

Read/write/permission failures expose QQ_ARCHIVE_FAILED separately from transport
status and prevent archive-context generation from silently using failed reads.
Received recall processing first persists a body-free account/group/message-ID
intent in a profile-local privacy JSON journal using flush/fsync and atomic
replacement. The existing single owned Sidecar event loop is its writer. Once
intent is durable, crash before or after the SQLite commit is safely replayable;
completion removes the intent only after the commit. Failed
recall clears RAM context immediately and blocks retrieval until successful retry. It is not possible to backfill events never delivered
while the bridge is offline, or recover every unsaved event after a storage failure.
Restart loads pending privacy intents and resolves them before query/export
or model access; invalid journals fail closed. If disk failure also prevents
writing the privacy intent itself, no software can claim that event persisted;
the operator must reconcile missed privacy notices after repairing storage. Secure-delete
plus tombstones excludes removed rows from future retrieval; it is not a claim of
forensic erasure of SSD pages, WAL history, backups or existing exports. No backup,
media reconstruction, automatic recovery from disk exhaustion, multi-year query
benchmark or live QQ archive acceptance is claimed.

Step evidence is retained locally in the ignored
`tests/output/v48f/qq-group-archive-step1-report.md`. Isolated simulator/Release
results do not close REAL QQ ACCEPTANCE NOT VERIFIED. The later authorized safe
Git checkpoint may commit/push reviewed source, tests and this sanitized document
with HOLD unchanged; it cannot declare Final PASS or enter Step 2 / V4-8G.
