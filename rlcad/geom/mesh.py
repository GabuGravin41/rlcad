"""Robust tessellation: meshes face by face and skips faces OCC cannot triangulate (reports how many)."""
from __future__ import annotations

import numpy as np


def mesh(shape, tol: float = 0.3, ang: float = 0.5):
    """Return (vertices Nx3, triangles Mx3, skipped_faces)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    BRepMesh_IncrementalMesh(shape.wrapped, tol, False, ang, True)
    verts, tris, skipped, off = [], [], 0, 0
    for f in shape.faces():
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(f.wrapped, loc)
        t = tol
        while poly is None and t > tol / 30:
            # some small or strongly curved faces only triangulate at a finer deflection
            t /= 3.0
            BRepMesh_IncrementalMesh(f.wrapped, t, False, ang, True)
            poly = BRep_Tool.Triangulation_s(f.wrapped, loc)
        if poly is None:
            skipped += 1
            continue
        trsf = loc.Transformation()
        rev = f.wrapped.Orientation() == TopAbs_REVERSED
        for i in range(1, poly.NbNodes() + 1):
            p = poly.Node(i).Transformed(trsf)
            verts.append((p.X(), p.Y(), p.Z()))
        for i in range(1, poly.NbTriangles() + 1):
            a, b, c = poly.Triangle(i).Get()
            tris.append((off + a - 1, off + c - 1, off + b - 1) if rev else (off + a - 1, off + b - 1, off + c - 1))
        off += poly.NbNodes()
    return np.array(verts, dtype=float).reshape(-1, 3), np.array(tris, dtype=int).reshape(-1, 3), skipped
