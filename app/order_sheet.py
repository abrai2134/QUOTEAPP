"""Writes every saved quotation into the Google Sheet as an Order items row.

The row has exactly the 75 columns AppSheet wrote, in the same order, with the
same value shapes (GST as a fraction, dates as datetimes, an 8-character hex
id).  Two destinations, both optional and independent:

* **Google Sheet** - the app POSTs the row to a small Apps Script web app that
  lives in your own Google account and appends it to the sheet.  No service
  account, no credentials file: see google-apps-script/README.md.
* **Local mirror** - every row is also appended to instance/order_items.csv, so
  nothing is ever lost when the sheet is unreachable and the history can be
  re-imported later.

Only the first seven items reach the sheet, because the sheet has seven item
slots; the quotation .xlsx itself carries as many as you like.
"""

import csv
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from .db import INSTANCE_DIR, get_setting, now

MIRROR_PATH = os.path.join(INSTANCE_DIR, "order_items.csv")
ITEM_SLOTS = 7
SYNC_TIMEOUT = 30

# The trailing spaces in some of these names are part of the sheet's own
# headers - they must be reproduced exactly or the Apps Script cannot match
# the columns.
COLUMNS = [
    "ID", "HEADING ", "M/S", "M/S ADD", "BANK DETAILS", "Made By ", "STD FILE",
    "Date ", "PARTY", "PARTY ADD", "CITY", "CC TO CLIENT", "EMAILID",
    "WHATSAPP NO", "ORDER STATUS ", "PAYMENT STATUS", "DISPATCH STATUS",
]
for _n in range(1, ITEM_SLOTS + 1):
    COLUMNS += [f"MACHINE{_n}", f"MODEL{_n}", f"QTY{_n}", f"RATE{_n}",
                f"GST{_n}", f"SUB TOTAL{_n}"]
COLUMNS += [
    "GST AMT", "G TOTAL", "TOTAL QTY", "DISPATCH QTY", "PENDING QTY",
    "FOLLOWUP DATE 1", "REMARKS1", "FOLLOWUP DATE 2", "REMARKS 2",
    "FOLLOWUP DATE3", "REMARKS 3", "ADVANCE RECEIVE", "BALANCE PAYABLE",
    "DELIVERY PAYMENT NOTES", "REMINDER DATE", "REMIND AT",
]

HEADINGS = ["QUOTATION", "PROFORMA", "DELIVERY CHALLAN", "TAX INVOICE"]
STD_FILES = ["NON STD FILE", "FT STD FILE", "STD FILE"]


def new_sheet_id():
    """An 8-character hex id, the same shape AppSheet generated."""
    return uuid.uuid4().hex[:8]


def _parse(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _date(value):
    """Sheet dates go over the wire as ISO text; blanks stay blank."""
    if not value:
        return ""
    parsed = _parse(value)
    return parsed.isoformat() if parsed else str(value).strip()


def _midnight(value):
    """Follow-up and reminder columns carry the day, not the time of day."""
    parsed = _parse(value)
    if not parsed:
        return ""
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def build_row(quote):
    """Return the Order items row for `quote` as an ordered dict."""
    company = quote.get("company") or {}
    items = [i for i in (quote.get("items") or []) if i.get("description") or i.get("model")]

    row = {
        "ID": quote.get("sheet_id") or new_sheet_id(),
        "HEADING ": quote.get("heading") or "QUOTATION",
        "M/S": company.get("name", ""),
        "M/S ADD": "\n".join(x for x in [company.get("address", ""),
                                         company.get("address2", "")] if x),
        "BANK DETAILS": company.get("bank_details", ""),
        "Made By ": " ".join(x for x in [quote.get("salesperson"),
                                         quote.get("salesperson_phone")] if x),
        "STD FILE": quote.get("std_file") or "NON STD FILE",
        "Date ": _date(quote.get("quote_date")),
        "PARTY": quote.get("party_name", ""),
        "PARTY ADD": quote.get("party_address", ""),
        "CITY": quote.get("city", ""),
        "CC TO CLIENT": quote.get("cc_to_client") or "NO",
        "EMAILID": quote.get("party_email", ""),
        "WHATSAPP NO": quote.get("whatsapp_no", ""),
        "ORDER STATUS ": quote.get("order_status", ""),
        "PAYMENT STATUS": quote.get("payment_status") or "PENDING",
        "DISPATCH STATUS": quote.get("dispatch", ""),
    }

    total_qty = 0.0
    for slot in range(1, ITEM_SLOTS + 1):
        item = items[slot - 1] if slot <= len(items) else None
        if item:
            qty = float(item.get("qty") or 0)
            total_qty += qty
            row[f"MACHINE{slot}"] = item.get("description", "")
            row[f"MODEL{slot}"] = item.get("model", "")
            row[f"QTY{slot}"] = qty
            row[f"RATE{slot}"] = float(item.get("rate") or 0)
            # The sheet stores GST as a fraction (0.18), not a percentage.
            row[f"GST{slot}"] = float(item.get("gst_percent") or 0) / 100.0
            row[f"SUB TOTAL{slot}"] = float(item.get("amount") or 0)
        else:
            row[f"MACHINE{slot}"] = ""
            row[f"MODEL{slot}"] = ""
            row[f"QTY{slot}"] = ""
            row[f"RATE{slot}"] = ""
            row[f"GST{slot}"] = ""
            row[f"SUB TOTAL{slot}"] = 0

    dispatch_qty = float(quote.get("dispatch_qty") or 0)
    row.update({
        "GST AMT": float(quote.get("gst_amount") or 0),
        "G TOTAL": float(quote.get("grand_total") or 0),
        "TOTAL QTY": total_qty,
        "DISPATCH QTY": dispatch_qty or "",
        "PENDING QTY": total_qty - dispatch_qty,
        "FOLLOWUP DATE 1": _midnight(quote.get("followup1")),
        "REMARKS1": quote.get("remarks1", ""),
        "FOLLOWUP DATE 2": _midnight(quote.get("followup2")),
        "REMARKS 2": quote.get("remarks2", ""),
        "FOLLOWUP DATE3": _midnight(quote.get("followup3")),
        "REMARKS 3": quote.get("remarks3", ""),
        # AppSheet left the cell empty rather than writing a zero.
        "ADVANCE RECEIVE": float(quote.get("advance") or 0) or "",
        "BALANCE PAYABLE": float(quote.get("balance") or 0),
        "DELIVERY PAYMENT NOTES": quote.get("terms", ""),
        "REMINDER DATE": _midnight(quote.get("reminder_date")),
        "REMIND AT": _midnight(quote.get("quote_date")),
    })
    return row


def append_mirror(row):
    """Append the row to instance/order_items.csv, writing headers once."""
    os.makedirs(os.path.dirname(MIRROR_PATH), exist_ok=True)
    fresh = not os.path.exists(MIRROR_PATH)
    with open(MIRROR_PATH, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        if fresh:
            writer.writeheader()
        writer.writerow(row)
    return MIRROR_PATH


def sheet_url():
    return (get_setting("sheet_webapp_url", "") or "").strip()


def is_configured():
    return bool(sheet_url())


def push_to_sheet(row):
    """POST one row to the Apps Script web app.

    Returns the parsed response.  Raises RuntimeError with a message meant for
    the user when the sheet cannot be reached or refuses the row.
    """
    url = sheet_url()
    if not url:
        raise RuntimeError("No Google Sheet is connected yet. Add the web app "
                           "URL under Setup.")

    payload = json.dumps({
        "secret": get_setting("sheet_secret", "") or "",
        "columns": COLUMNS,
        "row": row,
    }).encode("utf-8")

    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"The sheet refused the row (HTTP {exc.code}). "
                           "Check that the web app is deployed with access set "
                           "to 'Anyone'.") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the sheet: {exc.reason}") from exc

    try:
        result = json.loads(body)
    except ValueError:
        # A Google sign-in page instead of JSON means the deployment is private.
        raise RuntimeError("The sheet replied with a sign-in page. Re-deploy "
                           "the Apps Script with 'Who has access: Anyone'.")
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "The sheet rejected the row.")
    return result


def sync_quote(quote):
    """Mirror locally, then push to the sheet when one is connected.

    Returns (synced, message).  A failed push is never fatal: the row is always
    in the local mirror and the quote can be re-synced from Setup.
    """
    row = build_row(quote)
    append_mirror(row)
    if not is_configured():
        return False, "Saved locally. Connect a Google Sheet under Setup to sync."
    try:
        push_to_sheet(row)
    except RuntimeError as exc:
        return False, str(exc)
    return True, f"Added to the Order items sheet at {now()}."


def fetch_rows(limit=500):
    """Read the most recent Order items rows back out of the sheet.

    Used to repopulate the quotations list on a server that started with an
    empty disk, and to pick up rows a colleague raised elsewhere.
    """
    url = sheet_url()
    if not url:
        raise RuntimeError("No Google Sheet is connected yet.")

    secret = get_setting("sheet_secret", "") or ""
    query = f"{url}?action=rows&limit={int(limit)}"
    if secret:
        query += f"&secret={urllib.parse.quote(secret)}"

    try:
        with urllib.request.urlopen(query, timeout=SYNC_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"The sheet refused the request (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the sheet: {exc.reason}") from exc

    try:
        result = json.loads(body)
    except ValueError:
        raise RuntimeError("The sheet replied with a sign-in page. Re-deploy the "
                           "Apps Script with 'Who has access: Anyone'.")
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "The sheet refused the request.")
    rows = result.get("rows") or []
    if rows and "rows" not in result:
        raise RuntimeError("This Apps Script is an older version - paste the "
                           "current Code.gs in and re-deploy it.")
    return rows


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def row_to_quote(row):
    """Turn one sheet row back into the quote/items shape the app stores."""
    items = []
    for slot in range(1, ITEM_SLOTS + 1):
        description = str(row.get(f"MACHINE{slot}") or "").strip()
        model = str(row.get(f"MODEL{slot}") or "").strip()
        if not description and not model:
            continue
        qty = _num(row.get(f"QTY{slot}"))
        rate = _num(row.get(f"RATE{slot}"))
        gst = _num(row.get(f"GST{slot}"))
        items.append({
            "position": len(items) + 1,
            "model": model,
            "description": description,
            # Stored as a fraction in the sheet, as a percentage in the app.
            "gst_percent": gst * 100 if gst <= 1 else gst,
            "qty": qty,
            "rate": rate,
            "amount": _num(row.get(f"SUB TOTAL{slot}")) or round(qty * rate, 2),
        })

    made_by = str(row.get("Made By ") or "").strip()
    name, _, phone = made_by.partition(" ")

    return {
        "sheet_id": str(row.get("ID") or "").strip(),
        "heading": str(row.get("HEADING ") or "QUOTATION").strip(),
        "std_file": str(row.get("STD FILE") or "").strip(),
        "quote_date": _sheet_datetime(row.get("Date ")),
        "company_name": str(row.get("M/S") or "").strip(),
        "party_name": str(row.get("PARTY") or "").strip(),
        "party_address": str(row.get("PARTY ADD") or "").strip(),
        "city": str(row.get("CITY") or "").strip(),
        "party_email": str(row.get("EMAILID") or "").strip(),
        "whatsapp_no": str(row.get("WHATSAPP NO") or "").strip(),
        "cc_to_client": str(row.get("CC TO CLIENT") or "NO").strip(),
        "salesperson": name,
        "salesperson_phone": phone.strip(),
        "order_status": str(row.get("ORDER STATUS ") or "").strip(),
        "payment_status": str(row.get("PAYMENT STATUS") or "").strip(),
        "dispatch": str(row.get("DISPATCH STATUS") or "").strip(),
        "dispatch_qty": _num(row.get("DISPATCH QTY")),
        "advance": _num(row.get("ADVANCE RECEIVE")),
        "gst_amount": _num(row.get("GST AMT")),
        "grand_total": _num(row.get("G TOTAL")),
        "balance": _num(row.get("BALANCE PAYABLE")),
        "terms": str(row.get("DELIVERY PAYMENT NOTES") or "").strip(),
        "reminder_date": _sheet_datetime(row.get("REMINDER DATE")),
        "followup1": _sheet_datetime(row.get("FOLLOWUP DATE 1")),
        "remarks1": str(row.get("REMARKS1") or "").strip(),
        "items": items,
    }


def _sheet_datetime(value):
    """Sheet dates come back as ISO text; store them the way the app does."""
    if not value:
        return ""
    parsed = _parse(str(value)[:19].replace("Z", ""))
    if parsed:
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()
