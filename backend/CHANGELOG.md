# Changelog

## Beta 2 · Optimization — 2026-10-04

- Added Debt Transfer Optimizer with fee/APR/promo-horizon modeling.
- Added Credit Line Engineering with before/after per-card utilization and issuer-policy checks.
- Added New Card Opportunity Engine with transparent ICE Fit ranking.
- Added Application/Prequalification Hub directory.
- Added manual line-reallocation lab so testers without two cards at one issuer can test the feature.
- Added five optimization-engine tests; total suite now 18 tests.
- Preserved payment-history priority over utilization and acquisition recommendations.

# Changelog

## ICE-800 Closed Beta — 2026-10-04

- Converted v3.0 into a closed founder Beta.
- Added invite-only registration and optional single-use invite enforcement.
- Added required Terms/Privacy acceptance at registration and separate credit-report consent.
- Added Beta cohort/profile tracking and onboarding launchpad.
- Added structured in-app feedback and minimal allowlisted product telemetry.
- Added Beta status/dashboard UI and limitations disclosure.
- Added invite-generation and operator-report scripts.
- Replaced passlib/python-jose authentication dependencies with PBKDF2-SHA256 password hashing and HS256 JWT handling using standard Python primitives.
- Added optional scheduler fallback so the API can start even when APScheduler is not present in a development environment.
- Maintained v3 deterministic credit engine, portfolio analysis, simulator, calendar, Plaid boundary, credit-provider boundary, alerts, export/delete and PWA behavior.
- Test suite: 13/13 passing plus API smoke test for Beta registration, one-use invites, dashboard, feedback and event validation.
