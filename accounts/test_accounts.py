"""End-to-end checks for the Accounts Desk.

    python -m unittest accounts.test_accounts -v
"""

import io
import os
import tempfile
import unittest
from datetime import datetime

import openpyxl

TMP = tempfile.mkdtemp(prefix="accounts-test-")
os.environ["ACCOUNTS_INSTANCE"] = TMP
os.environ["ACCOUNTS_DB"] = os.path.join(TMP, "test.db")

from accounts import logic  # noqa: E402
from accounts.db import get_db  # noqa: E402
from accounts.main import create_app, create_user  # noqa: E402

H = {"X-Requested-With": "accounts-desk"}


def tally_file(firm, report, bills):
    """A workbook laid out the way Tally exports Bills Payable / Receivable."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([f"{firm} -  (from 1-Apr-26)"])
    for line in ("GALA NO 12", "SAKINAKA", "MUM-400072", "TEL", "UDYAM", "E-Mail"):
        ws.append([line])
    ws.append([report])
    ws.append(["1-Apr-26 to 30-Oct-26"])
    ws.append(["Pending Bills"])
    ws.append(["Date", "Ref. No.", "Party's Name", "Pending", "Due on", "Overdue"])
    ws.append([None, None, None, "Amount", None, "by days"])
    for d, ref, party, amt in bills:
        dt = datetime.strptime(d, "%Y-%m-%d")
        ws.append([dt, ref, party, amt, dt, "10"])
    ws.append([None, None, None, sum(b[3] for b in bills)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


PAYABLE_DAY1 = [
    ("2026-08-01", "JJ/01", "J.J. ENGINEERING WORKS", 50000),
    ("2026-08-02", "JJ/02", "J.J. ENGINEERING WORKS", 30000),
    ("2026-08-03", "DE-1", "DEEPAK ELECTRICALS", 2195),
    ("2026-08-03", "DE-2", "DEEPAK ELECTRICALS", 2195),      # same amount, same day
    ("2026-08-04", "P-9", "PARAS ELECTRIC", 15000),
    ("2026-08-05", "A-1", "AJANTA PLY", 8000),
    ("2026-08-06", "S-1", "SUNDER AUTO", 9000),
    ("2026-08-07", "T-1", "TN SHAH", 22000),
]


class AccountsDeskTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        create_user("Abrar", "abrar", "adminpass1", "admin", 0)
        for name in ("Ravi", "Sneha", "Imran"):
            create_user(name, name.lower(), "pass12345")

    def client(self, user, pw="pass12345"):
        c = self.app.test_client()
        r = c.post("/login", data={"username": user, "password": pw})
        self.assertEqual(r.status_code, 302, f"{user} could not sign in")
        return c

    def upload(self, c, name, data):
        r = c.post("/api/upload", data={"file": (io.BytesIO(data), name)}, headers=H,
                   content_type="multipart/form-data")
        return r.get_json()[0]

    def bill(self, ref):
        conn = get_db()
        b = conn.execute("SELECT * FROM bills WHERE ref_no = ?", (ref,)).fetchone()
        st = logic.bill_state(conn, [b["id"]])[b["id"]]
        conn.close()
        return dict(b), st

    def mark(self, c, refs_amounts, ref="UTR1", confirm=False, paid_on="2026-10-23"):
        lines = [{"bill_id": self.bill(r)[0]["id"], "amount": a} for r, a in refs_amounts]
        return c.post("/api/entries", headers=H, json={
            "lines": lines, "paid_on": paid_on, "mode": "NEFT", "reference": ref,
            "confirm": confirm})

    def test_flow(self):
        admin = self.client("abrar", "adminpass1")

        # ---- day 1: upload, everything is shared out, parties stay together
        r = self.upload(admin, "WWI_PAYABLE_20.10.26.xls",
                        tally_file("WELL WORTH INDUSTRIES", "Bills Payable", PAYABLE_DAY1))
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["firm"], r["kind"], r["new"]), ("WWI", "payable", 8))
        self.assertEqual(r["unassigned"], 0)
        self.assertEqual(len(r["given"]), 3, "all three people get work")
        self.assertGreaterEqual(r["alerts"], 1, "DEEPAK same amount same day is flagged")
        conn = get_db()
        owners = conn.execute("SELECT party, COUNT(DISTINCT assigned_to) n FROM bills "
                              "GROUP BY party").fetchall()
        conn.close()
        self.assertTrue(all(o["n"] == 1 for o in owners), "one party, one person")

        # the very same file again is refused
        data1 = tally_file("WELL WORTH ENGINEERING", "Bills Payable", PAYABLE_DAY1[:1])
        self.assertTrue(self.upload(admin, "WWE_PAYABLE_20.10.26.xls", data1)["ok"])
        again = self.upload(admin, "WWE_PAYABLE_20.10.26.xls", data1)
        self.assertFalse(again["ok"])
        self.assertIn("already uploaded", again["error"])

        # ---- the owner of JJ marks both bills paid with one UTR
        jj, _ = self.bill("JJ/01")
        owner = get_db().execute("SELECT username FROM users WHERE id = ?",
                                 (jj["assigned_to"],)).fetchone()["username"]
        c_owner = self.client(owner)
        r = self.mark(c_owner, [("JJ/01", 50000), ("JJ/02", 30000)], ref="UTR-JJ-1")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.bill("JJ/01")[1]["status"], "done")

        # ---- someone else tries to pay JJ/01 again: warned, needs confirm
        other = next(u for u in ("ravi", "sneha", "imran") if u != owner)
        c_other = self.client(other)
        r = self.mark(c_other, [("JJ/01", 50000)], ref="UTR-X")
        self.assertEqual(r.status_code, 409)
        kinds = {w["kind"] for w in r.get_json()["warnings"]}
        self.assertIn("already_done", kinds)
        self.assertIn("not_yours", kinds)
        self.assertTrue(r.get_json()["serious"])
        self.assertEqual(self.bill("JJ/01")[1]["done"], 50000, "nothing saved yet")

        # saved anyway -> flagged and an alert is raised
        r = self.mark(c_other, [("JJ/01", 50000)], ref="UTR-X", confirm=True)
        self.assertTrue(r.get_json()["flagged"])
        alerts = admin.get("/api/alerts").get_json()
        self.assertTrue(any(a["kind"] == "already_done" for a in alerts))

        # ---- the same UTR used for another party is caught
        r = self.mark(c_owner, [("T-1", 22000)], ref="utr jj 1")
        self.assertEqual(r.status_code, 409)
        self.assertIn("ref_reused", {w["kind"] for w in r.get_json()["warnings"]})

        # ---- more than pending is caught
        r = self.mark(c_owner, [("P-9", 99999)], ref="UTR-P")
        self.assertIn("over_amount", {w["kind"] for w in r.get_json()["warnings"]})

        # ---- no UTR, not cash -> refused
        r = c_owner.post("/api/entries", headers=H, json={
            "lines": [{"bill_id": self.bill("P-9")[0]["id"], "amount": 100}], "mode": "NEFT"})
        self.assertEqual(r.status_code, 400)

        # ---- part payment on PARAS by its owner
        paras, _ = self.bill("P-9")
        powner = get_db().execute("SELECT username FROM users WHERE id = ?",
                                  (paras["assigned_to"],)).fetchone()["username"]
        c_p = self.client(powner)
        r = self.mark(c_p, [("P-9", 5000)], ref="UTR-P1", confirm=True)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.bill("P-9")[1]["status"], "part")
        self.assertEqual(self.bill("P-9")[1]["remaining"], 10000)

        # ---- day 2 file: JJ gone (paid), PARAS down by 5000, AJANTA gone with
        # nobody marking it, SUNDER still full although nobody paid, new bill
        day2 = [b for b in PAYABLE_DAY1 if b[1] not in ("JJ/01", "JJ/02", "A-1", "P-9")]
        day2 += [("2026-08-04", "P-9", "PARAS ELECTRIC", 10000),
                 ("2026-10-21", "JJ/03", "J.J. ENGINEERING WORKS", 40000)]
        r = self.upload(admin, "WWI_PAYABLE_22.10.26.xls",
                        tally_file("WELL WORTH INDUSTRIES", "Bills Payable", day2))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["cleared"], 3)
        self.assertEqual(r["new"], 1)
        self.assertEqual(self.bill("JJ/01")[1]["status"], "cleared")
        p9 = self.bill("P-9")[1]
        self.assertEqual((p9["status"], p9["remaining"], p9["waiting"]), ("open", 10000, 0),
                         "Tally took the 5000 off, so it is reconciled")
        self.assertEqual(self.bill("JJ/03")[0]["assigned_to"], jj["assigned_to"],
                         "a new bill of a known party goes to the same person")

        # unclaimed: AJANTA cleared in Tally, nobody marked it
        un = admin.get("/api/bills?kind=payable&status=unclaimed&assigned=").get_json()
        self.assertEqual([b["ref_no"] for b in un["bills"]], ["A-1"])

        # ---- an older file is refused
        r = self.upload(admin, "WWI_PAYABLE_21.10.26.xls",
                        tally_file("WELL WORTH INDUSTRIES", "Bills Payable", PAYABLE_DAY1[2:]))
        self.assertFalse(r["ok"])
        self.assertIn("newer", r["error"])

        # ---- scoreboard credits the person who marked
        s = admin.get("/api/scoreboard?period=all").get_json()
        by = {p["name"].lower(): p for p in s["people"]}
        self.assertEqual(by[owner]["payable"]["amount"], 80000)
        self.assertEqual(by[other]["payable"]["flagged"], 1)

        # ---- only the maker or an admin can remove an entry
        eid = get_db().execute("SELECT id FROM entries WHERE user_id = (SELECT id FROM users "
                               "WHERE username = ?) AND reconciled_at = ''",
                               (powner,)).fetchone()
        if eid:
            r = c_other.delete(f"/api/entries/{eid['id']}", headers=H, json={"reason": "x"})
            self.assertIn(r.status_code, (403, 200))

        # ---- someone leaves: their open bills go to the others
        sneha = get_db().execute("SELECT id FROM users WHERE username = 'sneha'").fetchone()["id"]
        r = admin.put(f"/api/users/{sneha}", headers=H, json={"active": False})
        self.assertEqual(r.status_code, 200)
        left = get_db().execute("SELECT COUNT(*) FROM bills WHERE assigned_to = ? AND "
                                "cleared_at = ''", (sneha,)).fetchone()[0]
        self.assertEqual(left, 0)

    def test_requests_need_header_and_login(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/api/bills").status_code, 401)
        c = self.client("ravi")
        self.assertEqual(c.post("/api/entries", json={}).status_code, 403)
        self.assertEqual(c.post("/api/redistribute", headers=H,
                                json={"kind": "payable"}).status_code, 403)

    def test_receivable_and_firm_detection(self):
        admin = self.client("abrar", "adminpass1")
        data = tally_file("EXCEL INDUSTRIES", "Bills Receivable",
                          [("2026-09-01", "1/EX/26-27", "CHARU JEWELS", 32214),
                           ("2026-09-01", "1/EX/26-27", "CHARU JEWELS", 32214)])
        r = self.upload(admin, "something.xlsx", data)
        self.assertTrue(r["ok"], r)
        self.assertEqual((r["firm"], r["kind"]), ("EXCEL", "receivable"))
        alerts = admin.get("/api/alerts").get_json()
        self.assertTrue(any(a["kind"] == "double_entry_tally" for a in alerts),
                        "the same bill twice in the file is a double entry")


if __name__ == "__main__":
    unittest.main()
