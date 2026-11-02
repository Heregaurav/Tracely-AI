# SPEDIA security review — 2 November 2026

This review covers the public SPEDIA application snapshot and its dependency
manifests. It is not a penetration test, a full Git-history credential audit or
an assurance that an internet-facing deployment is secure.

## Checks and fixes

| Check | Result |
|---|---|
| Tracked-file secret scan | Seven detector findings reviewed: one example connection placeholder, one publisher checksum, five test-fixture findings. No live credentials identified in the scanned source tree. |
| Private-file inventory | No tracked private environment profiles, source CSVs, model binaries, Parquet files or private keys. `.env.example` contains placeholders only. |
| Python advisory audit | Initially four affected packages. Updated FastAPI to 0.162.0, explicitly pinned Starlette 1.10.0, updated python-multipart to 0.0.33 and Werkzeug to 3.1.9. One unique advisory remains, described below. |
| npm advisory audit | Initially six moderate dependency findings rooted in minimatch. Added an override requiring minimatch >=11.0.1 within major 11 and regenerated the lockfile. Final audit: zero reported vulnerabilities, including development dependencies. |
| Bandit 1.9.4 | Initially two high and four low findings. Marked the two publisher-compatibility MD5 operations `usedforsecurity=False`. Final scan: zero high/medium findings and four low assertion findings in offline research/benchmark scripts. Digest values are unchanged; trusted artifact integrity still uses SHA-256. |
| Upload boundary | Added a 320 KiB maximum for the complete API request body, before JSON/multipart parsing. Enforces both declared length and streamed bytes without trusting Content-Length alone. The CSV's existing 256 KiB limit remains. |
| Regression tests | Patched web stack: 38 passed, 19 skipped. Includes production startup without login, public reads/writes reaching business validation, multipart round trip, and oversized/chunked body rejection. Skips require private assets or a dedicated test database. |
| Frontend verification | Lint and production build passed using a fresh isolated npm install. The existing bundle-size warning remains. |

Security tools ran in a separate temporary environment. Compatibility tests used
Python 3.12 with the patched web packages layered over the existing numerical
stack. The deployment remains configured for Python 3.11.11; no live Render smoke
test or production PostgreSQL integration test was performed by this review.
The running local application's installed packages were not upgraded in place.

## Remaining Python advisory

`scikit-learn==1.3.2` is retained for the approved frozen checkpoint's compatibility.
The advisory database reports **PYSEC-2024-110 / CVE-2024-5206 /
GHSA-jw8x-6495-233v**, fixed in scikit-learn 1.5.0. It concerns sensitive tokens
retained by `TfidfVectorizer.stop_words_`. The published SPEDIA code does not use
TfidfVectorizer or text-vectorizer training; it uses numerical behavior features.
The audit returned the same advisory twice; that is one unique unresolved advisory,
not two different defects. No scanner finding was silently suppressed.

This is a documented compatibility exception, not a patched dependency. A later
scikit-learn upgrade needs an isolated checkpoint-loading and exact-score
compatibility study before activation. Do not replace the frozen runtime casually.

Primary advisory: https://github.com/advisories/GHSA-jw8x-6495-233v

## Public access remains deliberate

Authentication was removed at the owner's request. Anyone who can reach the API
can read exposed data and invoke enabled imports, alert updates, exports and
model activation. Audit actor `public` does not identify a person. CORS is not
access control. The service is not suitable for confidential employee data without
an external access boundary or restored authorization.

The body limit reduces memory exposure per request; it does not provide request
rate limiting or stop an attacker repeatedly calling expensive endpoints. Use
platform/gateway rate and concurrency limits for an internet-facing service.
Actual platform settings were not reviewed or changed here. Runtime training
remains disabled and model/feature validation still applies.

Model deserialization accepts trusted provisioned artifacts only after their
recorded SHA-256 is checked. A digest does not make an attacker-controlled model
safe: database registry records and artifact storage must remain trusted. Native
CSV upload does not accept pickle/joblib uploads.

## Reproduce

```bash
pip-audit -r requirements.txt --format json
bandit -r src scripts
# Expect the documented sklearn advisory and low offline assert findings.
cd frontend
npm ci --ignore-scripts
npm audit
npm run lint
npm run build
```

`detect-secrets scan` was also run over tracked text files, with generated lockfile
entropy excluded and findings manually reviewed. It is heuristic and cannot prove
that no possible secret exists. Private working-tree profiles and datasets were
excluded from the publication snapshot. The broader development checkout has
unrelated experiments; those are not part of this security push.
