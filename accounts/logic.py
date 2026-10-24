"""The rules: bringing a Tally file in, sharing bills out, and the checks
that catch a bill being paid twice or entered twice."""

import hashlib
import re
import json
import uuid
from collections import defaultdict
from datetime import datetime

from .db import KINDS, log, now, squeeze, today
from .tally import bill_key, parse_report

TOLERANCE = 1.0          # rupees; rounding in Tally never moves more than this
WORD = {"payable": "paid", "receivable": "received"}
NOUN = {"payable": "payment", "receivable": "receipt"}


class UploadRefused(ValueError):
    pass


def money(value):
    return f"₹{value:,.0f}"


# ---------------------------------------------------------------- firms

def match_firm(conn, firm_text, file_name=""):
    """Line 1 of the Tally report names the firm.  The firm code in the file
    name (WWI_PAYABLE_...) is the fallback."""
    firms = conn.execute("SELECT * FROM firms WHERE active = 1").fetchall()
    text = squeeze(firm_text)
    best = None
    for firm in firms:
        names = [firm["name"]] + [a for a in firm["aliases"].splitlines() if a.strip()]
        for name in names:
            key = squeeze(name)
            if key and key in text and (best is None or len(key) > best[1]):
                best = (firm, len(key))
    if best:
        return best[0]
    parts = {squeeze(p) for p in re.split(r"[^0-9A-Za-z]+", file_name or "") if p}
    for firm in firms:
        if squeeze(firm["code"]) in parts:
            return firm
    return None


# ---------------------------------------------------------------- bill status

def bill_state(conn, bill_ids=None):
    """bill id -> dict(done, waiting, remaining, status, done_by).

    'waiting' is what has been marked here but not yet seen to come off in a
    later Tally file.  Until Tally catches up, that amount still counts, so
    nobody else is told the bill is open and pays it again."""
    params = []
    where = "e.deleted_at = ''"
    if bill_ids is not None:
        if not bill_ids:
            return {}
        where += f" AND e.bill_id IN ({','.join('?' * len(bill_ids))})"
        params = list(bill_ids)
    sums = defaultdict(lambda: {"done": 0.0, "waiting": 0.0, "by": []})
    for r in conn.execute(
            f"SELECT e.bill_id, e.amount, e.reconciled_at, u.name FROM entries e "
            f"JOIN users u ON u.id = e.user_id WHERE {where} ORDER BY e.id", params):
        s = sums[r["bill_id"]]
        s["done"] += r["amount"]
        if not r["reconciled_at"]:
            s["waiting"] += r["amount"]
        if r["name"] not in s["by"]:
            s["by"].append(r["name"])

    q = "SELECT id, pending, cleared_at FROM bills"
    if bill_ids is not None:
        q += f" WHERE id IN ({','.join('?' * len(bill_ids))})"
    out = {}
    for b in conn.execute(q, params):
        s = sums.get(b["id"], {"done": 0.0, "waiting": 0.0, "by": []})
        remaining = 0.0 if b["cleared_at"] else round(b["pending"] - s["waiting"], 2)
        if b["cleared_at"]:
            status = "cleared"
        elif s["waiting"] > 0 and remaining <= TOLERANCE:
            status = "done"
        elif s["waiting"] > 0:
            status = "part"
        else:
            status = "open"
        out[b["id"]] = {"done": round(s["done"], 2), "waiting": round(s["waiting"], 2),
                        "remaining": remaining, "status": status, "done_by": s["by"]}
    return out


# ---------------------------------------------------------------- sharing out

def workers(conn):
    return [dict(r) for r in conn.execute(
        "SELECT id, name FROM users WHERE active = 1 AND takes_work = 1 ORDER BY id")]


def _assign_groups(groups, people, base_load):
    """Hand party groups to people so each ends up with about the same number
    of bills AND about the same rupee value.

    groups: [(group_key, bill_count, amount)]; base_load: user -> [count, amount]
    Biggest groups first, each to whoever is lightest right now."""
    if not people:
        return {}
    load = {p: list(base_load.get(p, [0, 0.0])) for p in people}
    total_count = sum(g[1] for g in groups) + sum(v[0] for v in load.values()) or 1
    total_amount = sum(abs(g[2]) for g in groups) + sum(v[1] for v in load.values()) or 1

    def weight(count, amount):
        return count / total_count + abs(amount) / total_amount

    result = {}
    for key, count, amount in sorted(groups, key=lambda g: -weight(g[1], g[2])):
        who = min(people, key=lambda p: (weight(*load[p]), load[p][0], p))
        result[key] = who
        load[who][0] += count
        load[who][1] += abs(amount)
    return result


def _open_load(conn, kind, people):
    """What each person already has open of this kind, across all firms."""
    load = {p: [0, 0.0] for p in people}
    state = bill_state(conn)
    for b in conn.execute("SELECT id, assigned_to FROM bills WHERE kind = ? "
                          "AND cleared_at = '' AND assigned_to IS NOT NULL", (kind,)):
        st = state.get(b["id"])
        if b["assigned_to"] in load and st and st["status"] in ("open", "part"):
            load[b["assigned_to"]][0] += 1
            load[b["assigned_to"]][1] += st["remaining"]
    return load


def assign_new_bills(conn, firm_id, kind, bill_ids):
    """Bills of a party someone already owns go to that person; new parties
    are spread so the load stays even."""
    people = [p["id"] for p in workers(conn)]
    if not bill_ids or not people:
        return {}
    marks = ",".join("?" * len(bill_ids))
    rows = conn.execute(f"SELECT id, party_key, pending FROM bills WHERE id IN ({marks})",
                        list(bill_ids)).fetchall()
    owners = {r["party_key"]: r["user_id"] for r in conn.execute(
        "SELECT party_key, user_id FROM party_owners WHERE firm_id = ? AND kind = ?",
        (firm_id, kind)) if r["user_id"] in people}

    groups = defaultdict(lambda: [0, 0.0, []])
    for r in rows:
        g = groups[r["party_key"]]
        g[0] += 1
        g[1] += r["pending"]
        g[2].append(r["id"])

    fresh = [(k, g[0], g[1]) for k, g in groups.items() if k not in owners]
    chosen = dict(owners)
    chosen.update(_assign_groups(fresh, people, _open_load(conn, kind, people)))

    given = defaultdict(int)
    for key, g in groups.items():
        who = chosen[key]
        conn.execute("INSERT INTO party_owners (firm_id, kind, party_key, user_id) "
                     "VALUES (?, ?, ?, ?) ON CONFLICT(firm_id, kind, party_key) "
                     "DO UPDATE SET user_id = excluded.user_id", (firm_id, kind, key, who))
        conn.executemany("UPDATE bills SET assigned_to = ? WHERE id = ?",
                         [(who, bid) for bid in g[2]])
        given[who] += len(g[2])
    return dict(given)


def redistribute(conn, kind, user_id, firm_id=None):
    """Share every open bill of this kind out again from scratch.

    A party where somebody has already marked a payment stays with that
    person, so nobody loses work they started."""
    people = [p["id"] for p in workers(conn)]
    if not people:
        raise UploadRefused("Nobody is set to take work. Turn on 'Gets bills' for "
                            "at least one person under Team.")
    state = bill_state(conn)
    q = "SELECT id, firm_id, party_key, assigned_to FROM bills WHERE kind = ? AND cleared_at = ''"
    params = [kind]
    if firm_id:
        q += " AND firm_id = ?"
        params.append(firm_id)
    groups = defaultdict(lambda: {"ids": [], "count": 0, "amount": 0.0, "keep": None})
    for b in conn.execute(q, params):
        st = state[b["id"]]
        g = groups[(b["firm_id"], b["party_key"])]
        g["ids"].append(b["id"])
        if st["status"] in ("open", "part"):
            g["count"] += 1
            g["amount"] += st["remaining"]
        if st["waiting"] > 0 and b["assigned_to"] in people:
            g["keep"] = b["assigned_to"]

    base = {p: [0, 0.0] for p in people}
    if firm_id:
        # other firms' work still counts towards how busy someone is
        for b in conn.execute("SELECT id, assigned_to FROM bills WHERE kind = ? AND "
                              "cleared_at = '' AND firm_id != ?", (kind, firm_id)):
            st = state[b["id"]]
            if b["assigned_to"] in base and st["status"] in ("open", "part"):
                base[b["assigned_to"]][0] += 1
                base[b["assigned_to"]][1] += st["remaining"]
    free = []
    for key, g in groups.items():
        if g["keep"]:
            base[g["keep"]][0] += g["count"]
            base[g["keep"]][1] += g["amount"]
        else:
            free.append((key, g["count"], g["amount"]))
    chosen = _assign_groups(free, people, base)

    moved = 0
    for key, g in groups.items():
        who = g["keep"] or chosen[key]
        fid, pkey = key
        conn.execute("INSERT INTO party_owners (firm_id, kind, party_key, user_id) "
                     "VALUES (?, ?, ?, ?) ON CONFLICT(firm_id, kind, party_key) "
                     "DO UPDATE SET user_id = excluded.user_id", (fid, kind, pkey, who))
        for bid in g["ids"]:
            cur = conn.execute("UPDATE bills SET assigned_to = ? WHERE id = ? AND "
                               "(assigned_to IS NULL OR assigned_to != ?)", (who, bid, who))
            moved += cur.rowcount
    log(conn, user_id, "redistribute",
        f"Shared out open {kind}s again{' for one firm' if firm_id else ''}; {moved} bill(s) moved")
    return moved


def reassign_party(conn, bill_id, to_user, user_id):
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    target = conn.execute("SELECT * FROM users WHERE id = ? AND active = 1", (to_user,)).fetchone()
    if not bill or not target:
        raise UploadRefused("No such bill or person.")
    conn.execute("INSERT INTO party_owners (firm_id, kind, party_key, user_id) VALUES (?,?,?,?) "
                 "ON CONFLICT(firm_id, kind, party_key) DO UPDATE SET user_id = excluded.user_id",
                 (bill["firm_id"], bill["kind"], bill["party_key"], to_user))
    cur = conn.execute("UPDATE bills SET assigned_to = ? WHERE firm_id = ? AND kind = ? "
                       "AND party_key = ? AND cleared_at = ''",
                       (to_user, bill["firm_id"], bill["kind"], bill["party_key"]))
    log(conn, user_id, "reassign",
        f"{bill['party']} ({bill['kind']}) given to {target['name']}; {cur.rowcount} bill(s)",
        bill_id)
    return cur.rowcount


# ---------------------------------------------------------------- alerts

def raise_alert(conn, kind, message, bill_id=None, entry_id=None, upload_id=None,
                severity="high", raised_by=None, once=True):
    if once and bill_id is not None:
        if conn.execute("SELECT 1 FROM alerts WHERE kind = ? AND bill_id = ? AND "
                        "IFNULL(entry_id, 0) = IFNULL(?, 0)",
                        (kind, bill_id, entry_id)).fetchone():
            return None
    cur = conn.execute(
        "INSERT INTO alerts (kind, severity, bill_id, entry_id, upload_id, message, "
        "raised_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, severity, bill_id, entry_id, upload_id, message, raised_by, now()))
    return cur.lastrowid


# ---------------------------------------------------------------- uploading

def import_file(conn, data, file_name, user_id, firm_id=None, kind=None, report_date=None):
    report = parse_report(data, file_name)
    kind = kind or report["kind"]
    if kind not in KINDS:
        raise UploadRefused("Could not tell whether this is Bills Payable or Bills "
                            "Receivable. Pick it from the list and upload again.")
    if firm_id:
        firm = conn.execute("SELECT * FROM firms WHERE id = ?", (firm_id,)).fetchone()
    else:
        firm = match_firm(conn, report["firm_text"], file_name)
    if not firm:
        raise UploadRefused(f"Could not tell which firm '{report['firm_text']}' is. "
                            "Pick the firm from the list and upload again.")
    if report["kind"] and kind != report["kind"]:
        raise UploadRefused(f"This file says it is Bills {report['kind'].title()}, "
                            f"but {kind} was picked. Check the file.")

    file_hash = hashlib.sha256(data).hexdigest()
    again = conn.execute(
        "SELECT u.created_at, us.name FROM uploads u JOIN users us ON us.id = u.user_id "
        "WHERE u.file_hash = ?", (file_hash,)).fetchone()
    if again:
        raise UploadRefused(f"This exact file was already uploaded by {again['name']} "
                            f"on {again['created_at'][:16]}. Nothing was changed.")

    report_date = report_date or report["report_date"] or today()
    latest = conn.execute("SELECT MAX(report_date) AS d FROM uploads WHERE firm_id = ? AND kind = ?",
                          (firm["id"], kind)).fetchone()["d"]
    if latest and report_date < latest:
        raise UploadRefused(
            f"A newer {firm['code']} {kind} file (dated {latest}) is already in. Uploading "
            f"an older one would bring back bills that are already settled.")

    stamp = now()
    cur = conn.execute(
        "INSERT INTO uploads (firm_id, kind, file_name, file_hash, report_date, user_id, "
        "created_at, bills_in_file, total_in_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (firm["id"], kind, file_name, file_hash, report_date, user_id, stamp,
         len(report["bills"]), report["total"]))
    upload_id = cur.lastrowid

    existing = {r["bill_key"]: r for r in conn.execute(
        "SELECT * FROM bills WHERE firm_id = ? AND kind = ?", (firm["id"], kind))}
    seen_keys, new_ids, updated, alerts = set(), [], 0, 0
    key_count = defaultdict(int)

    for bill in report["bills"]:
        base = bill_key(bill)
        key_count[base] += 1
        key = base if key_count[base] == 1 else f"{base}#{key_count[base]}"
        seen_keys.add(key)
        party_key = squeeze(bill["party"])
        old = existing.get(key)
        if old is None:
            cur = conn.execute(
                "INSERT INTO bills (firm_id, kind, bill_key, party, party_key, ref_no, "
                "bill_date, due_date, overdue_days, original_amount, pending, "
                "first_upload_id, last_upload_id, last_seen_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (firm["id"], kind, key, bill["party"], party_key, bill["ref_no"],
                 bill["bill_date"], bill["due_date"], bill["overdue_days"],
                 bill["pending"], bill["pending"], upload_id, upload_id, stamp, stamp))
            bid = cur.lastrowid
            new_ids.append(bid)
            if key_count[base] > 1:
                alerts += bool(raise_alert(
                    conn, "double_entry_tally",
                    f"{bill['party']}: bill {bill['ref_no'] or '(no ref)'} dated "
                    f"{bill['bill_date']} for {money(bill['pending'])} is in the Tally "
                    f"file more than once. It may have been entered twice in Tally.",
                    bill_id=bid, upload_id=upload_id))
            continue

        updated += 1
        reopened = bool(old["cleared_at"])
        _reconcile(conn, old, bill["pending"], stamp, upload_id)
        conn.execute(
            "UPDATE bills SET pending = ?, due_date = ?, overdue_days = ?, party = ?, "
            "last_upload_id = ?, last_seen_at = ?, cleared_at = '' WHERE id = ?",
            (bill["pending"], bill["due_date"], bill["overdue_days"], bill["party"],
             upload_id, stamp, old["id"]))
        if reopened:
            alerts += bool(raise_alert(
                conn, "reappeared", f"{bill['party']}: bill {bill['ref_no']} had gone out "
                f"of Tally and is pending again ({money(bill['pending'])}).",
                bill_id=old["id"], upload_id=upload_id, severity="check", once=False))
        if old["assigned_to"] is None:
            new_ids.append(old["id"])

    cleared = 0
    for key, old in existing.items():
        if key in seen_keys or old["cleared_at"]:
            continue
        cleared += 1
        conn.execute("UPDATE bills SET cleared_at = ? WHERE id = ?", (stamp, old["id"]))
        conn.execute("UPDATE entries SET reconciled_at = ? WHERE bill_id = ? AND "
                     "reconciled_at = '' AND deleted_at = ''", (stamp, old["id"]))

    alerts += _check_file_doubles(conn, firm["id"], kind, upload_id)
    alerts += _check_overpaid_in_tally(conn, firm["id"], kind, upload_id)

    given = assign_new_bills(conn, firm["id"], kind, new_ids)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}
    summary = {
        "firm": firm["code"], "firm_name": firm["name"], "kind": kind,
        "report_date": report_date, "bills": len(report["bills"]),
        "total": report["total"], "tally_total": report["total_row"],
        "new": len(new_ids), "updated": updated, "cleared": cleared, "alerts": alerts,
        "given": {names.get(k, "?"): v for k, v in given.items()},
        "unassigned": len(new_ids) - sum(given.values()),
    }
    conn.execute("UPDATE uploads SET new_bills = ?, updated_bills = ?, cleared_bills = ?, "
                 "summary = ? WHERE id = ?",
                 (len(new_ids), updated, cleared, json.dumps(summary), upload_id))
    log(conn, user_id, "upload",
        f"{firm['code']} {kind} {file_name}: {len(report['bills'])} bills, "
        f"{len(new_ids)} new, {cleared} cleared")
    summary["upload_id"] = upload_id
    return summary


def _reconcile(conn, bill, new_pending, stamp, upload_id):
    """Tally's pending amount came down: tick off the entries it covers,
    oldest first.  An entry that is still not covered a day after it was
    made gets flagged - either it was never entered in Tally, or the payment
    did not go through."""
    drop = round(bill["pending"] - new_pending, 2)
    waiting = conn.execute(
        "SELECT e.*, u.name FROM entries e JOIN users u ON u.id = e.user_id "
        "WHERE e.bill_id = ? AND e.reconciled_at = '' AND e.deleted_at = '' ORDER BY e.id",
        (bill["id"],)).fetchall()
    covered = 0.0
    for e in waiting:
        if drop > 0 and covered + e["amount"] <= drop + TOLERANCE:
            covered += e["amount"]
            conn.execute("UPDATE entries SET reconciled_at = ? WHERE id = ?", (stamp, e["id"]))
            continue
        made = datetime.strptime(e["created_at"], "%Y-%m-%d %H:%M:%S")
        if not e["nagged_at"] and (datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S") - made).days >= 1:
            conn.execute("UPDATE entries SET nagged_at = ? WHERE id = ?", (stamp, e["id"]))
            raise_alert(
                conn, "not_in_tally",
                f"{bill['party']}: {e['name']} marked {money(e['amount'])} {WORD[bill['kind']]} "
                f"on {e['paid_on']} (ref {e['reference'] or '-'}), but the latest Tally file "
                f"still shows this bill pending. Enter it in Tally, or check whether the "
                f"payment really went through.",
                bill_id=bill["id"], entry_id=e["id"], upload_id=upload_id, severity="check")


def _check_file_doubles(conn, firm_id, kind, upload_id):
    """Same party, same amount, same date under two bill numbers - or the
    same bill number twice for one party - looks like a double entry."""
    raised = 0
    rows = conn.execute("SELECT * FROM bills WHERE firm_id = ? AND kind = ? AND cleared_at = ''",
                        (firm_id, kind)).fetchall()
    by_amount = defaultdict(list)
    by_ref = defaultdict(list)
    for b in rows:
        by_amount[(b["party_key"], round(b["original_amount"]), b["bill_date"])].append(b)
        ref = squeeze(b["ref_no"])
        if ref:
            by_ref[(b["party_key"], ref)].append(b)
    for (_, amount, day), group in by_amount.items():
        if len(group) < 2:
            continue
        refs = ", ".join(b["ref_no"] or "(no ref)" for b in group)
        b = group[0]            # one alert per pair, on the first bill
        raised += bool(raise_alert(
            conn, "same_amount_same_day",
            f"{b['party']}: {len(group)} bills of {money(amount)} on {day} ({refs}). "
            f"Check this is not one bill entered twice.",
            bill_id=b["id"], upload_id=upload_id, severity="check"))
    for (_, ref), group in by_ref.items():
        dates = {b["bill_date"] for b in group}
        if len(group) < 2 or len(dates) < 2:
            continue
        b = group[0]
        raised += bool(raise_alert(
            conn, "same_ref_twice",
            f"{b['party']}: bill number {b['ref_no']} appears on {len(group)} different "
            f"dates ({', '.join(sorted(dates))}). It may have been entered twice.",
            bill_id=b["id"], upload_id=upload_id))
    return raised


def _check_overpaid_in_tally(conn, firm_id, kind, upload_id):
    """A negative pending in Tally means more was paid / received than the
    bill was for."""
    raised = 0
    for b in conn.execute("SELECT * FROM bills WHERE firm_id = ? AND kind = ? AND "
                          "cleared_at = '' AND pending < 0", (firm_id, kind)):
        raised += bool(raise_alert(
            conn, "negative_in_tally",
            f"{b['party']}: Tally shows {money(b['pending'])} on {b['ref_no'] or 'this bill'} - "
            f"more {WORD[kind]} than the bill. Possible double payment, or an advance "
            f"not yet set against a bill.", bill_id=b["id"], upload_id=upload_id))
    return raised


# ---------------------------------------------------------------- marking

def check_entries(conn, user, lines, paid_on, reference):
    """Look for anything that smells like a double payment before saving.

    lines: [(bill_row, amount)].  -> list of warnings, each
    {bill_id, kind, message, alert(bool)}."""
    warnings = []
    ids = [b["id"] for b, _ in lines]
    state = bill_state(conn, ids)
    ref_key = squeeze(reference)
    parties = {b["party_key"] for b, _ in lines}

    for bill, amount in lines:
        st = state[bill["id"]]
        word = WORD[bill["kind"]]
        others = conn.execute(
            "SELECT e.*, u.name FROM entries e JOIN users u ON u.id = e.user_id WHERE "
            "e.bill_id = ? AND e.deleted_at = '' ORDER BY e.id", (bill["id"],)).fetchall()
        if amount <= 0:
            warnings.append({"bill_id": bill["id"], "kind": "bad_amount", "alert": False,
                             "block": True, "message": f"{bill['party']}: amount must be more than 0."})
            continue
        if st["status"] == "cleared":
            warnings.append({"bill_id": bill["id"], "kind": "already_cleared", "alert": True,
                             "message": f"{bill['party']} {bill['ref_no']}: Tally already shows "
                             f"this bill as settled. Marking it again may be a double {NOUN[bill['kind']]}."})
        elif st["status"] == "done":
            who = ", ".join(f"{o['name']} ({money(o['amount'])} on {o['paid_on']})"
                            for o in others if not o["reconciled_at"])
            warnings.append({"bill_id": bill["id"], "kind": "already_done", "alert": True,
                             "message": f"{bill['party']} {bill['ref_no']}: already marked "
                             f"{word} in full by {who}. This looks like a DOUBLE {NOUN[bill['kind']].upper()}."})
        elif amount > st["remaining"] + TOLERANCE:
            warnings.append({"bill_id": bill["id"], "kind": "over_amount", "alert": True,
                             "message": f"{bill['party']} {bill['ref_no']}: {money(amount)} is more "
                             f"than the {money(st['remaining'])} still pending."})
        elif st["waiting"] > 0:
            who = ", ".join(sorted({o["name"] for o in others if not o["reconciled_at"]}))
            warnings.append({"bill_id": bill["id"], "kind": "part_by_other", "alert": False,
                             "message": f"{bill['party']} {bill['ref_no']}: {who} already marked "
                             f"{money(st['waiting'])} on this bill. Make sure this is the balance, "
                             f"not the same {word} again."})

        same = conn.execute(
            "SELECT e.*, u.name, b.ref_no FROM entries e JOIN users u ON u.id = e.user_id "
            "JOIN bills b ON b.id = e.bill_id WHERE b.party_key = ? AND b.kind = ? AND "
            "b.firm_id = ? AND e.bill_id != ? AND e.deleted_at = '' AND e.paid_on = ? AND "
            "ABS(e.amount - ?) <= ?",
            (bill["party_key"], bill["kind"], bill["firm_id"], bill["id"], paid_on,
             amount, TOLERANCE)).fetchall()
        if same and not (ref_key and all(squeeze(s["reference"]) == ref_key for s in same)):
            s = same[0]
            warnings.append({"bill_id": bill["id"], "kind": "same_amount_same_day", "alert": True,
                             "message": f"{bill['party']}: {s['name']} already marked "
                             f"{money(s['amount'])} {word} on {paid_on} against bill "
                             f"{s['ref_no']}. Same party, same amount, same day - check it is "
                             f"not one {NOUN[bill['kind']]} entered twice."})

        if bill["assigned_to"] and bill["assigned_to"] != user["id"]:
            owner = conn.execute("SELECT name FROM users WHERE id = ?",
                                 (bill["assigned_to"],)).fetchone()
            warnings.append({"bill_id": bill["id"], "kind": "not_yours", "alert": False,
                             "message": f"{bill['party']} is given to {owner['name'] if owner else 'someone else'}. "
                             f"It will be counted as your work."})

    if ref_key:
        used = conn.execute(
            "SELECT e.*, u.name, b.party, b.party_key FROM entries e JOIN users u ON "
            "u.id = e.user_id JOIN bills b ON b.id = e.bill_id WHERE e.reference_key = ? "
            "AND e.deleted_at = ''", (ref_key,)).fetchall()
        clash = [u for u in used if u["party_key"] not in parties]
        if clash:
            u = clash[0]
            warnings.append({"bill_id": ids[0], "kind": "ref_reused", "alert": True,
                             "message": f"Reference {reference} was already used by {u['name']} "
                             f"for {u['party']} ({money(u['amount'])} on {u['paid_on']}). One UTR / "
                             f"cheque cannot pay two different parties."})
    return warnings


def save_entries(conn, user, lines, paid_on, mode, reference, remarks, warnings):
    batch = uuid.uuid4().hex[:10]
    alert_on = defaultdict(list)
    for w in warnings:
        if w.get("alert"):
            alert_on[w["bill_id"]].append(w)
    stamp = now()
    saved = []
    for bill, amount in lines:
        flagged = 1 if alert_on.get(bill["id"]) else 0
        cur = conn.execute(
            "INSERT INTO entries (bill_id, user_id, amount, paid_on, mode, reference, "
            "reference_key, remarks, batch, flagged, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bill["id"], user["id"], round(amount, 2), paid_on, mode, reference,
             squeeze(reference), remarks, batch, flagged, stamp))
        eid = cur.lastrowid
        saved.append(eid)
        for w in alert_on.get(bill["id"], []):
            raise_alert(conn, w["kind"], f"Saved anyway by {user['name']}: {w['message']}",
                        bill_id=bill["id"], entry_id=eid, raised_by=user["id"], once=False)
        log(conn, user["id"], f"mark_{WORD[bill['kind']]}",
            f"{bill['party']} {bill['ref_no']}: {money(amount)} {mode} {reference}".strip(),
            bill["id"])
    return saved
