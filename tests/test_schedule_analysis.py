"""Schedule analysis (S-curves, earned value, resources, quality) and progress updates against a fixed baseline."""
import io

import pytest

from revive import schedule_analysis as sa
from revive.schedule_import import _mspdi_full, _xer_full
from revive.scheduling import Activity, cpm

from conftest import new_project


def xer(progress: bool = False, extra_task: bool = False) -> str:
    """Three activities in a chain, 10 days each, budget 100 / 200 / 100, two resources."""
    st = (("TK_Complete", 0, 100), ("TK_Active", 40, 50), ("TK_NotStart", 80, 0)) if progress else (("TK_NotStart", 80, 0),) * 3
    rows = ["ERMHDR\t19.12", "%T\tPROJECT", "%F\tproj_id\tlast_recalc_date\tplan_start_date",
            f"%R\t1\t{'2026-01-21 00:00' if progress else '2026-01-01 00:00'}\t2026-01-01 00:00",
            "%T\tRSRC", "%F\trsrc_id\trsrc_name\trsrc_type", "%R\t1\tMason\tRT_Labor", "%R\t2\tCement\tRT_Mat",
            "%T\tTASK", "%F\ttask_id\ttask_code\ttask_name\ttask_type\ttarget_drtn_hr_cnt\tremain_drtn_hr_cnt\tstatus_code"
            "\tcomplete_pct_type\tphys_complete_pct\ttarget_start_date\ttarget_end_date"]
    for i, (code, (status, remain, phys)) in enumerate(zip("ABC", st), start=1):
        rows.append(f"%R\t{i}\t{code}\tActivity {code}\tTT_Task\t80\t{remain}\t{status}\tCP_Phys\t{phys}"
                    f"\t2026-01-{1 + 10 * (i - 1):02d} 08:00\t2026-01-{10 * i:02d} 17:00")
    if extra_task:
        rows.append("%R\t4\tD\tNew scope\tTT_Task\t40\t40\tTK_NotStart\tCP_Phys\t0\t2026-01-31 08:00\t2026-02-04 17:00")
    rows += ["%T\tTASKPRED", "%F\ttask_id\tpred_task_id\tpred_type\tlag_hr_cnt", "%R\t2\t1\tPR_FS\t0", "%R\t3\t2\tPR_FS\t0",
             "%T\tTASKRSRC", "%F\ttask_id\trsrc_id\ttarget_qty\ttarget_cost\tact_reg_qty\tact_ot_qty\tact_reg_cost\tact_ot_cost\tremain_qty",
             f"%R\t1\t1\t80\t100\t{80 if progress else 0}\t0\t{125 if progress else 0}\t0\t0",
             f"%R\t2\t1\t160\t150\t{80 if progress else 0}\t0\t{125 if progress else 0}\t0\t80",
             "%R\t2\t2\t50\t50\t0\t0\t0\t0\t50", "%R\t3\t1\t80\t100\t0\t0\t0\t0\t80", "%E"]
    return "\n".join(rows) + "\n"


def test_xer_carries_cost_resources_and_progress():
    acts, _, base = _xer_full(xer())
    assert [a.id for a in acts] == ["A", "B", "C"] and cpm(acts)["finish"] == 30
    assert base["activities"]["B"]["budget"] == 200 and base["start"] == "2026-01-01" and base["finish"] == "2026-01-30"
    assert {r["name"]: r["type"] for r in base["activities"]["B"]["resources"]} == {"Mason": "labour", "Cement": "material"}
    _, _, upd = _xer_full(xer(progress=True))
    assert upd["data_date"] == "2026-01-21"
    assert [upd["activities"][k]["pct"] for k in "ABC"] == [100, 50, 0]
    assert upd["activities"]["A"]["actual_cost"] == 125


def test_earned_value_from_a_cost_loaded_schedule():
    acts, _, base = _xer_full(xer())
    _, _, upd = _xer_full(xer(progress=True))
    w, basis, bac = sa.weights(acts, base)
    assert basis == "cost" and bac == 400
    pct = {k: v["pct"] for k, v in upd["activities"].items()}
    actual = {k: v["actual_cost"] for k, v in upd["activities"].items()}
    st = sa.status(acts, cpm(acts), w, basis, bac, pct, actual, elapsed_pct=50)     # day 15 of 30
    # PV at day 15 = 100 + 200 x 0.5 = 200; EV = 100 + 200 x 0.5 = 200; AC = 250
    assert st["pv"] == 200 and st["ev"] == 200 and st["ac"] == 250
    assert st["spi"] == 1.0 and st["cpi"] == 0.8 and st["cv"] == -50 and st["eac"] == 500
    late = sa.status(acts, cpm(acts), w, basis, bac, pct, actual, elapsed_pct=70)   # day 21: plan = 100 + 200 + 10
    assert late["spi"] == round(200 / 310, 3) and late["sv_days"] == -6.0


def test_no_cost_loading_means_no_cpi_and_says_why():
    acts = [Activity("A", "Dig", "A", 10), Activity("B", "Pour", "B", 10, preds=["A"])]
    w, basis, bac = sa.weights(acts, None)
    st = sa.status(acts, cpm(acts), w, basis, bac, {"A": 100, "B": 0}, {}, elapsed_pct=75)
    assert basis == "duration" and st["cpi"] is None and "not cost-loaded" in st["cpi_reason"]
    assert st["spi"] == round(0.5 / 0.75, 3)


def test_resources_spread_over_periods_and_curves_form_a_banana():
    acts, _, base = _xer_full(xer())
    out = sa.analyse({"loading": base, "details": {"planned_months": 3}}, acts)
    mason = next(r for r in out["resources"]["rows"] if r["name"] == "Mason")
    assert out["periods"] == 3 and mason["by_period"] == [80, 160, 80] and mason["peak_period"] == 2
    assert out["resources"]["materials"] == [{"name": "Cement", "units": 50}]
    assert out["cash_flow"]["early"] == [100, 200, 100]
    assert all(e >= l - 1e-9 for e, l in zip(out["curve"]["early_pct"], out["curve"]["late_pct"]))
    assert out["status"] is None and out["quality"]["checks"][0]["value"] == 0


def test_quality_flags_open_ends():
    acts = [Activity("A", "a", "A", 5), Activity("B", "b", "B", 5, preds=["A"]), Activity("C", "c", "C", 5),
            Activity("D", "d", "D", 5)]
    q = sa.quality(acts, cpm(acts))
    assert q["checks"][0]["value"] == 4 and not q["checks"][0]["ok"]      # two extra starts and two extra finishes


MSPDI_COST = """<?xml version="1.0"?><Project xmlns="http://schemas.microsoft.com/project">
  <MinutesPerDay>480</MinutesPerDay><StartDate>2026-01-01T08:00:00</StartDate><StatusDate>2026-01-11T17:00:00</StatusDate>
  <Tasks>
    <Task><UID>1</UID><ID>1</ID><Name>Dig</Name><Duration>PT80H0M0S</Duration><Cost>1000000</Cost><ActualCost>600000</ActualCost>
      <PercentComplete>50</PercentComplete><Start>2026-01-01T08:00:00</Start><Finish>2026-01-10T17:00:00</Finish></Task>
    <Task><UID>2</UID><ID>2</ID><Name>Pour</Name><Duration>PT80H0M0S</Duration><Cost>1000000</Cost><PercentComplete>0</PercentComplete>
      <Start>2026-01-11T08:00:00</Start><Finish>2026-01-20T17:00:00</Finish>
      <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type></PredecessorLink></Task>
  </Tasks>
  <Resources><Resource><UID>1</UID><Name>Excavator</Name><Type>1</Type></Resource></Resources>
  <Assignments><Assignment><TaskUID>1</TaskUID><ResourceUID>1</ResourceUID><Work>PT80H0M0S</Work><Cost>400000</Cost></Assignment></Assignments>
</Project>"""


def test_ms_project_cost_is_divided_by_100():
    _, _, load = _mspdi_full(MSPDI_COST)
    a = load["activities"]["1"]
    assert a["budget"] == 10000 and a["actual_cost"] == 6000 and a["pct"] == 50 and load["data_date"] == "2026-01-11"
    assert a["resources"] == [{"name": "Excavator", "type": "labour", "units": 80, "cost": 4000}]


def _upload(c, url, text, name="plan.xer", **data):
    return c.post(url, files={"file": (name, io.BytesIO(text.encode()), "application/octet-stream")}, data=data)


def test_updates_are_snapshots_against_a_fixed_baseline(client, other):
    p = new_project(client, start_date="2026-01-01", details={"planned_months": 1})
    hdr = {"X-Revive-Project": str(p["id"])}
    r = client.post("/api/schedule/upload", files={"file": ("plan.xer", io.BytesIO(xer().encode()), "application/octet-stream")}, headers=hdr)
    assert r.status_code == 200, r.text
    url = f"/api/projects/{p['id']}"
    a = client.get(f"{url}/schedule-analysis").json()
    assert a["basis"] == "cost" and a["bac"] == 400 and a["status"] is None and a["has_loading"]

    r = _upload(client, f"{url}/schedule-update", xer(progress=True, extra_task=True), elapsed_pct=50)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"]["as_of"] == "2026-01-21" and a["status"]["cpi"] == 0.8 and a["status"]["spi"] == 1.0
    assert a["status"]["compare"]["added"] == 1 and any("differs from the baseline" in n for n in a["notes"])
    assert a["suggested_inputs"] == {"gate": "G50", "as_of": "2026-01-21", "inputs": {"spi_50": 1.0, "cpi_50": 0.8}}
    # the baseline is untouched and the current delay analysis now runs on the update
    assert len(client.get("/api/schedule", headers=hdr).json()) == 3
    d = client.get(f"{url}/delay").json()
    assert d["available"] and d["source"].startswith("Activity progress")

    # the same status date replaces its snapshot; another company cannot see or change any of it
    assert len(_upload(client, f"{url}/schedule-update", xer(progress=True), elapsed_pct=60).json()["history"]) == 1
    assert other.get(f"{url}/schedule-analysis").status_code == 404
    assert _upload(other, f"{url}/schedule-update", xer(progress=True), elapsed_pct=50).status_code == 404
    assert other.delete(f"{url}/schedule-update/0").status_code == 404

    a = client.delete(f"{url}/schedule-update/0").json()
    assert a["history"] == [] and client.get(f"{url}/activities").json()["progress"] is None


@pytest.mark.parametrize("text, name, why", [
    (xer(), "plan.xer", "no progress"),
    (xer(progress=True).replace("\tA\t", "\tX1\t").replace("\tB\t", "\tX2\t").replace("\tC\t", "\tX3\t"), "plan.xer", "match the baseline"),
    ("not a schedule", "plan.xer", "not a Primavera"),
], ids=["no-progress", "other-programme", "not-a-schedule"])
def test_bad_updates_are_refused(client, text, name, why):
    p = new_project(client)
    hdr = {"X-Revive-Project": str(p["id"])}
    assert client.post("/api/schedule/upload", files={"file": ("plan.xer", io.BytesIO(xer().encode()), "application/octet-stream")}, headers=hdr).status_code == 200
    r = _upload(client, f"/api/projects/{p['id']}/schedule-update", text, name=name, elapsed_pct=50)
    assert r.status_code == 400 and why in r.text
