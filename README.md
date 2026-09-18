# Well Worth Quotation App

A replacement for the AppSheet quotation app. Pick a party, tap the machines,
and it produces the **same .xlsx quotation** you have always sent — same layout,
same fonts, same terms block, same file name — plus a PDF and an optional e-mail.

Everything runs on your own machine. There is no AppSheet subscription, no row
limit, and your client list never leaves your computer.

---

## What is inside

| Screen | What it does |
|---|---|
| **Quotes** | Every quotation and proforma you have raised, newest first, searchable by party, city or id |
| **New** | The quotation form (document → company → party → items → totals → follow-up → terms) |
| **Parties** | All **6,723** parties; search, tap to edit, or **+ Add a new party** |
| **Machines** | All **628** models with live rates; tap to edit a rate, or **+ Add a new machine** |
| **Setup** | Google Sheet sync, default terms, salespersons, bank details, e-mail |

Each person picks their own name under **Prepared by**; their device remembers
it, so their name and number are filled in on every later quotation and land in
the **Made By** column of the sheet.

Every quotation you save is also written into your **Order items** Google Sheet,
in the same 75 columns AppSheet used — see *Recording quotations in your Google
Sheet* below.

From a saved quotation you can:

- **Download XLSX** — the workbook, identical in layout to your AppSheet output
- **Print / Save as PDF** — opens an A4 page; your browser's Print dialog saves the PDF
- **Download PDF file** — a one-page A4 PDF, drawn by the app itself
- **E-mail to party** — sends the xlsx + pdf straight to the party's address

---

## Running it

You need **Python 3.9 or newer**. Nothing else.

### Mac / Linux

```bash
./run.sh
```

### Windows

Double-click **`run.bat`**, or from Command Prompt:

```
run.bat
```

The first run creates the database and imports the three CSV files (about 20
seconds). Then open **<http://localhost:5000>** in your browser.

**To use it from your phone**, find your computer's IP address (e.g.
`192.168.1.14`) and open `http://192.168.1.14:5000` on the phone while both are
on the same Wi-Fi. On an iPhone, tap Share → *Add to Home Screen* and it behaves
like the AppSheet app did.

**To give the whole team an always-online link**, see **[DEPLOY.md](DEPLOY.md)**.
One hosted copy means every quotation anybody raises goes into your Order items
sheet by itself, from any phone, at any hour. The repository carries a
`render.yaml`, so Render can set it up from the repository in about fifteen
minutes. Set `QUOTEAPP_PIN` first and the app asks for that PIN once per device.

Once it is hosted, everyone should open the address on their phone and use
**Add to Home Screen** — it then behaves like an installed app, full screen,
with its own icon.

---

## Raising a quotation

1. **Document & company** — QUOTATION, PROFORMA, DELIVERY CHALLAN or TAX
   INVOICE, the file type (NON STD / FT STD), and which of your seven companies
   is quoting. Defaults to WELL WORTH; change the default under Setup. Pick the
   salesperson and their number — that prints in the *Prepared by* box.
2. **Party** — tap *Choose a party* and search by name, city, phone or GST no.
   The address, city, WhatsApp number and e-mail fill in for you, and you can
   edit any of them before printing. A party that is not in the database yet
   can be added from the **Parties** tab with *+ Add a new party*, or typed
   straight into the form and saved with *+ Save as a new party*.
3. **Items** — tap *Choose a machine*, search the model or description, and the
   rate fills in automatically. Change the qty or override the rate if you are
   giving a discount. Add as many items as you like — the sheet grows to fit,
   and short quotations still print the familiar 7-row table.
4. **Totals** — GST % and advance received. Sub total, GST, G. Total and balance
   payable update as you type.
5. **Follow-up** — the reminder date (a week out by default), the first
   follow-up date and its remark. These are the columns your reminder list
   reads from.
6. **Terms** — pre-filled with your standard terms; edit for this quote only, or
   save them as the new default.

Tap **Save quotation**. The quote is stored, pushed to your Google Sheet, and
you land on it — then pick XLSX, PDF, or e-mail.

The file is named exactly as before:
`PARTY NAME FIRST ITEM DESCRIPTION.xlsx`, e.g.
`AMIT CHAUHAN & SONS FILING TABLE WITH 0.75HP DC (24inch Table).xlsx`

---

## Recording quotations in your Google Sheet

Every quotation you save is appended to your **Order items** sheet as one row,
in the same 75 columns AppSheet wrote — party and address, all seven item slots
with model, qty, rate and GST, the totals, the follow-up and reminder dates, the
terms, and an 8-character id in the same shape AppSheet used.

Connecting it takes about five minutes, once, and needs no credentials file: a
small Apps Script lives in your own Google account and appends the rows. The
steps are in **[`google-apps-script/README.md`](google-apps-script/README.md)**.
Then paste the web app URL into **Setup → Google Sheet** and press **Test the
connection**.

The sheet is also read **back**: **Setup → Bring in quotations from the sheet**
pulls in rows the app does not have, which is how a hosted server repopulates
its list after a restart and how one person sees quotations another raised. A
server that started on an empty disk does this by itself.

**Nothing is ever lost if the sheet is unreachable.** Every row is written to
`instance/order_items.csv` first. A quotation that did not reach the sheet shows
a **NOT IN SHEET** tag in the list, the quotation itself has a **Send to the
Order items sheet** button, and Setup has **Sync all pending** for everything
still waiting.

Two things worth knowing:

- The sheet has seven item slots, so only the first seven items of a quotation
  reach it. The quotation .xlsx itself carries as many items as you like.
- Columns are matched on your sheet's own header row, ignoring case, spaces and
  punctuation — so columns you add by hand, or reorder, do not break the sync.

## Setting up e-mail (optional)

1. Copy `.env.example` to `.env`.
2. In your Google Account → Security → **App passwords**, create a 16-character
   app password. Your normal Gmail password will not work.
3. Put your address and that app password into `.env`:

   ```
   QUOTEAPP_SMTP_USER=wellworth.marketing2@gmail.com
   QUOTEAPP_SMTP_PASS=abcd efgh ijkl mnop
   ```

4. Restart the app. The ✉ button now sends the quotation with both the xlsx and
   the PDF attached.

Without this, everything else still works — you just download the file and
attach it yourself.

---

## PDF notes

**Download PDF file** draws the quotation straight to a one-page A4 PDF — same
layout as the workbook, rupee signs and all. It needs nothing installed, so it
works on a phone and on a hosted server alike.

**Print / Save as PDF** is still there if you would rather use the browser's own
print dialog, for instance to print on paper.

---

## Updating your master data

The app reads three CSVs in `data/` — the same exports you pull out of AppSheet:

- `CLIENT_DATA_BASE.csv`
- `MACHINE_DATA.csv`
- `COMPANIES_WITH_GST.csv`

Replace a file with a fresh export and re-import:

```bash
python -m app.seed --force      # wipes the master tables and re-reads the CSVs
```

Your saved quotations are never touched by this. Rates, parties and machines can
also be added from inside the app as you go.

Two things the importer cleans up on the way in:

- placeholder values (`NOEMAIL@GMAIL.COM`, `NO GST`, `nogst`) become blank, so
  they no longer print on a quotation;
- duplicate party rows collapse to one — 15,311 rows in the CSV are 6,723
  distinct parties.

Machines whose description is `DONT USE` are imported but hidden from the item
picker.

---

## Where your data lives

```
data/            the CSV exports (checked into git)
instance/
  quoteapp.db    SQLite database - every party, machine and quotation
  output/        the generated .xlsx and .pdf files
```

`instance/` is **not** in git. Back it up by copying the folder — that single
file is your whole quotation history.

---

## Project layout

```
app/
  main.py         Flask routes (the API the screens talk to)
  db.py           database schema
  seed.py         CSV import
  quote_xlsx.py   the workbook generator - a faithful rebuild of your template
  order_sheet.py  builds the 75-column Order items row, sends it to the sheet
                  and reads rows back
  auth.py         the optional team PIN
  print_view.py   the A4 HTML view used for Print → Save as PDF
  mailer.py       SMTP sending
  static/         the app itself (index.html, app.js, style.css)
google-apps-script/
  Code.gs         paste this into your Google Sheet to receive the rows
  README.md       the five-minute setup
data/
  SAMPLE_QUOTE_REFERENCE.xlsx   your original AppSheet output, kept as the
                                reference the generator is checked against
```

### How close is the output to the original?

The generator was diffed cell-by-cell against your
`AMIT CHAUHAN & SONS` quotation. Every populated cell, merge, font, fill,
border, column width and number format matches. The only differences are:

- the quotation date (naturally);
- serial numbers are written as plain numbers instead of
  `=IF(ISBLANK(B17)," ","1")` formulas — they print the same;
- unused item rows are left genuinely empty instead of carrying a `₹0.00`,
  so you no longer have to clear those cells by hand before sending.
