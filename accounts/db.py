"""SQLite storage for the Accounts Desk.

Kept in its own file (instance/accounts.db) so it never touches the
quotation app's database.
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.environ.get("ACCOUNTS_INSTANCE", os.path.join(BASE_DIR, "instance"))
DB_PATH = os.environ.get("ACCOUNTS_DB", os.path.join(INSTANCE_DIR, "accounts.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',   -- admin | member
    takes_work    INTEGER NOT NULL DEFAULT 1,       -- gets bills when a file is shared out
    active        INTEGER NOT NULL DEFAULT 1,
    -- changes on every password reset, which signs that person out everywhere
    session_salt  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS firms (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT NOT NULL UNIQUE,     -- WWI, WWE ...
    name      TEXT NOT NULL,            -- as Tally prints it on line 1
    aliases   TEXT NOT NULL DEFAULT '', -- other spellings, one per line
    active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS uploads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id       INTEGER NOT NULL REFERENCES firms(id),
    kind          TEXT NOT NULL,          -- payable | receivable
    file_name     TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    report_date   TEXT NOT NULL,          -- the date the Tally report was taken
    user_id       INTEGER NOT NULL REFERENCES users(id),
    created_at    TEXT NOT NULL,
    bills_in_file INTEGER NOT NULL DEFAULT 0,
    total_in_file REAL NOT NULL DEFAULT 0,
    new_bills     INTEGER NOT NULL DEFAULT 0,
    updated_bills INTEGER NOT NULL DEFAULT 0,
    cleared_bills INTEGER NOT NULL DEFAULT 0,
    summary       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    firm_id         INTEGER NOT NULL REFERENCES firms(id),
    kind            TEXT NOT NULL,          -- payable | receivable
    bill_key        TEXT NOT NULL,          -- party|ref|date, squeezed
    party           TEXT NOT NULL,
    party_key       TEXT NOT NULL,
    ref_no          TEXT NOT NULL DEFAULT '',
    bill_date       TEXT NOT NULL DEFAULT '',
    due_date        TEXT NOT NULL DEFAULT '',
    overdue_days    INTEGER NOT NULL DEFAULT 0,
    original_amount REAL NOT NULL DEFAULT 0,  -- pending amount the first time it was seen
    pending         REAL NOT NULL DEFAULT 0,  -- pending amount in the latest Tally file
    assigned_to     INTEGER REFERENCES users(id),
    first_upload_id INTEGER REFERENCES uploads(id),
    last_upload_id  INTEGER REFERENCES uploads(id),
    last_seen_at    TEXT NOT NULL DEFAULT '',
    cleared_at      TEXT NOT NULL DEFAULT '', -- dropped out of a later Tally file
    created_at      TEXT NOT NULL,
    UNIQUE (firm_id, kind, bill_key)
);
CREATE INDEX IF NOT EXISTS idx_bills_assigned ON bills(assigned_to);
CREATE INDEX IF NOT EXISTS idx_bills_party ON bills(firm_id, kind, party_key);

-- Who owns which party, so every new bill of a party goes to the same person
-- and two people never chase or pay the same party.
CREATE TABLE IF NOT EXISTS party_owners (
    firm_id   INTEGER NOT NULL REFERENCES firms(id),
    kind      TEXT NOT NULL,
    party_key TEXT NOT NULL,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (firm_id, kind, party_key)
);

-- One row per "I paid this" / "I received this".
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id       INTEGER NOT NULL REFERENCES bills(id),
    user_id       INTEGER NOT NULL REFERENCES users(id),
    amount        REAL NOT NULL,
    paid_on       TEXT NOT NULL,
    mode          TEXT NOT NULL DEFAULT '',
    reference     TEXT NOT NULL DEFAULT '',  -- UTR / cheque no
    reference_key TEXT NOT NULL DEFAULT '',
    remarks       TEXT NOT NULL DEFAULT '',
    batch         TEXT NOT NULL DEFAULT '',  -- entries saved together share this
    flagged       INTEGER NOT NULL DEFAULT 0,
    -- set once a later Tally file shows the pending amount came down by it
    reconciled_at TEXT NOT NULL DEFAULT '',
    nagged_at     TEXT NOT NULL DEFAULT '',  -- "still not in Tally" already raised
    created_at    TEXT NOT NULL,
    deleted_at    TEXT NOT NULL DEFAULT '',
    deleted_by    INTEGER REFERENCES users(id),
    delete_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entries_bill ON entries(bill_id);
CREATE INDEX IF NOT EXISTS idx_entries_user ON entries(user_id);
CREATE INDEX IF NOT EXISTS idx_entries_ref ON entries(reference_key);

-- Follow-ups: "called, promised by Friday".
CREATE TABLE IF NOT EXISTS notes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id      INTEGER NOT NULL REFERENCES bills(id),
    user_id      INTEGER NOT NULL REFERENCES users(id),
    text         TEXT NOT NULL,
    promise_date TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_bill ON notes(bill_id);

-- Possible double payments / double entries for someone to look at.
CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'high',   -- high | check
    bill_id      INTEGER REFERENCES bills(id),
    entry_id     INTEGER REFERENCES entries(id),
    upload_id    INTEGER REFERENCES uploads(id),
    message      TEXT NOT NULL,
    raised_by    INTEGER REFERENCES users(id),
    created_at   TEXT NOT NULL,
    resolved_at  TEXT NOT NULL DEFAULT '',
    resolved_by  INTEGER REFERENCES users(id),
    resolve_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_alerts_bill ON alerts(bill_id);

CREATE TABLE IF NOT EXISTS activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id),
    action     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    bill_id    INTEGER,
    created_at TEXT NOT NULL
);
"""

DEFAULT_FIRMS = [
    ("WWI", "WELL WORTH INDUSTRIES", ""),
    ("WWE", "WELL WORTH ENGINEERING", ""),
    ("WWAS", "WELL WORTH AIR SYSTEMS", "WELL WORTH AIR SYSTEM\nWELLWORTH AIR SYSTEMS"),
    ("EXCEL", "EXCEL INDUSTRIES", ""),
]

KINDS = ("payable", "receivable")

_SQUEEZE = re.compile(r"[^0-9A-Za-z]+")


def squeeze(text):
    """'jj/2627/0245' and 'JJ-2627-0245' are the same bill; drop the
    separators and the case so they compare equal."""
    return _SQUEEZE.sub("", str(text or "")).upper()


IST = timezone(timedelta(hours=5, minutes=30))


def _zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("ACCOUNTS_TZ", "Asia/Kolkata"))
    except Exception:
        return IST


LOCAL_TZ = _zone()


def local_now():
    return datetime.now(LOCAL_TZ)


def now():
    return local_now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return local_now().strftime("%Y-%m-%d")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM firms").fetchone()[0] == 0:
        conn.executemany("INSERT INTO firms (code, name, aliases) VALUES (?, ?, ?)",
                         DEFAULT_FIRMS)
    conn.commit()
    conn.close()


def log(conn, user_id, action, detail="", bill_id=None):
    conn.execute(
        "INSERT INTO activity (user_id, action, detail, bill_id, created_at) "
        "VALUES (?, ?, ?, ?, ?)", (user_id, action, detail, bill_id, now()))
