import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(os.environ.get("ICE800_DB_PATH", Path(__file__).with_name("ice800.db")))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS connections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  item_id TEXT NOT NULL,
  institution_name TEXT,
  access_token_enc TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  last_sync_at TEXT,
  last_sync_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, item_id),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  connection_id INTEGER NOT NULL,
  account_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT,
  subtype TEXT,
  mask TEXT,
  balance REAL,
  available REAL,
  credit_limit REAL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, account_id),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(connection_id) REFERENCES connections(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS liabilities (
  account_id TEXT PRIMARY KEY,
  last_statement_issue_date TEXT,
  last_statement_balance REAL,
  next_payment_due_date TEXT,
  minimum_payment REAL,
  last_payment_date TEXT,
  last_payment_amount REAL,
  is_overdue INTEGER DEFAULT 0,
  apr REAL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS preferences (
  user_id INTEGER PRIMARY KEY,
  target_low REAL NOT NULL DEFAULT 0.03,
  target_high REAL NOT NULL DEFAULT 0.05,
  warning REAL NOT NULL DEFAULT 0.07,
  user_max REAL NOT NULL DEFAULT 0.10,
  hard_warning REAL NOT NULL DEFAULT 0.30,
  close_lead_days INTEGER NOT NULL DEFAULT 3,
  due_lead_days INTEGER NOT NULL DEFAULT 5,
  email_notifications INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS credit_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT,
  score_model TEXT,
  score INTEGER,
  report_date TEXT,
  utilization REAL,
  hard_inquiries_6m INTEGER,
  late_payments_24m INTEGER,
  collections_count INTEGER,
  derogatory_count INTEGER,
  oldest_age_months INTEGER,
  average_age_months INTEGER,
  total_accounts INTEGER,
  payload_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_credit_reports_user_date ON credit_reports(user_id, report_date DESC, id DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  fingerprint TEXT NOT NULL,
  payload TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'in_app',
  status TEXT NOT NULL DEFAULT 'created',
  sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at TEXT,
  UNIQUE(user_id, fingerprint, channel),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  consent_type TEXT NOT NULL,
  version TEXT NOT NULL,
  granted INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, consent_type, version),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS webhook_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  event_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  processed_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, event_key)
);
CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  event_type TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_user_date ON audit_log(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS beta_profiles (
  user_id INTEGER PRIMARY KEY,
  cohort TEXT NOT NULL DEFAULT 'founder-beta',
  invite_fingerprint TEXT,
  joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT,
  onboarding_completed_at TEXT,
  strategy_reviewed_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS beta_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  feedback_type TEXT NOT NULL,
  rating INTEGER,
  message TEXT NOT NULL,
  page TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_beta_feedback_user_date ON beta_feedback(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS product_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  event_name TEXT NOT NULL,
  page TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_product_events_user_date ON product_events(user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS provider_profiles (
  user_id INTEGER PRIMARY KEY,
  method_entity_id TEXT,
  method_connect_status TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS provider_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  provider_account_id TEXT NOT NULL,
  local_account_id TEXT,
  role TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, provider, provider_account_id),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS payment_intents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL DEFAULT 'method',
  source_provider_account_id TEXT NOT NULL,
  destination_provider_account_id TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  description TEXT,
  idempotency_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'created',
  provider_payment_id TEXT,
  provider_payload_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  confirmed_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, idempotency_key),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS credit_applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  provider TEXT NOT NULL,
  offer_id TEXT,
  offer_name TEXT,
  application_url TEXT,
  status TEXT NOT NULL DEFAULT 'created',
  prequalified INTEGER,
  payload_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS bank_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  connection_id INTEGER NOT NULL,
  account_id TEXT NOT NULL,
  transaction_id TEXT NOT NULL,
  amount REAL,
  iso_currency_code TEXT,
  merchant_name TEXT,
  name TEXT,
  category_json TEXT,
  pending INTEGER NOT NULL DEFAULT 0,
  transaction_date TEXT,
  authorized_date TEXT,
  removed INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, transaction_id),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(connection_id) REFERENCES connections(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bank_tx_user_date ON bank_transactions(user_id, transaction_date DESC);

CREATE TABLE IF NOT EXISTS user_settings_v2 (
  user_id INTEGER PRIMARY KEY,
  language TEXT NOT NULL DEFAULT 'es',
  currency TEXT NOT NULL DEFAULT 'USD',
  require_payment_confirmation INTEGER NOT NULL DEFAULT 1,
  biometric_confirmation INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

MIGRATIONS = [
    "ALTER TABLE connections ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
    "ALTER TABLE connections ADD COLUMN last_sync_at TEXT",
    "ALTER TABLE connections ADD COLUMN last_sync_error TEXT",
    "ALTER TABLE connections ADD COLUMN created_at TEXT",
    "ALTER TABLE connections ADD COLUMN transactions_cursor TEXT",
    "ALTER TABLE alerts ADD COLUMN channel TEXT NOT NULL DEFAULT 'in_app'",
    "ALTER TABLE alerts ADD COLUMN status TEXT NOT NULL DEFAULT 'created'",
    "ALTER TABLE alerts ADD COLUMN read_at TEXT",
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass
        con.execute("INSERT OR IGNORE INTO beta_profiles(user_id,cohort,last_seen_at) SELECT id,'legacy-beta',CURRENT_TIMESTAMP FROM users")


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()
