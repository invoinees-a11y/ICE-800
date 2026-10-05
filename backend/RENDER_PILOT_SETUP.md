# ICE-800 Pilot Live — Render deployment

This backend is intended for the founder pilot. It includes Plaid Link, encrypted access tokens, Transactions Sync, liabilities, a verified Plaid webhook receiver, ICE-800 strategy endpoints, debt-transfer analysis, payment-intent boundaries, language preferences, and audit logging.

## Render Web Service

Upload `ICE-800-Pilot-Live-Backend.zip` to the GitHub repository root.

Use these Render commands:

Build command:
`unzip -o ICE-800-Pilot-Live-Backend.zip -d app && pip install -r app/requirements.txt`

Start command:
`cd app && uvicorn main:app --host 0.0.0.0 --port $PORT`

Health endpoint: `/api/health`

## Required environment variables for live Plaid pilot

- `APP_ENV=production`
- `PUBLIC_BASE_URL=https://<your-service>.onrender.com`
- `PLAID_ENV=production`
- `PLAID_CLIENT_ID=<set in Render secret>`
- `PLAID_SECRET=<set in Render secret>`
- `PLAID_WEBHOOK_URL=https://<your-service>.onrender.com/api/plaid/webhook`
- `PLAID_VERIFY_WEBHOOKS=true`
- `ANDROID_PACKAGE_NAME=com.ice800.app`
- `JWT_SECRET=<long random value>`
- `FERNET_KEY=<valid Fernet key>`
- `CRON_SECRET=<long random value>`
- `BETA_INVITE_REQUIRED=false` (founder pilot only)
- `DEFAULT_LANGUAGE=es`
- `PAYMENTS_ENABLED=false` until Method production approval is active
- `APPLICATIONS_ENABLED=false` until marketplace/issuer integration is active

For SQLite persistence on Render, use a paid persistent disk mounted at `/var/data` and set:
- `ICE800_DB_PATH=/var/data/ice800.db`

Do not put provider secrets in GitHub or in the Android APK.
