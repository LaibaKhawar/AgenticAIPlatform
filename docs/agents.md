# Agents

## What an agent is here

A declared, bounded capability — not a loop that can decide to do more. Each
agent declares:

```python
config = AgentConfig(
    agent_type=AgentType.INVESTIGATOR,
    role="...",                       # shown in the System UI
    allowed_tools=("get_usage_summary", ...),   # enforced in code
    temperature=None,                 # None = use the configured default
    timeout_seconds=180.0,
    max_retries=2,
    uses_llm=True,
)
```

`validate_against(registry)` runs at construction, so an agent declaring a tool
that does not exist fails immediately rather than at call time.

There is no dynamic capability acquisition, no tool discovery, and no
agent-to-agent conversation. Agents are called by the orchestrator in a fixed
graph.

## The shared system preamble

Every LLM-backed agent inherits five non-negotiable rules:

1. Respond with JSON matching the provided schema. No prose outside the JSON.
2. Never compute or restate a metric that was not supplied. All arithmetic,
   dates, rankings and scores are computed by the platform and given as inputs.
3. Every factual statement must cite the reference id of its evidence. If you
   cannot cite evidence, do not make the statement.
4. Distinguish observed / calculated / inferred. Never write an inference as
   settled fact.
5. If data is insufficient, say so. An honest "insufficient evidence" is
   correct; an invented detail is a defect.

## Planner

**In:** objective + operator parameters. **Out:** `ExecutionPlan`.

Constrained by construction: the prompt lists the exact agent names and task ids
that exist, and `validate_plan()` rejects anything else. The planner cannot
invent a capability, because an invented task id has no executor and is refused.

Parameter extraction (`renewal_window_days`, `max_accounts`, `account_tier`) is
**deterministic regex**, not a model call — "within the next 90 days" is not a
judgement call. Explicit operator controls always win; parsing only fills gaps;
results are clamped to configured limits.

Objective scope is checked against a domain-term list. An out-of-domain
objective is refused with a `422` that explains what the workflow does, rather
than producing a confident churn report about an AWS bill.

## Data agent — no LLM

Candidate selection and metric collection through seven read-only tools. Returns
typed dataclasses.

Notably it reports **explicit data gaps**:

```
No subscription record, so renewal timing and contract value are unknown.
No product-usage history is recorded for this account.
No CSAT responses are available.
No NPS response is on record.
```

These flow into the investigation and the report. Partial data continues with
the gap named, rather than failing or silently scoring the absence as healthy.

## Risk agent — no LLM

Screens every candidate in one batch — five queries regardless of how many
accounts, via `load_bundles()` — and selects the top *N* above the threshold.

The score is documented in `app/analytics/risk.py`:

```
score = 100 · renewal_multiplier · (0.75 · Σ(wᵢ·componentᵢ) + 0.25 · max(componentᵢ))
```

| Component | Weight |
|---|---|
| active user decline (30d vs prior 60d) | 0.22 |
| product usage decline (sessions, or API calls) | 0.14 |
| support pressure (ticket growth + unresolved critical) | 0.14 |
| relationship sentiment (NPS level and drop) | 0.12 |
| billing delinquency | 0.12 |
| support satisfaction (CSAT) | 0.10 |
| seat utilisation | 0.08 |
| feature adoption decline | 0.08 |

Renewal proximity is a **multiplier** (1.18 within 30 days, down to 0.94 beyond
180), not a component: the same health signals are more urgent closer to a
renewal.

Three deliberate properties:

- **Missing data is renormalised, not scored as zero.** Weights are divided by
  the weight actually usable, so absent data neither inflates nor deflates the
  score. `coverage` reports how much was available.
- **Growth never contributes negatively.** A thriving signal cannot subsidise a
  failing one down to zero.
- **The dominant-signal term** lets one severe problem reach MEDIUM alone. See
  the README tradeoffs section.

It is a transparent weighted heuristic, not a trained model, and
`formula_documentation()` says so in the API response.

## Retrieval agent — no LLM

Produces the evidence set an investigation may cite.

```
for each of 4 concern-specific queries (renewal intent, product experience,
                                        relationship, support/billing):
    pgvector cosine search, HARD-filtered to this customer
    dedupe by chunk id, respect the global chunk budget
```

Four queries rather than one so an account with a single dominant issue still
surfaces evidence about the others, instead of returning four near-duplicates.

Also persists one **metric evidence record per risk signal**, tagged
`computed_by: deterministic_risk_engine`. That is what makes a numeric claim
mechanically checkable.

Retrieved content is untrusted: sanitised, injection attempts recorded as
`PROMPT_INJECTION_DETECTED` audit events, and rendered only inside a delimited
block.

## Investigator

**In:** profile, subscription, platform-computed usage/support/billing/NPS, the
deterministic assessment with per-signal detail, known data gaps, and the
evidence block. **Out:** `InvestigationResult`.

Post-return guardrails, in code:

1. Evidence references validated against this run **and this customer**. A
   hallucinated id is stripped; a factual claim left with no citation is dropped
   and recorded in `dropped_claims`, plus a `VALIDATION_FAILED` audit event.
2. The score is clamped to ±15 points of the deterministic score.
3. The risk level is **recomputed** from the final score, not trusted.

Claim typing is enforced by the schema itself: `OBSERVED_FACT` and
`CALCULATED_METRIC` with no citation fail validation before any verifier runs.

## Verifier

**In:** claims with only their own cited evidence. **Out:** `VerificationBatch`.

Independent by construction: a separate call with a separate prompt that never
sees the investigator's reasoning, so it cannot inherit its confidence. It has
**no tools**.

Three stages — programmatic validation, deterministic rules, then model
judgement capped at the rule ceiling. See the README for the full diagram. The
key invariant: **the model may only weaken a claim.**

```python
_STRENGTH = {SUPPORTED: 3, PARTIALLY_SUPPORTED: 2, UNSUPPORTED: 1, CONTRADICTED: 0}
if _STRENGTH[model_verdict] > _STRENGTH[rule_ceiling]:
    verdict = rule_ceiling          # and the reason records that it was capped
```

Final text by status: `SUPPORTED` → the claim as written; `PARTIALLY_SUPPORTED`
→ the verifier's revision, or a deterministically hedged rewrite;
`UNSUPPORTED`/`CONTRADICTED` → **no reportable text at all**.

## Reporter

**In:** verified material only. **Out:** `ReportNarrative` — a title, an
executive summary, portfolio observations, uncertainties and per-account prose.

That schema is the whole point. Scores, rankings, evidence references and the
supported/rejected split are assembled by the application from verified rows, so
the reporter **cannot** reorder accounts, invent a number, or resurrect a
rejected claim. Narrative prose is appended to verified conclusions, never
substituted for them.

Output is persisted as structured JSON and Markdown, with an evidence appendix.

## The deterministic fake provider

`app/llm/fake_provider.py` is a **scripted model**, not a stub. It derives
output from the real inputs — computed signals, retrieved evidence text, the
verification rules — which is what makes the offline test suite meaningful.

| Operation | Behaviour |
|---|---|
| `plan` | the canonical DAG, shaped by the resolved parameters |
| `investigate` | risk factors from material signals; calculated-metric claims citing the metric evidence rows; observed-fact claims from the most salient sentence of retrieved documents; one hedged inference |
| `verify` | the deterministic rules in `app/analytics/claim_rules.py` |
| `report` | narrative assembled from the verified material it is handed |

Two behaviours are deliberate and documented:

1. **One over-reaching claim per investigation** when the evidence contains an
   exploratory intent signal. The claim asserts a settled cancellation decision,
   and the verifier is expected to reject it. This keeps the
   hallucination-mitigation path on the happy path of every demo and test run
   rather than only in unit tests.
2. **Pure function of its inputs**, so the same run produces the same report
   twice — which is what lets the evaluation harness attribute changes to code
   rather than sampling noise.

Its "judgement" is rules, not language understanding. Verification quality
figures measured with `LLM_PROVIDER=fake` measure the rules.

## Structured output handling

```
attempt 1 → provider → validate against the Pydantic model
    valid   → return
    invalid → log validation failure, re-prompt with the error appended
attempt 2.. → up to LLM_STRUCTURED_OUTPUT_RETRIES
exhausted   → StructuredOutputError (permanent; the task fails with the reason)
```

Transient provider failures are retried separately, with backoff, inside the
same call. Malformed JSON is never silently accepted.

Every call records provider, model, operation, tokens, latency, attempts,
validity and estimated cost to `llm_calls`.
