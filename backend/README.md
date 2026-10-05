# ICE-800 Closed Beta

ICE-800 is a credit-engineering web/PWA prototype that combines linked-card data, deterministic utilization/payment rules, a credit-report adapter boundary, simulations, calendar events, prioritized actions, and a closed-beta feedback loop.

## Beta capabilities

- Email/password accounts with PBKDF2-SHA256 password hashing and expiring HS256 JWT sessions.
- Closed-beta registration with invite codes, optional one-use enforcement, Terms/Privacy acceptance, cohort tracking, onboarding progress, and in-app feedback.
- Plaid Link boundary for user-authorized bank/card connections, account/liability sync, webhooks, encrypted access tokens, disconnect/delete/export controls.
- Individual and portfolio utilization analysis with configurable 3–5% target, 7% warning, 10% operating ceiling and payment/cutoff priorities.
- Due-date/cutoff calendar, action queue, simulator, persistent alert center, scheduled sync/alert hooks and PWA installability.
- Credit-report provider boundary with explicit consent. Development can accept a manual snapshot; production mode blocks that shortcut.
- Minimal product telemetry uses an allowlist of coarse events only. Event payloads do not accept balances, card numbers, credentials, or arbitrary financial metadata.

ICE-800 does **not** guarantee score changes and does not execute payments.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# load environment variables from .env with your preferred process manager
uvicorn main:app --reload
```

Open `http://localhost:8000`.

The example beta invite is `ICE800-BETA`. Replace it before sharing the app.

## Generate tester invite codes

```bash
python scripts/generate_invites.py 10
```

Copy the emitted `BETA_INVITE_CODES=...` value into your deployment secrets. With `BETA_INVITE_SINGLE_USE=true`, an invite fingerprint can register only one account.

## Closed-beta operator report

```bash
python scripts/beta_report.py
```

This summarizes tester count, onboarding completion, connections, ratings and recent feedback from the local database.

## Test

```bash
PYTHONPATH=. pytest -q
```

The Beta package currently includes 13 deterministic/unit tests. An API smoke test was also run against registration, one-use invite enforcement, dashboard access, feedback and telemetry validation.

## Environment

See `.env.example`. Important beta settings:

- `BETA_INVITE_REQUIRED=true`
- `BETA_INVITE_CODES=...`
- `BETA_INVITE_SINGLE_USE=true`
- `BETA_COHORT=founder-beta`
- `PLAID_ENV=sandbox` for testing before production approval
- `CREDIT_PROVIDER=disabled|mock|partner_http`

For production-like deployments set strong `JWT_SECRET`, `FERNET_KEY`, `CRON_SECRET`, HTTPS `PUBLIC_BASE_URL`, restricted origins/hosts, real provider credentials and externalized persistent storage.

## Architecture

`Browser/PWA -> FastAPI API -> ICE deterministic engines -> SQLite (Beta)`

Provider boundaries:

`Plaid -> accounts/liabilities -> ICE engine`

`Authorized credit-report provider -> normalized credit snapshot -> credit engine`

The language-model layer is intentionally not required for core calculations. Explanations can be added later without making balances, utilization or payment priority dependent on generative output.

## Beta vs production

This package is a **closed Beta**, not a public financial product. Before a public launch, replace SQLite with a production database, use centralized secret management and observability, complete provider approvals, penetration/security review, privacy/legal/compliance review, incident response, backup/restore, rate limiting and abuse controls. Review `BETA_LAUNCH.md` and `PRODUCTION_READINESS.md`.


## Beta 2: Optimization Engine

New endpoints:

- `POST /api/optimization/debt-transfer` — estimate transfer amount, fee, monthly payoff and savings.
- `POST /api/optimization/line-reallocation` — analyze two linked cards.
- `POST /api/optimization/line-reallocation/simulate` — manual issuer scenario for testing.
- `POST /api/optimization/card-recommendations` — rank supplied candidates with transparent ICE Fit.
- `GET /api/optimization/platforms` — versioned application/prequalification directory and issuer-policy examples.

The Optimization tab in the web app exposes all three Beta modules. Live card offers are deliberately not hardcoded as permanent facts; production should use a refreshed product-catalog adapter and verify terms immediately before recommendation/application.
