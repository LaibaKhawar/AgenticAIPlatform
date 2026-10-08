# Evaluation

`make evaluate`, `POST /api/v1/evaluations/run`, or the **Evaluation** page.
Results are persisted to `evaluation_runs`.

> Every number is computed from the synthetic dataset this repository generates.
> They measure the implementation, not real-world churn prediction. The risk
> model is a transparent weighted heuristic and was never fitted on data.
> The harness exists to measure, not to flatter — it reports what the code does.

## Three families

### 1 · Ranking quality

**Question:** can the deterministic risk model find the accounts that actually
churned?

Each labelled customer is scored **as of its own outcome date**, so the model
only ever sees pre-outcome behaviour. It never reads `customer_outcomes` or
`scenario_persona`.

| Metric | Definition |
|---|---|
| `roc_auc` | Mann-Whitney U with tie handling. 0.5 = chance. |
| `average_precision` | Area under precision-recall; rewards early hits. |
| `at_k.{k}.precision` | Of the top-k scored accounts, the fraction that churned. |
| `at_k.{k}.recall` | Of all churned accounts, the fraction in the top k. |
| `at_percentile.{p}.lift` | Precision in the top p% ÷ base rate. |
| `mean_score_positive` / `_negative` | Mean score by actual outcome. The gap is the signal. |
| `score_distribution` | min / p25 / median / p75 / max / mean. |

Positives are `CHURNED` and `DOWNGRADED`; negatives are `RENEWED` and
`EXPANDED`.

**Measured:** ROC-AUC **0.841**, AP 0.650, precision@25 **0.96**, lift@5%
**3.93×**, mean score 34.2 (churned) vs 15.4 (renewed).

AUC 0.84 rather than 0.99 is the intended result. The dataset deliberately
contains a false-positive persona that looks alarming and renews, and a
quiet-disengagement persona that looks fine and churns. A perfect score would
mean the data was trivially separable and the evaluation worthless.

### 2 · Retrieval quality

| Metric | Definition |
|---|---|
| `customer_scope_precision` | Fraction of retrieved chunks belonging to the queried customer. **Must be 1.0.** |
| `risk_relevant_chunk_rate` | Fraction containing a risk keyword. A proxy, not ground truth. |
| `accounts_with_risk_signal_rate` | Fraction of sampled churned accounts where retrieval surfaced at least one risk-relevant chunk. |
| `mean_relevance_score` | Mean cosine similarity. |
| `accounts_with_no_matches` | Accounts where retrieval returned nothing. |

`customer_scope_precision` is a **correctness gate, not a quality metric**:
anything below 1.0 means the customer filter leaked another account's documents,
which is a security defect. The UI renders it red if it ever drops.

**Measured:** scope precision **1.000**, risk-relevant chunk rate 0.781,
accounts with a signal 0.920, mean cosine 0.03 (local embedder).

The low absolute cosine is expected and honest: with hashed bag-of-features
embeddings, a short query against a long document yields small similarity
values. *Ranking* carries the meaning — which is what
`risk_relevant_chunk_rate` measures. Switch to
`EMBEDDING_PROVIDER=openai` for meaningful magnitudes.

### 3 · Workflow quality

Computed from the runs that have actually executed.

| Metric | Definition |
|---|---|
| `completion_rate` | Completed ÷ terminal runs. |
| `avg_duration_seconds`, `p95_duration_seconds` | Wall-clock, completed runs. |
| `tasks_retried`, `retry_recovery_rate` | Retried tasks, and the fraction that then completed. |
| `llm_calls`, `total_tokens`, `avg_tokens_per_call`, `estimated_cost_usd` | From `llm_calls`. |
| `invalid_structured_outputs` | Calls that never produced schema-valid output. |

#### Claim metrics — the ones that matter

| Metric | Definition |
|---|---|
| `claims_with_valid_evidence_rate` | Claims with at least one surviving evidence link. |
| `supported_rate` / `partially_supported_rate` / `rejected_rate` | Post-verification split. |
| `unsupported_before_verification_rate` | Recomputed with the deterministic rules alone, with **no verifier LLM involved** — how the investigator's claims stood on their own. |
| `unsupported_after_verification_rate` | Zero by construction; the report check below proves it. |

The gap between "before" and "after" is the verification stage doing its job.

#### Report integrity

`rejected_claims_leaked_into_reports` cross-checks every conclusion in every
stored report against the set of claims verification rejected.

**It must be 0.** This is the single most important number in the harness: it is
the end-to-end proof that the hallucination-mitigation pipeline actually holds,
measured on stored artefacts rather than asserted in a unit test.

**Measured:** 33 claims — 81.8% supported, 15.2% partially supported, 3.0%
rejected; 0.0% unsupported after verification; **0 rejected claims leaked**; 0
invalid structured outputs.

## Reproducibility

Seeding is deterministic, and the default provider is a pure function of its
inputs. The same `SEED_RANDOM_SEED` and the same code produce the same metrics,
so a change in the numbers is attributable to a change in the code rather than
to sampling noise. (Verified by fingerprinting the dataset across repeated
reseeds.)

## What is not measured

- **Report usefulness.** No human judgement of whether a report would actually
  help a CSM. That needs human raters.
- **Retrieval relevance against ground truth.** The keyword proxy is a
  reasonable signal, not a labelled relevance set.
- **Live-model verification quality.** With `LLM_PROVIDER=fake` the verifier's
  judgement *is* the deterministic rules, so these figures measure the rules.
  Re-run with `LLM_PROVIDER=openai` to measure a real model.
- **Calibration.** Confidence values are not calibrated probabilities.
