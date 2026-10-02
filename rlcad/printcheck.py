"""Print audit of the STL files a slicer will receive (FDM, 0.4 mm nozzle by default).

For each part, in the orientation it is exported in:

  watertight   the mesh is closed and consistently oriented (a slicer needs a volume)
  thickness    local wall thickness, by casting a ray inward from each triangle; areas thinner than two
               extrusion lines (0.8 mm) print as a single weak line or not at all
  edges        knife edges (thickness under one line width) are listed separately: they vanish in the slice
  overhang     downward-facing area steeper than the overhang limit (45° from vertical by default) that is
               above the bed: it needs support or it sags. Short flat spans between walls (bridges, <= 30 mm),
               small isolated patches (< 25 mm²) and narrow ledges (mean width <= 2.5 mm) print without support
               and are not counted
  bed          contact area on the first layer; small contact with a tall part tends to detach
  islands      regions that start in mid-air (the lowest point of a separate surface patch above the bed)

Thresholds are the usual FDM rules of thumb (Prusa/Bambu design guides): 2 perimeters ≈ 0.8–0.9 mm minimum wall,
45° overhang without support, first-layer contact large enough for the part's height.
"""
from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

NOZZLE = 0.4


def audit_mesh(tm, nozzle: float = NOZZLE, overhang_deg: float = 45.0, name: str = "",
               max_bridge: float = 30.0, small_overhang: float = 25.0, ledge: float = 2.5) -> Dict:
    import trimesh
    res: Dict = {"name": name}
    res["watertight"] = bool(tm.is_watertight)
    res["winding_ok"] = bool(tm.is_winding_consistent)
    res["volume_cm3"] = round(float(tm.volume) / 1000, 2) if tm.is_volume else None
    area = tm.area_faces
    normals = tm.face_normals
    centres = tm.triangles_center
    zmin = float(tm.bounds[0][2])

    # --- thickness: ray from just inside each face, along -normal, to the next hit
    origins = centres - normals * 1e-3
    dirs = -normals
    try:
        from trimesh.ray.ray_pyembree import RayMeshIntersector  # noqa: F401  (fast if available)
    except Exception:
        pass
    thick = np.full(len(tm.faces), np.inf)
    step = 2000                                   # batches keep the ray-tree memory bounded on big parts
    for k in range(0, len(origins), step):
        o, dd = origins[k:k + step], dirs[k:k + step]
        locs, idx_ray, _ = tm.ray.intersects_location(o, dd, multiple_hits=False)
        if len(idx_ray):
            thick[k + idx_ray] = np.linalg.norm(locs - o[idx_ray], axis=1)
    min_wall = 2 * nozzle
    thin = thick < min_wall
    knife = thick < nozzle
    res["thin_area_mm2"] = round(float(area[thin].sum()), 1)
    res["knife_area_mm2"] = round(float(area[knife].sum()), 1)
    res["min_thickness_mm"] = round(float(thick[np.isfinite(thick)].min()), 2) if np.isfinite(thick).any() else None
    # where are the thin bits? cluster centres coarsely (5 mm grid) for the report
    res["thin_spots"] = _spots(centres[thin], area[thin])
    res["knife_spots"] = _spots(centres[knife], area[knife])

    # --- overhangs: faces pointing down more steeply than the limit, not on the bed
    lim = -math.cos(math.radians(overhang_deg))            # nz below this needs support
    down = (normals[:, 2] < lim) & (centres[:, 2] > zmin + 0.3)
    # flat ceilings that span a short gap are bridges (printed in mid-air between two walls, no support needed)
    flat = down & (normals[:, 2] < -0.985)
    bridged = np.zeros(len(down), bool)
    bridges = []
    if flat.any():
        import trimesh
        idx = np.nonzero(flat)[0]
        adj = tm.face_adjacency
        keep = flat[adj[:, 0]] & flat[adj[:, 1]]
        comps = trimesh.graph.connected_components(adj[keep], nodes=idx, min_len=1)
        # which faces sit across each edge (to tell a bridge, held by walls below it on its sides, from a
        # cantilever, whose free edges lead up into the part)
        edge_faces: Dict = {}
        for fi, tri in enumerate(tm.faces):
            for a_, b_ in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                edge_faces.setdefault((min(a_, b_), max(a_, b_)), []).append(fi)
        for comp in comps:
            pts = tm.vertices[tm.faces[comp].ravel()]
            ext = np.ptp(pts[:, :2], axis=0)
            span = float(min(ext))
            cset = set(int(c) for c in comp)
            sup_len = tot_len = 0.0
            for fi in comp:
                tri = tm.faces[fi]
                for a_, b_ in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                    others = [f for f in edge_faces[(min(a_, b_), max(a_, b_))] if f not in cset]
                    if not others:
                        continue
                    va, vb = tm.vertices[a_], tm.vertices[b_]
                    L_ = float(np.linalg.norm(va - vb))
                    tot_len += L_
                    if centres[others[0], 2] < (va[2] + vb[2]) / 2 - 0.05:
                        sup_len += L_
            held = tot_len > 0 and sup_len / tot_len >= 0.6
            if span <= max_bridge and held:
                bridged[comp] = True
                bridges.append({"span_mm": round(span, 1), "area_mm2": round(float(area[comp].sum()), 1),
                                "at_mm": [round(float(v), 1) for v in pts.mean(0)]})
    need = down & ~bridged
    # small isolated overhangs (under a 5 mm boss, the top of a small hole, a 1 mm ledge) print unsupported:
    # count only connected overhang regions larger than `small_overhang` mm²
    if need.any():
        import trimesh
        idx = np.nonzero(need)[0]
        adj = tm.face_adjacency
        keep = need[adj[:, 0]] & need[adj[:, 1]]
        small = 0.0
        edges = tm.edges_sorted.reshape(-1, 3, 2)
        for comp in trimesh.graph.connected_components(adj[keep], nodes=idx, min_len=1):
            a_ = float(area[comp].sum())
            # mean width of the region = 2·area / boundary length; a narrow ledge (<= ledge mm) prints as is
            e = edges[comp].reshape(-1, 2)
            uniq, cnt = np.unique(e, axis=0, return_counts=True)
            border = uniq[cnt == 1]
            blen = float(np.linalg.norm(tm.vertices[border[:, 0]] - tm.vertices[border[:, 1]], axis=1).sum())
            width = 2 * a_ / blen if blen > 0 else 0.0
            if a_ < small_overhang or width <= ledge:
                need[comp] = False
                small += a_
        res["small_overhangs_mm2"] = round(small, 1)
    res["overhang_area_mm2"] = round(float(area[need].sum()), 1)
    res["overhang_spots"] = _spots(centres[need], area[need])
    res["bridges"] = sorted(bridges, key=lambda b: -b["area_mm2"])[:5]
    # --- bed contact
    bed = (normals[:, 2] < -0.99) & (centres[:, 2] < zmin + 0.05)
    res["bed_contact_mm2"] = round(float(area[bed].sum()), 1)
    res["height_mm"] = round(float(tm.bounds[1][2] - zmin), 1)
    res["footprint_mm"] = [round(float(v), 1) for v in (tm.bounds[1][:2] - tm.bounds[0][:2])]
    return res


def _spots(pts, w, cell=6.0, top=5):
    if len(pts) == 0:
        return []
    keys = np.floor(pts / cell).astype(int)
    agg: Dict = {}
    for k, p, a in zip(map(tuple, keys), pts, w):
        s = agg.setdefault(k, [0.0, np.zeros(3)])
        s[0] += a
        s[1] += p * a
    best = sorted(agg.values(), key=lambda s: -s[0])[:top]
    return [{"at_mm": [round(float(v), 1) for v in s[1] / s[0]], "area_mm2": round(s[0], 1)} for s in best if s[0] > 0.5]


def audit_shape(shape, name: str = "", tol: float = 0.04, **kw) -> Dict:
    """Audit a build123d shape as it sits (z up, lowest point on the bed)."""
    import trimesh
    from .geom.mesh import mesh
    v, t, skipped = mesh(shape, tol, 0.3)
    tm = trimesh.Trimesh(vertices=v, faces=t, process=True)
    tm.merge_vertices()
    r = audit_mesh(tm, name=name, **kw)
    r["unmeshed_faces"] = skipped
    return r


def audit_stl(path: str, **kw) -> Dict:
    import trimesh
    tm = trimesh.load_mesh(path, process=True)
    return audit_mesh(tm, **kw)


def findings(results: Dict[str, Dict], supports_ok: Dict[str, float] = None) -> List[Dict]:
    """Turn audit results into check findings. supports_ok: part -> overhang area (mm²) accepted by design
    (for example the underside of a wing that is printed on supports on purpose)."""
    supports_ok = supports_ok or {}
    out = []
    for name, r in results.items():
        if not r["watertight"] or not r["winding_ok"]:
            out.append(("error", "print_mesh", f"{name}: STL is not a closed, consistently oriented volume; slicers "
                                               f"may drop or fill parts of it", [name]))
        if r["knife_area_mm2"] > 5.0:
            spot = r["knife_spots"][0]["at_mm"] if r["knife_spots"] else "?"
            out.append(("error", "print_thin", f"{name}: {r['knife_area_mm2']} mm² of surface is thinner than one "
                                               f"extrusion line (min {r['min_thickness_mm']} mm, e.g. near {spot}); it "
                                               f"will not print", [name]))
        elif r["thin_area_mm2"] > 20.0:
            spot = r["thin_spots"][0]["at_mm"] if r["thin_spots"] else "?"
            out.append(("warning", "print_thin", f"{name}: {r['thin_area_mm2']} mm² thinner than two lines (0.8 mm), "
                                                 f"e.g. near {spot}; weak or gappy", [name]))
        ok = supports_ok.get(name, 0.0)
        if r["overhang_area_mm2"] > ok + 30.0:
            spot = r["overhang_spots"][0]["at_mm"] if r["overhang_spots"] else "?"
            out.append(("warning", "print_overhang", f"{name}: {r['overhang_area_mm2']} mm² of overhang steeper than "
                                                     f"45° (e.g. near {spot}); needs supports in this orientation",
                        [name]))
        if r["height_mm"] > 20 and r["bed_contact_mm2"] < 0.02 * r["footprint_mm"][0] * r["footprint_mm"][1]:
            out.append(("warning", "print_bed", f"{name}: only {r['bed_contact_mm2']} mm² on the bed for a "
                                                f"{r['height_mm']} mm tall part; use a brim", [name]))
    return out
