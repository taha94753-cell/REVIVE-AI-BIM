"""
Account e-mail: sign-up codes and password-reset codes.

With SMTP_HOST set the message is sent (SMTP_PORT 587, SMTP_USER, SMTP_PASSWORD, MAIL_FROM or ALERT_FROM).
Without it the message is written to data/outbox/account/ and printed in the server window, so a laptop
install with no mail server still works: whoever runs the server reads the code there.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import time
from email.message import EmailMessage

from .config import load_config, path

log = logging.getLogger("revive")


def send(to: str, subject: str, body: str) -> str:
    """Returns the channel used: "email" or "console". Never raises: sign-up must not fail on a mail hiccup."""
    msg = EmailMessage()
    msg["Subject"] = re.sub(r"[\x00-\x1f\x7f]+", " ", subject)[:160]
    msg["From"] = os.environ.get("MAIL_FROM") or os.environ.get("ALERT_FROM", "revive@localhost")
    msg["To"] = to
    msg.set_content(body)
    host = os.environ.get("SMTP_HOST")
    if host:
        try:
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=15) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            return "email"
        except Exception as exc:   # fall through to the console so the person is not locked out
            log.warning("SMTP error (%s); the message is in the server window instead", exc.__class__.__name__)
    outbox = path((load_config().get("alerts") or {}).get("outbox_dir", "data/outbox")) / "account"
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / f"mail_{time.strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}.eml").write_bytes(bytes(msg))
    print(f"\n[REVIVE] E-mail is not configured (set SMTP_HOST). Message for {to}:\n  {subject}\n  "
          + body.replace("\n", "\n  ") + "\n", flush=True)
    return "console"


def send_code(to: str, code: str, purpose: str, minutes: int) -> str:
    what = "finish creating your REVIVE workspace" if purpose == "signup" else "reset your REVIVE password"
    return send(to, f"Your REVIVE code: {code}",
                f"Use this code to {what}:\n\n    {code}\n\nIt works once and expires in {minutes} minutes.\n"
                "If you did not ask for it, ignore this message; nothing changes without the code.")
