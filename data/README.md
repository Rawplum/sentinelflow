# data/

Only synthetic test data belongs here. Do not add real production logs,
personal data, credentials, or customer data.

## sample_events.jsonl

A reusable synthetic dataset for the deterministic end-to-end flow:

- `alice.demo` / `198.51.100.10`: five failures within five minutes.
- `alice.demo` success after the failures.
- `bob.demo`: three failures (below threshold).
- `carol.demo`: five failures spread over twenty minutes (outside the window).
- `dave.demo` / `203.0.113.30`: five failures within five minutes.
- `dave.demo` / `203.0.113.31` and `erin.demo` / `203.0.113.30`: two failures each,
  verifying that different users/IPs are not merged.
- One duplicate `event_id` (skipped by the importer).
- Four invalid lines: missing `event_type`, timestamp without timezone,
  malformed IP, and invalid outcome.

Import with the tolerant CLI:

```bat
sentinelflow-import data\sample_events.jsonl
```

The API import endpoint validates the whole batch and will return 422 for the
invalid lines, so use valid-only batches with the API.
