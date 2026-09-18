"""Optional e-mail delivery of a finished quotation.

Configure with environment variables (a .env file next to run.sh is read by
run.sh before starting the server):

    QUOTEAPP_SMTP_HOST   default smtp.gmail.com
    QUOTEAPP_SMTP_PORT   default 587
    QUOTEAPP_SMTP_USER   the sending mailbox
    QUOTEAPP_SMTP_PASS   a Gmail *app password*, not the account password
    QUOTEAPP_SMTP_FROM   optional display sender, defaults to SMTP_USER

When nothing is configured the app simply reports that mail is switched off;
the download link always works regardless.
"""

import os
import smtplib
from email.message import EmailMessage


class MailNotConfigured(RuntimeError):
    pass


def is_configured():
    return bool(os.environ.get("QUOTEAPP_SMTP_USER")
                and os.environ.get("QUOTEAPP_SMTP_PASS"))


def send_quote(to_addrs, subject, body, attachments, cc_addrs=None):
    """Send `attachments` (list of file paths) to `to_addrs` (list of e-mails)."""
    if not is_configured():
        raise MailNotConfigured(
            "SMTP is not configured. Set QUOTEAPP_SMTP_USER and "
            "QUOTEAPP_SMTP_PASS (Gmail app password) to enable e-mail.")

    host = os.environ.get("QUOTEAPP_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("QUOTEAPP_SMTP_PORT", "587"))
    user = os.environ["QUOTEAPP_SMTP_USER"]
    password = os.environ["QUOTEAPP_SMTP_PASS"]
    sender = os.environ.get("QUOTEAPP_SMTP_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg.set_content(body)

    for path in attachments or []:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as fh:
            data = fh.read()
        if path.lower().endswith(".pdf"):
            maintype, subtype = "application", "pdf"
        else:
            maintype = "application"
            subtype = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        msg.add_attachment(data, maintype=maintype, subtype=subtype,
                           filename=os.path.basename(path))

    with smtplib.SMTP(host, port, timeout=60) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)

    return list(to_addrs) + list(cc_addrs or [])
