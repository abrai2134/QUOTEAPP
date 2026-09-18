"""One-time import of the AppSheet CSV exports into the SQLite database.

Run with:  python -m app.seed          (skips tables that already hold rows)
           python -m app.seed --force  (wipes the master tables and re-imports)

Quotes raised in the app are never touched by this script.
"""

import csv
import os
import re
import sys
from difflib import SequenceMatcher

from .db import BASE_DIR, get_db, init_db

DATA_DIR = os.path.join(BASE_DIR, "data")

CLIENTS_CSV = os.path.join(DATA_DIR, "CLIENT_DATA_BASE.csv")
MACHINES_CSV = os.path.join(DATA_DIR, "MACHINE_DATA.csv")
COMPANIES_CSV = os.path.join(DATA_DIR, "COMPANIES_WITH_GST.csv")

# Values that stand in for "not supplied" in the AppSheet data.  The e-mail
# placeholders are typed by hand and come in dozens of misspellings
# (noemail@gmail.com, NOEMAIL@GAMIL.COM, noemail@gmil.com ...), so match on the
# part before the @ rather than the whole address.
PLACEHOLDER_EMAIL_USERS = {"noemail", "no", "na", "none", "nil", "nomail",
                           "noemailid", "noid", "nogmail", "test", "not", "nomailid"}
PLACEHOLDER_EMAIL_TARGETS = ("noemail", "noemailid", "nomailid")
PLACEHOLDER_GST = {"no", "no gst", "nogst", "no gst no", "nogstno", "gst no",
                   "gstno", "gst", "none", "nil", "n/a", "na", "-", "--"}


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def clean(value):
    return (value or "").strip()


def parse_rate(value):
    """'78,000.00' -> 78000.0 ; blank/garbage -> 0.0"""
    text = re.sub(r"[^0-9.\-]", "", clean(value))
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def parse_int(value):
    text = re.sub(r"[^0-9\-]", "", clean(value))
    try:
        return int(text) if text else None
    except ValueError:
        return None


def normalise_gst(value):
    """Turn the AppSheet 'NO GST' / 'nogst' fillers into empty text."""
    text = clean(value)
    return "" if text.lower() in PLACEHOLDER_GST else text


def _letters(text):
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _is_placeholder_user(candidate):
    """True for 'noemail' and its many hand-typed misspellings.

    The database holds noemial@, noeamil@, noemilid@, 'NO EMAIL @' and so on,
    but also real addresses that merely start with 'no' (noorjewels@yahoo.com,
    noraah.finance@gmail.com), so compare by similarity rather than by prefix.
    """
    if not candidate:
        return False
    if candidate in PLACEHOLDER_EMAIL_USERS:
        return True
    return any(SequenceMatcher(None, candidate, target).ratio() >= 0.82
               for target in PLACEHOLDER_EMAIL_TARGETS)


def normalise_email(value):
    """Drop placeholder addresses; keep anything that looks like a real one."""
    text = clean(value)
    if not text or "@" not in text:
        return "" if _letters(text) in PLACEHOLDER_EMAIL_USERS else text
    local, _, domain = text.partition("@")
    # 'NOE@MAIL.COM' is 'noemail' with the @ typed one character early, so test
    # the local part on its own and joined to the first label of the domain.
    joined = _letters(local) + _letters(domain.split(".")[0])
    if _is_placeholder_user(_letters(local)) or _is_placeholder_user(joined):
        return ""
    return text


# The bold contact strip printed under the bank box, taken from the existing
# quotation template.  Editable per company under Setup in the app.
OFFICE_CELLS = "9930 253 293 / 932 452 1664"
OFFICE_TEL = "022-28511664/2405"


def build_contact_line(tel):
    """Blank in the CSV means the shared Sakinaka office line; N/A means none."""
    tel = clean(tel)
    if tel.upper() in {"N/A", "NA", "-"}:
        return f"CELL:- {OFFICE_CELLS}"
    return f"CELL:- {OFFICE_CELLS} ;    TEL:- {tel or OFFICE_TEL}."


def seed_companies(conn):
    rows = read_csv(COMPANIES_CSV)
    inserted = 0
    for row in rows:
        name = clean(row.get("M/S"))
        if not name:
            continue
        tel = clean(row.get("TEL:-"))
        # Re-seeding refreshes the address from the CSV but never clobbers the
        # bank details or contact strip once they have been edited in the app.
        conn.execute(
            """INSERT INTO companies
               (name, address, address2, tel, bank_details, contact_line)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   address = excluded.address,
                   address2 = excluded.address2,
                   tel = excluded.tel,
                   bank_details = CASE WHEN COALESCE(companies.bank_details, '') = ''
                                       THEN excluded.bank_details
                                       ELSE companies.bank_details END,
                   contact_line = CASE WHEN COALESCE(companies.contact_line, '') = ''
                                       THEN excluded.contact_line
                                       ELSE companies.contact_line END""",
            (
                name,
                clean(row.get("M/S ADD")),
                clean(row.get("M/S ADD2")),
                tel,
                clean(row.get("BANK DETAILS")),
                build_contact_line(tel),
            ),
        )
        inserted += 1
    return inserted


def seed_clients(conn):
    rows = read_csv(CLIENTS_CSV)
    inserted = 0
    seen = set()
    for row in rows:
        party = clean(row.get("PARTY"))
        if not party:
            continue
        # The export carries duplicate party rows; keep the first occurrence.
        key = party.upper()
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            """INSERT INTO clients
               (party, address, address2, city, cell_no, cell_no2, email, email2,
                gst_no, remarks, entry_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                party,
                clean(row.get("PARTY ADD")),
                clean(row.get("PARTY ADD2")),
                clean(row.get("CITY")),
                clean(row.get("CELL NO")),
                clean(row.get("CELLNO2")),
                normalise_email(row.get("EMAILID")),
                normalise_email(row.get("EMAILID2")),
                normalise_gst(row.get("GST NO")),
                clean(row.get("REMARKS")),
                clean(row.get("ENTRY BY")),
                clean(row.get("NEW SINCE")),
            ),
        )
        inserted += 1
    return inserted


def seed_machines(conn):
    rows = read_csv(MACHINES_CSV)
    inserted = 0
    people = set()
    for row in rows:
        model = clean(row.get("MODEL1"))
        if not model:
            continue
        description = clean(row.get("MACHINE1"))
        entry_by = clean(row.get("ENTRY BY"))
        if entry_by:
            people.add(entry_by.upper())
        conn.execute(
            """INSERT INTO machines
               (model, description, rate, entry_by, wed, min_days, max_days, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model,
                description,
                parse_rate(row.get("RATE1")),
                entry_by,
                clean(row.get("w.e.d")),
                parse_int(row.get("MIN DAYS")),
                parse_int(row.get("MAX DAYS")),
                # Items marked DONT USE stay in the table for history but are
                # hidden from the item picker.
                0 if "DONT USE" in description.upper() else 1,
            ),
        )
        inserted += 1
    return inserted, people


def seed_salespersons(conn, names):
    for name in sorted(names):
        conn.execute(
            "INSERT INTO salespersons (name) VALUES (?) ON CONFLICT(name) DO NOTHING",
            (name,),
        )
    return len(names)


def main(force=False):
    init_db()
    conn = get_db()
    try:
        if force:
            for table in ("clients", "machines", "companies", "salespersons"):
                conn.execute(f"DELETE FROM {table}")

        # The company list is seven rows, so keep it in step on every start.
        n_companies = seed_companies(conn)

        existing = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]
        if existing and not force:
            conn.commit()
            print(f"Master data already loaded ({existing} clients, "
                  f"{n_companies} companies refreshed). Re-run with --force to reload.")
            return

        n_clients = seed_clients(conn)
        n_machines, people = seed_machines(conn)
        n_people = seed_salespersons(conn, people)
        conn.commit()
        print(f"Imported {n_companies} companies, {n_clients} clients, "
              f"{n_machines} machines, {n_people} salespersons.")
    finally:
        conn.close()


if __name__ == "__main__":
    main(force="--force" in sys.argv)
