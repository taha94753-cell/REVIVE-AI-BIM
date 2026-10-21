"""
BIM layer (IfcOpenShell).

BIM -> AI   quantities read from the model become model inputs:
            gross floor area and storey count fill the prediction form, and the
            schedule's planned duration comes from the WBS network linked to the model.
AI -> BIM   every element is linked to a schedule activity (WBS_Code property,
            or storey + IFC class rule). Forecast float, criticality, risk score
            and recovery crash days are computed per activity, drawn on the 3D
            model, and written back into the IFC as a property set
            (Pset_REVIVE_Risk) that opens in Revit, Navisworks or any IFC viewer.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.pset
import ifcopenshell.geom
import ifcopenshell.util.element as uel

from .config import ROOT, active_file, load_config, path
from .scheduling import Activity

SKIP = {"IfcOpeningElement", "IfcSpace", "IfcSite", "IfcBuilding", "IfcBuildingStorey",
        "IfcAnnotation", "IfcGrid", "IfcVirtualElement"}


def _file_hash(p: Path) -> str:
    # SHA-256, not MD5: the hash keys a geometry cache shared by every company, so it must be collision-resistant
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:32]


def active_ifc_path() -> Path | None:
    return active_file("ifc")


def _storey_of(el) -> str:
    c = uel.get_container(el)
    seen = 0
    while c is not None and not c.is_a("IfcBuildingStorey") and seen < 5:
        c = uel.get_aggregate(c) or uel.get_container(c)
        seen += 1
    return c.Name if c is not None and c.is_a("IfcBuildingStorey") else "Unassigned"


def _wbs_of(el, prop: str) -> str | None:
    target = prop.lower()
    for props in uel.get_psets(el).values():
        for k, v in props.items():
            if k.lower() == target and v not in (None, ""):
                return str(v).strip()
    return None


def _material_of(el) -> str:
    try:
        m = uel.get_material(el, should_skip_usage=True)
    except TypeError:
        m = uel.get_material(el)
    if m is None:
        return ""
    for attr in ("Name", "LayerSetName", "MaterialProfileSet"):
        if getattr(m, attr, None):
            return str(getattr(m, attr))
    return m.is_a()


def _mesh_stats(verts: np.ndarray, faces: np.ndarray) -> tuple[float, float]:
    """(closed-mesh volume, area of upward-facing triangles)."""
    if len(faces) == 0:
        return 0.0, 0.0
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    vol = abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1) / 2.0
    nz = np.divide(n[:, 2], 2 * area, out=np.zeros_like(area), where=area > 0)
    return float(vol), float(area[nz > 0.9].sum())


class BimModel:
    def __init__(self, ifc_path: Path | None = None):
        ifc_path = ifc_path or active_ifc_path()
        if ifc_path is None:
            raise FileNotFoundError("No BIM model is connected")
        self.path = Path(ifc_path)
        self.hash = _file_hash(self.path)
        self.ifc = ifcopenshell.open(str(self.path))
        prop = load_config()["bim"]["wbs_property"]
        self.elements = {}
        for el in self.ifc.by_type("IfcProduct"):
            if el.is_a() in SKIP or not el.Representation:
                continue
            self.elements[el.GlobalId] = {
                "guid": el.GlobalId, "ifc_class": el.is_a(), "name": el.Name or el.is_a(),
                "storey": _storey_of(el), "wbs": _wbs_of(el, prop), "material": _material_of(el),
                "predefined": str(getattr(el, "PredefinedType", "") or ""),
            }
        self._geom = None

    # ------------------------------------------------------------------
    def geometry(self) -> dict:
        if self._geom is not None:
            return self._geom
        cache = path(load_config()["bim"]["cache_dir"]) / f"geom_{self.hash}.json"
        if cache.exists():
            self._geom = json.loads(cache.read_text())
            return self._geom
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        it = ifcopenshell.geom.iterator(settings, self.ifc, max(1, multiprocessing.cpu_count() - 1))
        meshes, lo, hi = [], np.full(3, np.inf), np.full(3, -np.inf)
        if it.initialize():
            while True:
                sh = it.get()
                if sh.guid in self.elements:
                    v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
                    f = np.asarray(sh.geometry.faces, dtype=int).reshape(-1, 3)
                    if len(v):
                        vol, up = _mesh_stats(v, f)
                        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
                        meshes.append({"guid": sh.guid, "verts": np.round(v, 3).ravel().tolist(),
                                       "faces": f.ravel().tolist(), "volume": round(vol, 4),
                                       "up_area": round(up, 3), "zmin": round(float(v[:, 2].min()), 3)})
                if not it.next():
                    break
        self._geom = {"file": self.path.name, "hash": self.hash, "meshes": meshes,
                      "bounds": {"min": lo.round(3).tolist(), "max": hi.round(3).tolist()}}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(self._geom))
        return self._geom

    # ------------------------------------------------------------------
    def storeys(self) -> list[dict]:
        out = []
        for st in self.ifc.by_type("IfcBuildingStorey"):
            out.append({"name": st.Name, "elevation": float(st.Elevation or 0.0)})
        return sorted(out, key=lambda s: s["elevation"])

    def mapping(self, acts: list[Activity]) -> dict[str, str | None]:
        ids = {a.id for a in acts}
        by_wbs = {a.wbs: a.id for a in acts}
        result = {}
        for guid, e in self.elements.items():
            act = None
            if e["wbs"]:
                act = e["wbs"] if e["wbs"] in ids else by_wbs.get(e["wbs"])
            if act is None:
                for a in acts:
                    if not a.ifc_types:
                        continue
                    storeys = [s.strip() for s in a.ifc_storey.split(";") if s.strip()] or ["*"]
                    cls_ok = any(e["ifc_class"] == t or e["ifc_class"].startswith(t) for t in a.ifc_types)
                    st_ok = "*" in storeys or e["storey"] in storeys
                    if cls_ok and st_ok:
                        act = a.id
                        break
            result[guid] = act
        return result

    def quantities(self, acts: list[Activity] | None = None) -> dict:
        g = self.geometry()
        cfg = load_config()["bim"]
        by_guid = {m["guid"]: m for m in g["meshes"]}
        floor_area, concrete = 0.0, 0.0
        for guid, e in self.elements.items():
            m = by_guid.get(guid)
            if not m:
                continue
            roofish = e["predefined"].upper() == "ROOF" or "roof" in e["storey"].lower()
            if e["ifc_class"] == "IfcSlab" and not roofish:
                floor_area += m["up_area"]
            mat = e["material"].lower()
            if "concrete" in mat or (not mat and e["ifc_class"] in cfg["concrete_classes"]):
                concrete += m["volume"]
        storeys = [s for s in self.storeys() if s["elevation"] >= -0.01 and "roof" not in (s["name"] or "").lower()]
        counts: dict[str, int] = {}
        for e in self.elements.values():
            counts[e["ifc_class"]] = counts.get(e["ifc_class"], 0) + 1
        out = {"file": self.path.name, "elements": len(self.elements), "element_counts": counts,
               "storeys_above_ground": len(storeys), "gross_floor_area_m2": round(floor_area, 1),
               "concrete_m3": round(concrete, 1),
               "rebar_t_estimate": round(concrete * load_config()["sustainability"]["rebar_kg_per_m3_concrete"] / 1000, 1)}
        if acts is not None:
            mp = self.mapping(acts)
            out["mapped_elements"] = sum(1 for v in mp.values() if v)
            out["unmapped_elements"] = sum(1 for v in mp.values() if not v)
            out["mapping_source"] = "WBS_Code property" if any(e["wbs"] for e in self.elements.values()) else "storey + IFC class rules"
        return out

    # ------------------------------------------------------------------
    def export_with_risk(self, element_props: dict[str, dict], label: str = "", out_dir: Path | None = None) -> Path:
        """Write Pset_REVIVE_Risk onto each element and save a new IFC file (in the company's own folder)."""
        model = ifcopenshell.open(str(self.path))
        for guid, props in element_props.items():
            try:
                el = model.by_guid(guid)
            except RuntimeError:
                continue
            pset = ifcopenshell.api.pset.add_pset(model, product=el, name="Pset_REVIVE_Risk")
            ifcopenshell.api.pset.edit_pset(model, pset=pset, properties=props)
        out_dir = Path(out_dir) if out_dir else ROOT / "models" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        # one fixed file per project folder, overwritten each export, so repeated exports cannot grow the disk
        dest = out_dir / f"{self.path.stem}_REVIVE_risk.ifc"
        model.write(str(dest))
        return dest


_MODELS: "OrderedDict[str, BimModel]" = OrderedDict()   # small cache: one model per project file
_LOCK = threading.Lock()


def get_bim(reload: bool = False) -> BimModel | None:
    """The BIM model of the current project scope, or None when it runs on the schedule alone.
    Models are cached by path (the last few projects), so switching projects stays fast."""
    p = active_ifc_path()
    if p is None:
        return None
    key = str(Path(p).resolve())
    with _LOCK:
        if not reload and key in _MODELS:
            _MODELS.move_to_end(key)
            return _MODELS[key]
    try:
        model = BimModel(p)
    except Exception as exc:  # a broken upload must never take the app down: run on the schedule
        print(f"[REVIVE] BIM model {Path(p).name} could not be opened ({exc.__class__.__name__}); "
              "running on the baseline schedule only.")
        return None
    with _LOCK:
        _MODELS[key] = model
        while len(_MODELS) > 4:
            _MODELS.popitem(last=False)
    return model


def forget(p: Path | str) -> None:
    """Drop a cached model (after its file is replaced or deleted)."""
    with _LOCK:
        _MODELS.pop(str(Path(p).resolve()), None)
