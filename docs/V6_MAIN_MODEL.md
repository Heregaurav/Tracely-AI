# Main output: SPEDIA V6 Maximum

The owner selected `spedia-v6-maximum-20261102` as the main application output.
The numerical model is the frozen `behavior_55_if_ae_max` candidate at the saved
50-per-1,000 normal-calibration-hour operating budget. No model was refitted.
The original V2 model, records and reports remain available for rollback.

## Main result shown in the dashboard

This is **reused development validation**, not a new independent test.

| Metric | Value |
|---|---:|
| Precision | 95.71% |
| Recall | 87.01% |
| F1 | 91.16% |
| False-positive rate | 1.18% (3 / 255 normal hours) |
| ROC-AUC | 0.98717 |
| Average precision | 0.96694 |
| Correctly detected / missed positive hours | 67 / 10 |
| False alerts / correctly unflagged normal hours | 3 / 252 |
| Evaluated hours | 332 (77 positive, 255 normal) |

The ensemble takes the maximum of separately calibrated Isolation Forest and
autoencoder indices. It uses 55 causal numerical features and a fixed HIGH
threshold of 97.72727272727273. The NORMAL/LOW/MEDIUM/CRITICAL display boundaries
follow the existing arithmetic band policy; those bands are not independently
validated security categories. Indices are not malicious probabilities.

The original 1,546 historical user-hours were rescored for application use.
Rescoring the old test observations is operational playback, not a new untouched
V6 performance evaluation. Only the previously saved validation result is promoted
as the main report. Source-origin confounding remains unresolved.

## Why every user previously looked HIGH

User badges summarize each account's **highest hourly risk over the last 30 data
days**. One high hour can keep the user badge high despite many normal hours.
Changing models does not justify inventing low-risk users or changing the cutoff
to force a balanced chart.

The overview chart now counts **individual observed user-hours**, with its own
denominator and explicit label. User peak badges and the top user cards retain
their historical-peak meaning. V6 historical hourly counts are:

| Tier | Hours |
|---|---:|
| NORMAL | 328 |
| LOW | 409 |
| MEDIUM | 498 |
| HIGH | 36 |
| CRITICAL | 275 |
| Total | 1,546 |

## Serving and preservation

`src/models/v6_maximum.py` is an inference-only adapter containing the already
fitted estimators, scalers and normal references. It has no fit method. The saved
332 validation indices and confusion matrix reproduce exactly. Raw imports use
the same causal 55-feature transformation. Historical replay receives separate
versioned input manifests. Old contexts and replay artifacts are retained.

Version-specific replay and inference-context paths come from the active model's
report and resolve through the existing trusted PostgreSQL asset cache. Render
must materialize assets at startup as described in [deployment](PUBLIC_DEPLOYMENT.md).
After a new version is staged, restart/redeploy the backend to populate its cache
before switching the active version.

The explicit offline build/stage/activate commands are:

```bash
.venv/bin/python -m scripts.promote_spedia_v6 build
# With the intended PostgreSQL DATABASE_URL exported:
.venv/bin/python -m scripts.promote_spedia_v6 stage
.venv/bin/python -m scripts.promote_spedia_v6 activate
```

Build requires the private original source, frozen experimental checkpoints and
historical assets. It refuses an existing output directory. Stage checks digests
and adds a new inactive version, scores and serving assets in one transaction.
Activation is a separate explicit operation, after compatible code and assets
are ready. Neither build nor serving trains a model. Do not repeatedly rerun a
completed publication or commit private model/data files.

## Rollback

Activate the preserved model version
`spedia-dcd995bcea1644cabd261b4bcc4dd223` through the existing model-version API.
The original assets and data remain stored. This returns the old numerical
model's output; it does not make V6's development metrics a held-out result.

Related: [complete V6 experiments](spedia-origin-audit-v6/EXPERIMENT_REPORT.md),
[source limitations](spedia-origin-audit-v6/SOURCE_ORIGIN_AUDIT.md),
[security review](SECURITY_REVIEW.md).
