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

## Option A — always online, on Render *(recommended)*

**Best if:** you want a link that works at any hour, from any phone, with
nothing running in the office. About ₹600 a month.

The repository already carries `render.yaml`, so Render sets everything up
itself.

1. Go to <https://render.com> and sign in with your GitHub account.
2. **New → Blueprint**, and choose the `QUOTEAPP` repository. Pick the branch
   `claude/appsheet-quote-generator-qhjvnu` (or `main`, once it is merged).
3. Render reads `render.yaml` and shows one service. It asks for
   **QUOTEAPP_PIN** — type the number your team will use.
4. Press **Apply**. The first build takes five to ten minutes.
5. You get an address like `https://wellworth-quotations.onrender.com`. That is
   your app.

On its first start it imports the party, machine and company databases by
itself — nothing to run by hand.

Then open the address, sign in with the PIN, go to **Setup → Google Sheet**,
paste your Apps Script web app URL and press **Test the connection**. From that
moment every quotation anybody raises goes into your Order items sheet.

**Why the paid tier.** Render's free plan gives no permanent disk and puts the
app to sleep after fifteen minutes, so the first person each morning waits
about a minute and the app's own copy of the quotations is wiped on every
restart. The Starter plan keeps a 1 GB disk mounted at `instance/` and stays
awake. Your sheet is safe either way — see *Losing the disk* below — but the
paid tier is the one to use in daily work.

Any similar host works the same way: **Railway**, **Fly.io**, **DigitalOcean App
Platform**. What matters is a persistent disk on `instance/` and permission to
make outbound requests (so the app can reach your Apps Script).

### Losing the disk

The app is built so this is survivable, which is worth knowing before you
depend on it:

- The party, machine and company lists are rebuilt from the CSVs in `data/` on
  every start.
- The quotations are read back out of your **Order items** sheet — the sheet is
  the record, so nothing is lost. There is also **Setup → Bring in quotations
  from the sheet** to do it on demand.

The one thing to write down somewhere is your **Apps Script web app URL**,
since it lives in the database. Paste it back in under Setup after a wipe, or
better, keep it out of harm's way by leaving the disk enabled.

---

## Option B — your own PC, with a Cloudflare tunnel

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
| **A · Render** | Anywhere, always | Automatically | ~₹600/month | 15 minutes |
| **B · Cloudflare tunnel** | Anywhere, while the PC is on | Automatically | Free | 10 minutes |
| **C · Web page + export** | Anywhere, always | You import daily | Free | Nothing to set up |

For a team raising quotations through the day, **A**. Moving between them
changes nothing about how the app works — same code, same sheet, same PIN.

## Putting it on your team's phones

The app installs like a real app, no store needed:

- **Android / Chrome** — open the address, menu **⋮ → Add to Home screen**.
- **iPhone / Safari** — open the address, **Share → Add to Home Screen**.

It then opens full screen with its own icon, and the PIN is remembered for 30
days. Tell your team to do this once and they will not think about it again.

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
