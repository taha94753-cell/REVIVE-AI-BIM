"""
Early-warning e-mail. When a saved assessment falls in an alert band (config
alerts.send_on_bands), the project manager is e-mailed. Without SMTP settings the
message is written to data/outbox/ as an .eml file, so the feature can be shown
in a demo without sending anything.

Environment variables: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, ALERT_TO, ALERT_FROM
"""
from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage

from .config import load_config, path


def _oneline(s, n: int = 120) -> str:
    """Project names come from users: strip control characters so they cannot inject e-mail headers."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()[:n]


def compose(name: str, result: dict, to: list[str] | None = None) -> EmailMessage:
    name = _oneline(name) or "Project"
    band = _oneline((result.get("band") or {}).get("name", ""), 40)
    msg = EmailMessage()
    msg["Subject"] = f"[REVIVE] {name}: {band} - forecast overrun {result.get('time_overrun_pct')}%"
    msg["From"] = os.environ.get("ALERT_FROM", "revive@localhost")
    msg["To"] = ", ".join(to) if to else os.environ.get("ALERT_TO", "project.manager@example.com")
    lo, hi = result.get("time_interval_pct", [None, None])
    drivers = [c for c in result.get("explanation", {}).get("contributions", []) if c["key"] != "_other" and c["shap"] > 0][:3]
    lines = [
        f"Project: {name}",
        f"Checkpoint: {result.get('gate_label')}",
        f"Forecast time overrun: {result.get('time_overrun_pct')}% (80% range {lo}% to {hi}%)",
        f"Probability of exceeding {result.get('high_risk_threshold_pct')}%: {round(100 * result.get('high_risk_probability', 0))}%",
        f"Project health score: {(result.get('health') or {}).get('score')}/100",
        "",
        "Main factors pushing the forecast up:",
        *[f"  - {d['label']} ({d['value']}): +{d['shap']} percentage points" for d in drivers],
        "",
        "Open REVIVE to review the optimised recovery plan.",
    ]
    msg.set_content("\n".join(lines))
    return msg


def maybe_alert(name: str, result: dict, company_id: int | None = None) -> dict:
    """Alert the company's own users (security.alerts.to_company_users) or ALERT_TO; never another company."""
    cfg = load_config()["alerts"]
    band = (result.get("band") or {}).get("name")
    if band not in cfg.get("send_on_bands", []):
        return {"sent": False, "reason": f"band '{band}' does not trigger an alert"}
    to = None
    if company_id is not None and cfg.get("to_company_users", True):
        from .auth import company_emails
        to = company_emails(company_id)[:20] or None
    msg = compose(name, result, to)
    host = os.environ.get("SMTP_HOST")
    if cfg.get("enabled") and host:
        try:
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=15) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            return {"sent": True, "channel": "email", "to": f"{len((to or [None]))} recipient(s)"}
        except Exception as exc:
            print(f"[REVIVE] SMTP error: {exc.__class__.__name__}: {exc}")
            return {"sent": False, "reason": "SMTP error (see the server window)"}
    outbox = path(cfg.get("outbox_dir", "data/outbox"))
    if company_id is not None:
        outbox = outbox / f"c{int(company_id)}"
    outbox.mkdir(parents=True, exist_ok=True)
    f = outbox / f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.eml"
    f.write_bytes(bytes(msg))
    return {"sent": False, "channel": "outbox", "file": f.name,
            "reason": "SMTP not configured - message written to data/outbox"}
