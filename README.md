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
| **Quotes** | Every quotation you have raised, newest first, searchable by party |
| **New** | The 5-step quotation form (company → party → items → totals → terms) |
| **Parties** | All **6,723** parties from your client database; tap one to start a quote |
| **Machines** | All **628** models with live rates from your machine database |
| **Setup** | Default terms, salespersons and their numbers, bank details, e-mail |

From a saved quotation you can:

- **Download XLSX** — the workbook, identical in layout to your AppSheet output
- **Print / Save as PDF** — opens an A4 page; your browser's Print dialog saves the PDF
- **Download PDF file** — direct PDF (needs LibreOffice installed, see below)
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

---

## Raising a quotation

1. **Quoting from** — which of your seven companies is quoting. Defaults to
   WELL WORTH; change the default under Setup. Pick the salesperson and their
   number — that prints in the *Prepared by* box.
2. **Party** — tap *Choose a party* and search by name, city, phone or GST no.
   The address box is filled in for you and you can edit it before printing.
   A party that is not in the database yet can be typed in and saved with
   *+ Save as a new party*.
3. **Items** — tap *Choose a machine*, search the model or description, and the
   rate fills in automatically. Change the qty or override the rate if you are
   giving a discount. Add as many items as you like — the sheet grows to fit,
   and short quotations still print the familiar 7-row table.
4. **Totals** — GST % and advance received. Sub total, GST, G. Total and balance
   payable update as you type.
5. **Terms** — pre-filled with your standard terms; edit for this quote only, or
   save them as the new default.

Tap **Save quotation**, then pick XLSX, PDF, or e-mail.

The file is named exactly as before:
`PARTY NAME FIRST ITEM DESCRIPTION.xlsx`, e.g.
`AMIT CHAUHAN & SONS FILING TABLE WITH 0.75HP DC (24inch Table).xlsx`

---

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

There are two ways to get a PDF:

- **Print / Save as PDF** (recommended) — works everywhere, no extra software.
  It opens an A4 page laid out like the quotation; use the browser's Print
  dialog and choose *Save as PDF*.
- **Download PDF file** — converts the real workbook using
  [LibreOffice](https://www.libreoffice.org/), which must be installed. If it is
  not, the app says so and you use the print route instead.

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
  main.py        Flask routes (the API the screens talk to)
  db.py          database schema
  seed.py        CSV import
  quote_xlsx.py  the workbook generator - a faithful rebuild of your template
  print_view.py  the A4 HTML view used for Print → Save as PDF
  mailer.py      SMTP sending
  static/        the app itself (index.html, app.js, style.css)
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
