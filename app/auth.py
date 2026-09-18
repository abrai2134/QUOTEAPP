"""A shared PIN gate, so the app can be put on a link the team can reach.

Set QUOTEAPP_PIN to switch it on.  With no PIN set, the app is wide open,
which is what you want while it only runs on your own machine.

The PIN is checked against a hash in constant time, the session cookie is
signed with a secret that persists in instance/secret_key, and repeated wrong
guesses from one address are slowed down.
"""

import hashlib
import hmac
import os
import secrets
import time

from flask import redirect, request, session

from .db import INSTANCE_DIR

SECRET_PATH = os.path.join(INSTANCE_DIR, "secret_key")

# Paths reachable without signing in.
OPEN_PATHS = {"/login", "/health"}

# address -> (failed attempts, when the lockout ends)
_attempts = {}
MAX_ATTEMPTS = 6
LOCKOUT_SECONDS = 300


def get_pin():
    return (os.environ.get("QUOTEAPP_PIN") or "").strip()


def is_enabled():
    return bool(get_pin())


def secret_key():
    """A stable signing key, so sessions survive a restart."""
    env = os.environ.get("QUOTEAPP_SECRET_KEY")
    if env:
        return env
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, encoding="utf-8") as fh:
            saved = fh.read().strip()
        if saved:
            return saved
    fresh = secrets.token_hex(32)
    with open(SECRET_PATH, "w", encoding="utf-8") as fh:
        fh.write(fresh)
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return fresh


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def caller():
    """The client address, honouring one proxy hop when hosted behind one."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def locked_out():
    entry = _attempts.get(caller())
    if not entry:
        return 0
    count, until = entry
    if count >= MAX_ATTEMPTS and until > time.time():
        return int(until - time.time())
    return 0


def note_failure():
    who = caller()
    count, _ = _attempts.get(who, (0, 0))
    count += 1
    _attempts[who] = (count, time.time() + LOCKOUT_SECONDS)


def note_success():
    _attempts.pop(caller(), None)


def check_pin(candidate):
    return hmac.compare_digest(_digest((candidate or "").strip()), _digest(get_pin()))


def signed_in():
    return session.get("pin_hash") == _digest(get_pin())


def sign_in():
    session["pin_hash"] = _digest(get_pin())
    session.permanent = True


def require_pin():
    """before_request hook: send anyone without a session to the login page."""
    if not is_enabled() or signed_in():
        return None
    if request.path in OPEN_PATHS or request.path.startswith("/static/"):
        return None
    if request.path.startswith("/api/"):
        return {"error": "Please sign in again."}, 401
    return redirect("/login")


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Well Worth Quotation App</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; background: #eef1f6; padding: 20px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    color: #17202e;
  }
  form {
    background: #fff; border: 1px solid #d6dce6; border-radius: 14px;
    padding: 26px 22px; width: 100%; max-width: 360px;
    box-shadow: 0 6px 24px rgba(15,45,82,.08);
  }
  h1 { margin: 0 0 4px; font-size: 19px; color: #0f2d52; }
  p.sub { margin: 0 0 20px; font-size: 13px; color: #6b7687; }
  label { display: block; font-size: 12px; font-weight: 600; color: #6b7687;
          text-transform: uppercase; letter-spacing: .04em; }
  input {
    width: 100%; margin-top: 6px; padding: 12px; font-size: 20px;
    letter-spacing: .3em; text-align: center; border: 1px solid #d6dce6;
    border-radius: 9px; font-family: inherit;
  }
  input:focus { outline: 2px solid #0f2d52; outline-offset: -1px; }
  button {
    width: 100%; margin-top: 16px; padding: 13px; font-size: 15px;
    font-weight: 700; color: #fff; background: #0f2d52; border: 0;
    border-radius: 9px; cursor: pointer; font-family: inherit;
  }
  .err { margin-top: 14px; padding: 10px 12px; border-radius: 8px;
         background: #fde8e6; color: #b42318; font-size: 13px; }
</style></head>
<body>
  <form method="post" action="/login">
    <h1>Well Worth Quotations</h1>
    <p class="sub">Enter the team PIN to continue.</p>
    <label for="pin">PIN</label>
    <input id="pin" name="pin" type="password" inputmode="numeric"
           autocomplete="current-password" autofocus>
    <button type="submit">Sign in</button>
    __ERROR__
  </form>
</body></html>
"""


def login_page(error=""):
    block = f'<div class="err">{error}</div>' if error else ""
    return LOGIN_PAGE.replace("__ERROR__", block)
