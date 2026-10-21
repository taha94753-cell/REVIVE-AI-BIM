from conftest import new_project

from revive import live
from revive.presets import PRESETS
from revive.recovery import run_recovery


def test_count_bands_round_trip():
    assert live.count_to_label("late_payments_q1", 0) == "0"
    assert live.count_to_label("late_payments_q1", 2.4) == "1-2"
    assert live.count_to_label("weather_days_q1", 11) == "11-30"
    assert live.count_to_label("variations_q1", 40) == "More than 10"
    assert live.label_to_count("late_payments_q1", "3-5") == 4


def test_update_changes_state_and_forecast():
    p = PRESETS[0]
    proj = live.create_project("Test hospital", p["inputs"], p["gate"])
    first = proj["updates"][0]["summary"]["time_overrun_pct"]
    msg = live.add_update(proj["id"], {"elapsed_pct": 34, "spi": 0.86, "events": {"late_payments": 2}})
    s = msg["update"]["summary"]
    assert s["elapsed_pct"] == 34 and s["spi"] == 0.86
    assert s["time_overrun_pct"] > first                 # late payments and lower SPI push the forecast up
    assert any("IPCs paid" in c for c in msg["update"]["changes"])
    later = live.add_update(proj["id"], {"elapsed_pct": 55, "spi": 0.84, "cpi": 0.9, "cert": 38})
    assert later["update"]["summary"]["gate"] == "G50"   # past halfway the 50% model takes over
    assert len(live.get_project(proj["id"])["updates"]) == 3


def test_time_cannot_run_backwards():
    p = PRESETS[1]
    proj = live.create_project("Plaza", p["inputs"], p["gate"])
    msg = live.add_update(proj["id"], {"elapsed_pct": 10})
    assert msg["update"]["summary"]["elapsed_pct"] == 50


def test_monte_carlo_plan_improves_finish():
    r = run_recovery("G25", 0.91, 50.0, 0.8)
    sim = r["simulation"]
    assert sim["p80_after_day"] <= sim["p80_before_day"]
    assert sim["p50_before_day"] <= sim["p80_before_day"]
    assert 0 <= sim["p_on_time_before"] <= sim["p_on_time_after"] <= 1


def _monitor(c, preset=0, name="Carriageway"):
    proj = new_project(c, name)
    p = PRESETS[preset]
    lp = c.post("/api/live", json={"name": name, "inputs": p["inputs"], "gate": p["gate"]},
                headers={"X-Revive-Project": str(proj["id"])}).json()
    return proj, lp


def test_live_api_token_links_and_qr(client):
    proj, lp = _monitor(client)
    path = lp["site_path"]
    token = path.rsplit("/", 1)[1]
    assert len(token) >= 20 and str(lp["id"]) != token          # capability token, not the row id
    assert lp["site_url"].endswith(path) and "site_token" not in lp
    r = client.post(f"/api/site/{token}/update", json={"elapsed_pct": 60, "events": {"material_events": 1}})
    assert r.status_code == 200 and r.json()["update"]["summary"]["elapsed_pct"] == 60
    assert client.post(f"/api/site/{token}/update", json={"spi": 5}).status_code == 400
    assert client.post(f"/api/site/{token}/update", json={"events": {"bogus": 1}}).status_code == 422
    qr = client.get(f"/api/live/{lp['id']}/qr.svg")
    assert qr.status_code == 200 and b"xmlns" in qr.content
    assert client.get(path).status_code == 200
    assert client.get(f"/site/{lp['id']}").status_code == 404                 # a sequential id is not a link
    # a second start on the same project is refused, not duplicated
    again = client.post("/api/live", json={"inputs": PRESETS[0]["inputs"]}, headers={"X-Revive-Project": str(proj["id"])})
    assert again.status_code == 409 and again.json()["live_id"] == lp["id"]


def test_rotating_the_link_revokes_the_old_one(client):
    proj, lp = _monitor(client, 1, "Rotate")
    old = lp["site_path"].rsplit("/", 1)[1]
    new = client.post(f"/api/projects/{proj['id']}/site-link").json()["site_url"].rsplit("/", 1)[1]
    assert new != old
    assert client.post(f"/api/site/{old}/update", json={"elapsed_pct": 30}).status_code == 404
    assert client.post(f"/api/site/{new}/update", json={"elapsed_pct": 30}).status_code == 200


def test_catch_up_returns_missed_updates_in_stream_shape(client):
    """A dashboard that missed an update (Wi-Fi drop, sleep) gets it back from /updates?after=<id>."""
    _, lp = _monitor(client, 0, "Catch-up")
    tok = lp["site_path"].rsplit("/", 1)[1]
    first_id = lp["updates"][-1]["id"]
    client.post(f"/api/site/{tok}/update", json={"elapsed_pct": 35, "spi": 0.8})
    client.post(f"/api/site/{tok}/update", json={"elapsed_pct": 40, "events": {"variations": 2}})
    ups = client.get(f"/api/live/{lp['id']}/updates", params={"after": first_id}).json()
    assert [u["update"]["summary"]["elapsed_pct"] for u in ups] == [35, 40]
    assert {"project_id", "project_name", "update", "inputs", "prediction"} <= set(ups[0])
    last = ups[-1]["update"]["id"]
    assert client.get(f"/api/live/{lp['id']}/updates", params={"after": last}).json() == []
    assert client.get("/api/live/99999/updates").status_code == 404


def test_presence_and_site_links(client):
    _, lp = _monitor(client, 1, "Presence")
    tok = lp["site_path"].rsplit("/", 1)[1]
    r = client.post(f"/api/site/{tok}/presence", json={"device": "abc123", "label": "An Android phone"}).json()
    assert r["devices"] == 1 and r["first"] is True
    assert client.post(f"/api/site/{tok}/presence", json={"device": "abc123"}).json()["first"] is False
    assert client.get(f"/api/live/{lp['id']}").json()["site_devices"] == 1
    base = lp["site_urls"][0].rsplit("/site/", 1)[0]
    assert client.get(f"/api/live/{lp['id']}/qr.svg", params={"base": base}).status_code == 200
    assert client.post("/api/site/not-a-real-token/presence", json={"device": "x"}).status_code == 404


def test_broker_keeps_companies_apart():
    import asyncio

    async def run():
        b = live.Broker()
        dash_a = b.subscribe(live.company_channel(1))     # company 1's dashboard
        dash_b = b.subscribe(live.company_channel(2))     # company 2's dashboard
        phone = b.subscribe(7, site=True)                 # the phone page of project 7 (company 1)
        assert b.listeners(7, 1) == 1
        assert b.publish(7, {"x": 1}, company_id=1) == 1  # delivered to company 1's dashboard and the phone
        assert (await dash_a.get())[0] == "update" and (await phone.get())[1] == {"x": 1}
        assert dash_b.empty()                             # company 2 never sees it
        b.unsubscribe(7, phone)
        assert b.listeners(7, 1) == 1
        for i in range(80):                               # device table is bounded
            b.seen(7, f"dev{i}", {"label": "x"})
        assert b.device_count(7) <= live.MAX_DEVICES
    asyncio.run(run())


def test_ping_and_lan_addresses(client):
    d = client.get("/api/ping").json()
    assert d["app"] == "REVIVE" and d["status"] == "ok"
    assert client.get("/").headers.get("cache-control") == "no-cache"   # never run a stale page
    ips = live.lan_ips()
    assert all(ip.count(".") == 3 and not ip.startswith("127.") for ip in ips)
