# Sending your quotations to the Google Sheet

Every quotation you save can be appended to your **Order items** sheet, in the
same 75 columns AppSheet used. It takes about five minutes to connect, once.

There are no passwords to hand over and no credentials file — the script below
lives inside your own Google account and only ever appends rows.

## 1. Open the script editor

1. Open the Google Sheet that holds your **Order items** tab.
2. Menu: **Extensions → Apps Script**.
3. Delete whatever is in the editor.
4. Paste the entire contents of `Code.gs` from this folder.
5. If you want a password on it, put a word of your own between the quotes on
   the `SHARED_SECRET` line. Otherwise leave it as it is.
6. Click the **Save** icon.

## 2. Deploy it

1. Click **Deploy → New deployment**.
2. Press the gear next to *Select type* and pick **Web app**.
3. Fill in:
   - **Execute as**: *Me*
   - **Who has access**: *Anyone*
4. Click **Deploy**, then **Authorize access** and allow it for your account.
   Google shows a warning because the script is your own and unverified —
   choose *Advanced* → *Go to (project name)* → *Allow*.
5. Copy the **Web app URL**. It looks like
   `https://script.google.com/macros/s/AKfy..../exec`.

> *Who has access: Anyone* means anyone **with that URL**. It is a long random
> address that only you have. Set the `SHARED_SECRET` as well if you would
> rather it also needed a password.

## 3. Connect the app

1. In the quotation app open **Setup → Google Sheet**.
2. Paste the Web app URL (and the secret word, if you set one).
3. Press **Test the connection** — it should answer *Sheet is connected*.
   The test only reads; it never writes a row into your sheet.

From now on, every quotation you save is added to the sheet straight away.

## If a row does not arrive

Nothing is lost. Every row is always written to `instance/order_items.csv`
first, and a quotation that failed to sync shows a **Not synced** tag in the
quotes list with a **Retry** button next to it. Setup also has **Sync all
pending**, which pushes everything still waiting.

Common causes:

- *The sheet replied with a sign-in page* — the deployment's access is not set
  to **Anyone**. Redeploy with that setting.
- *No tab named "Order items"* — the message lists the tab names the file
  actually has. Rename your tab to match, or change `SHEET_NAME` at the top of
  `Code.gs` to one of those names. A file with only one tab is used as-is, so
  this only comes up when there are several.
- You changed the script after deploying — Apps Script keeps serving the old
  version until you do **Deploy → Manage deployments → Edit → Version: New
  version → Deploy**.

## Checking what the script can see

Open the web app URL in a browser. It answers with the file name and the list
of tab names it found, which is the quickest way to confirm you deployed the
script into the sheet you meant.

## Changing the columns

The script matches your sheet's own header row, ignoring case, spaces and
punctuation. Columns you add by hand are left alone, and reordering the sheet's
columns does not break anything.
