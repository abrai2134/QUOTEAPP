# Accounts Desk

Shares the **Bills Payable** and **Bills Receivable** from Tally out evenly
between the accounts team, records **who** paid or collected each bill, and
stops the same bill being paid or entered twice.

Works for all four firms: **Well Worth Industries (WWI)**, **Well Worth
Engineering (WWE)**, **Well Worth Air Systems (WWAS)** and **Excel Industries
(EXCEL)**. More firms can be added under **More → Firms**.

---

## Starting it

| | |
|---|---|
| Windows | double-click **`run_accounts.bat`** |
| Mac / Linux | `./run_accounts.sh` |

Open **http://localhost:5100**. The first time, it asks you to create the
**admin** login (that is you). The team opens the same address from their own
PC or phone, using this computer's IP (e.g. `http://192.168.1.14:5100`).

To put it online for everyone, Render reads `render.yaml` and sets up a
second service, **wellworth-accounts**. It asks for `ACCOUNTS_ADMIN_USER` and
`ACCOUNTS_ADMIN_PASSWORD`, which become your admin login.

---

## First day setup (admin)

1. **More → Team → + Add a person**. Add each accounts person with their own
   username and password. Leave **Gets bills** ticked.
2. **More → Upload**: choose the Tally files, e.g. `WWI_PAYABLE_23.10.26.xls`
   and `WWI_RECEIVABLE_23.10.26.xls` (you can pick several at once, for all
   four firms). The firm and the type are read from the file itself.
3. Every bill is given to someone. Each person now sees their list under
   **My work**.

## Every day (anyone in the team)

1. Export Bills Payable and Bills Receivable from Tally for each firm and
   **upload** them, as they are. The date in the file name (`23.10.26`) is the
   report date.
   - Bills that have **gone** from Tally are marked **Cleared**.
   - **New** bills go to whoever already handles that party, or to whoever has
     the least work if the party is new.
   - The same file twice, or an **older** file after a newer one, is refused,
     so settled bills never come back by mistake.
2. Each person opens **My work**, ticks the bills they paid / collected (tick
   the party name to pick all its bills), taps **Mark paid** / **Mark
   received**, and enters the date, mode and **UTR / cheque no.**
3. For receivables, **Add follow-up** on a bill to log a call ("promised by
   Friday"). Follow-ups count on the scoreboard too.

## How the work is shared

- **All bills of one party go to one person**, for every firm and type. Two
  people never chase or pay the same party.
- Parties are spread so everyone has about the **same number of bills and the
  same rupee value**. (One very large party, like J.J. Engineering Works at
  ₹30 lakh, stays whole with one person, and that person gets fewer other
  parties.)
- Admin can **give a party to someone else** from the bill screen, or press
  **More → Share out again** to rebalance everything. A party where someone has
  already marked a payment stays with them.
- Switching a person off (or untick **Gets bills**) hands their open bills to
  the others automatically.

## Who did what: the Scoreboard

For today / this week / this month / all time, per person:

- payments made and receipts collected: number of entries and ₹
- follow-ups logged
- what is still open with them, and how much is 60+ days overdue
- **flagged** entries (saved despite a double-payment warning)
- **Cleared, not marked**: Tally shows it settled but nobody marked it, so
  nobody gets credit for it.

Every action (upload, mark, remove, reassign) is in **More → Activity** with
the person's name and time, and can be downloaded as CSV.

## Double payment / double entry checks

**When someone marks a bill**, they are stopped and shown a warning if:

| Check | Example |
|---|---|
| Already marked in full by someone | Sneha marks a bill Ravi already paid |
| Tally already shows it settled | the bill dropped out of today's file |
| Amount is more than what is pending | ₹99,999 against a ₹15,000 bill |
| Same UTR / cheque already used for a **different** party | one UTR cannot pay two vendors |
| Same party, same amount, same day already marked on another bill | the same payment entered against two bills |
| Someone already marked part of it | to make sure this is the balance |
| The bill is given to someone else | they will get the credit |

They can still save after ticking *"I have checked, this is not a double
payment"*, but the entry is **flagged** and goes to **Alerts** for the admin.

**When a file is uploaded**, it raises an alert if:

- the **same bill appears twice** in the Tally file (entered twice in Tally)
- the same party has two bills of the **same amount on the same day**
- the same **bill number** appears on two different dates for one party
- Tally shows a **negative** pending (more paid than the bill)
- something marked paid here **still shows pending** in Tally a day later
  (either not entered in Tally, or the payment did not go through)

Admin opens **Alerts**, checks each one, and presses **Mark checked** with a
note. That note stays on record.

## Undoing a mistake

The person who made an entry (or an admin) can **Remove** it from the bill
screen, with a reason. It stays visible, struck through, with who removed it
and why. Once Tally shows the payment, only an admin can remove it.

## Where the data lives

`instance/accounts.db` (SQLite), separate from the quotation app. Back up
this one file. **More → Download** gives CSVs of all entries and bills.

## Tests

```
python -m unittest accounts.test_accounts -v
```
