"""SQLite storage for the quotation app.

Holds the four master tables that used to live in AppSheet (clients, machines,
companies, salespersons) plus the quotes/quote_items tables that record every
quotation raised through the app.
"""

import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DB_PATH = os.environ.get("QUOTEAPP_DB", os.path.join(INSTANCE_DIR, "quoteapp.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    address       TEXT DEFAULT '',
    address2      TEXT DEFAULT '',
    tel           TEXT DEFAULT '',
    bank_details  TEXT DEFAULT '',
    -- the bold strip printed just under the bank box
    contact_line  TEXT DEFAULT '',
    is_active     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    party       TEXT NOT NULL,
    address     TEXT DEFAULT '',
    address2    TEXT DEFAULT '',
    city        TEXT DEFAULT '',
    cell_no     TEXT DEFAULT '',
    cell_no2    TEXT DEFAULT '',
    email       TEXT DEFAULT '',
    email2      TEXT DEFAULT '',
    gst_no      TEXT DEFAULT '',
    remarks     TEXT DEFAULT '',
    entry_by    TEXT DEFAULT '',
    created_at  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_clients_party ON clients(party);
CREATE INDEX IF NOT EXISTS idx_clients_city  ON clients(city);

CREATE TABLE IF NOT EXISTS machines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    model        TEXT NOT NULL,
    description  TEXT DEFAULT '',
    rate         REAL DEFAULT 0,
    entry_by     TEXT DEFAULT '',
    wed          TEXT DEFAULT '',
    min_days     INTEGER,
    max_days     INTEGER,
    is_active    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_machines_model ON machines(model);
CREATE INDEX IF NOT EXISTS idx_machines_desc  ON machines(description);

CREATE TABLE IF NOT EXISTS salespersons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    phone     TEXT DEFAULT '',
    email     TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS quotes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_no       TEXT,
    quote_date     TEXT NOT NULL,
    company_id     INTEGER REFERENCES companies(id),
    client_id      INTEGER REFERENCES clients(id),
    -- party details are snapshotted so editing a client later never rewrites
    -- a quotation that was already sent out
    party_name     TEXT DEFAULT '',
    party_address  TEXT DEFAULT '',
    salesperson    TEXT DEFAULT '',
    salesperson_phone TEXT DEFAULT '',
    order_status   TEXT DEFAULT 'PENDING',
    dispatch       TEXT DEFAULT 'PENDING',
    advance        REAL DEFAULT 0,
    gst_percent    REAL DEFAULT 18,
    terms          TEXT DEFAULT '',
    subtotal       REAL DEFAULT 0,
    gst_amount     REAL DEFAULT 0,
    grand_total    REAL DEFAULT 0,
    balance        REAL DEFAULT 0,
    file_name      TEXT DEFAULT '',
    created_at     TEXT DEFAULT '',
    updated_at     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quote_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id    INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    model       TEXT DEFAULT '',
    description TEXT DEFAULT '',
    gst_percent REAL DEFAULT 18,
    qty         REAL DEFAULT 1,
    rate        REAL DEFAULT 0,
    amount      REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_quote ON quote_items(quote_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_TERMS = (
    "PAYMENT:- 50% ADVANCE 50% BEFORE DELIVERY\n"
    "DELIVERY:- 15-20 DAYS (EXCLUDING SUNDAYS & HOLIDAYS)\n"
    "CANCELLATION:- NON-REFUNDABLE 25% - 40% OF ADVANCE AMT\n"
    "TAX:- GST AS APPLICABLE/NO GST FOR SEZ\n"
    "FREIGHT:- ON TO PAYABLE BASIS(OUT OF MUMBAI)\n"
    "ELECTRICAL INPUTS:- 3-PHASE POWER,415Volts,50hz"
)


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # Keep databases created by earlier versions working.
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(companies)")}
    if "contact_line" not in existing:
        conn.execute("ALTER TABLE companies ADD COLUMN contact_line TEXT DEFAULT ''")
    defaults = {"default_terms": DEFAULT_TERMS, "default_company": "WELL WORTH"}
    for key, value in defaults.items():
        if conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone() is None:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
