import db as dbmod
from db import db, init_db
from security import hash_password, make_token
from fastapi.testclient import TestClient
from main import app


def setup_user(tmp_path):
    dbmod.DB_PATH = tmp_path / 'prodtest.db'
    init_db()
    with db() as con:
        cur = con.execute("INSERT INTO users(email,password_hash) VALUES(?,?)", ('prod@example.com', hash_password('1234567890abc')))
        uid = cur.lastrowid
        con.execute("INSERT OR IGNORE INTO preferences(user_id) VALUES(?)", (uid,))
        con.execute("INSERT OR IGNORE INTO user_settings_v2(user_id,language) VALUES(?,?)", (uid, 'es'))
    return uid, {'Authorization': 'Bearer ' + make_token(uid)}


def test_language_round_trip(tmp_path):
    _, headers = setup_user(tmp_path)
    c = TestClient(app)
    r = c.put('/api/v1/settings/language', headers=headers, json={'language':'en'})
    assert r.status_code == 200
    assert r.json()['language'] == 'en'
    r = c.get('/api/v1/settings/language', headers=headers)
    assert r.json()['language'] == 'en'


def test_payment_requires_explicit_confirmation(tmp_path):
    uid, headers = setup_user(tmp_path)
    with db() as con:
        con.execute("INSERT INTO payment_intents(user_id,provider,source_provider_account_id,destination_provider_account_id,amount_cents,description,idempotency_key,status) VALUES(?,?,?,?,?,?,?,'created')",
                    (uid,'method','src_test','dst_test',5000,'test','idem-test'))
        pid = con.execute("SELECT id FROM payment_intents WHERE user_id=?", (uid,)).fetchone()['id']
    c = TestClient(app)
    r = c.post(f'/api/v1/payments/intents/{pid}/confirm', headers=headers, json={'confirm':False})
    assert r.status_code == 400
    assert 'confirmation' in r.json()['detail'].lower()


def test_live_application_disabled_without_provider(tmp_path):
    _, headers = setup_user(tmp_path)
    c = TestClient(app)
    r = c.post('/api/v1/applications/card/start', headers=headers, json={'personal_information':{},'financial_information':{},'credit_card_information':{}})
    assert r.status_code == 503
