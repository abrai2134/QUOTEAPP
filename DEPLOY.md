# Putting the app on a link your team can use

You want two things at once:

1. every quotation, whoever raises it, lands in the **Order items** Google Sheet;
2. the whole team can reach the app — from a phone, from home, from Surat.

Both come from the same move: **run one copy of the app somewhere, and give the
team its link.** The app is the only thing that talks to your sheet, so one copy
means one tidy stream of rows, exactly as AppSheet worked.

> The tap-and-try web page is a different thing. It is handy for checking a
> quotation on the move, but a browser page cannot write into your Google Sheet
> — you download the rows and import them. If several people are raising
> quotations, host the app instead.

---

## First: switch the PIN on

Before the app is reachable from outside your office, give it a PIN. Put this in
your `.env` file (next to `run.sh`):

```
QUOTEAPP_PIN=4321
QUOTEAPP_HTTPS=1
```

Choose your own number, and share it with the team the way you would a door
code. Everyone gets the same PIN; the app remembers each person's browser for 30
days, so they type it once.

`QUOTEAPP_HTTPS=1` tells the app it is being served over https, so the sign-in
cookie is never sent over a plain connection. Set it for every hosted option
below. Leave both out while you are only using the app on your own machine.

Each person picks their own name under **Prepared by** — their device remembers
it, so their name and number are already filled in the next time. That is what
lands in the **Made By** column of the sheet.

---

## Option A — your own PC, with a Cloudflare tunnel

**Best if:** the office PC is on during working hours and you want this today,
free, with nothing to move.

Cloudflare gives your PC a public https address without touching your router.

1. Download **cloudflared** from
   <https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/>
   and install it.
2. Start the quotation app as usual (`run.sh`, or `run.bat` on Windows).
3. In a second terminal or Command Prompt:

   ```
   cloudflared tunnel --url http://localhost:5000
   ```

4. It prints an address like
   `https://random-words-here.trycloudflare.com`. That is the team's link.

Send that address and the PIN to the team. Everyone works in the same app, and
every quotation they save goes into your Google Sheet as it is made.

Two things to know: the free address changes each time you restart cloudflared,
and it stops working when the PC sleeps. For a fixed address, make a free
Cloudflare account and run `cloudflared tunnel create wellworth` — their
documentation walks through it, and you can then point a name like
`quotes.yourdomain.com` at it.

---

## Option B — a small cloud host

**Best if:** you would rather it was always on, and not tied to a PC in the
office. Expect roughly ₹500–700 a month for the smallest paid tier, which is
still far less than AppSheet per seat.

Any host that runs a Python app works. What matters is that the host gives you a
**persistent disk** mounted at `instance/`, because that folder holds your
database. Free tiers usually wipe the disk on every restart — fine for a trial,
not for your records.

The repository is ready to deploy as it is:

```
Procfile         tells the host how to start the app
requirements.txt the two libraries it needs
```

On the host, set these environment variables:

```
QUOTEAPP_PIN=4321
QUOTEAPP_HTTPS=1
PORT                 (most hosts set this for you)
```

Then open the app once, go to **Setup → Google Sheet**, paste your Apps Script
web app URL and press **Test the connection** — exactly as you would locally.

After the first start, import your master data once:

```
python -m app.seed
```

Most hosts let you run that from a console in their dashboard.

---

## Option C — leave it on your PC, team uses the web page

**Best if:** only one or two people raise quotations, and the rest just need to
look.

The team uses the tap-and-try page from their phones; you export
**Quotes → Export all for the sheet (.csv)** at the end of the day and import it
into the sheet with **File → Import → Upload → Append rows to current sheet**.

Honest about the trade-off: this is manual, and if two people export the same
quotations you get duplicate rows. Every row carries its own `ID`, so duplicates
are findable, but it is work you would not have with Option A or B.

---

## Which to choose

| | Team reach | Sheet updated | Cost | Effort |
|---|---|---|---|---|
| **A · Cloudflare tunnel** | Anywhere, while the PC is on | Automatically | Free | 10 minutes |
| **B · Cloud host** | Anywhere, always | Automatically | ~₹500/month | An hour |
| **C · Web page + export** | Anywhere, always | You import daily | Free | Nothing to set up |

Start with **A**. It costs nothing, it takes ten minutes, and if the office PC
being on becomes a nuisance you can move to **B** later without changing
anything about how the app works — same code, same sheet, same PIN.

---

## Keeping your records safe

Whichever option you pick:

- The Google Sheet is your long-term record — it is the one thing that is backed
  up by Google and readable by anything.
- `instance/quoteapp.db` is the app's own copy. Copy that folder somewhere safe
  now and then; on a cloud host, that is what the persistent disk is for.
- `instance/order_items.csv` holds every row the app has ever built for the
  sheet, in order. If the sheet ever loses rows, they can be restored from here.

---

## If a team member says a quotation did not reach the sheet

1. Open the quotations list — a row that has not reached Google carries a red
   **NOT IN SHEET** tag.
2. Open it and press **Send to the Order items sheet**, or use
   **Setup → Sync all pending** to push everything waiting at once.
3. If it still fails, the message says why. The usual causes are in
   [`google-apps-script/README.md`](google-apps-script/README.md) — most often
   the Apps Script deployment needs *Who has access: Anyone*.

Nothing is ever lost while this is being sorted out: the row is written to
`instance/order_items.csv` before the app tries the sheet at all.
