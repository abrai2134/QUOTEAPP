"""Accounts Desk web server.

    python -m accounts.main          (or ./run_accounts.sh)

Every person signs in with their own username and password, so each payment
or receipt marked here carries the name of whoever did it.
"""

import csv
import hmac
import io
import json
import os
import secrets
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Flask, Response, jsonify, redirect, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from . import logic
from .db import INSTANCE_DIR, KINDS, get_db, init_db, log, now, squeeze, today
from .tally import TallyFileError

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_NAME="accounts_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("ACCOUNTS_HTTPS", "") == "1",
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
)

MODES = ["NEFT", "RTGS", "IMPS", "UPI", "Cheque", "Cash", "Adjustment", "Other"]


def _secret_key():
    env = os.environ.get("ACCOUNTS_SECRET_KEY")
    if env:
        return env
    path = os.path.join(INSTANCE_DIR, "accounts_secret_key")
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            saved = fh.read().strip()
        if saved:
            return saved
    fresh = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(fresh)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return fresh


app.secret_key = _secret_key()


# ================================================================ sign in

_attempts = {}
MAX_ATTEMPTS = 6
LOCKOUT_SECONDS = 300


def _caller():
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else (request.remote_addr or "?")


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (uid,)).fetchone()
    conn.close()
    if not user or not hmac.compare_digest(session.get("salt", ""), user["session_salt"]):
        return None
    return dict(user)


def user_count():
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n


OPEN_PATHS = {"/login", "/setup", "/health"}


@app.before_request
def _gate():
    if request.path in OPEN_PATHS or request.path.startswith("/static/"):
        return None
    user = current_user()
    if user is None:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Please sign in again."}), 401
        return redirect("/setup" if user_count() == 0 else "/login")
    request.user = user
    # A page on another site cannot add this header, so it cannot make a
    # signed-in browser mark a payment.
    if request.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
        if request.headers.get("X-Requested-With") != "accounts-desk":
            return jsonify({"error": "Request refused."}), 403
    return None


@app.errorhandler(Exception)
def _errors(exc):
    status = exc.code if isinstance(exc, HTTPException) else 500
    if not request.path.startswith("/api/"):
        return exc if isinstance(exc, HTTPException) else ("Server error", 500)
    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), status
    app.logger.exception("Error on %s", request.path)
    return jsonify({"error": f"{exc.__class__.__name__}: {exc}"}), 500


def admin_only():
    if request.user["role"] != "admin":
        return jsonify({"error": "Only an admin can do that."}), 403
    return None


def page(title, body, error=""):
    err = f'<div class="err">{error}</div>' if error else ""
    with open(os.path.join(STATIC, "login.html"), encoding="utf-8") as fh:
        html = fh.read()
    return html.replace("__TITLE__", title).replace("__BODY__", body).replace("__ERROR__", err)


LOGIN_BODY = """
<form method="post" action="/login">
  <h1>Accounts Desk</h1>
  <p class="sub">Well Worth Group &middot; sign in with your own login</p>
  <label>Username<input name="username" autocomplete="username" autocapitalize="none" autofocus required></label>
  <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
  <button type="submit">Sign in</button>
  __ERROR__
</form>"""

SETUP_BODY = """
<form method="post" action="/setup">
  <h1>Accounts Desk &middot; first start</h1>
  <p class="sub">Create the admin login. You will add the accounts team after this.</p>
  __CODE__
  <label>Your name<input name="name" required autofocus></label>
  <label>Username<input name="username" autocapitalize="none" required></label>
  <label>Password (8+ characters)<input name="password" type="password" minlength="8" required></label>
  <button type="submit">Create admin</button>
  __ERROR__
</form>"""


def _setup_body():
    code = ""
    if os.environ.get("ACCOUNTS_SETUP_CODE"):
        code = '<label>Setup code<input name="code" required></label>'
    return SETUP_BODY.replace("__CODE__", code)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/login")
def login_form():
    if user_count() == 0:
        return redirect("/setup")
    return page("Sign in", LOGIN_BODY)


@app.post("/login")
def login_submit():
    who = _caller()
    count, until = _attempts.get(who, (0, 0))
    if count >= MAX_ATTEMPTS and until > time.time():
        return page("Sign in", LOGIN_BODY, "Too many wrong attempts. Wait 5 minutes."), 429
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1",
                        (username,)).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        _attempts.pop(who, None)
        session.clear()
        session["uid"] = user["id"]
        session["salt"] = user["session_salt"]
        session.permanent = True
        log(conn, user["id"], "sign_in", "Signed in")
        conn.commit()
        conn.close()
        return redirect("/")
    conn.close()
    _attempts[who] = (count + 1, time.time() + LOCKOUT_SECONDS)
    return page("Sign in", LOGIN_BODY, "Username or password is not right."), 401


@app.get("/setup")
def setup_form():
    if user_count() > 0:
        return redirect("/login")
    return page("First start", _setup_body())


@app.post("/setup")
def setup_submit():
    if user_count() > 0:
        return redirect("/login")
    code = os.environ.get("ACCOUNTS_SETUP_CODE")
    if code and not hmac.compare_digest(request.form.get("code", ""), code):
        return page("First start", _setup_body(), "Setup code is not right."), 403
    try:
        uid = create_user(request.form.get("name"), request.form.get("username"),
                          request.form.get("password"), "admin", takes_work=0)
    except ValueError as exc:
        return page("First start", _setup_body(), str(exc)), 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    session.clear()
    session["uid"], session["salt"] = uid, user["session_salt"]
    session.permanent = True
    return redirect("/")


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


def create_user(name, username, password, role="member", takes_work=1, conn=None):
    name = " ".join((name or "").split())
    username = (username or "").strip().lower()
    if not name or not username:
        raise ValueError("Name and username are needed.")
    if not username.replace(".", "").replace("_", "").isalnum():
        raise ValueError("Username: letters and numbers only.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    own = conn is None
    conn = conn or get_db()
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        if own:
            conn.close()
        raise ValueError(f"Username '{username}' is taken.")
    cur = conn.execute(
        "INSERT INTO users (username, name, password_hash, role, takes_work, session_salt, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (username, name, generate_password_hash(password), role if role in ("admin", "member")
         else "member", 1 if takes_work else 0, secrets.token_hex(8), now()))
    if own:
        conn.commit()
        conn.close()
    return cur.lastrowid


# ================================================================ pages

@app.get("/")
def index():
    return app.send_static_file("index.html")


def body():
    return request.get_json(silent=True) or {}


def rows(cur):
    return [dict(r) for r in cur]


# ================================================================ people & firms

@app.get("/api/me")
def me():
    u = request.user
    return {"id": u["id"], "name": u["name"], "username": u["username"], "role": u["role"],
            "modes": MODES, "today": today()}


@app.put("/api/me/password")
def my_password():
    data = body()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (request.user["id"],)).fetchone()
    if not check_password_hash(user["password_hash"], data.get("current") or ""):
        conn.close()
        return {"error": "Current password is not right."}, 400
    if len(data.get("new") or "") < 8:
        conn.close()
        return {"error": "New password must be at least 8 characters."}, 400
    salt = secrets.token_hex(8)
    conn.execute("UPDATE users SET password_hash = ?, session_salt = ? WHERE id = ?",
                 (generate_password_hash(data["new"]), salt, user["id"]))
    log(conn, user["id"], "password", "Changed own password")
    conn.commit()
    conn.close()
    session["salt"] = salt
    return {"ok": True}


@app.get("/api/users")
def list_users():
    conn = get_db()
    out = rows(conn.execute("SELECT id, username, name, role, takes_work, active, created_at "
                            "FROM users ORDER BY active DESC, name"))
    conn.close()
    return jsonify(out)


@app.post("/api/users")
def add_user():
    if (bad := admin_only()):
        return bad
    d = body()
    conn = get_db()
    try:
        uid = create_user(d.get("name"), d.get("username"), d.get("password"),
                          d.get("role", "member"), d.get("takes_work", 1), conn=conn)
    except ValueError as exc:
        conn.close()
        return {"error": str(exc)}, 400
    log(conn, request.user["id"], "user_add", f"Added {d.get('name')} ({d.get('username')})")
    conn.commit()
    conn.close()
    return {"id": uid}


@app.put("/api/users/<int:uid>")
def edit_user(uid):
    if (bad := admin_only()):
        return bad
    d = body()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        conn.close()
        return {"error": "No such person."}, 404
    fields, params, said = [], [], []
    if "name" in d and d["name"].strip():
        fields.append("name = ?"); params.append(" ".join(d["name"].split()))
    if "role" in d and d["role"] in ("admin", "member"):
        if uid == request.user["id"] and d["role"] != "admin":
            conn.close()
            return {"error": "You cannot take admin away from yourself."}, 400
        fields.append("role = ?"); params.append(d["role"]); said.append(f"role {d['role']}")
    for flag in ("takes_work", "active"):
        if flag in d:
            if flag == "active" and uid == request.user["id"] and not d[flag]:
                conn.close()
                return {"error": "You cannot switch off your own login."}, 400
            fields.append(f"{flag} = ?"); params.append(1 if d[flag] else 0)
            said.append(f"{flag} {'on' if d[flag] else 'off'}")
    if d.get("password"):
        if len(d["password"]) < 8:
            conn.close()
            return {"error": "Password must be at least 8 characters."}, 400
        fields += ["password_hash = ?", "session_salt = ?"]
        params += [generate_password_hash(d["password"]), secrets.token_hex(8)]
        said.append("password reset")
    if fields:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", params + [uid])
    moved = 0
    if d.get("active") is not None and not d.get("active") or \
            d.get("takes_work") is not None and not d.get("takes_work"):
        moved = hand_over(conn, uid)
        if moved:
            said.append(f"{moved} open bill(s) shared out to the others")
    log(conn, request.user["id"], "user_edit", f"{user['name']}: {', '.join(said) or 'edited'}")
    conn.commit()
    conn.close()
    return {"ok": True, "moved": moved}


def hand_over(conn, uid):
    """Someone left or stopped taking work: their open bills go to the rest."""
    state = logic.bill_state(conn)
    open_ids = defaultdict(list)
    for b in conn.execute("SELECT id, firm_id, kind FROM bills WHERE assigned_to = ? "
                          "AND cleared_at = ''", (uid,)):
        if state[b["id"]]["status"] in ("open", "part"):
            open_ids[(b["firm_id"], b["kind"])].append(b["id"])
    conn.execute("DELETE FROM party_owners WHERE user_id = ?", (uid,))
    moved = 0
    for (firm_id, kind), ids in open_ids.items():
        conn.executemany("UPDATE bills SET assigned_to = NULL WHERE id = ?", [(i,) for i in ids])
        moved += sum(logic.assign_new_bills(conn, firm_id, kind, ids).values())
    return moved


@app.get("/api/firms")
def list_firms():
    conn = get_db()
    out = rows(conn.execute("SELECT * FROM firms ORDER BY id"))
    conn.close()
    return jsonify(out)


@app.post("/api/firms")
def add_firm():
    if (bad := admin_only()):
        return bad
    d = body()
    code, name = squeeze(d.get("code")), " ".join((d.get("name") or "").upper().split())
    if not code or not name:
        return {"error": "Short code and the firm name as Tally prints it are both needed."}, 400
    conn = get_db()
    try:
        conn.execute("INSERT INTO firms (code, name, aliases) VALUES (?, ?, ?)",
                     (code, name, d.get("aliases", "")))
    except Exception:
        conn.close()
        return {"error": f"Code {code} is already used."}, 400
    log(conn, request.user["id"], "firm_add", f"{code} {name}")
    conn.commit()
    conn.close()
    return {"ok": True}


@app.put("/api/firms/<int:fid>")
def edit_firm(fid):
    if (bad := admin_only()):
        return bad
    d = body()
    conn = get_db()
    conn.execute("UPDATE firms SET name = COALESCE(?, name), aliases = COALESCE(?, aliases), "
                 "active = COALESCE(?, active) WHERE id = ?",
                 (" ".join(d["name"].upper().split()) if d.get("name") else None,
                  d.get("aliases"), (1 if d["active"] else 0) if "active" in d else None, fid))
    log(conn, request.user["id"], "firm_edit", json.dumps(d))
    conn.commit()
    conn.close()
    return {"ok": True}


# ================================================================ uploads

@app.post("/api/upload")
def upload():
    files = request.files.getlist("file")
    if not files:
        return {"error": "Choose the Tally file first."}, 400
    firm_id = request.form.get("firm_id", type=int) or None
    kind = request.form.get("kind") or None
    if kind and kind not in KINDS:
        kind = None
    results = []
    for f in files:
        data = f.read()
        conn = get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            summary = logic.import_file(conn, data, f.filename or "upload.xls",
                                        request.user["id"], firm_id=firm_id, kind=kind)
            conn.commit()
            results.append({"file": f.filename, "ok": True, **summary})
        except (TallyFileError, logic.UploadRefused) as exc:
            conn.rollback()
            results.append({"file": f.filename, "ok": False, "error": str(exc)})
        finally:
            conn.close()
    return jsonify(results)


@app.get("/api/uploads")
def list_uploads():
    conn = get_db()
    out = rows(conn.execute(
        "SELECT u.*, f.code AS firm, us.name AS by_name FROM uploads u "
        "JOIN firms f ON f.id = u.firm_id JOIN users us ON us.id = u.user_id "
        "ORDER BY u.id DESC LIMIT 100"))
    conn.close()
    for r in out:
        r["summary"] = json.loads(r["summary"] or "{}")
    return jsonify(out)


# ================================================================ bills

def bills_query(conn, args, uid):
    where, params = [], []
    kind = args.get("kind")
    if kind in KINDS:
        where.append("b.kind = ?"); params.append(kind)
    if args.get("firm"):
        where.append("b.firm_id = ?"); params.append(int(args["firm"]))
    who = args.get("assigned", "")
    if who == "me":
        where.append("b.assigned_to = ?"); params.append(uid)
    elif who == "none":
        where.append("b.assigned_to IS NULL")
    elif who.isdigit():
        where.append("b.assigned_to = ?"); params.append(int(who))
    q = (args.get("q") or "").strip()
    if q:
        where.append("(b.party_key LIKE ? OR UPPER(b.ref_no) LIKE ?)")
        params += [f"%{squeeze(q)}%", f"%{q.upper()}%"]
    status = args.get("status", "active")
    if status in ("cleared", "unclaimed"):
        where.append("b.cleared_at != ''")
    elif status != "all":
        where.append("b.cleared_at = ''")
    sql = ("SELECT b.*, f.code AS firm, u.name AS assigned_name, "
           "(SELECT COUNT(*) FROM alerts a WHERE a.bill_id = b.id AND a.resolved_at = '') AS alerts "
           "FROM bills b JOIN firms f ON f.id = b.firm_id LEFT JOIN users u ON u.id = b.assigned_to")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY b.party, b.bill_date"
    out = rows(conn.execute(sql, params))
    state = logic.bill_state(conn, [b["id"] for b in out])
    for b in out:
        b.update(state[b["id"]])
    if status in ("open", "part", "done"):
        out = [b for b in out if b["status"] == status]
    elif status == "todo":
        out = [b for b in out if b["status"] in ("open", "part")]
    elif status == "unclaimed":
        out = [b for b in out if not b["done_by"]]
    elif status == "alerts":
        out = [b for b in out if b["alerts"]]
    return out


@app.get("/api/bills")
def list_bills():
    conn = get_db()
    out = bills_query(conn, request.args, request.user["id"])
    conn.close()
    limit = request.args.get("limit", type=int) or 2000
    return jsonify({"bills": out[:limit], "count": len(out),
                    "total": round(sum(b["remaining"] if b["status"] != "cleared" else b["pending"]
                                       for b in out), 2)})


@app.get("/api/bills/<int:bid>")
def read_bill(bid):
    conn = get_db()
    bill = conn.execute(
        "SELECT b.*, f.code AS firm, f.name AS firm_name, u.name AS assigned_name FROM bills b "
        "JOIN firms f ON f.id = b.firm_id LEFT JOIN users u ON u.id = b.assigned_to "
        "WHERE b.id = ?", (bid,)).fetchone()
    if not bill:
        conn.close()
        return {"error": "No such bill."}, 404
    out = dict(bill)
    out.update(logic.bill_state(conn, [bid])[bid])
    out["entries"] = rows(conn.execute(
        "SELECT e.*, u.name AS by_name, d.name AS deleted_by_name FROM entries e "
        "JOIN users u ON u.id = e.user_id LEFT JOIN users d ON d.id = e.deleted_by "
        "WHERE e.bill_id = ? ORDER BY e.id", (bid,)))
    out["notes"] = rows(conn.execute(
        "SELECT n.*, u.name AS by_name FROM notes n JOIN users u ON u.id = n.user_id "
        "WHERE n.bill_id = ? ORDER BY n.id DESC", (bid,)))
    out["alerts"] = rows(conn.execute(
        "SELECT a.*, r.name AS resolved_by_name FROM alerts a LEFT JOIN users r ON "
        "r.id = a.resolved_by WHERE a.bill_id = ? ORDER BY a.id DESC", (bid,)))
    out["history"] = rows(conn.execute(
        "SELECT a.*, u.name AS by_name FROM activity a LEFT JOIN users u ON u.id = a.user_id "
        "WHERE a.bill_id = ? ORDER BY a.id DESC LIMIT 50", (bid,)))
    out["same_party_open"] = conn.execute(
        "SELECT COUNT(*) FROM bills WHERE firm_id = ? AND kind = ? AND party_key = ? AND "
        "cleared_at = ''", (bill["firm_id"], bill["kind"], bill["party_key"])).fetchone()[0]
    conn.close()
    return jsonify(out)


@app.post("/api/bills/<int:bid>/notes")
def add_note(bid):
    d = body()
    text = (d.get("text") or "").strip()
    if not text:
        return {"error": "Write what happened."}, 400
    conn = get_db()
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bid,)).fetchone()
    if not bill:
        conn.close()
        return {"error": "No such bill."}, 404
    conn.execute("INSERT INTO notes (bill_id, user_id, text, promise_date, created_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (bid, request.user["id"], text[:1000], d.get("promise_date") or "", now()))
    log(conn, request.user["id"], "follow_up", f"{bill['party']}: {text[:120]}", bid)
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/bills/<int:bid>/reassign")
def reassign(bid):
    if (bad := admin_only()):
        return bad
    conn = get_db()
    try:
        n = logic.reassign_party(conn, bid, int(body().get("user_id") or 0), request.user["id"])
    except logic.UploadRefused as exc:
        conn.close()
        return {"error": str(exc)}, 400
    conn.commit()
    conn.close()
    return {"ok": True, "moved": n}


@app.post("/api/redistribute")
def redistribute():
    if (bad := admin_only()):
        return bad
    d = body()
    if d.get("kind") not in KINDS:
        return {"error": "Pick payable or receivable."}, 400
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        moved = logic.redistribute(conn, d["kind"], request.user["id"],
                                   int(d["firm_id"]) if d.get("firm_id") else None)
        conn.commit()
    except logic.UploadRefused as exc:
        conn.rollback()
        return {"error": str(exc)}, 400
    finally:
        conn.close()
    return {"ok": True, "moved": moved}


# ================================================================ marking paid / received

def _valid_day(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


@app.post("/api/entries")
def add_entries():
    d = body()
    lines_in = d.get("lines") or []
    paid_on = _valid_day(d.get("paid_on")) or today()
    if paid_on > today():
        return {"error": "The date cannot be in the future."}, 400
    mode = d.get("mode") if d.get("mode") in MODES else "Other"
    reference = (d.get("reference") or "").strip()[:80]
    remarks = (d.get("remarks") or "").strip()[:500]
    if not lines_in:
        return {"error": "Pick at least one bill."}, 400
    if mode not in ("Cash", "Adjustment") and not reference:
        return {"error": "Enter the UTR / cheque number, so a second payment of the same "
                         "bill can be caught."}, 400

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")      # one person at a time, so two cannot race
        lines = []
        kinds = set()
        for line in lines_in:
            bill = conn.execute("SELECT * FROM bills WHERE id = ?",
                                (int(line.get("bill_id") or 0),)).fetchone()
            if not bill:
                conn.rollback()
                return {"error": "One of those bills no longer exists."}, 404
            try:
                amount = round(float(line.get("amount")), 2)
            except (TypeError, ValueError):
                amount = 0
            lines.append((bill, amount))
            kinds.add(bill["kind"])
        if len(kinds) > 1:
            conn.rollback()
            return {"error": "Payables and receivables have to be marked separately."}, 400
        if len({b["party_key"] for b, _ in lines}) > 1:
            conn.rollback()
            return {"error": "Mark one party at a time."}, 400

        warnings = logic.check_entries(conn, request.user, lines, paid_on, reference)
        if any(w.get("block") for w in warnings):
            conn.rollback()
            return {"error": " ".join(w["message"] for w in warnings if w.get("block"))}, 400
        serious = [w for w in warnings if w.get("alert")]
        if warnings and not d.get("confirm"):
            conn.rollback()
            return {"needs_confirm": True, "warnings": warnings, "serious": bool(serious)}, 409
        ids = logic.save_entries(conn, request.user, lines, paid_on, mode, reference,
                                 remarks, warnings)
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "entries": ids, "flagged": bool(serious)}


@app.delete("/api/entries/<int:eid>")
def delete_entry(eid):
    reason = (body().get("reason") or "").strip()
    if not reason:
        return {"error": "Say why it is being removed."}, 400
    conn = get_db()
    e = conn.execute("SELECT e.*, b.party, b.ref_no FROM entries e JOIN bills b ON "
                     "b.id = e.bill_id WHERE e.id = ?", (eid,)).fetchone()
    if not e or e["deleted_at"]:
        conn.close()
        return {"error": "No such entry."}, 404
    if e["user_id"] != request.user["id"] and request.user["role"] != "admin":
        conn.close()
        return {"error": "Only the person who made it, or an admin, can remove it."}, 403
    if e["reconciled_at"] and request.user["role"] != "admin":
        conn.close()
        return {"error": "Tally already shows this one. Ask an admin."}, 403
    conn.execute("UPDATE entries SET deleted_at = ?, deleted_by = ?, delete_reason = ? "
                 "WHERE id = ?", (now(), request.user["id"], reason[:300], eid))
    log(conn, request.user["id"], "entry_removed",
        f"{e['party']} {e['ref_no']}: removed ₹{e['amount']:,.0f} entry - {reason[:120]}",
        e["bill_id"])
    conn.commit()
    conn.close()
    return {"ok": True}


# ================================================================ alerts

@app.get("/api/alerts")
def list_alerts():
    state = request.args.get("state", "open")
    conn = get_db()
    sql = ("SELECT a.*, b.party, b.ref_no, b.kind AS bill_kind, f.code AS firm, u.name AS assigned_name, "
           "r.name AS resolved_by_name, rb.name AS raised_by_name FROM alerts a "
           "LEFT JOIN bills b ON b.id = a.bill_id LEFT JOIN firms f ON f.id = b.firm_id "
           "LEFT JOIN users u ON u.id = b.assigned_to LEFT JOIN users r ON r.id = a.resolved_by "
           "LEFT JOIN users rb ON rb.id = a.raised_by ")
    sql += "WHERE a.resolved_at = '' " if state == "open" else "WHERE a.resolved_at != '' "
    sql += "ORDER BY CASE a.severity WHEN 'high' THEN 0 ELSE 1 END, a.id DESC LIMIT 500"
    out = rows(conn.execute(sql))
    conn.close()
    return jsonify(out)


@app.post("/api/alerts/<int:aid>/resolve")
def resolve_alert(aid):
    if (bad := admin_only()):
        return bad
    note = (body().get("note") or "").strip()
    if not note:
        return {"error": "Write what was found."}, 400
    conn = get_db()
    a = conn.execute("SELECT * FROM alerts WHERE id = ?", (aid,)).fetchone()
    if not a:
        conn.close()
        return {"error": "No such alert."}, 404
    conn.execute("UPDATE alerts SET resolved_at = ?, resolved_by = ?, resolve_note = ? "
                 "WHERE id = ?", (now(), request.user["id"], note[:500], aid))
    log(conn, request.user["id"], "alert_resolved", f"{a['message'][:100]} -> {note[:100]}",
        a["bill_id"])
    conn.commit()
    conn.close()
    return {"ok": True}


# ================================================================ scoreboard

def period(args):
    t = date.fromisoformat(today())
    name = args.get("period", "month")
    if name == "today":
        return t.isoformat(), t.isoformat()
    if name == "week":
        return (t - timedelta(days=t.weekday())).isoformat(), t.isoformat()
    if name == "month":
        return t.replace(day=1).isoformat(), t.isoformat()
    if name == "custom":
        return (_valid_day(args.get("from")) or "2000-01-01",
                _valid_day(args.get("to")) or t.isoformat())
    return "2000-01-01", "2999-12-31"


@app.get("/api/scoreboard")
def scoreboard():
    start, end = period(request.args)
    firm = request.args.get("firm", type=int)
    conn = get_db()
    people = {u["id"]: {"id": u["id"], "name": u["name"], "active": u["active"],
                        "takes_work": u["takes_work"],
                        **{k: {"count": 0, "bills": 0, "amount": 0.0, "flagged": 0,
                               "open_count": 0, "open_amount": 0.0, "overdue_60": 0,
                               "followups": 0, "unclaimed": 0} for k in KINDS}}
              for u in conn.execute("SELECT * FROM users")}
    fsql, fparams = ("AND b.firm_id = ?", [firm]) if firm else ("", [])

    for r in conn.execute(
            f"SELECT e.user_id, b.kind, COUNT(*) n, COUNT(DISTINCT e.bill_id) bills, "
            f"SUM(e.amount) amt, SUM(e.flagged) flagged FROM entries e JOIN bills b ON "
            f"b.id = e.bill_id WHERE e.deleted_at = '' AND e.paid_on BETWEEN ? AND ? {fsql} "
            f"GROUP BY e.user_id, b.kind", [start, end] + fparams):
        p = people[r["user_id"]][r["kind"]]
        p["count"], p["bills"], p["amount"], p["flagged"] = r["n"], r["bills"], r["amt"] or 0, r["flagged"] or 0

    for r in conn.execute(
            f"SELECT n.user_id, b.kind, COUNT(*) n FROM notes n JOIN bills b ON b.id = n.bill_id "
            f"WHERE substr(n.created_at, 1, 10) BETWEEN ? AND ? {fsql} GROUP BY n.user_id, b.kind",
            [start, end] + fparams):
        people[r["user_id"]][r["kind"]]["followups"] = r["n"]

    state = logic.bill_state(conn)
    for b in conn.execute(f"SELECT b.* FROM bills b WHERE b.assigned_to IS NOT NULL {fsql}",
                          fparams):
        st = state[b["id"]]
        p = people[b["assigned_to"]][b["kind"]]
        if st["status"] in ("open", "part"):
            p["open_count"] += 1
            p["open_amount"] += st["remaining"]
            if b["overdue_days"] >= 60:
                p["overdue_60"] += 1
        elif st["status"] == "cleared" and not st["done_by"] and \
                start <= b["cleared_at"][:10] <= end:
            p["unclaimed"] += 1
    conn.close()
    out = [p for p in people.values()
           if (p["active"] and p["takes_work"]) or any(p[k]["count"] or p[k]["open_count"] or p[k]["followups"] for k in KINDS)]
    for p in out:
        for k in KINDS:
            p[k]["amount"] = round(p[k]["amount"], 2)
            p[k]["open_amount"] = round(p[k]["open_amount"], 2)
    out.sort(key=lambda p: -(p["payable"]["amount"] + p["receivable"]["amount"]))
    return jsonify({"from": start, "to": end, "people": out})


@app.get("/api/activity")
def activity():
    conn = get_db()
    params = []
    sql = ("SELECT a.*, u.name AS by_name FROM activity a LEFT JOIN users u ON u.id = a.user_id ")
    if request.args.get("user", type=int):
        sql += "WHERE a.user_id = ? "
        params.append(request.args.get("user", type=int))
    sql += "ORDER BY a.id DESC LIMIT ?"
    params.append(min(request.args.get("limit", type=int) or 200, 1000))
    out = rows(conn.execute(sql, params))
    conn.close()
    return jsonify(out)


# ================================================================ exports

def csv_response(name, header, data):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(data)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export/entries.csv")
def export_entries():
    start, end = period(request.args)
    conn = get_db()
    data = [list(r) for r in conn.execute(
        "SELECT e.paid_on, f.code, b.kind, b.party, b.ref_no, b.bill_date, e.amount, e.mode, "
        "e.reference, u.name, e.remarks, e.created_at, CASE WHEN e.flagged THEN 'YES' ELSE '' END, "
        "CASE WHEN e.reconciled_at != '' THEN 'YES' ELSE '' END, e.deleted_at, e.delete_reason "
        "FROM entries e JOIN bills b ON b.id = e.bill_id JOIN firms f ON f.id = b.firm_id "
        "JOIN users u ON u.id = e.user_id WHERE e.paid_on BETWEEN ? AND ? ORDER BY e.paid_on, e.id",
        (start, end))]
    conn.close()
    return csv_response(f"entries_{start}_to_{end}.csv",
                        ["Paid/received on", "Firm", "Type", "Party", "Bill no", "Bill date",
                         "Amount", "Mode", "UTR / cheque", "Done by", "Remarks", "Entered at",
                         "Flagged", "Seen in Tally", "Removed at", "Removed because"], data)


@app.get("/api/export/bills.csv")
def export_bills():
    conn = get_db()
    out = bills_query(conn, request.args, request.user["id"])
    conn.close()
    return csv_response("bills.csv",
                        ["Firm", "Type", "Party", "Bill no", "Bill date", "Due on", "Overdue days",
                         "Pending in Tally", "Marked, waiting for Tally", "Still to do", "Status",
                         "Given to", "Done by"],
                        [[b["firm"], b["kind"], b["party"], b["ref_no"], b["bill_date"],
                          b["due_date"], b["overdue_days"], b["pending"], b["waiting"],
                          b["remaining"], b["status"], b["assigned_name"] or "",
                          ", ".join(b["done_by"])] for b in out])


# ================================================================ start

def bootstrap_admin():
    """ACCOUNTS_ADMIN_USER + ACCOUNTS_ADMIN_PASSWORD create the first admin on
    a hosted server, so the setup page is never left open to the internet."""
    user = os.environ.get("ACCOUNTS_ADMIN_USER")
    pw = os.environ.get("ACCOUNTS_ADMIN_PASSWORD")
    if user and pw and user_count() == 0:
        create_user(os.environ.get("ACCOUNTS_ADMIN_NAME", "Admin"), user, pw, "admin", 0)


def create_app():
    init_db()
    bootstrap_admin()
    return app


if __name__ == "__main__":
    create_app().run(host=os.environ.get("HOST", "0.0.0.0"),
                     port=int(os.environ.get("ACCOUNTS_PORT", os.environ.get("PORT", 5100))),
                     debug=False, threaded=True)
