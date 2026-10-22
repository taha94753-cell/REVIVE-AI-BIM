"""MS Project XML import and the Monte Carlo criticality index (both ported from the REVIVE web app)."""
import numpy as np
import pytest

from revive.scheduling import Activity, cpm
from revive.schedule_import import mspdi_days, parse_mspdi
from revive.simulation import criticality

MSPDI = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <Title>Clinic block</Title><MinutesPerDay>480</MinutesPerDay>
  <Tasks>
    <Task><UID>0</UID><ID>0</ID><Name>Clinic block</Name><Summary>1</Summary></Task>
    <Task><UID>1</UID><ID>1</ID><Name>Structure</Name><Summary>1</Summary></Task>
    <Task><UID>2</UID><ID>2</ID><Name>Excavation</Name><Duration>PT80H0M0S</Duration></Task>
    <Task><UID>3</UID><ID>3</ID><Name>Footings concrete</Name><Duration>PT120H0M0S</Duration>
      <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type></PredecessorLink></Task>
    <Task><UID>4</UID><ID>4</ID><Name>Columns</Name><Duration>PT40H0M0S</Duration>
      <PredecessorLink><PredecessorUID>3</PredecessorUID><Type>3</Type><LinkLag>4800</LinkLag></PredecessorLink>
      <PredecessorLink><PredecessorUID>1</PredecessorUID><Type>1</Type></PredecessorLink></Task>
    <Task><UID>5</UID><ID>5</ID><Name>Handover</Name><Duration>PT0H0M0S</Duration><Milestone>1</Milestone>
      <PredecessorLink><PredecessorUID>4</PredecessorUID><Type>1</Type></PredecessorLink></Task>
    <Task><UID>6</UID><ID>6</ID><Name>Dropped scope</Name><Duration>PT8H0M0S</Duration><Active>0</Active></Task>
  </Tasks>
</Project>"""


def test_ms_project_xml_becomes_a_network():
    acts, rep = parse_mspdi(MSPDI)
    by = {a.id: a for a in acts}
    assert [a.name for a in acts] == ["Excavation", "Footings concrete", "Columns", "Handover"]
    assert by["2"].duration == 10 and by["3"].duration == 15 and by["5"].duration == 0
    assert by["3"].preds == ["2"] and by["4"].preds == ["3"] and by["5"].preds == ["4"]
    assert rep["format"] == "MS Project XML" and rep["project"] == "Clinic block"
    assert rep["skipped_summary"] == 1 and rep["skipped_inactive"] == 1 and rep["links_to_summary_dropped"] == 1
    assert rep["non_finish_to_start_treated_as_fs"] == 1 and rep["lags_ignored"] == 1
    assert by["3"].weather_sensitive and by["4"].weather_sensitive is False
    assert cpm(acts)["finish"] == rep["planned_days"] == 30


def test_ms_project_durations():
    assert mspdi_days("PT40H0M0S") == 5 and mspdi_days("PT4H30M0S") == 0.562 and mspdi_days("P2DT8H0M0S") == 3
    assert mspdi_days("PT45H0M0S", 540) == 5 and mspdi_days("garbage") == 0


@pytest.mark.parametrize("bad", [
    "<NotProject/>",
    "<Project xmlns='http://schemas.microsoft.com/project'><Tasks/></Project>",
    "not xml at all",
    # entity expansion ("billion laughs") is refused by defusedxml, never expanded
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
    "<Project><Title>&lol2;</Title></Project>",
])
def test_bad_ms_project_files_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_mspdi(bad)


def test_schedule_upload_accepts_ms_project_xml(client):
    from conftest import new_project
    p = new_project(client, "XML upload")
    r = client.post("/api/schedule/upload", headers={"X-Revive-Project": str(p["id"])},
                    files={"file": ("plan.xml", MSPDI.encode(), "application/xml")})
    assert r.status_code == 200, r.text
    assert r.json()["import_report"]["format"] == "MS Project XML"
    wrong = client.post("/api/schedule/upload", headers={"X-Revive-Project": str(p["id"])},
                        files={"file": ("plan.xml", b"<html>hello</html>", "application/xml")})
    assert wrong.status_code == 400


def test_criticality_counts_the_runs_an_activity_drives_the_finish():
    acts = [Activity("A", "A", "A", 1), Activity("B", "B", "B", 5, ["A"]), Activity("C", "C", "C", 1, ["A"]),
            Activity("D", "D", "D", 1, ["B", "C"])]
    idx = {a.id: i for i, a in enumerate(acts)}
    preds = {a.id: a.preds for a in acts}
    dur = np.tile(np.array([1, 5, 1, 1.0]), (100, 1))
    np.testing.assert_allclose(criticality(acts, set(idx), preds, 0, dur, idx), [1, 1, 0, 1])
    dur[:30, 2] = 9                                   # C takes over in 30 of 100 futures
    np.testing.assert_allclose(criticality(acts, set(idx), preds, 0, dur, idx), [1, .7, .3, 1])


def test_recovery_reports_what_drives_the_finish(client):
    from revive.presets import PRESETS
    p = PRESETS[0]
    pred = client.post("/api/predict", json={"inputs": p["inputs"], "gate": p["gate"]}).json()
    rec = client.post("/api/recovery", json={"gate": pred["gate"], "spi": p["inputs"]["spi_25"],
                                             "time_overrun_pct": pred["time_overrun_pct"],
                                             "high_risk_probability": pred["high_risk_probability"]}).json()
    drivers = rec["simulation"]["drivers"]
    assert drivers and all(0.05 <= d["criticality"] <= 1 for d in drivers)
    assert [d["criticality"] for d in drivers] == sorted((d["criticality"] for d in drivers), reverse=True)
