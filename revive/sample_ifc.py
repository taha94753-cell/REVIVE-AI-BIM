"""
Builds an ILLUSTRATIVE IFC4 model (G+3 reinforced-concrete frame, 24 m x 18 m) so the
product runs before your Revit case-study model is ready.

Replace it with your own model: export IFC4 from Revit (Coordination View), add a
shared parameter named WBS_Code to every element (values = activity ids in
bim/schedule.csv, e.g. "A06"), tick "Export user defined property sets", and upload
the file in the dashboard or set bim.ifc_file in config.yaml.

Every element here carries Pset "REVIVE_WBS" -> WBS_Code, exactly the property a
Revit export would carry.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial

GRID_X = [0.0, 6.0, 12.0, 18.0, 24.0]
GRID_Y = [0.0, 6.0, 12.0, 18.0]
LEVELS = [("Ground", 0.0), ("Level 1", 3.6), ("Level 2", 7.0), ("Level 3", 10.4), ("Roof", 13.8)]
COL, BEAM_B, BEAM_H, SLAB_T, WALL_T = 0.45, 0.30, 0.60, 0.15, 0.23


def _box(model, ctx, dx, dy, dz):
    origin = model.createIfcCartesianPoint((0.0, 0.0, 0.0))
    profile = model.createIfcRectangleProfileDef(
        "AREA", None, model.createIfcAxis2Placement2D(model.createIfcCartesianPoint((dx / 2, dy / 2))), dx, dy)
    solid = model.createIfcExtrudedAreaSolid(profile, model.createIfcAxis2Placement3D(origin),
                                             model.createIfcDirection((0.0, 0.0, 1.0)), dz)
    return model.createIfcShapeRepresentation(ctx, "Body", "SweptSolid", [solid])


def build(dest: str | Path) -> Path:
    model = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="REVIVE demo project")
    units = [model.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
             model.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
             model.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE")]
    project.UnitsInContext = model.createIfcUnitAssignment(units)
    model_ctx = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(model, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model_ctx)

    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Demo site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding",
                                                   name="G+3 RC frame (illustrative model)")
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)

    storeys = {}
    for name, z in [("Foundation", -1.6)] + LEVELS:
        st = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name=name)
        st.Elevation = z
        ifcopenshell.api.aggregate.assign_object(model, products=[st], relating_object=building)
        storeys[name] = st

    concrete = ifcopenshell.api.material.add_material(model, name="Concrete C25/30", category="concrete")
    brick = ifcopenshell.api.material.add_material(model, name="Brick masonry", category="brick")
    screed = ifcopenshell.api.material.add_material(model, name="Screed and tiles", category="finishes")
    membrane = ifcopenshell.api.material.add_material(model, name="Bituminous membrane", category="waterproofing")

    def add(ifc_class, name, storey, wbs, xyz, size, mat, predefined=None):
        el = ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=name, predefined_type=predefined)
        ifcopenshell.api.geometry.assign_representation(model, product=el, representation=_box(model, body, *size))
        m = np.eye(4)
        m[:3, 3] = xyz
        ifcopenshell.api.geometry.edit_object_placement(model, product=el, matrix=m)
        ifcopenshell.api.spatial.assign_container(model, products=[el], relating_structure=storeys[storey])
        ifcopenshell.api.material.assign_material(model, products=[el], type="IfcMaterial", material=mat)
        pset = ifcopenshell.api.pset.add_pset(model, product=el, name="REVIVE_WBS")
        ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"WBS_Code": wbs})
        return el

    # foundations
    for i, x in enumerate(GRID_X):
        for j, y in enumerate(GRID_Y):
            add("IfcFooting", f"Pad footing {i + 1}{chr(65 + j)}", "Foundation", "A03",
                (x - 1.0, y - 1.0, -1.6), (2.0, 2.0, 0.6), concrete, "PAD_FOOTING")
    add("IfcSlab", "Ground slab on grade", "Ground", "A04", (-0.3, -0.3, -SLAB_T),
        (GRID_X[-1] + 0.6, GRID_Y[-1] + 0.6, SLAB_T), concrete, "BASESLAB")

    col_wbs = {"Ground": "A05", "Level 1": "A07", "Level 2": "A09", "Level 3": "A11"}
    frame_wbs = {"Level 1": "A06", "Level 2": "A08", "Level 3": "A10", "Roof": "A12"}
    wall_wbs = {"Ground": "A13", "Level 1": "A14", "Level 2": "A15", "Level 3": "A16"}
    finish_wbs = {"Ground": "A19", "Level 1": "A19", "Level 2": "A20", "Level 3": "A20"}

    for k in range(len(LEVELS) - 1):
        name, z0 = LEVELS[k]
        z1 = LEVELS[k + 1][1]
        up_name = LEVELS[k + 1][0]
        # columns of this storey
        for i, x in enumerate(GRID_X):
            for j, y in enumerate(GRID_Y):
                add("IfcColumn", f"Column {i + 1}{chr(65 + j)} {name}", name, col_wbs[name],
                    (x - COL / 2, y - COL / 2, z0), (COL, COL, z1 - z0 - SLAB_T), concrete, "COLUMN")
        # beams and slab that form the floor above
        for j, y in enumerate(GRID_Y):
            for i in range(len(GRID_X) - 1):
                add("IfcBeam", f"Beam {up_name} {chr(65 + j)}{i + 1}-{i + 2}", up_name, frame_wbs[up_name],
                    (GRID_X[i], y - BEAM_B / 2, z1 - BEAM_H), (GRID_X[i + 1] - GRID_X[i], BEAM_B, BEAM_H - SLAB_T),
                    concrete, "BEAM")
        for i, x in enumerate(GRID_X):
            for j in range(len(GRID_Y) - 1):
                add("IfcBeam", f"Beam {up_name} {i + 1}{chr(65 + j)}-{chr(66 + j)}", up_name, frame_wbs[up_name],
                    (x - BEAM_B / 2, GRID_Y[j], z1 - BEAM_H), (BEAM_B, GRID_Y[j + 1] - GRID_Y[j], BEAM_H - SLAB_T),
                    concrete, "BEAM")
        add("IfcSlab", f"Slab {up_name}", up_name, frame_wbs[up_name], (-0.3, -0.3, z1 - SLAB_T),
            (GRID_X[-1] + 0.6, GRID_Y[-1] + 0.6, SLAB_T), concrete, "ROOF" if up_name == "Roof" else "FLOOR")
        # perimeter infill walls (entrance left open on the ground floor)
        h = z1 - z0 - BEAM_H
        for i in range(len(GRID_X) - 1):
            for y, side in ((GRID_Y[0], "south"), (GRID_Y[-1], "north")):
                if name == "Ground" and side == "south" and i in (1, 2):
                    continue
                add("IfcWall", f"Wall {name} {side} bay {i + 1}", name, wall_wbs[name],
                    (GRID_X[i] + COL / 2, y - WALL_T / 2, z0), (GRID_X[i + 1] - GRID_X[i] - COL, WALL_T, h),
                    brick, "SOLIDWALL")
        for j in range(len(GRID_Y) - 1):
            for x, side in ((GRID_X[0], "west"), (GRID_X[-1], "east")):
                add("IfcWall", f"Wall {name} {side} bay {j + 1}", name, wall_wbs[name],
                    (x - WALL_T / 2, GRID_Y[j] + COL / 2, z0), (WALL_T, GRID_Y[j + 1] - GRID_Y[j] - COL, h),
                    brick, "SOLIDWALL")
        # floor finish on this storey
        add("IfcCovering", f"Floor finish {name}", name, finish_wbs[name], (0.4, 0.4, z0),
            (GRID_X[-1] - 0.8, GRID_Y[-1] - 0.8, 0.05), screed, "FLOORING")
    add("IfcCovering", "Roof waterproofing", "Roof", "A17", (-0.2, -0.2, LEVELS[-1][1]),
        (GRID_X[-1] + 0.4, GRID_Y[-1] + 0.4, 0.08), membrane, "ROOFING")

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(dest))
    return dest


if __name__ == "__main__":  # pragma: no cover
    print(build(Path(__file__).resolve().parent.parent / "bim" / "sample_building.ifc"))
