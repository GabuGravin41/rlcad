"""F-35-style ducted quadcopter airframe (parametric, build123d / OpenCascade).

Frame of reference: X forward (nose +X), Y left, Z up; origin at the thrust centre (middle of the four ducts) on the
bottom face of the frame plate. Units: mm.

Structure
  * frame (PETG, load-bearing): centre plate + four arms to the motor pads; FC/ESC stack holes, battery strap slots,
    duct discs cut out of the plate so the airflow is not blocked.
  * pods (LW-PLA, cosmetic + prop guard): duct ring with bell-mouth inlet lip + wing (front) or horizontal tail (rear)
    plate. Each pod is screwed to a post on its arm.
  * fuselage (LW-PLA): nose (closed), centre shell (open bottom, sits on the frame), tail with nozzle; chined
    cross-sections lofted along X; slip-fit collars between sections.
  * canopy, two canted vertical fins.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from build123d import (Vertex, Align, Axis, Box, BuildLine, BuildSketch, Color, Compound, Cylinder, Ellipse, Face, Line, Location,
                       Plane, Polygon, Pos, Rot, Sphere, Spline, ThreePointArc, Vector, Wire, extrude, loft, make_face,
                       revolve, scale)


@dataclass
class AirframeParams:
    # propulsion geometry (from the parts chosen)
    prop_d: float = 76.2
    tip_gap: float = 1.5
    duct_wall: float = 1.6
    duct_lip_r: float = 4.0
    duct_z0: float = 10.5         # duct bottom (above the arm rib)
    duct_depth: float = 26.0
    motor_h: float = 13.5         # motor body (base + bell) above the frame; the prop hub sits on top of the bell
    motor_base_d: float = 15.0
    motor_bell_d: float = 19.9    # rotating bell: the arm rib must stay clear of it
    motor_pattern: float = 9.0
    motor_pattern_alt: float = 0.0   # second square pattern (0 = none)
    motor_hole_d: float = 2.2
    prop_hub_h: float = 5.5
    # layout
    duct_dx: float = 50.0         # duct centres at (±dx, ±dy)
    fus_half_w: float = 23.0      # fuselage outer half-width at the chine
    duct_to_fus_gap: float = 2.8  # duct outer wall to fuselage side
    # frame
    frame_t: float = 2.5
    plate_half_w: float = 20.0
    plate_x: Tuple[float, float] = (-65.0, 65.0)
    arm_w: float = 12.0
    rib_w: float = 2.4            # stiffening rib on top of each arm
    rib_h: float = 6.5
    stack_pattern: float = 30.5
    stack_x: float = 30.0         # FC/ESC stack centre
    # skin
    skin_t: float = 1.0
    wing_t: float = 3.0           # wing/tail root thickness (thin symmetric airfoil)
    wing_tip_t: float = 1.6       # wing/tail tip thickness (printable minimum ≈1.2)
    fin_root_t: float = 2.4
    fin_tip_t: float = 1.3
    wing_z: float = 10.5          # wing/tail flat underside; = duct_z0 so each pod prints flat on the bed
    te_min: float = 0.9           # blunt trailing edge: at least two 0.4 mm extrusion lines
    wing_sweep_deg: float = 35.0
    wing_le_root_ahead: float = 78.0   # wing root leading edge, ahead of the front duct centre
    wing_te_root_x: float = 4.0
    wing_tip_chord: float = 26.0
    tail_sweep_deg: float = 40.0
    tail_le_root_x: float = -6.0
    tail_te_root_x: float = -104.0
    tail_tip_chord: float = 24.0
    tail_span_inset: float = 4.0
    wing_margin: float = 3.0      # min distance from duct outer wall to a plate edge
    span_margin: float = 4.8
    nose_x: float = 175.0
    tail_x: float = -108.0
    fus_top_z: float = 44.0
    chine_z: float = 20.0
    fin_cant_deg: float = 25.0
    fin_h: float = 42.0
    fit_clear: float = 0.2        # slip-fit clearance
    # access holes in the fuselage centre shell for connectors on the stack: (x, side +1/-1, z, width, height)
    port_holes: Tuple = ()
    # where a connector is brought out to the skin with an extension, (x, z); empty = at the connector itself
    usb_port: Tuple = (0.0, 25.0)   # above the chine and the wing roots, between the front and rear ducts

    # derived ---------------------------------------------------------------
    @property
    def duct_ri(self):
        return self.prop_d / 2 + self.tip_gap

    @property
    def duct_ro(self):
        return self.duct_ri + self.duct_wall

    @property
    def duct_dy(self):
        return self.fus_half_w + self.duct_to_fus_gap + self.duct_ro

    @property
    def duct_centres(self):
        return [(sx * self.duct_dx, sy * self.duct_dy) for sx in (1, -1) for sy in (1, -1)]

    @property
    def span_y(self):
        return self.duct_dy + self.duct_ro + self.span_margin

    @property
    def prop_z(self):
        return self.frame_t + self.motor_h + self.prop_hub_h / 2    # mid-plane of the prop hub on the bell

    def to_dict(self):
        d = asdict(self)
        d.update(duct_ri=self.duct_ri, duct_ro=self.duct_ro, duct_dy=round(self.duct_dy, 2),
                 span_y=round(self.span_y, 2), prop_z=self.prop_z)
        return d


# ---------------------------------------------------------------------------------------------- helpers
def _poly_xy(pts, z=0.0):
    return Plane.XY.offset(z) * Polygon(*pts, align=None)


def _dist_point_line(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    return abs(dx * (py - ay) - dy * (px - ax)) / math.hypot(dx, dy)


def _clear_line(a, b, centre, r, margin):
    return _dist_point_line(centre, a, b) >= r + margin


# ---------------------------------------------------------------------------------------------- duct
def duct_ring(p: AirframeParams):
    """Ducted-fan shroud, revolved from a smooth profile: elliptical bell-mouth inlet, straight throat around the
    prop plane, a gentle diffuser to the exit (area ratio ≈1.06, which is where a duct earns its extra thrust), and
    an outer skin that tapers to a rounded trailing edge — a nacelle rather than a tube."""
    ri, w, lip = p.duct_ri, p.duct_wall, p.duct_lip_r
    z0, z1 = p.duct_z0, p.duct_z0 + p.duct_depth
    zp = p.prop_z
    r_exit = ri * 1.03
    r_top = ri + lip + w                 # outer radius at the lip
    r_bot = ri * 1.03 + w + 0.3          # outer radius at the exit
    throat_hi = min(z1 - lip, zp + 4.5)
    throat_lo = max(z0 + 3.0, zp - 4.5)
    c = math.cos(math.radians(45))
    pts_in = [(r_exit, z0 + 0.4), (ri + 0.25 * (r_exit - ri), throat_lo - 2.0), (ri, throat_lo), (ri, throat_hi)]
    with BuildSketch(Plane.XZ) as sk:
        with BuildLine():
            Spline(*pts_in)                                                       # diffuser + throat
            Line((ri, throat_hi), (ri, z1 - lip))
            ThreePointArc((ri, z1 - lip), (ri + lip - lip * c, z1 - lip + lip * c), (ri + lip, z1))   # bell mouth
            ThreePointArc((ri + lip, z1), (r_top - w * 0.3, z1 - w * 0.25), (r_top, z1 - w))
            Spline((r_top, z1 - w), (ri + w + 0.9, z1 - 2.4 * lip), (r_bot, z0 + 1.2),               # nacelle skin
                   tangents=((-0.35, -1), (0.03, -1)))
            # exit: small outer round, a flat land that sits on the print bed, 0.4 mm chamfer on the inner edge
            ThreePointArc((r_bot, z0 + 1.2), (r_bot - 0.6 + 0.6 * c, z0 + 0.6 - 0.6 * c), (r_bot - 0.6, z0))
            Line((r_bot - 0.6, z0), (r_exit + 0.4, z0))
            Line((r_exit + 0.4, z0), (r_exit, z0 + 0.4))
        make_face()
    return revolve(sk.sketch, Axis.Z)


# ---------------------------------------------------------------------------------------------- planforms
def _tangent_x(xp: float, yp: float, cx: float, cy: float, r: float, y: float, front: bool) -> float:
    """x at height y of the line through (xp, yp) tangent to the circle (cx, cy, r), passing ahead of it
    (front=True) or behind it."""
    dx, dy = cx - xp, cy - yp
    d = math.hypot(dx, dy)
    if d <= r:
        return xp
    phi, alpha = math.atan2(dy, dx), math.asin(r / d)
    xs = []
    for a in (phi + alpha, phi - alpha):
        ux, uy = math.cos(a), math.sin(a)
        if abs(uy) < 1e-9:
            continue
        xs.append(xp + ux * (y - yp) / uy)
        # which side of this line is the circle's centre? (for the line at the circle's height)
    xc_line = [xp + math.cos(a) * (cy - yp) / math.sin(a) for a in (phi + alpha, phi - alpha) if abs(math.sin(a)) > 1e-9]
    pick = [x for x, xl in zip(xs, xc_line) if (xl > cx if front else xl < cx)]
    if not pick:
        return xs[0]
    return min(pick) if front else max(pick)


def wing_planform(p: AirframeParams, front: bool) -> List[Tuple[float, float]]:
    """Left-side (y > 0) planform. Front pod: a swept wing whose leading edge is tangent to the duct nacelle
    (3 mm margin); rear pod: a horizontal tail whose trailing edge wraps behind the rear duct. The two meet at
    x = 0 with a 1 mm gap, so from above the aircraft reads as one cranked wing around its four fans."""
    y0 = p.fus_half_w + 1.0
    R = p.duct_ri + p.duct_lip_r + p.duct_wall + p.wing_margin
    split = 0.5
    ym = p.duct_dy                                   # the notch between wing and tail opens outboard of the fans
    if front:
        y1 = p.span_y
        le_root = p.duct_dx + p.wing_le_root_ahead
        tip_le = max(le_root - math.tan(math.radians(p.wing_sweep_deg)) * (y1 - y0),
                     _tangent_x(le_root, y0, p.duct_dx, p.duct_dy, R, y1, True))
        tip_te = _tangent_x(split, ym, p.duct_dx, p.duct_dy, R, y1, False) - 0.5
        tip_te = max(split, min(tip_te, tip_le - 18.0))
        return [(split, y0), (le_root, y0), (tip_le, y1), (tip_te, y1), (split, ym)]
    y1 = p.span_y - p.tail_span_inset
    te_root = p.tail_te_root_x
    tip_te = min(te_root + math.tan(math.radians(14.0)) * (y1 - y0),
                 _tangent_x(te_root, y0, -p.duct_dx, p.duct_dy, R, y1, False))
    tip_le = _tangent_x(-split, ym, -p.duct_dx, p.duct_dy, R, y1, True) + 0.5
    tip_le = min(-split, max(tip_le, tip_te + 18.0))
    return [(te_root, y0), (-split, y0), (-split, ym), (tip_le, y1), (tip_te, y1)]


def wing_solid(p: AirframeParams, front: bool):
    """Airfoil-section wing (front) or tail (rear) over the planform: straight-lofted between the root, the notch
    station and the tip, thickness tapering from wing_t to wing_tip_t."""
    plan = wing_planform(p, front)
    if front:
        (te_r, y0), (le_r, _), (le_t, y1), (te_t, _), (te_n, yn) = plan
        le_n = le_r + (le_t - le_r) * (yn - y0) / (y1 - y0)
        stations = [(y0, le_r, te_r), (yn, le_n, te_n), (y1, le_t, te_t)]
    else:
        (te_r, y0), (le_r, _), (le_n, yn), (le_t, y1), (te_t, _) = plan
        te_n = te_r + (te_t - te_r) * (yn - y0) / (y1 - y0)
        stations = [(y0, le_r, te_r), (yn, le_n, te_n), (y1, le_t, te_t)]
    secs = []
    for y, le, te in stations:
        u = (y - y0) / (y1 - y0)
        th = p.wing_t + (p.wing_tip_t - p.wing_t) * u
        secs.append(_airfoil_face(le, le - te, th, y, p.wing_z, p.te_min))
    a = loft(secs[:2], ruled=True)
    b = loft(secs[1:], ruled=True)
    return a + b


# ---------------------------------------------------------------------------------------------- pods
def pod(p: AirframeParams, front: bool, left: bool):
    cx = p.duct_dx if front else -p.duct_dx
    cy = p.duct_dy
    plate = wing_solid(p, front)
    ring = Pos(cx, cy, 0) * duct_ring(p)
    hole = Pos(cx, cy, p.duct_z0 - 1) * Cylinder(p.duct_ri, p.duct_depth + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = (plate - hole) + ring
    # mounting boss on the duct's inboard bottom: sits on the arm post, M2 screw from below
    ang = math.atan2(cy, cx)
    bx, by = cx - (p.duct_ri + p.duct_wall / 2) * math.cos(ang), cy - (p.duct_ri + p.duct_wall / 2) * math.sin(ang)
    boss = Pos(bx, by, p.duct_z0) * Cylinder(3.2, 5.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body = body + boss - Pos(bx, by, p.duct_z0 - 0.1) * Cylinder(0.8, 4.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    if not left:
        body = body.mirror(Plane.XZ)
    return body


# ---------------------------------------------------------------------------------------------- frame
def frame(p: AirframeParams):
    x0, x1 = p.plate_x
    plate = Pos((x0 + x1) / 2, 0, 0) * Box(x1 - x0, 2 * p.plate_half_w, p.frame_t,
                                             align=(Align.CENTER, Align.CENTER, Align.MIN))
    # remove the duct discs from the plate so the airflow is unobstructed
    for cx, cy in p.duct_centres:
        plate = plate - Pos(cx, cy, -1) * Cylinder(p.duct_ri, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    arms = None
    for cx, cy in p.duct_centres:
        length = math.hypot(cx, cy)
        ang = math.degrees(math.atan2(cy, cx))
        arm = Pos(0, 0, 0) * Rot(0, 0, ang) * Box(length, p.arm_w, p.frame_t, align=(Align.MIN, Align.CENTER, Align.MIN))
        # stiffening rib from the plate edge to the motor pad (T-section arm)
        root = max(p.plate_half_w, 19.5) / (abs(cy) / length)
        rib_len = length - root - max(p.motor_base_d / 2 + 2.5, p.motor_bell_d / 2 + 1.5)   # clear of the bell
        if p.rib_h > 0 and rib_len > 5:
            arm = arm + Rot(0, 0, ang) * Pos(root, 0, p.frame_t) * Box(rib_len, p.rib_w, p.rib_h,
                                                                        align=(Align.MIN, Align.CENTER, Align.MIN))
        pad = Pos(cx, cy, 0) * Cylinder(p.motor_base_d / 2 + 2.5, p.frame_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
        # post under the pod boss (duct inboard wall)
        ux, uy = cx / length, cy / length
        bx, by = cx - (p.duct_ri + p.duct_wall / 2) * ux, cy - (p.duct_ri + p.duct_wall / 2) * uy
        post = Pos(bx, by, p.frame_t) * Cylinder(3.2, p.duct_z0 - p.frame_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
        a = arm + pad + post
        arms = a if arms is None else arms + a
    f = plate + arms
    holes = []
    for cx, cy in p.duct_centres:
        holes.append(Pos(cx, cy, -1) * Cylinder(2.6, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))  # shaft/clip
        # square M2 patterns (side = pattern): the main one on the diagonals, the alternative turned 45° so the
        # two sets of holes never merge into slots
        for pat, rot in ((p.motor_pattern, 45.0), (p.motor_pattern_alt, 0.0)):
            if not pat:
                continue
            r = pat / math.sqrt(2)
            for k in range(4):
                a = math.radians(rot + 90 * k)
                sx, sy = r * math.cos(a), r * math.sin(a)
                holes.append(Pos(cx + sx, cy + sy, -1) * Cylinder(p.motor_hole_d / 2, p.frame_t + 2,
                                                                  align=(Align.CENTER, Align.CENTER, Align.MIN)))
        ux, uy = cx / math.hypot(cx, cy), cy / math.hypot(cx, cy)
        bx, by = cx - (p.duct_ri + p.duct_wall / 2) * ux, cy - (p.duct_ri + p.duct_wall / 2) * uy
        holes.append(Pos(bx, by, -1) * Cylinder(1.1, p.duct_z0 + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    h = p.stack_pattern / 2
    for sx in (h, -h):
        for sy in (h, -h):
            holes.append(Pos(p.stack_x + sx, sy, -1) * Cylinder(1.65, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    # battery strap slots: 18 × 3 mm, either side of the battery, at two strap positions
    # (kept clear of the rear arms, which leave the plate edge near x = -15 mm)
    for sx in (-48.0, -30.0):
        for sy in (p.plate_half_w - 2.5, -(p.plate_half_w - 2.5)):
            holes.append(Pos(sx, sy, -1) * Box(14.0, 2.5, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    # lightening window under the battery (the battery rests on the plate edges and is strapped)
    holes.append(Pos(-42.0, 0, -1) * Box(26.0, 2 * p.plate_half_w - 16.0, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    # fuselage screw holes
    for sx in (x0 + 3.5, x1 - 3.5):
        for sy in (p.fus_half_w - p.skin_t - 4.5, -(p.fus_half_w - p.skin_t - 4.5)):
            holes.append(Pos(sx, sy, -1) * Cylinder(1.1, p.frame_t + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
    for hh in holes:
        f = f - hh
    return f


# ---------------------------------------------------------------------------------------------- fuselage
# Cross-sections are smooth: two splines per station, an upper one (chine → spine → chine) and a lower one
# (chine → keel → chine), meeting at sharp chines like the F-35's. The same 12 control points, offset inward, give
# the inner skin, so outer and inner lofts always have matching topology.
def _section_ctrl(p: AirframeParams, s: float, z_bot: float):
    """Control points (y, z), closed loop, starting at the right chine and running over the top: 7 upper points
    (right chine … left chine) then 5 lower points back towards the right chine."""
    wc = max(0.5, p.fus_half_w * s)
    zc = z_bot + (p.chine_z - z_bot) * (0.35 + 0.65 * s)
    zt = z_bot + (p.fus_top_z - z_bot) * _hfac(s)
    H, D = zt - zc, zc - z_bot
    upper = [(wc, zc), (0.84 * wc, zc + 0.42 * H), (0.50 * wc, zt - 0.05 * H), (0.0, zt),
             (-0.50 * wc, zt - 0.05 * H), (-0.84 * wc, zc + 0.42 * H), (-wc, zc)]
    lower = [(-0.99 * wc, z_bot + 0.42 * D), (-0.88 * wc, z_bot + 0.07 * D), (0.0, z_bot),
             (0.88 * wc, z_bot + 0.07 * D), (0.99 * wc, z_bot + 0.42 * D)]
    return upper + lower


def _section_pts(p: AirframeParams, s: float, z_bot: float):
    """Outline (y, z) of the section (control polygon; the spline passes through every point)."""
    return _section_ctrl(p, s, z_bot)


def _inset_convex(pts, d):
    """Offset a convex polygon inward by d (sharp corners). If it collapses, shrink it about its centroid to a
    sliver instead (the nose tip is then solid, which is fine)."""
    import numpy as np
    P = np.array(pts, float)
    n = len(P)
    area = 0.5 * sum(P[i, 0] * P[(i + 1) % n, 1] - P[(i + 1) % n, 0] * P[i, 1] for i in range(n))
    sgn = 1.0 if area > 0 else -1.0
    lines = []
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        e = (b - a) / np.linalg.norm(b - a)
        nrm = sgn * np.array([-e[1], e[0]])          # inward normal
        lines.append((a + nrm * d, e))
    out = []
    for i in range(n):
        (p1, e1), (p2, e2) = lines[i - 1], lines[i]
        m = np.array([e1, -e2]).T
        t = np.linalg.solve(m, p2 - p1)
        out.append(tuple(p1 + e1 * t[0]))
    Q = np.array(out)
    area_q = 0.5 * sum(Q[i, 0] * Q[(i + 1) % n, 1] - Q[(i + 1) % n, 0] * Q[i, 1] for i in range(n))
    # every inset vertex must stay inside (a collapsing tip flips or crosses)
    if area_q * sgn <= 0 or abs(area_q) < 2.0:
        c = P.mean(0)
        return [tuple(c + (q - c) * 0.15) for q in P]
    return [tuple(q) for q in Q]


def _spline_face(x: float, pts):
    """Face in the plane X = x bounded by two splines through the 12 control points (sharp at both chines)."""
    P = [Vector(x, y, z) for y, z in pts]
    up = Spline(*P[0:7])
    lo = Spline(*(P[6:12] + [P[0]]))
    return Face(Wire([up, lo]))


def _section(p: AirframeParams, x: float, s: float, z_bot: float, inset: float = 0.0):
    """Smooth chined cross-section at station x (optionally offset inward by `inset`)."""
    pts = _section_ctrl(p, s, z_bot)
    if inset:
        pts = _inset_convex(pts, inset)
    return _spline_face(x, pts)


# stations: (x, scale, bottom z) — an ogive nose, parallel centre section, tapering tail
def _hfac(s: float) -> float:
    """Section height (spine above the keel) as a fraction of the full height, for width scale s. The power law
    keeps the mid-nose close to a plain linear taper but lets the tip close to a point instead of a flat blade."""
    return max(0.0, s) ** 0.55


def _key_stations(p: AirframeParams):
    """Design stations (x, width scale, keel z): an ogive nose, a parallel centre section, a tapering tail."""
    n = p.nose_x
    x1, x0 = p.plate_x[1], p.plate_x[0]
    return [(n, 0.035, 12.5), (n - 5, 0.17, 8.6), (n - 14, 0.35, 5.8), (n - 28, 0.56, 3.4), (n - 46, 0.75, 1.7),
            (n - 70, 0.91, 0.5), (x1 + 20, 1.0, 0.0), (x1, 1.0, 0.0), (x0, 1.0, 0.0), (x0 - 20, 0.93, 0.0),
            # boat-tail: the aft body converges onto the nozzle at about 33°, so the tail's end wall is a small
            # shell (it prints as the top of the tail without support) instead of a wide flat face
            (p.tail_x + 12, 0.72, 2.2), (p.tail_x + 5, 0.52, 5.5), (p.tail_x, 0.38, 8.5)]


def _profile(p: AirframeParams):
    """Smooth, overshoot-free (PCHIP) width-scale and keel-height curves through the design stations."""
    from scipy.interpolate import PchipInterpolator
    st = sorted(_key_stations(p), key=lambda t: t[0])
    xs = [t[0] for t in st]
    return PchipInterpolator(xs, [t[1] for t in st]), PchipInterpolator(xs, [t[2] for t in st]), xs[0], xs[-1]


def _stations(p: AirframeParams, spacing: float = 9.0):
    """Loft stations: the design stations plus intermediate ones every ~`spacing` mm taken from the smooth profile.
    A loft through sparse stations wanders between them (it sagged 0.4-0.6 mm, thinning the 1 mm skin to 0.7 mm);
    dense stations pin the surface to the profile, so the skin keeps its thickness and the checks see the real body."""
    fs, fz, xa, xb = _profile(p)
    keys = sorted({t[0] for t in _key_stations(p)}, reverse=True)
    xs = []
    for a, b in zip(keys, keys[1:]):
        k = max(1, int(math.ceil((a - b) / spacing)))
        xs += [a + (b - a) * i / k for i in range(k)]
    xs.append(keys[-1])
    return [(x, float(fs(x)), float(fz(x))) for x in xs]


def _interp(p, x):
    fs, fz, xa, xb = _profile(p)
    x = min(max(x, xa), xb)
    return float(fs(x)), float(fz(x))


def outer_loft(p: AirframeParams):
    return loft([_section(p, x, s, zb) for x, s, zb in _stations(p)])


def _inset_for(p, x: float, d: float) -> float:
    """In-plane inset that gives a wall `d` thick normal to the surface. Where the body tapers at angle a, an
    in-plane offset d leaves only d·cos(a) of material (0.8 mm instead of 1 mm on the nose), so it is scaled up."""
    fs, fz, xa, xb = _profile(p)
    x = min(max(x, xa), xb)
    s_, zb = float(fs(x)), float(fz(x))
    dw = abs(float(fs.derivative()(x))) * p.fus_half_w
    dh = abs(float(fz.derivative()(x))) + abs(float(fs.derivative()(x))) * (p.fus_top_z - zb) * 0.55 / max(s_, 0.05) ** 0.45
    slope = max(dw, dh)
    return min(1.35 * d, d * math.sqrt(1 + slope ** 2))


def _inner_loft(p, d):
    """Inner skin surface: the same control points offset in each station's plane.

    The cavity does not run to the very tips, where an in-plane offset collapses and leaves knife-thin skin. Over
    the last ~16 mm at each end the inset section is shrunk about its own centre (a smooth taper to 30 %), so the
    cavity closes in a steep dome: the nose tip and the tail end are solid, and since the nose and tail print
    standing on their cut faces, these domes are the tops of the prints and need no support."""
    import numpy as np
    n = p.nose_x
    close = 22.0
    x_nose = n - 12.0 - close

    def shrunk(x, f):
        s_, zb = _interp(p, x)
        P = np.array(_inset_convex(_section_ctrl(p, s_, zb), d))
        c = P.mean(0)
        return _spline_face(x, [tuple(c + (q - c) * f) for q in P])

    def ease(u):                                   # 1 → 0.3, flat at the start so the surface stays smooth
        return 1.0 - 0.7 * (1 - math.cos(math.pi * u)) / 2

    # tip first (loft order is nose → tail): 30 % at n-12, full size at n-12-close
    secs = [shrunk(n - 12.0 - close * u, ease(1 - u)) for u in (0.0, 0.25, 0.5, 0.75)]
    # the tail keeps its skin all the way to the end; the boat-tail's end wall (skin_t thick) closes it
    secs += [_section(p, x, s_, zb, inset=_inset_for(p, x, d)) for x, s_, zb in _stations(p)
             if p.tail_x + d + 0.2 <= x <= x_nose]
    secs += [_section(p, p.tail_x + d, *_interp(p, p.tail_x + d), inset=_inset_for(p, p.tail_x + d, d))]
    return loft(secs)


def section_profile(p: AirframeParams, x: float, n: int = 48):
    """Outer section at station x as a closed (y, z) polygon sampled on the actual splines (for clearance queries)."""
    s, zb = _interp(p, x)
    P = [Vector(x, y, z) for y, z in _section_ctrl(p, s, zb)]
    up = Spline(*P[0:7])
    lo = Spline(*(P[6:12] + [P[0]]))
    pts = [up.position_at(i / n) for i in range(n + 1)] + [lo.position_at(i / n) for i in range(1, n)]
    return [(v.Y, v.Z) for v in pts]


def spine_z(p: AirframeParams, x: float) -> float:
    s, zb = _interp(p, x)
    return zb + (p.fus_top_z - zb) * _hfac(s)


def half_width_at(p: AirframeParams, x: float, z: float) -> float:
    """Outer half-width of the fuselage at station x and height z (0 if z is above or below the section)."""
    pts = section_profile(p, x)
    best = 0.0
    n = len(pts)
    for i in range(n):
        (y1, z1), (y2, z2) = pts[i], pts[(i + 1) % n]
        if (z1 - z) * (z2 - z) <= 0 and z1 != z2:
            y = y1 + (y2 - y1) * (z - z1) / (z2 - z1)
            best = max(best, abs(y))
    return best


def roof_z_at(p: AirframeParams, x: float, y: float) -> float:
    """Outer roof height at station x over lateral position y (highest crossing of the section)."""
    pts = section_profile(p, x)
    y = abs(y)
    best = None
    n = len(pts)
    for i in range(n):
        (y1, z1), (y2, z2) = pts[i], pts[(i + 1) % n]
        if (y1 - y) * (y2 - y) <= 0 and y1 != y2:
            z = z1 + (z2 - z1) * (y - y1) / (y2 - y1)
            best = z if best is None else max(best, z)
    return best if best is not None else zb_of(p, x)


def zb_of(p: AirframeParams, x: float) -> float:
    return _interp(p, x)[1]


def nose_cap(p: AirframeParams):
    """Closes the nose loft to a point, so the tip is rounded rather than a flat end face."""
    x, s, zb = _stations(p)[0]
    f = _section(p, x, s, zb)
    c = f.center()
    # a tiny end face instead of a point: lofting to a vertex leaves a degenerate apex that meshes open
    tip = Plane(origin=(x + 2.5, c.Y, c.Z - 0.4), x_dir=(0, 1, 0), z_dir=(1, 0, 0)) * Ellipse(0.12, 0.25)
    return loft([f, tip])


def fuselage_parts(p: AirframeParams) -> Dict[str, object]:
    t = p.skin_t
    x0, x1 = p.plate_x
    outer = outer_loft(p)
    inner = _inner_loft(p, t)                           # skin of thickness t (in each station plane)
    # a 2.7 mm thick foot along the centre shell's bottom edges: the floor cut meets the skin where it is still
    # fairly flat, and the foot gives a solid edge that seats on the frame plate
    f_o = _section(p, x0 - 1, 1.0, 0.0, inset=0.5)   # inside the skin: never coincident with its surfaces
    f_i = _section(p, x0 - 1, 1.0, 0.0, inset=2.7)   # not 2.4: that is the collar's inner face (coincident faces)
    sides = None
    for sgn in (1, -1):                               # only along the side walls, not across the keel
        b = Pos((x0 + x1) / 2, sgn * (p.fus_half_w + 3), p.frame_t) * Box(
            x1 - x0, 2 * (p.fus_half_w + 3) - 2 * 18.5, 2.5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        sides = b if sides is None else sides + b
    foot = extrude(f_o - f_i, x1 - x0 + 2) & sides
    shell = outer - inner + foot
    big = 400
    cut_front = Pos(x1 + big / 2, 0, 0) * Box(big, big, big)
    cut_back = Pos(x0 - big / 2, 0, 0) * Box(big, big, big)
    nose = shell & cut_front
    tail = shell & cut_back
    centre = shell - cut_front - cut_back
    # open floor over the frame plate: cut across the full width, so the skin ends where it is steep (a narrower cut
    # leaves a knife-thin sliver of the nearly flat bottom skin)
    floor_band = Pos((x0 + x1) / 2, 0, p.frame_t) * Box(x1 - x0 + 30, 2 * p.fus_half_w + 6, 10,
                                                         align=(Align.CENTER, Align.CENTER, Align.MAX))
    centre = centre - floor_band
    # slip-fit collars: fused to the centre shell (3 mm overlap inside), entering nose and tail by 6 mm
    for xj, d in ((x1, 1), (x0, -1)):
        sc, zb = _interp(p, xj)
        f_out = _section(p, xj, sc, zb, inset=t + p.fit_clear)
        f_in = _section(p, xj, sc, zb, inset=t + p.fit_clear + 1.2)
        f_fuse = _section(p, xj, sc, zb, inset=t - 0.4)
        collar = extrude(f_out - f_in, 6.0 * d) + extrude(f_fuse - f_in, -3.0 * d)
        # the collar is an arch: its bottom, where the ring runs nearly flat, is cut away well above the floor cut
        # (cutting it at the floor plane leaves a knife-thin sliver)
        arch_cut = Pos(xj, 0, p.frame_t + 4.0) * Box(40, 2 * p.fus_half_w + 6, 20,
                                                      align=(Align.CENTER, Align.CENTER, Align.MAX))
        centre = centre + (collar - arch_cut)
    # slots where the arms (and their ribs) pass through the centre shell's side walls
    # Each window is square to the wall (cut along x), long enough for the arm crossing at an angle: a slot cut
    # along the arm would meet the skin obliquely and leave knife-edged slivers.
    for cx, cy in p.duct_centres:
        sin_a = abs(cy) / math.hypot(cx, cy)
        cos_a = abs(cx) / math.hypot(cx, cy)
        yw = p.fus_half_w
        xc = cx * yw / abs(cy)
        length = (p.arm_w + 0.6) / sin_a + 4.0 * cos_a / sin_a + 1.0
        win = Pos(xc, math.copysign(yw - 6.0, cy), -0.5) * Box(length, 16.0, p.frame_t + p.rib_h + 1.5,
                                                             align=(Align.CENTER, Align.CENTER, Align.MIN))
        centre = centre - win
    # connector access holes (e.g. the FC's USB-C) through the centre shell side wall
    for hx, side, hz, hw, hh in p.port_holes:
        hole = Pos(hx, side * (p.fus_half_w + 5) / 2, hz) * Box(hw, p.fus_half_w + 5, hh)
        centre = centre - hole
    tail = tail + nozzle(p, tail_end_plate=False)       # the tail's cavity closes ahead of its end face
    # screw bosses: centre shell to frame (4× M2 at the plate corners)
    # bosses sit against the side wall (fused to it) so they stiffen the skin and stay out of the battery bay
    by = half_width_at(p, x0 + 3.5, p.frame_t + 1.0) - t - 1.6
    # The centre shell prints standing on its x0 end: the two bosses at x1 sit on a 45° gusset so nothing inside
    # the shell needs support.
    for sx in (x0 + 3.5, x1 - 3.5):
        for sy in (by, -by):
            boss = Pos(sx, sy, p.frame_t) * Cylinder(2.4, 8.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
            sg = 1 if sy > 0 else -1
            if sx < 0:
                under = None                               # 1 mm above the end face: a short ledge, prints as is
            else:
                yw = sy + sg * 4.0                         # just outside the wall
                tri = Polygon((sx, yw), (sx, sy - sg * 2.4), (sx - 6.4 - 2.4, yw), align=None)
                under = Pos(0, 0, p.frame_t) * extrude(tri, 8.0, dir=(0, 0, 1))   # winding-independent
            centre = centre + ((boss if under is None else boss + under) & outer) - Pos(sx, sy, p.frame_t - 0.1) * Cylinder(
                0.8, 7.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    nose = nose + intakes(p, outer) + nose_cap(p) - canopy_void(p)
    return {"fuselage_nose": nose, "fuselage_centre": centre, "fuselage_tail": tail}


def nozzle(p: AirframeParams, tail_end_plate: bool = True):
    """F135-style exhaust: a short converging ring with a serrated trailing edge, a recessed centre body, and an end
    plate that closes the tail shell around it (so the tail stays one solid)."""
    prof = section_profile(p, p.tail_x)
    zs = [q[1] for q in prof]
    zc = (min(zs) + max(zs)) / 2
    r1 = 0.86 * min(max(abs(q[0]) for q in prof), (max(zs) - min(zs)) / 2)   # fills the boat-tail's end
    r2 = 0.86 * r1                            # at the exit
    L, t = 11.0, 1.2
    x0 = p.tail_x
    ring_out = loft([Plane.YZ.offset(x0 + 0.6) * Pos(0, zc) * Ellipse(r1, r1),     # 0.6 mm into the tail: fused
                     Plane.YZ.offset(x0 - L) * Pos(0, zc) * Ellipse(r2, r2)])
    ring_in = loft([Plane.YZ.offset(x0 + 0.5) * Pos(0, zc) * Ellipse(r1 - t, r1 - t),
                    Plane.YZ.offset(x0 - L - 0.5) * Pos(0, zc) * Ellipse(r2 - t, r2 - t)])
    body = ring_out - ring_in
    # serrated exit: 12 shallow V notches
    for k in range(12):
        a = 360.0 * k / 12
        notch = Pos(x0 - L, 0, zc) * Rot(a, 0, 0) * Pos(0, 0, r2) * Rot(0, 0, 45) * Box(3.0, 3.0, 4.0)
        body = body - notch
    # centre body (recessed cone) on three struts
    cone = loft([Plane.YZ.offset(x0 + 0.5) * Pos(0, zc) * Ellipse(0.45 * r1, 0.45 * r1),
                 Plane.YZ.offset(x0 - 0.6 * L) * Pos(0, zc) * Ellipse(0.12 * r1, 0.12 * r1)])
    for k in range(3):
        a = 360.0 * k / 3 + 90
        strut = Pos(x0 - 1.5, 0, zc) * Rot(a, 0, 0) * Pos(0, 0, 0.7 * r1) * Box(2.5, 1.2, 0.8 * r1)
        cone = cone + strut
    body = body + cone
    if tail_end_plate:
        end = extrude(_section(p, x0, s, zb), 1.2) - Pos(x0 - 1, 0, zc) * Rot(0, 90, 0) * Cylinder(
            r1 - t, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
        body = body + end
    return body


def intakes(p: AirframeParams, outer):
    """F-35-style caret intakes on the nose piece, above the wing root: a raked mouth with rounded corners that
    fairs back into the fuselage side, a recessed inlet, and a diverterless (DSI) bump ahead of each mouth."""
    from build123d import RectangleRounded
    x_mouth, x_back = p.plate_x[1] + 52.0, p.plate_x[1] + 12.0
    z0 = p.chine_z + 2.6                    # just above the chine
    h = 12.0
    zm = z0 + h / 2
    rake = 32.0
    parts = None
    for side in (1, -1):
        sm, _ = _interp(p, x_mouth)
        w_m = 8.0
        ym = side * (half_width_at(p, x_mouth, zm) + w_m / 2 - 2.0)
        mouth_plane = Plane(origin=(x_mouth, ym, zm), x_dir=(0, 1, 0), z_dir=(1, 0, 0)).rotated((0, 0, -side * rake))
        yb = side * (half_width_at(p, x_back, zm - 1) + 1.0)
        back_plane = Plane(origin=(x_back, yb, zm - 1.0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        mid_x = (x_mouth + x_back) / 2
        ymid = side * (half_width_at(p, mid_x, zm) + 2.2)
        mid_plane = Plane(origin=(mid_x, ymid, zm - 0.4), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        body = loft([mouth_plane * RectangleRounded(w_m, h, 2.2),
                     mid_plane * RectangleRounded(w_m - 1.5, h - 1.0, 2.2),
                     back_plane * RectangleRounded(3.0, h - 3.0, 1.2)])
        # a shallow, dark-looking recess with 1.2 mm lips; it stops short of the skin so it never opens into the bay
        inlet = loft([mouth_plane.offset(0.2) * RectangleRounded(w_m - 3.2, h - 3.2, 1.0),
                      mouth_plane.offset(-4.5) * RectangleRounded(w_m - 4.6, h - 5.0, 0.8)])
        body = body - inlet
        # DSI bump just ahead of the mouth
        # sunk so that it stays attached along its whole length (the body narrows towards the nose, so the bump is
        # positioned against the skin at its front end)
        xb = x_mouth + 5.0
        hf, hb = half_width_at(p, xb + 5.0, zm), half_width_at(p, xb - 5.0, zm)
        yaw = math.degrees(math.atan2(hf - hb, 10.0)) * side      # follow the skin, which narrows towards the nose
        bump = Pos(xb, side * ((hf + hb) / 2 - 0.7), zm) * Rot(0, 0, yaw) * scale(Rot(0, 90, 0) * Sphere(1.0), (6.0, 2.4, 4.2))
        body = body + bump
        parts = body if parts is None else parts + body
    inner = _inner_loft(p, p.skin_t)
    return parts - inner


def canopy(p: AirframeParams):
    """Long teardrop canopy (loft of ellipses) seated on the spine; its base follows the fuselage exactly."""
    x_c = p.nose_x - 58
    L = 72.0
    s, _ = _interp(p, x_c)
    wt = 0.50 * p.fus_half_w * s
    secs = []
    for u in (-1.0, -0.8, -0.5, -0.15, 0.2, 0.55, 0.85, 1.0):
        # blunt at the back, pointed at the front
        f = (1 - abs(u) ** 2.2) ** 0.5 if u < 0 else (1 - u ** 1.6) ** 0.62
        f = max(f, 0.04)
        x = x_c + u * L / 2
        z = spine_z(p, x) - 3.0
        secs.append(Plane.YZ.offset(x) * Pos(0, z) * Ellipse(max(0.3, wt * 1.18 * f), max(0.3, 10.5 * f)))
    bubble = loft(secs)
    return bubble - outer_loft(p) - canopy_void(p)


def canopy_void(p: AirframeParams):
    """The inside of the canopy: the bubble shrunk by 1 mm (in each section plane). It is removed from both the
    canopy and the nose skin below it, so the canopy is a 1 mm shell open to the nose cavity (a solid bubble weighs
    ~3 g right at the nose)."""
    x_c = p.nose_x - 58
    L = 72.0
    s, _ = _interp(p, x_c)
    wt = 0.50 * p.fus_half_w * s
    secs = []
    for u in (-0.8, -0.5, -0.15, 0.2, 0.55, 0.8):
        f = (1 - abs(u) ** 2.2) ** 0.5 if u < 0 else (1 - u ** 1.6) ** 0.62
        x = x_c + u * L / 2
        z = spine_z(p, x) - 3.0
        secs.append(Plane.YZ.offset(x) * Pos(0, z - 0.5) * Ellipse(max(0.3, wt * 1.18 * f - 1.0), max(0.3, 10.5 * f - 1.0)))
    return loft(secs)


def _thickness(x: float) -> float:
    """NACA 4-digit thickness distribution, normalised to 1.0 at its maximum (x in 0..1 of chord)."""
    return (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x ** 2 + 0.2843 * x ** 3 - 0.1036 * x ** 4) / 0.10015


def _airfoil_pts(chord: float, thick: float, te: float = 0.9, flat: bool = True, n: int = 20):
    """Printable airfoil (x from the LE, z) with absolute thickness `thick` and a blunt trailing edge of at least
    `te` mm (a sharp edge thinner than two extrusion lines does not print).

    flat=True: plano-convex (flat underside at z = 0, all thickness above) so the part prints flat on the bed with no
    support. flat=False: symmetric about z = 0.
    Returns (upper points TE→LE, lower points LE→TE)."""
    xs = [(1 - math.cos(math.pi * i / n)) / 2 for i in range(n + 1)]   # cosine spacing, LE dense

    def t(x):
        # blend the NACA thickness into a straight taper that ends at `te` (keeps the aft section printable)
        base = thick * _thickness(x) if x > 0.0 else 0.0
        # blunt at both ends: >= te at the trailing edge, >= 0.8 mm (two lines) at the leading edge
        return max(base, te) if x > 0.3 else max(base, min(0.8, 0.5 * thick))
    up = [(x * chord, t(x) if flat else t(x) / 2) for x in reversed(xs)]
    lo = [(x * chord, 0.0 if flat else -t(x) / 2) for x in xs]
    return up, lo


def _airfoil_wire(pts3_up, pts3_lo):
    """Closed wire: upper spline TE→LE, lower edge LE→TE (straight when flat), blunt TE line."""
    edges = [Spline(*pts3_up)]
    if (pts3_up[-1] - pts3_lo[0]).length > 1e-6:          # blunt leading edge
        edges.append(Line(pts3_up[-1], pts3_lo[0]))
    if all(abs(a.Z - pts3_lo[0].Z) < 1e-9 for a in pts3_lo) and all(abs(a.Y - pts3_lo[0].Y) < 1e-9 for a in pts3_lo):
        edges.append(Line(pts3_lo[0], pts3_lo[-1]))
    else:
        edges.append(Spline(*pts3_lo))
    if (pts3_lo[-1] - pts3_up[0]).length > 1e-6:           # blunt trailing edge
        edges.append(Line(pts3_lo[-1], pts3_up[0]))
    return Wire(edges)


def _airfoil_face(le_x: float, chord: float, thick: float, y: float, z_bot: float, te: float = 0.9):
    """Flat-bottomed airfoil in the plane Y = y, chord along -X from the leading edge at le_x, underside at z_bot."""
    up, lo = _airfoil_pts(chord, thick, te, flat=True)
    U = [Vector(le_x - px, y, z_bot + pz) for px, pz in up]
    L = [Vector(le_x - px, y, z_bot + pz) for px, pz in lo]
    return Face(_airfoil_wire(U, L))


def fin(p: AirframeParams, left: bool):
    """Canted, swept vertical fin with a thin airfoil section; the tab locks into the tail's slot."""
    x_root_le, x_root_te = -74.0, -106.0
    h = p.fin_h
    sweep = 22.0
    c_root = x_root_le - x_root_te
    c_tip = 17.0
    root = _fin_section(x_root_le, c_root, p.fin_root_t, 0.0, p.te_min)
    tip = _fin_section(x_root_le - sweep, c_tip, p.fin_tip_t, h, p.te_min)
    blade = loft([root, tip], ruled=True)
    s, zb = _interp(p, (x_root_le + x_root_te) / 2)
    z_root = spine_z(p, (x_root_le + x_root_te) / 2) - 4.0
    y_root = 0.42 * p.fus_half_w * s + 1.0
    cant = p.fin_cant_deg if left else -p.fin_cant_deg
    tab = Pos((x_root_le + x_root_te) / 2, 0, -3.0) * Box(20.0, 2.2, 6.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = blade + tab
    return Pos(0, y_root if left else -y_root, z_root) * Rot(-cant, 0, 0) * part


def _fin_section(le_x, chord, thick, z, te=0.9):
    """Plano-convex fin section in the plane Z = z: flat face at y = -1.1 (same plane as the tab's face, so the fin
    prints lying flat on it), thickness towards +y."""
    up, lo = _airfoil_pts(chord, thick, te, flat=True)
    U = [Vector(le_x - px, -1.1 + pz, z) for px, pz in up]
    L = [Vector(le_x - px, -1.1 + pz, z) for px, pz in lo]
    return Face(_airfoil_wire(U, L))


def fin_slot(p: AirframeParams, left: bool, grow: float = 0.0):
    x_root_le, x_root_te = -74.0, -106.0
    s, zb = _interp(p, (x_root_le + x_root_te) / 2)
    z_root = spine_z(p, (x_root_le + x_root_te) / 2) - 4.0
    y_root = 0.42 * p.fus_half_w * s + 1.0
    cant = p.fin_cant_deg if left else -p.fin_cant_deg
    # the slot runs well past the outer surface (12 mm) so no thin roof of skin is left over its mouth
    slot = Pos((x_root_le + x_root_te) / 2, 0, -3.2 - grow) * Box(20.4 + 2 * grow, 2.6 + 2 * grow,
                                                                  (7.0 + grow) if grow else 12.0,
                                                                  align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Pos(0, y_root if left else -y_root, z_root) * Rot(-cant, 0, 0) * slot


# ---------------------------------------------------------------------------------------------- assembly

MATERIAL = {"frame": "PETG", "pod": "LW-PLA", "fuselage": "LW-PLA", "canopy": "LW-PLA", "fin": "LW-PLA"}
COLOURS = {"frame": (0.15, 0.15, 0.17), "pod": (0.55, 0.58, 0.60), "fuselage": (0.55, 0.58, 0.60),
           "canopy": (0.85, 0.65, 0.20), "fin": (0.50, 0.53, 0.55)}


def build(p: Optional[AirframeParams] = None) -> Dict[str, Dict]:
    """All printable parts: name → {shape, material, colour, role}."""
    p = p or AirframeParams()
    parts = {"frame": frame(p)}
    for front in (True, False):
        for left in (True, False):
            parts[f"pod_{'front' if front else 'rear'}_{'left' if left else 'right'}"] = pod(p, front, left)
    parts.update(fuselage_parts(p))
    parts["canopy"] = canopy(p)
    parts["fin_left"] = fin(p, True)
    parts["fin_right"] = fin(p, False)
    # slots in the tail for the fin tabs (0.2 mm clearance)
    outer = outer_loft(p)
    for side in ("fin_left", "fin_right"):
        # (the slot runs 12 mm up, clear through the skin, so it leaves no thin roof; see fin_slot)
        parts["fuselage_tail"] = parts["fuselage_tail"] - fin_slot(p, side == "fin_left")
    out = {}
    for name, shape in parts.items():
        kind = name.split("_")[0]
        out[name] = {"shape": shape, "material": MATERIAL.get(kind, "PLA"), "colour": COLOURS.get(kind, (0.6, 0.6, 0.6)),
                     "role": {"frame": "structure: carries motors, stack, battery", "pod": "duct (prop guard) + wing/tail",
                              "fuselage": "skin / electronics cover", "canopy": "cosmetic", "fin": "cosmetic"}[kind]}
    return out
