# Security

The effort here is concentrated on the agent and tool boundary and on state
integrity — the places where an AI system actually goes wrong — rather than on
building an identity platform.

## Threat model

| Threat | Mitigation |
|---|---|
| Model fabricates a fact | Every material claim cites evidence by id; ids validated against the rows retrieved for this run **and this customer**; uncited factual claims dropped before verification |
| Model upgrades certainty | Deterministic rules veto a settled-decision claim the evidence does not support; the model cannot override a veto |
| Model invents a number | All arithmetic in Python; numbers absent from the evidence downgrade the claim |
| Prompt injection in customer data | Detection, neutralisation, audit events, delimited untrusted-data block, no write tools |
| Agent reads another customer's data | Vector search filters by customer in SQL; verification discards cross-customer evidence; cross-customer document fetch returns 404 |
| Agent takes an unauthorised action | No SQL/shell/filesystem/HTTP tools; per-agent allow-lists enforced in code; tool-call budgets |
| Unsafe action executes without review | Deterministic approval policy; an LLM cannot decide review is unnecessary |
| Secret leakage via logs | Key-pattern redaction before any sink |
| Runaway cost or infinite loop | Bounded plan size, tool calls, retrieval chunks, retries, concurrency, prompt and objective size |
| Data loss from a test run | The suite refuses to truncate anything but a `*_test` database |

## The agent boundary

```
Agent ──> ToolInvoker ──> ToolRegistry ──> handler ──> Repository ──> PostgreSQL
             │                 │
             │                 └─ validated Pydantic input, typed output,
             │                    access class, timeout, retry policy
             └─ allow-list check, call budget, span, structured log
```

**What does not exist** is as important as what does: no SQL tool, no shell
tool, no filesystem tool, no arbitrary-HTTP tool, no code execution. A model
cannot author a query. A unit test asserts no registered tool name contains
`sql`, `shell`, `exec`, `http`, `eval`, and that the only `SENSITIVE_WRITE`
tool is `propose_customer_action` — which creates an approval record and never
acts.

Permission failures raise `ToolPermissionError`, which is **permanent** — never
retried.

## Prompt-injection defence

The dataset ships ~47 documents containing real injection attempts, so this
path is exercised on every run rather than only in a unit test.

Four layers:

1. **Structural.** Retrieved content appears only inside
   `<<<UNTRUSTED_CUSTOMER_DATA … UNTRUSTED_CUSTOMER_DATA>>>`, which the system
   prompt declares to be data that can never change the task.
2. **Detection.** Seven pattern families: instruction override, role hijack,
   system-prompt spoofing, tag spoofing, output coercion, exfiltration, tool
   coercion.
3. **Neutralisation.** Matched spans are replaced with
   `[instruction-like text removed]` — a visible marker, not a silent deletion,
   so a reviewer can see something was there. The evidence card in the UI shows
   an "Injection attempt neutralised" badge.
4. **Delimiter hygiene.** Content cannot close or reopen the block.

Detections are recorded as `PROMPT_INJECTION_DETECTED` audit events with the
document id and pattern names.

**What this does not claim.** Pattern matching will miss novel phrasings. The
real guarantees are structural: the agent has no write tools, and every claim is
verified against evidence before it can appear in a report. A successful
injection could at worst distort a *claim*, which verification then checks
against the same evidence. A unit test also asserts that ordinary business
language — "we must always escalate reporting bugs" — is **not** flagged,
because a defence that fires on every real document is useless.

## Data isolation

- Vector search takes `customer_id` as a hard SQL predicate.
- The verifier discards evidence whose `run_id` or `customer_id` does not match
  the claim, and marks the claim `UNSUPPORTED` if nothing survives.
- `GET /customers/{id}/documents/{doc_id}` returns 404 when the document
  belongs to another customer.
- The evaluation harness measures `customer_scope_precision` and treats
  anything below 1.0 as a defect.

## Secrets

Only from the environment. `.env` is git-ignored; `.env.example` contains no
real values. Redaction covers `api_key`, `apikey`, `secret`, `password`,
`passwd`, `authorization`, `credential`, `private_key`, `bearer`, any key ending
`_token`, and the bare keys `token` / `key` / `auth`.

Deliberately **not** redacted: `prompt_tokens`, `completion_tokens`,
`total_tokens`. An over-broad "token" match destroyed the cost telemetry this
system promises — a real bug, now covered by a test asserting both directions.

## API surface

- Request body size capped (`API_MAX_REQUEST_BYTES`, default 256 KB) → `413`.
- Page size capped (`API_MAX_PAGE_SIZE`) regardless of what the client asks.
- Objective length bounded both by Pydantic and by the planner.
- Malformed UUIDs return `404`, not `500`.
- Validation errors return a structured list of field-level problems.
- Unhandled exceptions return a generic payload; the detail goes to the log.
- CORS from `CORS_ORIGINS`; methods limited to `GET`, `POST`, `OPTIONS`.
- `X-Request-ID` echoed or generated, and bound into every log line.

## Authentication — honest scope

A pragmatic development boundary: when `API_KEY` is set, every `/api/v1`
request must send `X-API-Key`. Health and docs stay public so orchestrators can
probe them.

It is **one dependency** (`app/api/deps.require_api_key`) attached at router
level, so production auth replaces a single function rather than touching 33
endpoints. What does not exist: users, roles, sessions, per-user permissions,
tenant isolation, row-level security, audit attribution to a real identity
(`reviewed_by` is a free-text field).

This was a deliberate scope decision — building an identity platform would have
consumed the effort that went into the verification pipeline, which is where
this system's actual risk lives.

## Container hardening

Both images run as a non-root user (uid 10001). The backend image contains no
build toolchain; the frontend uses Next's `standalone` output, so it ships the
traced runtime dependencies rather than all of `node_modules`.

## Production checklist

- [ ] Replace the API-key boundary with real authentication
- [ ] `APP_ENV=production` (hard-disables failure injection)
- [ ] Rotate the PostgreSQL password; use a secret manager
- [ ] TLS termination in front of both services
- [ ] `CORS_ORIGINS` restricted to real origins
- [ ] Managed PostgreSQL with backups and PITR
- [ ] Redis with auth and persistence
- [ ] Ship logs to a sink with retention; enable OTEL
- [ ] Review `MAX_PARALLEL_INVESTIGATIONS` against the provider's rate limits
- [ ] Add tenant scoping before multi-tenant use
