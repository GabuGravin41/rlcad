"""Headless shaded renders of parts/assemblies (matplotlib), so the model and the user can see the design."""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

VIEWS = {"iso": (28, -52), "top": (90, -90), "front": (0, 0), "side": (0, -90), "iso_rear": (25, 140),
         "bottom": (-90, -90)}


def _mesh(shape, tol=0.25):
    from .geom.mesh import mesh
    v, t, _ = mesh(shape, tol, 0.35)
    return v, t


def render(items: Sequence[Tuple[object, Tuple[float, float, float]]], path: str, views: Iterable[str] = ("iso", "top", "side", "front"),
           title: str = "", size_px: int = 1600, tol: float = 0.35, labels: Optional[List[Tuple[str, Tuple[float, float, float]]]] = None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    meshes = []
    for shape, colour in items:
        try:
            v, t = _mesh(shape, tol)
        except Exception:
            continue
        if len(t):
            meshes.append((v, t, np.array(colour)))
    allv = np.vstack([m[0] for m in meshes])
    lo, hi = allv.min(0), allv.max(0)
    ctr, rng = (lo + hi) / 2, (hi - lo).max() / 2 * 1.05
    views = list(views)
    cols = 2 if len(views) > 1 else 1
    rows = math.ceil(len(views) / cols)
    fig = plt.figure(figsize=(size_px / 100, size_px / 100 * rows / cols * 0.8), dpi=100)
    light = np.array([0.35, -0.45, 0.82])
    light = light / np.linalg.norm(light)
    for i, name in enumerate(views):
        ax = fig.add_subplot(rows, cols, i + 1, projection="3d")
        elev, azim = VIEWS.get(name, VIEWS["iso"])
        for v, t, c in meshes:
            tri = v[t]
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            nn = np.linalg.norm(n, axis=1, keepdims=True)
            n = np.divide(n, nn, out=np.zeros_like(n), where=nn > 0)
            shade = 0.45 + 0.55 * np.abs(n @ light)
            fc = np.clip(c[None, :] * shade[:, None], 0, 1)
            pc = Poly3DCollection(tri, facecolors=fc, edgecolors="none", linewidths=0)
            ax.add_collection3d(pc)
        ax.set_xlim(ctr[0] - rng, ctr[0] + rng)
        ax.set_ylim(ctr[1] - rng, ctr[1] + rng)
        ax.set_zlim(ctr[2] - rng, ctr[2] + rng)
        ax.set_box_aspect((1, 1, 1), zoom=1.3)
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(name, fontsize=11)
        for text, pos in labels or []:
            ax.text(*pos, text, fontsize=7)
    if title:
        fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path
