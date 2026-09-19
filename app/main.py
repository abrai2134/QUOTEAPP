"""Flask backend for the Well Worth quotation app."""

import csv
import io
import os
import time
from datetime import datetime

from datetime import timedelta

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from . import auth

from .db import (DEFAULT_TERMS, INSTANCE_DIR, TIMEZONE, get_db, get_setting,
                 init_db, local_now, now, same_zone, set_setting, squeeze)
from .mailer import MailNotConfigured, is_configured as mail_configured, send_quote
from .order_sheet import (COLUMNS as SHEET_COLUMNS, HEADINGS, MIRROR_PATH,
                          SAVE_TIMEOUT, STD_FILES,
                          build_row, fetch_rows, is_configured as sheet_configured,
                          clean_url, new_sheet_id, push_to_sheet, row_to_quote,
                          sheet_health, url_complaint,
                          sheet_url,
                          sync_quote)
from .print_view import render as render_print_view
from .quote_pdf import generate_quote_pdf
from .quote_xlsx import build_filename, generate_quote_xlsx

OUTPUT_DIR = os.path.join(INSTANCE_DIR, "output")

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = auth.secret_key()
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set QUOTEAPP_HTTPS=1 when the app is served over https (any hosted setup),
    # so the session cookie is never sent over a plain connection.
    SESSION_COOKIE_SECURE=os.environ.get("QUOTEAPP_HTTPS", "") == "1",
)


@app.before_request
def _gate():
    return auth.require_pin()


@app.errorhandler(Exception)
def _api_errors_stay_json(exc):
    """The screens read every reply as JSON, so an /api/ route must never hand
    back an HTML error page - that used to surface as an unreadable
    "Unexpected token '<'" and hid whatever had actually gone wrong."""
    status = exc.code if isinstance(exc, HTTPException) else 500
    if not request.path.startswith("/api/"):
        return exc if isinstance(exc, HTTPException) else ("Server error", 500)
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), status
    app.logger.exception("Unhandled error on %s", request.path)
    return jsonify({"error": f"{exc.__class__.__name__}: {exc}"}), 500


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/login")
def login_form():
    if not auth.is_enabled():
        return redirect("/")
    return auth.login_page()


@app.post("/login")
def login_submit():
    if not auth.is_enabled():
        return redirect("/")
    wait = auth.locked_out()
    if wait:
        return auth.login_page(
            f"Too many wrong attempts. Try again in {wait // 60 + 1} minute(s)."), 429
    if auth.check_pin(request.form.get("pin")):
        auth.note_success()
        auth.sign_in()
        return redirect("/")
    auth.note_failure()
    return auth.login_page("That PIN is not right."), 401


@app.post("/logout")
def logout():
    from flask import session
    session.clear()
    return redirect("/login")


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# The form sends what a datetime-local box holds, which is "2026-09-19 13:32"
# on some browsers and "...:07" on others.  Either way it is stored the one way
# the rest of the app reads.
STAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def normalise_stamp(value):
    text = str(value or "").strip().replace("T", " ")
    for fmt in STAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return ""


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# static
# --------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# --------------------------------------------------------------------------
# master data
# --------------------------------------------------------------------------

@app.get("/api/companies")
def list_companies():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM companies WHERE is_active = 1 ORDER BY name").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.put("/api/companies/<int:company_id>")
def update_company(company_id):
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        "UPDATE companies SET contact_line = ?, bank_details = ? WHERE id = ?",
        (data.get("contact_line", ""), data.get("bank_details", ""), company_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.get("/api/salespersons")
def list_salespersons():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM salespersons WHERE is_active = 1 ORDER BY name").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.put("/api/salespersons/<int:sp_id>")
def update_salesperson(sp_id):
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        "UPDATE salespersons SET phone = ?, email = ? WHERE id = ?",
        (data.get("phone", ""), data.get("email", ""), sp_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM salespersons WHERE id = ?", (sp_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.post("/api/salespersons")
def create_salesperson():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip().upper()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO salespersons (name, phone, email) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET phone = excluded.phone, email = excluded.email",
        (name, data.get("phone", ""), data.get("email", "")),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM salespersons WHERE name = ?", (name,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


CLIENT_SORTS = {
    "name": "party COLLATE NOCASE ASC",
    "name_desc": "party COLLATE NOCASE DESC",
    "recent": "id DESC",
    "city": "city COLLATE NOCASE ASC, party COLLATE NOCASE ASC",
}


@app.get("/api/clients")
def search_clients():
    query = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 40)), 200)
    order = CLIENT_SORTS.get(request.args.get("sort"), CLIENT_SORTS["name"])
    conn = get_db()
    if query:
        # Punctuation and spacing are ignored on both sides, so "kpsanghvi"
        # finds K.P. SANGHVI and a phone number typed with or without spaces
        # finds the same party.  A name that starts with the search text still
        # comes first, then the chosen order applies within each group.
        key = squeeze(query)
        starts, contains = f"{key}%", f"%{key}%"
        rows = conn.execute(
            """SELECT * FROM clients
               WHERE squeeze(party) LIKE ? OR squeeze(city) LIKE ?
                  OR squeeze(cell_no) LIKE ? OR squeeze(gst_no) LIKE ?
               ORDER BY CASE WHEN squeeze(party) LIKE ? THEN 0 ELSE 1 END, """ + order + """
               LIMIT ?""",
            (contains, contains, contains, contains, starts, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clients ORDER BY " + order + " LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.get("/api/clients/<int:client_id>")
def get_client(client_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


@app.post("/api/clients")
def create_client():
    data = request.get_json(force=True)
    party = (data.get("party") or "").strip()
    if not party:
        return jsonify({"error": "Party name is required"}), 400
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO clients
           (party, address, address2, city, cell_no, cell_no2, email, email2,
            gst_no, remarks, entry_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (party, data.get("address", ""), data.get("address2", ""),
         data.get("city", ""), data.get("cell_no", ""), data.get("cell_no2", ""),
         data.get("email", ""), data.get("email2", ""), data.get("gst_no", ""),
         data.get("remarks", ""), data.get("entry_by", ""), now()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.put("/api/clients/<int:client_id>")
def update_client(client_id):
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        """UPDATE clients SET party = ?, address = ?, address2 = ?, city = ?,
               cell_no = ?, cell_no2 = ?, email = ?, email2 = ?, gst_no = ?,
               remarks = ?
           WHERE id = ?""",
        (data.get("party", ""), data.get("address", ""), data.get("address2", ""),
         data.get("city", ""), data.get("cell_no", ""), data.get("cell_no2", ""),
         data.get("email", ""), data.get("email2", ""), data.get("gst_no", ""),
         data.get("remarks", ""), client_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.delete("/api/clients/<int:client_id>")
def delete_client(client_id):
    conn = get_db()
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": client_id})


@app.get("/api/machines")
def search_machines():
    query = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 40)), 200)
    conn = get_db()
    if query:
        # Separators are ignored on both sides, so "ft24bk" finds FT~24BK and
        # "tp150cf" finds TP150~CF.  The model code typed in full wins, then a
        # code starting with it, then any model containing it, then a
        # description match - shortest model first inside each group.
        key = squeeze(query)
        starts, contains = f"{key}%", f"%{key}%"
        rows = conn.execute(
            """SELECT * FROM (
                 SELECT *, CASE WHEN model_code(model) = ?      THEN 0
                                WHEN model_code(model) LIKE ?   THEN 1
                                WHEN squeeze(model) LIKE ?      THEN 2
                                ELSE 3 END AS rank
                 FROM machines
                 WHERE is_active = 1
                   AND (squeeze(model) LIKE ? OR squeeze(description) LIKE ?)
               )
               ORDER BY rank,
                        CASE WHEN rank = 3 THEN 0 ELSE LENGTH(model) END,
                        model
               LIMIT ?""",
            (key, starts, contains, contains, contains, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM machines WHERE is_active = 1 ORDER BY model LIMIT ?",
            (limit,)).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.post("/api/machines")
def create_machine():
    data = request.get_json(force=True)
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "Model is required"}), 400
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO machines (model, description, rate, entry_by, wed) "
        "VALUES (?, ?, ?, ?, ?)",
        (model, data.get("description", ""), as_float(data.get("rate")),
         data.get("entry_by", ""), local_now().strftime("%m/%d/%Y")),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM machines WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.put("/api/machines/<int:machine_id>")
def update_machine(machine_id):
    data = request.get_json(force=True)
    conn = get_db()
    conn.execute(
        "UPDATE machines SET model = ?, description = ?, rate = ? WHERE id = ?",
        (data.get("model", ""), data.get("description", ""),
         as_float(data.get("rate")), machine_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM machines WHERE id = ?", (machine_id,)).fetchone()
    conn.close()
    return jsonify(dict(row) if row else {})


@app.delete("/api/machines/<int:machine_id>")
def delete_machine(machine_id):
    """Hide a model from the item picker; quotations that used it are untouched."""
    conn = get_db()
    conn.execute("UPDATE machines SET is_active = 0 WHERE id = ?", (machine_id,))
    conn.commit()
    conn.close()
    return jsonify({"hidden": machine_id})


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

@app.get("/api/settings")
def read_settings():
    conn = get_db()
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM quotes WHERE COALESCE(synced_at, '') = ''"
    ).fetchone()["n"]
    # Why the last one did not get through, so Setup can say so instead of
    # leaving the reason in a toast that has already gone.
    last = conn.execute(
        "SELECT sync_error FROM quotes WHERE COALESCE(sync_error, '') <> '' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return jsonify({
        "default_terms": get_setting("default_terms", DEFAULT_TERMS),
        "default_company": get_setting("default_company", ""),
        "mail_configured": mail_configured(),
        "sheet_url": sheet_url(),
        "sheet_secret": get_setting("sheet_secret", ""),
        "sheet_configured": sheet_configured(),
        "pending_sync": pending,
        "last_sync_error": last["sync_error"] if last else "",
        "headings": HEADINGS,
        "std_files": STD_FILES,
    })


@app.put("/api/settings")
def write_settings():
    data = request.get_json(force=True)
    for key in ("default_terms", "default_company", "sheet_webapp_url", "sheet_secret"):
        if key not in data:
            continue
        value = data[key]
        if key == "sheet_webapp_url":
            value = clean_url(value)
        elif isinstance(value, str):
            value = value.strip()
        set_setting(key, value)
    return jsonify({
        "default_terms": get_setting("default_terms", DEFAULT_TERMS),
        "default_company": get_setting("default_company", ""),
    })


# --------------------------------------------------------------------------
# quotes
# --------------------------------------------------------------------------

def compute_totals(items, gst_percent, advance):
    subtotal = 0.0
    gst_amount = 0.0
    cleaned = []
    for position, item in enumerate(items, start=1):
        description = (item.get("description") or "").strip()
        model = (item.get("model") or "").strip()
        if not description and not model:
            continue
        qty = as_float(item.get("qty"), 1)
        rate = as_float(item.get("rate"))
        line_gst = as_float(item.get("gst_percent"), gst_percent)
        amount = round(qty * rate, 2)
        subtotal += amount
        gst_amount += amount * line_gst / 100.0
        cleaned.append({
            "position": position,
            "model": model,
            "description": description,
            "gst_percent": line_gst,
            "qty": qty,
            "rate": rate,
            "amount": amount,
        })
    subtotal = round(subtotal, 2)
    gst_amount = round(gst_amount, 2)
    grand_total = round(subtotal + gst_amount, 2)
    balance = round(grand_total - as_float(advance), 2)
    return cleaned, subtotal, gst_amount, grand_total, balance


def load_quote(conn, quote_id):
    quote = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
    if not quote:
        return None
    quote = dict(quote)
    quote["items"] = rows_to_dicts(conn.execute(
        "SELECT * FROM quote_items WHERE quote_id = ? ORDER BY position",
        (quote_id,)).fetchall())
    company = conn.execute(
        "SELECT * FROM companies WHERE id = ?", (quote["company_id"],)).fetchone()
    quote["company"] = dict(company) if company else {}
    return quote


QUOTE_SORTS = {
    "date_desc": "q.quote_date DESC, q.id DESC",
    "date_asc": "q.quote_date ASC, q.id ASC",
    "party": "q.party_name COLLATE NOCASE ASC",
    "amount_desc": "q.grand_total DESC",
    "amount_asc": "q.grand_total ASC",
}


@app.get("/api/quotes")
def list_quotes():
    query = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    order = QUOTE_SORTS.get(request.args.get("sort"), QUOTE_SORTS["date_desc"])
    conn = get_db()
    if query:
        like = f"%{query}%"
        rows = conn.execute(
            """SELECT q.*, c.name AS company_name FROM quotes q
               LEFT JOIN companies c ON c.id = q.company_id
               WHERE q.party_name LIKE ? OR q.quote_no LIKE ? OR q.city LIKE ?
                  OR q.sheet_id LIKE ? OR q.salesperson LIKE ?
               ORDER BY """ + order + " LIMIT ?",
            (like, like, like, like, like, limit)).fetchall()
    else:
        rows = conn.execute(
            """SELECT q.*, c.name AS company_name FROM quotes q
               LEFT JOIN companies c ON c.id = q.company_id
               ORDER BY """ + order + " LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.get("/api/quotes/<int:quote_id>")
def read_quote(quote_id):
    conn = get_db()
    quote = load_quote(conn, quote_id)
    conn.close()
    if not quote:
        return jsonify({"error": "Not found"}), 404
    return jsonify(quote)


def persist_quote(data, quote_id=None):
    gst_percent = as_float(data.get("gst_percent"), 18)
    advance = as_float(data.get("advance"))
    items, subtotal, gst_amount, grand_total, balance = compute_totals(
        data.get("items", []), gst_percent, advance)

    quote_date = normalise_stamp(data.get("quote_date")) or now()
    fields = (
        data.get("quote_no", ""), quote_date,
        data.get("heading") or "QUOTATION", data.get("std_file") or "NON STD FILE",
        data.get("company_id"),
        data.get("client_id"), data.get("party_name", ""),
        data.get("party_address", ""), data.get("city", ""),
        data.get("party_email", ""), data.get("whatsapp_no", ""),
        data.get("cc_to_client") or "NO",
        data.get("salesperson", ""), data.get("salesperson_phone", ""),
        data.get("order_status", "PENDING"),
        data.get("payment_status") or "PENDING", data.get("dispatch", "PENDING"),
        data.get("followup1", ""), data.get("remarks1", ""),
        data.get("followup2", ""), data.get("remarks2", ""),
        data.get("followup3", ""), data.get("remarks3", ""),
        data.get("reminder_date", ""), as_float(data.get("dispatch_qty")),
        advance, gst_percent, data.get("terms", ""),
        subtotal, gst_amount, grand_total, balance,
    )

    conn = get_db()
    if quote_id:
        conn.execute(
            """UPDATE quotes SET quote_no = ?, quote_date = ?, heading = ?,
                   std_file = ?, company_id = ?, client_id = ?, party_name = ?,
                   party_address = ?, city = ?, party_email = ?, whatsapp_no = ?,
                   cc_to_client = ?, salesperson = ?, salesperson_phone = ?,
                   order_status = ?, payment_status = ?, dispatch = ?,
                   followup1 = ?, remarks1 = ?, followup2 = ?, remarks2 = ?,
                   followup3 = ?, remarks3 = ?, reminder_date = ?, dispatch_qty = ?,
                   advance = ?, gst_percent = ?, terms = ?, subtotal = ?,
                   gst_amount = ?, grand_total = ?, balance = ?, updated_at = ?
               WHERE id = ?""", fields + (now(), quote_id))
        conn.execute("DELETE FROM quote_items WHERE quote_id = ?", (quote_id,))
    else:
        cur = conn.execute(
            """INSERT INTO quotes (quote_no, quote_date, heading, std_file,
                   company_id, client_id, party_name, party_address, city,
                   party_email, whatsapp_no, cc_to_client, salesperson,
                   salesperson_phone, order_status, payment_status, dispatch,
                   followup1, remarks1, followup2, remarks2, followup3, remarks3,
                   reminder_date, dispatch_qty, advance, gst_percent, terms,
                   subtotal, gst_amount, grand_total, balance,
                   sheet_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            fields + (new_sheet_id(), now(), now()))
        quote_id = cur.lastrowid

    for item in items:
        conn.execute(
            """INSERT INTO quote_items
               (quote_id, position, model, description, gst_percent, qty, rate, amount)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (quote_id, item["position"], item["model"], item["description"],
             item["gst_percent"], item["qty"], item["rate"], item["amount"]))

    conn.commit()
    quote = load_quote(conn, quote_id)
    conn.close()
    return quote


def save_and_sync(data, quote_id=None):
    """Persist the quotation, then record it in the Order items sheet.

    A sheet that is unreachable never blocks the save: the row is always kept
    in the local mirror and the quote is listed as not synced.
    """
    quote = persist_quote(data, quote_id)
    synced, message = sync_quote(quote, timeout=SAVE_TIMEOUT)
    conn = get_db()
    record_sync(conn, quote["id"], synced, message)
    conn.close()
    quote["synced"] = synced
    quote["sync_message"] = message
    return quote


@app.post("/api/quotes")
def create_quote():
    data = request.get_json(force=True)
    if not data.get("party_name"):
        return jsonify({"error": "Select a party first"}), 400
    if not data.get("company_id"):
        return jsonify({"error": "Select which of your companies is quoting"}), 400
    return jsonify(save_and_sync(data)), 201


@app.put("/api/quotes/<int:quote_id>")
def edit_quote(quote_id):
    data = request.get_json(force=True)
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM quotes WHERE id = ?", (quote_id,)).fetchone()
    conn.close()
    if not exists:
        return jsonify({"error": "Not found"}), 404
    return jsonify(save_and_sync(data, quote_id))


@app.delete("/api/quotes/<int:quote_id>")
def delete_quote(quote_id):
    conn = get_db()
    conn.execute("DELETE FROM quote_items WHERE quote_id = ?", (quote_id,))
    conn.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": quote_id})


def render_quote_files(quote, want_pdf=False):
    """Write the .xlsx (and optionally the .pdf) for `quote` into instance/output."""
    payload = dict(quote)
    try:
        payload["quote_date"] = datetime.strptime(
            quote["quote_date"], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        payload["quote_date"] = local_now().replace(tzinfo=None)

    filename = build_filename(payload)
    xlsx_path = os.path.join(OUTPUT_DIR, f"{quote['id']:05d}_{filename}")
    generate_quote_xlsx(payload, xlsx_path)

    pdf_path = None
    if want_pdf:
        pdf_path = os.path.splitext(xlsx_path)[0] + ".pdf"
        generate_quote_pdf(payload, pdf_path)
    return xlsx_path, pdf_path, filename


@app.post("/api/quotes/<int:quote_id>/generate")
def generate(quote_id):
    want_pdf = bool((request.get_json(silent=True) or {}).get("pdf"))
    conn = get_db()
    quote = load_quote(conn, quote_id)
    if not quote:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    xlsx_path, pdf_path, filename = render_quote_files(quote, want_pdf)
    conn.execute("UPDATE quotes SET file_name = ? WHERE id = ?",
                 (os.path.basename(xlsx_path), quote_id))
    conn.commit()
    conn.close()
    return jsonify({
        "file_name": filename,
        "xlsx_url": f"/api/quotes/{quote_id}/download?fmt=xlsx",
        "pdf_url": f"/api/quotes/{quote_id}/download?fmt=pdf" if pdf_path else None,
    })


@app.get("/api/quotes/<int:quote_id>/download")
def download(quote_id):
    fmt = request.args.get("fmt", "xlsx")
    conn = get_db()
    quote = load_quote(conn, quote_id)
    conn.close()
    if not quote:
        return jsonify({"error": "Not found"}), 404

    xlsx_path, pdf_path, filename = render_quote_files(quote, want_pdf=(fmt == "pdf"))
    if fmt == "pdf":
        return send_file(pdf_path, as_attachment=True,
                         download_name=os.path.splitext(filename)[0] + ".pdf")
    return send_file(xlsx_path, as_attachment=True, download_name=filename)


@app.get("/api/quotes/<int:quote_id>/print")
def print_view(quote_id):
    """A4 HTML view - the browser's Print dialog turns it into a PDF."""
    conn = get_db()
    quote = load_quote(conn, quote_id)
    conn.close()
    if not quote:
        return jsonify({"error": "Not found"}), 404
    return render_print_view(quote)


def record_sync(conn, quote_id, synced, message):
    conn.execute(
        "UPDATE quotes SET synced_at = ?, sync_error = ? WHERE id = ?",
        (now() if synced else "", "" if synced else message, quote_id))
    conn.commit()


@app.post("/api/quotes/<int:quote_id>/sync")
def sync_one(quote_id):
    """Append this quotation to the Order items sheet (and the local mirror)."""
    conn = get_db()
    quote = load_quote(conn, quote_id)
    if not quote:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    if not sheet_configured():
        conn.close()
        return jsonify({
            "error": "No Google Sheet is connected yet. Open Setup, paste the "
                     "Apps Script web app URL and press Test the connection.",
        }), 400

    synced, message = sync_quote(quote)
    record_sync(conn, quote_id, synced, message)
    conn.close()
    if synced:
        return jsonify({"synced": True, "message": message})
    return jsonify({"synced": False, "error": message}), 502


# A hosted app sits behind a gateway that gives up on a request after a minute
# or so and answers with its own error page.  Pushing many rows to Apps Script
# can easily take longer than that, so a batch stops while there is still time
# to reply properly and says how many are left; pressing again carries on.
SYNC_BUDGET = 40.0


@app.post("/api/sync-pending")
def sync_pending():
    """Push quotations that have not reached the sheet yet, within a time budget."""
    started = time.monotonic()
    conn = get_db()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM quotes WHERE COALESCE(synced_at, '') = '' ORDER BY id")]
    done, failed, last_error = 0, 0, ""
    for position, quote_id in enumerate(ids):
        if position and time.monotonic() - started > SYNC_BUDGET:
            break
        quote = load_quote(conn, quote_id)
        synced, message = sync_quote(quote)
        record_sync(conn, quote_id, synced, message)
        if synced:
            done += 1
        else:
            failed += 1
            last_error = message
    remaining = len(ids) - done - failed
    conn.close()
    return jsonify({"synced": done, "failed": failed, "remaining": remaining,
                    "error": last_error})


def pull_from_sheet(limit=500):
    """Import sheet rows the app does not have yet.  Returns (added, skipped)."""
    rows = fetch_rows(limit)
    conn = get_db()
    known = {r["sheet_id"] for r in conn.execute(
        "SELECT sheet_id FROM quotes WHERE COALESCE(sheet_id, '') <> ''")}
    companies = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM companies")}

    added = skipped = 0
    for row in rows:
        quote = row_to_quote(row)
        sheet_id = quote.get("sheet_id")
        # Rows with no id, or ones already held, are left alone.
        if (not sheet_id or sheet_id in known or not quote.get("party_name")
                or sheet_id.upper() == "CONNECTION TEST"
                or quote.get("heading", "").upper() == "CONNECTION TEST"):
            skipped += 1
            continue
        known.add(sheet_id)

        cur = conn.execute(
            """INSERT INTO quotes (sheet_id, quote_date, heading, std_file, company_id,
                   party_name, party_address, city, party_email, whatsapp_no,
                   cc_to_client, salesperson, salesperson_phone, order_status,
                   payment_status, dispatch, dispatch_qty, reminder_date, followup1,
                   remarks1, advance, gst_percent, terms, subtotal, gst_amount,
                   grand_total, balance, synced_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sheet_id, quote["quote_date"] or now(), quote["heading"], quote["std_file"],
             companies.get(quote["company_name"]), quote["party_name"],
             quote["party_address"], quote["city"], quote["party_email"],
             quote["whatsapp_no"], quote["cc_to_client"], quote["salesperson"],
             quote["salesperson_phone"], quote["order_status"], quote["payment_status"],
             quote["dispatch"], quote["dispatch_qty"], quote["reminder_date"],
             quote["followup1"], quote["remarks1"], quote["advance"],
             quote["items"][0]["gst_percent"] if quote["items"] else 18,
             quote["terms"],
             round(quote["grand_total"] - quote["gst_amount"], 2),
             quote["gst_amount"], quote["grand_total"], quote["balance"],
             now(), now(), now()))

        for item in quote["items"]:
            conn.execute(
                """INSERT INTO quote_items (quote_id, position, model, description,
                       gst_percent, qty, rate, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (cur.lastrowid, item["position"], item["model"], item["description"],
                 item["gst_percent"], item["qty"], item["rate"], item["amount"]))
        added += 1

    conn.commit()
    conn.close()
    return added, skipped


@app.post("/api/sheet/pull")
def sheet_pull():
    """Bring in quotations raised elsewhere, or recover after a server restart."""
    if not sheet_configured():
        return jsonify({"error": "Connect a Google Sheet first."}), 400
    try:
        added, skipped = pull_from_sheet(
            int((request.get_json(silent=True) or {}).get("limit", 500)))
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify({
        "added": added, "skipped": skipped,
        "message": f"{added} quotation(s) brought in, {skipped} already here.",
    })


@app.post("/api/sheet/test")
def sheet_test():
    """Check the Apps Script URL by sending a row the script ignores."""
    data = request.get_json(force=True) or {}
    if "sheet_webapp_url" in data:
        set_setting("sheet_webapp_url", clean_url(data.get("sheet_webapp_url")))
        set_setting("sheet_secret", (data.get("sheet_secret") or "").strip())
    if not sheet_configured():
        return jsonify({"ok": False, "error": "Paste the web app URL first."}), 400
    # A URL that looks wrong is worth saying so, but never a reason to refuse
    # to try: if it works, it works.  The complaint is added to the failure.
    complaint = url_complaint(sheet_url())
    try:
        health = sheet_health()          # reading
        fetch_rows(limit=1)              # reading rows back
        # Only a script that says it understands a test row gets sent one -
        # an older copy would take it as a real quotation and append it.
        probe = (push_to_sheet(build_row({}), dry_run=True)
                 if health.get("canTest") else None)
    except RuntimeError as exc:
        error = str(exc)
        if complaint:
            error += f" Also: {complaint}"
        return jsonify({"ok": False, "error": error}), 502

    if probe is None:
        return jsonify({"ok": True, "message":
            "Reading from the sheet works, but this is an older copy of the "
            "script, so the part that adds rows could not be checked without "
            "writing one. Re-paste Code.gs into the script editor and deploy a "
            "New version to have this tested too."}), 200
    if not probe.get("test"):
        return jsonify({"ok": False, "error":
            "The script answered, but not from the part that adds rows. "
            "Re-paste Code.gs into the script editor, then Deploy > Manage "
            "deployments > pencil > Version: New version."}), 502

    message = "Sheet is connected, reading and writing. Nothing was written to it."
    if health.get("file"):
        message += f" File: {health['file']}."
    # Google reads and writes the dates in the spreadsheet's own timezone, so a
    # sheet set to another country stamps every quotation at the wrong time.
    zone = health.get("timezone")
    if zone and not same_zone(zone):
        message += (f" Warning: the sheet's timezone is {zone}, which keeps a "
                    f"different clock from {TIMEZONE} - quotation dates will be "
                    "hours out. Change it in the sheet under File > Settings > "
                    "Time zone.")
    return jsonify({"ok": True, "message": message, "timezone": zone})


# Column names match the CSV exports the databases came from, so a file
# downloaded here can be re-imported with `python -m app.seed --force`.
EXPORTS = {
    "clients": ("CLIENT DATA BASE",
                ["PARTY", "PARTY ADD", "PARTY ADD2", "CITY", "CELL NO", "CELLNO2",
                 "EMAILID", "EMAILID2", "GST NO", "REMARKS", "ENTRY BY"],
                "SELECT party, address, address2, city, cell_no, cell_no2, email, "
                "email2, gst_no, remarks, entry_by FROM clients ORDER BY party"),
    "machines": ("MACHINE DATA",
                 ["MODEL1", "MACHINE1", "RATE1", "ENTRY BY"],
                 "SELECT model, description, rate, entry_by FROM machines "
                 "WHERE is_active = 1 ORDER BY model"),
    "team": ("TEAM",
             ["NAME", "CONTACT NO", "EMAIL"],
             "SELECT name, phone, email FROM salespersons WHERE is_active = 1 "
             "ORDER BY name"),
}


@app.get("/api/export/<table>.csv")
def export_table(table):
    """Download a master table as CSV."""
    spec = EXPORTS.get(table)
    if not spec:
        return jsonify({"error": "Unknown table"}), 404
    name, headers, query = spec

    conn = get_db()
    rows = conn.execute(query).fetchall()
    conn.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else v for v in tuple(row)])

    data = buffer.getvalue().encode("utf-8-sig")   # BOM keeps Excel happy
    today = local_now().strftime("%Y-%m-%d")
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True,
                     download_name=f"{name} {today}.csv")


@app.get("/api/order-items.csv")
def download_mirror():
    """The local copy of every row that was built for the sheet."""
    if not os.path.exists(MIRROR_PATH):
        return jsonify({"error": "No rows yet."}), 404
    return send_file(MIRROR_PATH, as_attachment=True, download_name="Order items.csv")


@app.post("/api/quotes/<int:quote_id>/email")
def email_quote(quote_id):
    data = request.get_json(force=True) or {}
    conn = get_db()
    quote = load_quote(conn, quote_id)
    conn.close()
    if not quote:
        return jsonify({"error": "Not found"}), 404

    recipients = [a.strip() for a in (data.get("to") or "").replace(";", ",").split(",")
                  if a.strip()]
    if not recipients:
        return jsonify({"error": "No recipient e-mail address"}), 400

    want_pdf = bool(data.get("pdf", True))
    xlsx_path, pdf_path, filename = render_quote_files(quote, want_pdf)
    attachments = [xlsx_path] + ([pdf_path] if pdf_path else [])

    company_name = (quote.get("company") or {}).get("name", "")
    subject = data.get("subject") or f"QUOTATION - {quote['party_name']} - {company_name}"
    body = data.get("body") or (
        f"Dear Sir/Madam,\n\nPlease find attached our quotation "
        f"({os.path.splitext(filename)[0]}).\n\n"
        f"Regards,\n{quote.get('salesperson', '')}\n{company_name}\n"
        f"{quote.get('salesperson_phone', '')}")

    try:
        sent_to = send_quote(recipients, subject, body, attachments)
    except MailNotConfigured as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:  # network / auth problems surface to the UI
        return jsonify({"error": f"Could not send: {exc}"}), 502
    return jsonify({"sent_to": sent_to, "attachments": [os.path.basename(a)
                                                        for a in attachments]})


def create_app():
    init_db()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # A hosted server may start on an empty disk, so import the master data
    # when it is missing.  On a machine that already has it this is a no-op.
    from .seed import main as seed_main
    try:
        seed_main()
    except Exception as exc:                      # a bad CSV must not stop the app
        app.logger.warning("Master data import skipped: %s", exc)

    # Quotations live in the Google Sheet as well, so a server that lost its
    # disk can repopulate its list from there.
    try:
        conn = get_db()
        empty = conn.execute("SELECT COUNT(*) AS n FROM quotes").fetchone()["n"] == 0
        conn.close()
        if empty and sheet_configured():
            added, _ = pull_from_sheet()
            if added:
                app.logger.info("Recovered %s quotation(s) from the sheet", added)
    except Exception as exc:
        app.logger.warning("Could not read quotations back from the sheet: %s", exc)

    return app


if __name__ == "__main__":
    create_app().run(host=os.environ.get("HOST", "0.0.0.0"),
                     port=int(os.environ.get("PORT", 5000)),
                     debug=False, threaded=True)
