# Hourly Monitor — addition to the existing dashboard

Open **Monitor → Hourly Monitor**, or `/?page=hourly`. Existing Overview, Reports,
Threats, Users, Replay and New Data Inference remain available.

Choose an observation date and one of its 24 hour tiles. Each tile shows the
number of observed accounts and stored alerts. Grey tiles are hours without
stored observations, not hours proved safe. Times retain the source's wall-clock
basis because its timezone is not supplied. Intervals include their start and
exclude their end.

The selected hour shows:

- Observed accounts, flagged user-hours, open investigations, event count and
  average risk for that hour alone.
- One score and tier per observed account in the selected hour. These are not
  the account's maximum over the whole dataset.
- HIGH/CRITICAL alerts linked to those same score records, with their existing
  OPEN, IN_PROGRESS or RESOLVED statuses.
- Investigation and resolution actions using the existing optimistic version
  check and audit history.

Previous/next buttons move through observed hours. **Follow latest stored hour**
checks for published observations every 30 seconds and follows the newest stored
hour. Browsing an older hour turns that mode off. This is stored-data review; it
does not add live collection, a scheduled scoring worker, browser notifications
or alerts for unobserved hours.

**Review this hour's alerts** opens the existing Threats screen filtered to that
hour. Account-specific evidence links also carry the exact account ID. The alert
export keeps the selected hour, tier, status and account filters. Its existing
500-record export limit remains. All-historical-alert browsing is still available.

## Additive API

- `GET /api/hours?days=365`: observed-hour index for the active model, including
  counts, peak tier and observation bounds. Days must be 1–365.
- `GET /api/hours/{window_index}`: observed account scores, tier counts and existing
  alerts for exactly one hour and the active model. Missing hours return 404.
- Existing `/api/threats` and `/api/export` accept an optional nonnegative integer
  `hour` parameter. Omitting it retains the previous historical behavior.

No database migration, model fitting, threshold change or duplicate alert
generation is required. The active V6 Maximum model and its reused-validation
report are unchanged. Published historical scores are the source for this view;
raw-import predictions and investigations remain in New Data Inference's separate
stream, matching the existing persistence design.

## Verification

API tests check active-model and exact-hour scoping, an account that is normal in
one hour but critical in a later hour, existing alert IDs, missing-hour semantics,
invalid hour filters, and hour-filtered exports. Browser checks cover hour
navigation, the link to the existing alert worklist, a no-alert hour and mobile
layout. Tests use isolated stubs; real-data smoke checks read existing scores.
