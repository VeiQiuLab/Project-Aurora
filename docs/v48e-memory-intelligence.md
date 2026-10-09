# V4-8E — Companion Memory Intelligence & Context Enrichment

Starting revision: `e923e2a91c80fc615d60514b7311b3661c49801b` on `refactor/aurora-v4`.

This stage improves the existing Python candidate and retrieval paths. Memory CRUD,
coordinated persistence/recovery, approval, ranking/freshness, Persona, ContextBuilder
and post-turn scheduling already existed. No new store, schema, model or UI is introduced.

## Implemented behavior

- Extract complete, explicit user statements instead of detached regex groups. Keep
  the quoted evidence, role, message index, named subject/property and originating
  conversation/generation IDs in existing `source_detail` metadata.
- Direct analysis uses the same user-only extractor. Questions, tentative plans,
  temporary statements, sensitive values and oversized statements are withheld.
- Keep the latest scalar user fact in the current batch, including A → B → A
  corrections. Replaying a rejected exact statement does not regenerate it.
- Deduplication distinguishes subjects and properties; lexical similarity cannot
  erase a changed name or stage. An inactive old value can be proposed again as a
  correction of the active value. Candidate-record queueing preserves approval and
  rejection history. All these paths remain pending-only.
- Named person/project recall requires that subject, with exact ASCII name boundaries.
  A short follow-up can inherit the nearest explicitly named user topic within the
  last three user statements. Assistant assertions cannot supply that topic or facts.
- Withhold duplicate current-conversation facts, recognized scalar contradictions,
  older facts corrected by the user, and personal records in unrelated knowledge
  questions. Existing active/enabled filters, ranking weights, relevance threshold,
  freshness and injection count still apply.
- Preserve the existing Persona and structured chat history. Approved memory carries
  an explicit priority policy: current user instructions, then new conversation facts,
  then relevant approved memory. It is reference context, not a new instruction source.
- Apply the existing ContextPolicy memory allocation even when optional RAG is off.
  Count UTF-8 bytes conservatively, including the priority policy, and retain complete
  records, including multiline records; RAG fragments are withheld. Do not increase the context window or injection count.

## Reproducible evaluation

`tests/memory_quality_corpus.py` contains 18 synthetic cases with exact expected
candidate contents and retrieved IDs. `tests/test_companion_memory_quality.py` adds
isolated approval, correction, rejection/repetition, attribution, history, contradiction
and bounded-format checks. No real user profile is written by these tests.

Run the related Python tests with the repository virtual environment. The existing
Sidecar context/post-turn, conversation persistence/streaming, Memory governance and
concurrency/recovery suites are also regression gates.

The fixed corpus improved from 9/18 to 18/18 matching cases. Candidate precision
here means complete content matching the declared expected fact, including its
subject; it is not a standardized semantic benchmark. Exact precision was 0.20 → 1.00,
candidate recall 0.167 → 1.00, relevant recall 0.75 → 1.00, unwanted recalled IDs 4 → 0.
Duplicate rate within this corpus remained 0. Separate tests cover repetition across
conversations and after approval/rejection. These numbers do not establish general
natural-language memory accuracy.

Runtime and closeout evidence are saved under `tests/output/v48e/`, including the
final report, baseline protection hashes, before/after results, isolated context timing,
actual Release/4B observations and normal-exit process inventory. Native Computer Use
observations are distinct from controlled WebView checks and human acceptance.

## Limits retained

Extraction and scope recognition are conservative bilingual rules. Complex names,
pronouns, paraphrases, multi-property facts and arbitrary semantic contradictions are
not fully resolved. Old records with missing subjects are not migrated or rewritten.
Uncertain plans are withheld rather than inferred. A rejected exact fact stays withheld;
this stage adds no reconsideration UI. Tiny memory allocations may omit the memory
block entirely. Existing RAG optimization and total-history/knowledge policies remain
unchanged. A bounded runtime observation cannot prove absence of all long-term leaks.

Voice Full Manual Matrix **NOT COMPLETED**; G01 percentage pronunciation **Major**;
**LEGAL REVIEW RECOMMENDED** (including existing ORT obligations);
Packaging / First-run **NOT COMPLETED**. No V4-8F work is authorized by this stage.
