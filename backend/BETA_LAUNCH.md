# ICE-800 Founder Beta Launch Plan

## Scope

Start with 5–20 invited testers. Use Plaid Sandbox first; move selected testers to real provider connectivity only after credentials/approval, HTTPS deployment, privacy/legal review and a documented support path are in place.

## Before inviting anyone

1. Replace every example secret and the default invite code.
2. Generate unique invites with `python scripts/generate_invites.py 20` and store them as deployment secrets.
3. Keep `BETA_INVITE_SINGLE_USE=true`.
4. Set HTTPS `PUBLIC_BASE_URL`, strict `ALLOWED_ORIGINS` and `TRUSTED_HOSTS`.
5. Configure encrypted persistent storage and backup policy.
6. Configure Plaid Sandbox and verify Link, exchange, sync, webhook and disconnect.
7. Decide whether the credit-report adapter stays disabled during the first cohort. Do not present mock/manual report data as live bureau data.
8. Publish actual Beta Terms and Privacy text corresponding to the configured versions; the UI currently records acceptance but the legal text must be supplied by the operator.
9. Configure an operator support email/process and incident-response owner.
10. Run `PYTHONPATH=. pytest -q` and an end-to-end smoke test in the deployed environment.

## Cohort sequence

### Cohort A — internal (2–3 users)
Focus: authentication, onboarding, provider linking, mobile layout, deletion/export, severe failure modes.

### Cohort B — trusted testers (5–10 users)
Focus: comprehension of recommendations, calendar accuracy, simulations, notification quality, false positives/negatives.

### Cohort C — expanded closed beta (10–20 users)
Focus: reliability over multiple statement cycles, diverse issuers, operational support load and retention.

Do not advance cohorts only because the UI looks polished. Advance when connection failures, data ambiguity and action-priority errors are understood and bounded.

## Weekly Beta review

Run `python scripts/beta_report.py`, review bug feedback, sync failures and audit events, then classify issues as P0–P3:

- P0: security/privacy breach, cross-user data exposure, destructive behavior — stop Beta.
- P1: materially wrong payment/due-date guidance or user cannot access/delete data — fix before expansion.
- P2: broken integration, confusing priority, major mobile flow — fix in current cohort.
- P3: cosmetic/quality-of-life improvements — backlog.

## Exit criteria for public-production work

- No known P0/P1 issues.
- Security review and threat model completed.
- Production database, backups, monitoring and rate limiting deployed.
- Provider production approvals complete.
- Privacy/legal/compliance review complete for the exact data flows and claims.
- Notification deliverability and opt-out controls validated.
- Terms/Privacy pages publicly accessible and versioned.
- At least one full billing/statement cycle tested across representative cards.
