from revive.bim import BimModel
from revive.config import path, load_config
from revive.scheduling import load_schedule


def test_demo_model_quantities_and_links():
    bim = BimModel(path(load_config()["bim"]["ifc_file"]))
    q = bim.quantities(load_schedule(path(load_config()["bim"]["schedule_file"])))
    assert q["elements"] == 288
    assert q["mapped_elements"] == 288
    assert q["storeys_above_ground"] == 4
    assert abs(q["gross_floor_area_m2"] - 4 * 24.6 * 18.6) < 1.0
