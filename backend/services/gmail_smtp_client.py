"""Outbound SMTP send for consumer Gmail accounts authenticated via App Password.

Sister module to backend.services.gmail_imap_client (which handles inbound
reading). Where IMAP serves the email-monitor read path, this serves the
"email me my results" send path.

Auth is the same App Password used for IMAP — Google issues one App Password
per app, usable across IMAP + SMTP. Credential lookup is via
gmail_password_store (machine-wide .gmailpasswords.json, keyed by email).

No async wrapping; smtplib is sync and a single send is fast (typically
sub-second). Callers running inside asyncio should wrap in
`asyncio.to_thread` if they want to keep the event loop unblocked during
the SMTP handshake.
"""
from __future__ import annotations

import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from backend.services.logger_service import get_logger


log = get_logger("gmail_smtp_client")


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL


def smtp_send(
    *,
    from_email: str,
    app_password: str,
    to: str,
    subject: str,
    body: str,
    attachments: list[str] | None = None,
) -> None:
    """Send an email via Gmail SMTP using the supplied App Password.

    Raises smtplib.SMTPException (or subclasses) on send failure. Caller is
    responsible for translating that into a friendly error and logging the
    attempt to workflow_run_email_log.
    """
    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for path_str in attachments or []:
        p = Path(path_str)
        if not p.is_file():
            log.warning("smtp_attachment_missing", path=str(p))
            continue
        guessed, _ = mimetypes.guess_type(p.name)
        maintype, subtype = (guessed or "application/octet-stream").split("/", 1)
        with p.open("rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(from_email, app_password)
        smtp.send_message(msg)

    log.info("smtp_send_ok", from_email=from_email, to=to, attachments=len(attachments or []))
