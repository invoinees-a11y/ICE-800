# ICE-800 Beta — Production Readiness

## Status legend
- ✅ Implemented in reference build
- 🟡 Interface/structure implemented; production service or approval still required
- 🔴 Required before public launch

## Application
- ✅ Deterministic credit engine
- ✅ Credit-factor engine
- ✅ Unified priority queue
- ✅ Simulation and calendar
- ✅ PWA shell
- ✅ In-app alerts
- ✅ Email adapter
- ✅ Multi-user data separation by user id

## Financial connectivity
- ✅ Plaid Link/API adapter
- ✅ Account/liability refresh
- ✅ Webhook endpoint + idempotency record
- ✅ Item disconnect
- 🟡 Production Plaid account/plan
- 🟡 Production OAuth redirect registration
- 🔴 Provider-specific webhook authenticity verification and operational monitoring

## Credit-report connectivity
- ✅ Versioned consumer consent record
- ✅ Provider-neutral adapter boundary
- ✅ Mock provider for development
- 🟡 Contracted bureau/report provider adapter
- 🔴 Legal/permissible-purpose review for the exact product flow
- 🔴 Provider certification/security onboarding

## Security
- ✅ Password hashing
- ✅ Provider-token encryption
- ✅ Signed expiring JWT
- ✅ CSP/HSTS/trusted-host/CORS controls
- ✅ Audit events
- 🔴 MFA/passkeys
- 🔴 Account recovery + verified email
- 🔴 Refresh-token/session revocation architecture
- 🔴 Distributed rate limiting, bot/abuse protection
- 🔴 KMS/secrets manager
- 🔴 Pen test + dependency/SBOM scanning

## Data platform
- ✅ Development SQLite schema
- ✅ Export/delete controls
- ✅ Sync-run records
- 🔴 Managed relational DB (e.g. PostgreSQL) and schema migrations
- 🔴 Encrypted backups, restore testing, retention schedule
- 🔴 Regional/data residency decisions

## Operations
- 🟡 In-process scheduler for local/single-instance use
- ✅ Cron-authenticated job endpoints
- 🔴 Durable worker/queue or managed scheduler
- 🔴 Metrics, tracing, centralized logs, alerts/on-call
- 🔴 Disaster recovery and incident-response runbooks

## Compliance / product
- ✅ Versioned Beta Terms/Privacy acceptance framework (templates included; legal review still required)
- 🔴 Privacy policy + Terms reviewed for actual business model
- 🔴 FCRA/consumer-report counsel review where applicable
- 🔴 State privacy law review and DSAR process
- 🔴 Accessibility review
- 🔴 Marketing claims review: never promise exact score changes or approvals

## Launch criterion
Public launch should be considered blocked until all 🔴 items materially relevant to the deployed feature set are closed and provider contracts are active.


## Optimization Engine production gates

- Replace demo card candidates with a live/versioned product catalog.
- Store source URL, retrieval time and offer expiry/effective date for every displayed term.
- Re-verify issuer line-reallocation rules periodically; unknown issuers must remain `confirm_with_issuer`.
- Implement offer-specific balance-transfer eligibility/fee/APR rules; never assume same-issuer transfers are permitted.
- Keep sponsored/affiliate economics outside the ICE Fit scoring function and label paid placements.
- Record explicit user action before redirecting to a formal application.
- Security/privacy review any prequalification partner integration before sending consumer identifiers.
