"""
"What do we do this week?": every forecast driver turned into a reason with an
owner and one concrete action.

Adapted from the REVIVE web app's weekly card (reasons with owners), with no
LLM: fixed templates keyed by the input field, filled with the project's own
answers. Only drivers that push the forecast UP get an action, ranked by how
many percentage points of time overrun they add, so the list is short and
always tied to the explanation the manager can see.
"""
from __future__ import annotations

import math

OWNER_LABEL = {
    "client": "Client",
    "consultant": "Consultant / Engineer",
    "contractor": "Contractor",
    "subcontractor": "Subcontractor",
    "planning": "Planning engineer",
}

# field -> (owner, reason template, action). {value} is the project's answer.
TEMPLATES = {
    "spi_25": ("contractor", "Work is behind the planned pace at 25% (SPI {value})",
               "Compare this week's manpower and plant with the resource plan and open the Recovery sheet."),
    "spi_50": ("contractor", "Work is behind the planned pace at 50% (SPI {value})",
               "Re-baseline the look-ahead and run the recovery plan; SPI at 50% drives most of the forecast."),
    "cpi_25": ("contractor", "Cost performance is weak (CPI {value})",
               "Check rates, wastage and idle plant against the cost plan before it shows up in the schedule."),
    "cpi_50": ("contractor", "Cost performance is weak (CPI {value})",
               "Check rates, wastage and idle plant against the cost plan before it shows up in the schedule."),
    "cert_25": ("contractor", "Little value certified so far ({value})",
                "Submit the next IPC with every measured quantity; unbilled work is lost cash flow."),
    "cert_50": ("contractor", "Little value certified so far ({value})",
                "Submit the next IPC with every measured quantity; unbilled work is lost cash flow."),
    "late_payments_q1": ("client", "IPCs paid more than 30 days late: {value}",
                         "Send a notice of late payment under the payment clause and log it for the EOT claim."),
    "variations_q1": ("client", "Variation orders so far: {value}",
                      "Ask for each pending VO to be approved with a time extension, not only a cost adjustment."),
    "design_status": ("consultant", "Design at award: {value}",
                      "List the drawings still missing against the programme and send it to the Engineer this week."),
    "duration_setting": ("client", "Contract duration: {value}",
                         "Record in writing that the programme was imposed; it supports any later EOT claim."),
    "funding": ("client", "Funding committed at award: {value}",
                "Ask the client for the release schedule for this financial year and plan work around it."),
    "subcontractor_q1": ("subcontractor", "Subcontractor performance rated {value}",
                         "Hold a progress meeting with the weakest subcontractor and agree a two-week catch-up."),
    "planned_months": ("planning", "Long contract duration ({value})",
                       "Long jobs drift: review the programme monthly, not quarterly."),
    "rfis_q1": ("consultant", "Design changes or RFIs so far: {value}",
                "Chase open RFIs with the Engineer's representative and record each response date."),
    "material_events_q1": ("contractor", "Material shortages that stopped work: {value}",
                           "Line up an alternate supplier for the critical materials this week."),
    "weather_days_q1": ("planning", "Working days lost to weather: {value}",
                        "Keep the site diary entries and check the adverse-weather clause before claiming."),
    "labour_q1": ("contractor", "Labour availability rated {value}",
                  "Bring in a second gang or a labour subcontractor for the next two weeks."),
    "rework_q1": ("contractor", "Rework so far: {value}",
                  "Hold a quality walk-down on the activities with rework and fix the cause, not only the defect."),
    "mobilised_q1": ("contractor", "Mobilisation on time: {value}",
                     "Complete mobilisation of the missing plant and staff before the next IPC."),
    "site_handover": ("client", "Site handed over: {value}",
                      "Write to the Engineer to record the access restriction and ask for a date."),
    "utility_noc": ("client", "Utility relocation / NOC: {value}",
                    "Escalate the open NOC with the utility and copy the client; it is a client risk."),
}


def actions_for(explanation: dict, *, limit: int = 4, min_points: float = 0.5) -> list[dict]:
    """Reasons with owners and actions from the drivers that raise the forecast."""
    out = []
    for c in explanation.get("contributions", []):
        key, pts = c.get("key"), float(c.get("shap") or 0)
        if key not in TEMPLATES or not math.isfinite(pts) or pts < min_points:
            continue
        owner, reason, action = TEMPLATES[key]
        out.append({"key": key, "reason": reason.format(value=c.get("value") or "not given"),
                    "owner": owner, "owner_label": OWNER_LABEL[owner], "action": action,
                    "adds_pct_points": round(pts, 1)})
    out.sort(key=lambda a: -a["adds_pct_points"])
    return out[:limit]
