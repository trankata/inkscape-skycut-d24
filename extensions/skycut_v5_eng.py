#!/usr/bin/env python3
"""
SkyCut D24 - v5.0  (clean architecture, English)

Principle:
  * All closed SVG paths are opened automatically.
  * The end overlaps the start by overcut_mm along the contour.
  * The firmware receives only open paths - U...; D...; D...; U...;
  * Knife offset only for open paths with sharp corners.
  * No rotate, no is_closed branching in emit, no overcut_along_path for closed.
"""

import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath, ZoneClose
import socket
import math
import re
import tempfile
import webbrowser
from itertools import groupby

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCALE            = 40        # HPGL units per mm
STEPS_PER_SEG   = 20        # Bezier subdivision steps
MIN_DIST_MM      = 0.05     # Minimum point distance (mm)
CURVE_STEP_MM    = 0.5      # Resample step for curves (mm)

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def cubic_point(p0, c1, c2, p1, t):
    mt = 1 - t
    x = mt**3*p0[0] + 3*mt**2*t*c1[0] + 3*mt*t**2*c2[0] + t**3*p1[0]
    y = mt**3*p0[1] + 3*mt**2*t*c1[1] + 3*mt*t**2*c2[1] + t**3*p1[1]
    return x, y


def is_straight(p0, c1, c2, p1, tol=0.01):
    dx = p1[0] - p0[0]; dy = p1[1] - p0[1]
    seg_len = math.hypot(dx, dy)
    if seg_len < 0.001:
        return True
    nx = dx / seg_len; ny = dy / seg_len
    c1d = abs((c1[0]-p0[0]) * ny - (c1[1]-p0[1]) * nx)
    c2d = abs((c2[0]-p0[0]) * ny - (c2[1]-p0[1]) * nx)
    return c1d < tol and c2d < tol


def dedup_pts(pts, min_dist=0.001):
    if not pts:
        return pts
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0]-out[-1][0], p[1]-out[-1][1]) > min_dist:
            out.append(p)
    return out


def collinear_clean(pts):
    if len(pts) <= 2:
        return pts
    cleaned = [pts[0], pts[1]]
    for pt in pts[2:]:
        a = cleaned[-2]; b = cleaned[-1]
        area = abs((b[0]-a[0])*(pt[1]-a[1]) - (b[1]-a[1])*(pt[0]-a[0]))
        if area < 0.001 and math.hypot(pt[0]-a[0], pt[1]-a[1]) > 0.001:
            cleaned[-1] = pt
        else:
            cleaned.append(pt)
    return cleaned


def resample_by_length(pts, step_len):
    """Redistributes points evenly at step_len mm intervals.
    Works on an open list - does not assume closure."""
    if len(pts) < 2 or step_len <= 0:
        return pts
    segments = []
    total = 0.0
    for i in range(len(pts) - 1):
        d = math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1])
        segments.append((pts[i], pts[i+1], d))
        total += d
    if total < 0.001:
        return pts
    steps = max(3, int(round(total / step_len)))
    step  = total / steps
    result = [pts[0]]
    seg_i = 0; seg_start = 0.0
    for k in range(1, steps):
        target = k * step
        while seg_i < len(segments):
            p0, p1, d = segments[seg_i]
            if d < 0.001:
                seg_start += d; seg_i += 1; continue
            if target <= seg_start + d + 1e-9:
                t = (target - seg_start) / d
                result.append((p0[0]+(p1[0]-p0[0])*t, p0[1]+(p1[1]-p0[1])*t))
                break
            seg_start += d; seg_i += 1
    result.append(pts[-1])
    return result


# ---------------------------------------------------------------------------
# Open-path: follow contour forward for dist_mm mm
# ---------------------------------------------------------------------------

def follow_path(pts, dist_mm):
    """Walks forward along pts from pts[0] for dist_mm mm.
    Returns the points along the path (including the final interpolated one).
    Used for overcut on an open contour (after open_closed_path)."""
    if dist_mm <= 0 or len(pts) < 2:
        return []
    acc = 0.0
    prev = pts[0]
    result = []
    for cur in pts[1:]:
        d = math.hypot(cur[0]-prev[0], cur[1]-prev[1])
        if d < 0.001:
            prev = cur
            continue
        if acc + d >= dist_mm:
            r = (dist_mm - acc) / d
            result.append((prev[0]+(cur[0]-prev[0])*r,
                           prev[1]+(cur[1]-prev[1])*r))
            return result
        result.append(cur)
        acc += d
        prev = cur
    # dist_mm > total path length - return last point
    if result:
        return result
    return [pts[-1]]


# ---------------------------------------------------------------------------
# Open a closed path: remove duplicate end point, append overcut tail
# ---------------------------------------------------------------------------

def rotate_to_longest_straight(pts, min_len_mm=5.0):
    """Rotates a closed contour so the start falls in the middle of the
    longest straight run.

    Goal: the blade drop, the seam and the overcut land on a smooth
    straight line, not on an arc or sharp corner (where they leave a mark).

    If there is no straight run >= min_len_mm (e.g. a pure circle) - the
    contour is returned unchanged.
    """
    n = len(pts)
    if n < 4:
        return pts
    work = list(pts)
    if math.hypot(work[-1][0]-work[0][0], work[-1][1]-work[0][1]) < 0.001:
        work = work[:-1]
        n = len(work)
    if n < 4:
        return pts

    def direction(a, b):
        dx = b[0]-a[0]; dy = b[1]-a[1]
        d  = math.hypot(dx, dy)
        return (dx/d, dy/d) if d > 0.001 else None

    # Straight run: consecutive segments whose direction relative to the
    # FIRST segment of the run stays within STRAIGHT_TOL.
    # This way a circle (constant turn) does not count as a straight run.
    STRAIGHT_TOL = math.radians(10)
    best_len = 0.0
    best_start = -1
    best_count = 0

    for start in range(n):
        ref_dir = direction(work[start], work[(start+1) % n])
        if ref_dir is None:
            continue
        run_len = 0.0
        count = 0
        for k in range(n):
            a = work[(start + k) % n]
            b = work[(start + k + 1) % n]
            cur = direction(a, b)
            if cur is None:
                break
            dot = max(-1.0, min(1.0, ref_dir[0]*cur[0] + ref_dir[1]*cur[1]))
            if math.acos(dot) > STRAIGHT_TOL:
                break
            run_len += math.hypot(b[0]-a[0], b[1]-a[1])
            count += 1
        if run_len > best_len:
            best_len = run_len
            best_start = start
            best_count = count

    if best_len < min_len_mm or best_start < 0:
        return pts

    # Find the point at half the length of the straight run.
    # If it falls between two points - insert an interpolated point.
    half = best_len / 2.0
    acc = 0.0
    for k in range(best_count):
        a = work[(best_start + k) % n]
        b = work[(best_start + k + 1) % n]
        seg = math.hypot(b[0]-a[0], b[1]-a[1])
        if acc + seg >= half:
            t = (half - acc) / seg if seg > 0.001 else 0.0
            mid = (a[0] + (b[0]-a[0])*t, a[1] + (b[1]-a[1])*t)
            # Build a rotated contour starting from mid
            idx_b = (best_start + k + 1) % n
            rotated = [mid]
            for q in range(n):
                rotated.append(work[(idx_b + q) % n])
            return rotated
        acc += seg

    mid_idx = (best_start + best_count // 2) % n
    return work[mid_idx:] + work[:mid_idx]


def open_closed_path(pts, overcut_mm):
    """Opens a closed contour.

    Input:  pts  - points of the closed contour (last may equal first)
    Output: open list [p0, p1, ..., pN, *overcut_tail]
            The contour is no longer closed - the firmware receives it this way.

    Logic:
      1. Remove the duplicate at the end if pts[-1] ~= pts[0].
      2. Append pts[0] at the end - the point where the blade returns to start.
      3. Follow the contour from pts[0] forward for overcut_mm - added after closing.
    """
    work = list(pts)
    # Remove duplicate at the end
    if len(work) >= 2 and math.hypot(work[-1][0]-work[0][0],
                                      work[-1][1]-work[0][1]) < 0.001:
        work = work[:-1]
    if len(work) < 2:
        return work

    # Close with pts[0] - blade returns to the seam
    closed = work + [work[0]]

    # Overcut: follow the contour forward from work[0] for overcut_mm
    if overcut_mm > 0:
        tail = follow_path(work + [work[0]], overcut_mm)
        return closed + tail
    return closed


# ---------------------------------------------------------------------------
# Knife offset (corner arc) - open paths only
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Knife offset (corner arc)
# ---------------------------------------------------------------------------

def _corner_arc_v21(apex, in_nx, in_ny, out_nx, out_ny, k_off):
    """Arc identical to v2.1 - bulges OUTWARD from the contour."""
    MIN_ANGLE = math.radians(5)
    dot   = max(-1.0, min(1.0, in_nx*out_nx + in_ny*out_ny))
    angle = math.acos(dot)
    cross = in_nx*out_ny - in_ny*out_nx
    if angle < MIN_ANGLE or abs(cross) < 1e-9:
        return []
    entry = (apex[0] + in_nx*k_off,  apex[1] + in_ny*k_off)
    exit_ = (apex[0] + out_nx*k_off, apex[1] + out_ny*k_off)
    a_in  = math.atan2(in_ny,  in_nx)
    a_out = math.atan2(out_ny, out_nx)
    delta = a_out - a_in
    if cross > 0:
        while delta <= 0: delta += math.tau
    else:
        while delta >= 0: delta -= math.tau
    steps = max(2, int(abs(math.degrees(delta)) / 15))
    arc = [entry]
    for s in range(1, steps):
        a = a_in + delta * (s / steps)
        arc.append((apex[0] + math.cos(a)*k_off,
                    apex[1] + math.sin(a)*k_off))
    arc.append(exit_)
    return arc


def apply_corner_offset(pts, k_off, sensitivity=50):
    """Adds a knife-offset arc on sharp corners.

    Distinguishes a sharp corner from a rounded curve by the concentration
    of the turn:
    - Sharp corner (star, flap, square corner): the turn is concentrated
      at one point. The immediate angle ~= the angle measured in a wider
      window (+-WIN_DIST mm).
    - Rounding (arc): the turn is distributed. The wide-window angle is
      significantly larger than the immediate one.

    sensitivity (0-100): controls how easily an ear is added.
      0   = conservative (only very sharp corners, few ears)
      50  = balanced (default)
      100 = aggressive (more ears, even on softer corners)
    """
    if k_off <= 0 or len(pts) < 5:
        return list(pts)

    # Map sensitivity (0-100) to the two thresholds:
    #  high sensitivity -> low angle threshold + low concentration threshold
    s = max(0.0, min(100.0, sensitivity)) / 100.0
    # MIN_IMM_ANG: 45deg (conservative) -> 18deg (aggressive)
    MIN_IMM_ANG = math.radians(45 - s * 27)
    # CONC_RATIO: 0.70 (conservative) -> 0.40 (aggressive)
    CONC_RATIO  = 0.70 - s * 0.30
    WIN_DIST    = 1.5               # +-1.5mm window for measuring concentration

    def seg_dir(a, b):
        dx = b[0]-a[0]; dy = b[1]-a[1]
        d  = math.hypot(dx, dy)
        return (dx/d, dy/d) if d > 0.001 else (None, None)

    def angle_between(ax, ay, bx, by):
        return math.acos(max(-1.0, min(1.0, ax*bx + ay*by)))

    def far_point(i, step, max_dist):
        """Walk from i in direction step until max_dist mm accumulated."""
        acc = 0.0; j = i
        while 0 <= j + step < len(pts):
            nj = j + step
            acc += math.hypot(pts[nj][0]-pts[j][0], pts[nj][1]-pts[j][1])
            j = nj
            if acc >= max_dist:
                break
        return j

    result = [pts[0]]
    n = len(pts)
    for i in range(1, n - 1):
        apex = pts[i]
        in_nx, in_ny   = seg_dir(pts[i-1], apex)
        out_nx, out_ny = seg_dir(apex, pts[i+1])
        if in_nx is None or out_nx is None:
            result.append(apex); continue

        imm_ang = angle_between(in_nx, in_ny, out_nx, out_ny)
        if imm_ang < MIN_IMM_ANG:
            result.append(apex); continue

        lo = far_point(i, -1, WIN_DIST)
        hi = far_point(i, +1, WIN_DIST)
        w_in_x,  w_in_y  = seg_dir(pts[lo], apex)
        w_out_x, w_out_y = seg_dir(apex, pts[hi])
        if w_in_x is None or w_out_x is None:
            result.append(apex); continue
        wide_ang = angle_between(w_in_x, w_in_y, w_out_x, w_out_y)

        ratio = imm_ang / wide_ang if wide_ang > 0.01 else 1.0
        if ratio < CONC_RATIO:
            result.append(apex); continue

        arc = _corner_arc_v21(apex, in_nx, in_ny, out_nx, out_ny, k_off)
        if arc:
            result.extend(arc)
        else:
            result.append(apex)

    result.append(pts[-1])
    return result

def emit_open_path(hpgl, pts, coord):
    """Emits an open path: U start; D p1; D p2; ... U last;
    Assumes pts is already open (no closure needed).
    """
    pts = dedup_pts(pts)
    pts = collinear_clean(pts)
    if not pts:
        return

    sx, sy = coord(pts[0][0], pts[0][1])
    hpgl.append(f"U{sx},{sy};")

    last_tx, last_ty = sx, sy
    last_rx, last_ry = pts[0]

    for i in range(1, len(pts)):
        px, py = pts[i]
        # Skip only internal duplicates, the last point always passes
        if i != len(pts)-1 and math.hypot(px-last_rx, py-last_ry) < MIN_DIST_MM:
            continue
        tx, ty = coord(px, py)
        if (tx, ty) != (last_tx, last_ty):
            hpgl.append(f"D{tx},{ty};")
            last_tx, last_ty = tx, ty
            last_rx, last_ry = px, py

    hpgl.append(f"U{last_tx},{last_ty};")


def emit_dashed_path(hpgl, pts, coord, dash_mm, gap_mm,
                     dash_fs, gap_fs, cut_quickly, base_fs):
    """Emits a dashed line: walks pts, alternating dash (cut) and gap.

    dash_mm / gap_mm  - lengths of the cut segment and the gap
    dash_fs / gap_fs  - force for dash / gap (None = use base_fs)
    cut_quickly       - True: blade stays down, only changes FS
                        False: lifts the blade (U) in the gaps
    base_fs           - the color's base force (when dash/gap_fs are None)

    Behavior reproduced from the original plugin:
      cut_quickly + forces:  FS<dash>;D..D.. FS<gap>;D..D.. (blade down)
      cut_quickly without forces: only base_fs, but still U in the gaps
      without cut_quickly:        lifts the blade (U) at the start of each gap
    """
    pts = dedup_pts(pts)
    pts = collinear_clean(pts)
    if len(pts) < 2:
        return

    df = dash_fs if dash_fs is not None else base_fs
    gf = gap_fs  if gap_fs  is not None else base_fs

    # Start position
    sx, sy = coord(pts[0][0], pts[0][1])
    hpgl.append(f"U{sx},{sy};")
    if cut_quickly:
        hpgl.append(f"FS{df};")
    cur_fs = df
    last_tx, last_ty = sx, sy

    # Walk the polyline, tracking distance covered
    in_dash = True          # start with a cut segment
    remaining = dash_mm     # remaining length in current state
    pen_down = False

    def move_to(rx, ry, cutting):
        nonlocal last_tx, last_ty, pen_down
        tx, ty = coord(rx, ry)
        if cutting:
            hpgl.append(f"D{tx},{ty};")
        else:
            hpgl.append(f"U{tx},{ty};")
        last_tx, last_ty = tx, ty
        pen_down = cutting

    # Start the first dash: lower the blade
    move_to(pts[0][0], pts[0][1], True)

    i = 1
    cx, cy = pts[0]
    while i < len(pts):
        nx, ny = pts[i]
        seg = math.hypot(nx-cx, ny-cy)
        if seg < 1e-6:
            i += 1; continue

        if seg <= remaining:
            # whole segment is in the current state
            if in_dash:
                move_to(nx, ny, True)
            else:
                # gap: if cut_quickly -> light force (blade down), else lifted
                move_to(nx, ny, cut_quickly)
            remaining -= seg
            cx, cy = nx, ny
            i += 1
            if remaining <= 1e-6:
                # state change
                in_dash = not in_dash
                remaining = dash_mm if in_dash else gap_mm
                if in_dash:
                    if cut_quickly:
                        if cur_fs != df:
                            hpgl.append(f"FS{df};"); cur_fs = df
                    else:
                        # lifted blade must come down for the new dash
                        move_to(cx, cy, True)
                else:
                    if cut_quickly:
                        if cur_fs != gf:
                            hpgl.append(f"FS{gf};"); cur_fs = gf
                    else:
                        # gap begins -> lift the blade at the current point
                        move_to(cx, cy, False)
        else:
            # segment crosses the boundary - split it
            t = remaining / seg
            mx = cx + (nx-cx)*t
            my = cy + (ny-cy)*t
            if in_dash:
                move_to(mx, my, True)
            else:
                move_to(mx, my, cut_quickly)
            cx, cy = mx, my
            in_dash = not in_dash
            remaining = dash_mm if in_dash else gap_mm
            if in_dash:
                if cut_quickly:
                    if cur_fs != df:
                        hpgl.append(f"FS{df};"); cur_fs = df
                else:
                    move_to(cx, cy, True)
            else:
                if cut_quickly:
                    if cur_fs != gf:
                        hpgl.append(f"FS{gf};"); cur_fs = gf
                else:
                    move_to(cx, cy, False)

    hpgl.append(f"U{last_tx},{last_ty};")

def _stroke_to_color(elem):
    """Returns the color name (black/red/green/yellow) of the element.
    Unrecognized color -> 'red' (treated as cutting by default)."""
    stroke = elem.style.get('stroke')
    color  = str(stroke).strip().lower() if stroke else ""
    # Normalize shorthand hex: #f00 -> #ff0000
    if re.match(r'^#[0-9a-f]{3}$', color):
        color = '#' + ''.join(c*2 for c in color[1:])
    if color in ('#000000', 'black') or 'rgb(0,0,0)' in color:
        return "black"
    if color in ('#00ff00', 'lime', 'green') or 'rgb(0,255,0)' in color:
        return "green"
    if color in ('#ffff00', 'yellow') or 'rgb(255,255,0)' in color:
        return "yellow"
    if color in ('#ff0000', 'red') or 'rgb(255,0,0)' in color:
        return "red"
    return "red"


def _path_is_closed(abs_path):
    segs = list(abs_path)
    if any(isinstance(seg, ZoneClose) for seg in segs):
        return True
    if len(segs) >= 2:
        try:
            def _pt(seg):
                return (seg.end.x, seg.end.y) if hasattr(seg, 'end') else None
            p0 = _pt(segs[0]); p1 = _pt(segs[-1])
            if p0 and p1 and math.hypot(p1[0]-p0[0], p1[1]-p0[1]) < 0.01:
                return True
        except Exception:
            pass
    return False


def _simple_tool(elem):
    """Simple mode (like v3): black->P0 (crease), others->P1 (cut)."""
    color = _stroke_to_color(elem)
    if color == "black":
        return "P0", 0
    if color == "red":
        return "P1", 2
    return "P1", 1


def process_elements(cut_layer, color_settings, scale_x=1.0, scale_y=1.0):
    """If color_settings is a dict -> color mode (tool/force/speed/seq per color).
    If color_settings is None -> simple mode (black=P0, others=P1, no FS/VS)."""
    path_data = []
    for elem in cut_layer.iterdescendants():
        if not isinstance(elem, PathElement):
            continue

        if color_settings is None:
            tool, seq = _simple_tool(elem)
            force = speed = None
            color = None
        else:
            color = _stroke_to_color(elem)
            cfg   = color_settings.get(color, color_settings['red'])
            tool  = cfg['tool']
            seq   = cfg['seq']
            force = cfg['force']
            speed = cfg['speed']
            dashed = cfg.get('dashed', False)
        if color_settings is None:
            dashed = False

        abs_path = elem.path.to_absolute()
        composed = elem.composed_transform()
        if composed:
            abs_path = abs_path.transform(composed)
        elif elem.transform:
            abs_path = abs_path.transform(elem.transform)

        is_closed_svg = _path_is_closed(abs_path)
        csp = CubicSuperPath(abs_path)

        for subpath in csp:
            if len(subpath) < 2:
                continue
            pts = []; has_curve = False
            for i in range(1, len(subpath)):
                p0 = (subpath[i-1][1][0]*scale_x, subpath[i-1][1][1]*scale_y)
                c1 = (subpath[i-1][2][0]*scale_x, subpath[i-1][2][1]*scale_y)
                c2 = (subpath[i][0][0]  *scale_x, subpath[i][0][1]  *scale_y)
                p1 = (subpath[i][1][0]  *scale_x, subpath[i][1][1]  *scale_y)
                if is_straight(p0, c1, c2, p1):
                    pts.append(p0)
                else:
                    has_curve = True
                    for s in range(STEPS_PER_SEG):
                        pts.append(cubic_point(p0, c1, c2, p1, s/STEPS_PER_SEG))
            pts.append((subpath[-1][1][0]*scale_x, subpath[-1][1][1]*scale_y))

            if has_curve:
                pts = resample_by_length(pts, CURVE_STEP_MM)

            if pts:
                path_data.append({
                    'pts':       pts,
                    'tool':      tool,
                    'color':     color,
                    'force':     force,
                    'speed':     speed,
                    'priority':  seq,
                    'is_closed': is_closed_svg,
                    'has_curve': has_curve,
                    'dashed':    dashed,
                })
    return path_data


# ---------------------------------------------------------------------------
# Nesting / Route optimisation
# ---------------------------------------------------------------------------

def point_in_polygon(point, poly):
    x, y = point
    inside = False
    n = len(poly)
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if p1y == p2y:
            p1x, p1y = p2x, p2y; continue
        if not (min(p1y, p2y) < y <= max(p1y, p2y)):
            p1x, p1y = p2x, p2y; continue
        xinters = p1x + (y - p1y) * (p2x - p1x) / (p2y - p1y)
        if x < xinters:
            inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def _build_spatial_cache(paths):
    n = len(paths)
    centroids = [None] * n
    bboxes    = [None] * n
    for i in range(n):
        if not paths[i]['is_closed']:
            continue
        poly = paths[i]['pts']
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        centroids[i] = (cx, cy)
        bboxes[i] = (min(p[0] for p in poly), max(p[0] for p in poly),
                     min(p[1] for p in poly), max(p[1] for p in poly))
    return centroids, bboxes


def compute_depths(paths):
    n = len(paths)
    depths = [0 if paths[i]['is_closed'] else -1 for i in range(n)]
    centroids, bboxes = _build_spatial_cache(paths)
    for i in range(n):
        if depths[i] == -1:
            continue
        cx, cy = centroids[i]
        count = 0
        for j in range(n):
            if i == j or bboxes[j] is None:
                continue
            mnx, mxx, mny, mxy = bboxes[j]
            if cx < mnx or cx > mxx or cy < mny or cy > mxy:
                continue
            if point_in_polygon((cx, cy), paths[j]['pts']):
                count += 1
        depths[i] = count
    return depths, centroids


def group_into_islands(paths, depths, centroids):
    closed_indices = [i for i, d in enumerate(depths) if d >= 0]
    root_set = [i for i in closed_indices if depths[i] == 0]
    roots = {}
    for i in closed_indices:
        if depths[i] == 0:
            roots[i] = i
        else:
            cx, cy = centroids[i]
            for j in root_set:
                if point_in_polygon((cx, cy), paths[j]['pts']):
                    roots[i] = j; break
            else:
                roots[i] = i
    island_dict = {}
    for i in closed_indices:
        root = roots.get(i, i)
        island_dict.setdefault(root, []).append(i)
    for i, d in enumerate(depths):
        if d == -1:
            island_dict[i] = [i]
    return list(island_dict.values())


def sort_island_paths(island_idx_list, paths, depths, nesting_order):
    closed    = [i for i in island_idx_list if depths[i] >= 0]
    open_pths = [i for i in island_idx_list if depths[i] == -1]
    groups = {}
    for i in closed:
        groups.setdefault(depths[i], []).append(i)
    result = []
    for d in sorted(groups.keys(), reverse=(nesting_order == 'inside_first')):
        grp = groups[d]
        if len(grp) > 1:
            items = nearest_neighbor_sort(grp, lambda i: paths[i]['pts'][0])
            if len(items) > 3:
                items = two_opt(items, lambda i: paths[i]['pts'][0])
            result.extend(items)
        else:
            result.extend(grp)
    result.extend(open_pths)
    return result


def nearest_neighbor_sort(items, key_fn):
    if len(items) <= 1:
        return items
    result = [items[0]]
    remaining = list(items[1:])
    while remaining:
        last = key_fn(result[-1])
        best = min(range(len(remaining)),
                   key=lambda k: math.hypot(key_fn(remaining[k])[0]-last[0],
                                            key_fn(remaining[k])[1]-last[1]))
        result.append(remaining.pop(best))
    return result


def two_opt(items, key_fn):
    if len(items) <= 3:
        return items
    pts   = [key_fn(it) for it in items]
    n     = len(pts)
    order = list(range(n))

    def d(a, b):
        pa, pb = pts[a], pts[b]
        return math.hypot(pa[0]-pb[0], pa[1]-pb[1])

    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b    = order[i-1], order[i]
                c       = order[j]
                d_next  = order[j+1] if j+1 < n else None
                old = d(a, b) + (d(c, d_next) if d_next else 0)
                new = d(a, c) + (d(b, d_next) if d_next else 0)
                if new < old - 0.001:
                    order[i:j+1] = order[i:j+1][::-1]
                    improved = True
    return [items[k] for k in order]


# ---------------------------------------------------------------------------
# Main extension
# ---------------------------------------------------------------------------

class SkyCutV5Eng(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--tab",          type=str,           default="basic")
        pars.add_argument("--use_colors",    type=inkex.Boolean, default=False)
        pars.add_argument("--use_markers",   type=inkex.Boolean, default=False)
        pars.add_argument("--paper_size",    type=str,           default="a4p")
        pars.add_argument("--auto_nesting",  type=inkex.Boolean, default=True)
        pars.add_argument("--nesting_order", type=str,           default="inside_first")
        pars.add_argument("--ip",            type=str,           default="192.168.0.233")
        pars.add_argument("--port",          type=int,           default=8080)
        pars.add_argument("--knife_offset_mm", type=float,       default=0.25)
        pars.add_argument("--overcut_mm",    type=float,         default=1.00)
        pars.add_argument("--corner_sensitivity", type=int,      default=50)
        pars.add_argument("--rotate_seam",   type=inkex.Boolean, default=True)
        # Color settings: tool, force (0-160), speed (0-13), seq (1-4)
        pars.add_argument("--black_tool",  type=str, default="P0")
        pars.add_argument("--black_force", type=int, default=55)
        pars.add_argument("--black_speed", type=int, default=7)
        pars.add_argument("--black_seq",   type=int, default=1)
        pars.add_argument("--green_tool",  type=str, default="P1")
        pars.add_argument("--green_force", type=int, default=25)
        pars.add_argument("--green_speed", type=int, default=7)
        pars.add_argument("--green_seq",   type=int, default=2)
        pars.add_argument("--yellow_tool",  type=str, default="P1")
        pars.add_argument("--yellow_force", type=int, default=25)
        pars.add_argument("--yellow_speed", type=int, default=7)
        pars.add_argument("--yellow_seq",   type=int, default=3)
        pars.add_argument("--red_tool",  type=str, default="P1")
        pars.add_argument("--red_force", type=int, default=52)
        pars.add_argument("--red_speed", type=int, default=7)
        pars.add_argument("--red_seq",   type=int, default=4)
        # Dashed - dropdown per color: "yes"/"no"
        pars.add_argument("--black_dashed",  type=str, default="no")
        pars.add_argument("--green_dashed",  type=str, default="no")
        pars.add_argument("--yellow_dashed", type=str, default="no")
        pars.add_argument("--red_dashed",    type=str, default="no")
        # Global dashed settings
        pars.add_argument("--dash_len",    type=float,         default=3.0)
        pars.add_argument("--gap_len",     type=float,         default=2.0)
        pars.add_argument("--use_dash_force", type=inkex.Boolean, default=True)
        pars.add_argument("--dash_force",  type=int,           default=40)
        pars.add_argument("--use_gap_force",  type=inkex.Boolean, default=True)
        pars.add_argument("--gap_force",   type=int,           default=5)
        pars.add_argument("--cut_quickly", type=inkex.Boolean, default=False)
        pars.add_argument("--travel_speed", type=int,          default=350)
        pars.add_argument("--save_hpgl",     type=inkex.Boolean, default=False)
        pars.add_argument("--output_path",   type=str,           default="skycut_v3_output.hpgl")
        pars.add_argument("--debug",         type=inkex.Boolean, default=False)

    def effect(self):
        output = self._build_hpgl()
        if output is None:
            return
        if self.options.save_hpgl:
            import os
            out_path = self.options.output_path.strip()
            if not out_path:
                inkex.errormsg("Output file not set"); return
            out_dir = os.path.dirname(out_path) or "."
            if not os.path.isdir(out_dir):
                inkex.errormsg(f"Directory does not exist: {out_dir}"); return
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output)
                inkex.errormsg(f"HPGL saved: {out_path}")
            except OSError as e:
                inkex.errormsg(f"Write error: {e}"); return
            html = self._build_viewer_html(output)
            tmp  = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8")
            tmp.write(html); tmp.close()
            webbrowser.open(f"file://{tmp.name}")
        else:
            self._send_to_cutter(output)

    # ------------------------------------------------------------------

    def _build_hpgl(self):
        svg           = self.svg
        k_off         = self.options.knife_offset_mm
        ov_mm         = self.options.overcut_mm
        corner_sens   = self.options.corner_sensitivity
        debug         = self.options.debug
        use_markers   = self.options.use_markers
        auto_nesting  = self.options.auto_nesting
        nesting_order = self.options.nesting_order

        paper_sizes = {
            'a4p': (210.0, 297.0), 'a4l': (297.0, 210.0),
            'a3p': (297.0, 420.0), 'a3l': (420.0, 297.0),
        }
        page_w, page_h = paper_sizes.get(self.options.paper_size, (210.0, 297.0))

        viewbox = svg.get_viewbox()
        scale   = min(page_w / viewbox[2] if viewbox[2] else 1.0,
                      page_h / viewbox[3] if viewbox[3] else 1.0)

        if debug:
            inkex.errormsg(f"DEBUG scale={scale:.4f} overcut={ov_mm}mm "
                           f"knife_offset={k_off}mm nesting={auto_nesting}")

        cut_layer = next(
            (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
             if l.label and l.label.strip().lower() == 'cut'), None)
        if cut_layer is None:
            inkex.errormsg("Missing layer named 'Cut'"); return None

        o = self.options
        if o.use_colors:
            color_settings = {
                'black':  {'tool': o.black_tool,  'force': o.black_force,
                           'speed': o.black_speed, 'seq': o.black_seq,
                           'dashed': o.black_dashed == "yes"},
                'green':  {'tool': o.green_tool,  'force': o.green_force,
                           'speed': o.green_speed, 'seq': o.green_seq,
                           'dashed': o.green_dashed == "yes"},
                'yellow': {'tool': o.yellow_tool, 'force': o.yellow_force,
                           'speed': o.yellow_speed, 'seq': o.yellow_seq,
                           'dashed': o.yellow_dashed == "yes"},
                'red':    {'tool': o.red_tool,    'force': o.red_force,
                           'speed': o.red_speed,   'seq': o.red_seq,
                           'dashed': o.red_dashed == "yes"},
            }
        else:
            color_settings = None   # simple mode: black=P0, others=P1

        all_paths = process_elements(cut_layer, color_settings, scale, scale)
        if not all_paths:
            inkex.errormsg("No paths found in Cut layer"); return None

        all_paths.sort(key=lambda x: x['priority'])
        priority_groups = [list(g) for _, g in groupby(all_paths, key=lambda x: x['priority'])]

        final_sequence = []
        for group in priority_groups:
            if auto_nesting and any(p['is_closed'] for p in group):
                depths, centroids = compute_depths(group)
                islands           = group_into_islands(group, depths, centroids)
                ordered_islands   = []
                for island_idx_list in islands:
                    ordered_idx = sort_island_paths(island_idx_list, group, depths, nesting_order)
                    ordered_islands.append(ordered_idx)
                # Route islands by nearest-neighbor + 2-opt
                island_starts = [(group[isl[0]]['pts'][0], isl) for isl in ordered_islands]
                island_starts = nearest_neighbor_sort(island_starts, lambda x: x[0])
                if len(island_starts) > 3:
                    island_starts = two_opt(island_starts, lambda x: x[0])
                for _, isl in island_starts:
                    for idx in isl:
                        final_sequence.append(group[idx])
            else:
                items = nearest_neighbor_sort(list(group), lambda p: p['pts'][0])
                if len(items) > 3:
                    items = two_opt(items, lambda p: p['pts'][0])
                final_sequence.extend(items)

        # Coordinate transform
        if use_markers:
            mark_layer = next(
                (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
                 if l.label and 'mark' in l.label.lower()), None)
            if mark_layer is None:
                inkex.errormsg("Missing layer named 'Mark'"); return None
            marker_points = []
            for elem in mark_layer.iterdescendants():
                if isinstance(elem, PathElement) and elem.get('data-type') != 'triangle':
                    path = elem.path.to_absolute()
                    seg  = path[1] if len(path) > 1 else path[0]
                    try:
                        pt_x = seg.end.x if hasattr(seg, 'end') else seg.x
                        pt_y = seg.end.y if hasattr(seg, 'end') else seg.y
                        marker_points.append((pt_x*scale, pt_y*scale))
                    except AttributeError:
                        continue
            if not marker_points:
                inkex.errormsg("Mark layer has no valid elements"); return None
            min_x = min(p[0] for p in marker_points)
            min_y = min(p[1] for p in marker_points)
            max_x = max(p[0] for p in marker_points)
            max_y = max(p[1] for p in marker_points)
            work_w = max_x - min_x; work_h = max_y - min_y

            def coord(px, py):
                return (int(round((work_h-(py-min_y))*SCALE)),
                        int(round((work_w-(px-min_x))*SCALE)))

            cmd103 = "CMD:103,0;" if o.use_colors else ""
            hpgl = [
                "IN;", "PA;",
                f"FSIZE{int(page_h*SCALE)},{int(page_w*SCALE)};",
                f"CMD:32,{int(page_h*SCALE)},{int(page_w*SCALE)},"
                f"{int(min_x*SCALE)},{int(min_y*SCALE)};",
                "CMD:18,1;", cmd103, "CMD:35,1,2,0;",
                f"TB26,{int(work_h*SCALE)},{int(work_w*SCALE)};",
            ]
        else:
            all_x = [p[0] for item in final_sequence for p in item['pts']]
            all_y = [p[1] for item in final_sequence for p in item['pts']]
            max_x_bb = max(all_x); max_y_bb = max(all_y)

            def coord(px, py):
                return (int(round((max_y_bb-py)*SCALE)),
                        int(round((max_x_bb-px)*SCALE)))

            cmd103 = "CMD:103,0;" if o.use_colors else ""
            hpgl = ["IN;", "PA;", "CMD:18,1;", cmd103, "CMD:35,1,2,0;"]

        # Emit paths.
        # Color mode: before each block with new settings -> P;FS;VS
        # Simple mode: only P on tool change (like v3)
        current_key = None
        for item in final_sequence:
            if o.use_colors:
                key = (item['tool'], item['force'], item['speed'])
                if key != current_key:
                    hpgl.append(f"{item['tool']};")
                    hpgl.append(f"FS{item['force']};")
                    hpgl.append(f"VS{item['speed']};")
                    current_key = key
            else:
                if item['tool'] != current_key:
                    hpgl.append(f"{item['tool']};")
                    current_key = item['tool']

            pts       = item['pts']
            is_closed = item['is_closed']
            is_p1     = item['tool'] == "P1"
            is_dashed = item.get('dashed', False)

            if debug:
                inkex.errormsg(f"DEBUG path: pts={len(pts)} closed={is_closed} "
                               f"curve={item['has_curve']} tool={item['tool']} "
                               f"dashed={is_dashed}")

            # Prepare the points (closed -> open + knife offset + overcut;
            # open -> knife offset). Then, if dashed, cut dashed.
            if is_closed:
                oc = ov_mm if is_p1 else 0.0
                if is_p1 and self.options.rotate_seam:
                    pts = rotate_to_longest_straight(pts)
                body = open_closed_path(pts, 0.0)
                if is_p1 and k_off > 0:
                    if len(body) >= 4:
                        base = body[:-1]
                        cyclic = base + [base[0], base[1]]
                        processed = apply_corner_offset(cyclic, k_off, corner_sens)
                        body = processed[:-1]
                    else:
                        body = apply_corner_offset(body, k_off, corner_sens)
                if is_p1 and oc > 0:
                    tail = follow_path(pts + [pts[0]], oc)
                else:
                    tail = []
                open_pts = body + tail
            else:
                if is_p1 and k_off > 0:
                    open_pts = apply_corner_offset(pts, k_off, corner_sens)
                else:
                    open_pts = list(pts)

            if is_dashed:
                # Dashed: US travel speed + dash/gap splitting
                hpgl.append(f"US{o.travel_speed};")
                df = o.dash_force if o.use_dash_force else None
                gf = o.gap_force  if o.use_gap_force  else None
                emit_dashed_path(hpgl, open_pts, coord,
                                 o.dash_len, o.gap_len, df, gf,
                                 o.cut_quickly, item['force'] if item['force'] else 52)
            else:
                emit_open_path(hpgl, open_pts, coord)

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "".join(hpgl)

        if debug:
            inkex.errormsg(f"DEBUG total HPGL commands: {len(hpgl)}")

        return output

    # ------------------------------------------------------------------

    def _build_viewer_html(self, hpgl_data):
        import textwrap
        hpgl_escaped = hpgl_data.replace('\\', '\\\\').replace('`', '\\`')
        css = textwrap.dedent("""
            * { box-sizing: border-box; }
            body { margin:0; padding:10px; background:#0a0f1a; color:#c8d8e8;
              font-family:monospace; height:100vh; display:flex; flex-direction:column; gap:8px; }
            textarea { width:100%; height:80px; background:#0a1520; border:1px solid #1a3050;
              color:#7ec8a0; padding:8px; font-size:10px; resize:vertical; }
            .controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
            button { background:transparent; border:1px solid #00eebb; color:#00eebb;
              padding:5px 10px; cursor:pointer; border-radius:4px; font-size:11px; }
            button:hover { background:rgba(0,238,187,0.15); }
            button.stop { border-color:#ff5050; color:#ff5050; }
            label { font-size:10px; color:#8899aa; display:flex; align-items:center; gap:4px; cursor:pointer; }
            .canvas-wrap { flex:1; position:relative; min-height:300px;
              border:1px solid #1a3050; border-radius:4px; overflow:hidden; background:#060b14; }
            canvas { display:block; width:100%; height:100%; }
            .stats { font-size:10px; color:#557799; display:flex; gap:10px; flex-wrap:wrap; }
            .stats span { color:#00eebb; }
            .scale-ind { position:absolute; bottom:10px; right:10px;
              background:rgba(10,15,26,0.85); border:1px solid #1a3050;
              padding:4px 8px; border-radius:3px; font-size:9px; display:flex; align-items:center; gap:6px; }
            .scale-line { height:2px; background:#00eebb; }
            .coords { position:absolute; top:10px; left:10px;
              background:rgba(10,15,26,0.85); border:1px solid #1a3050;
              padding:4px 8px; border-radius:3px; font-size:9px; color:#8899aa; }
        """).strip()

        js = textwrap.dedent("""
            const canvas=document.getElementById("canvas"),ctx=canvas.getContext("2d");
            let segments=[],animating=false,animFrame=null,currentStep=0;
            let userZoom=1,userPanX=0,userPanY=0,isPanning=false,panStartX=0,panStartY=0;
            let progressLimit=0;
            const HPM=40;
            function parseHPGL(text){
              const moves=[],lines=text.replace(/\\r/g,"").split(/[\\n;]+/);
              let x=0,y=0;
              for(let line of lines){
                line=line.trim().toUpperCase();
                if(!line||line==="IN"||line==="PA"||line.startsWith("P1")||line.startsWith("P0")||
                   line.startsWith("CMD:")||line==="@"||line.startsWith("TB")||line.startsWith("FSIZE"))continue;
                const u=line.match(/^U\\s*(-?\\d+)\\s*,\\s*(-?\\d+)/);
                const d=line.match(/^D\\s*(-?\\d+)\\s*,\\s*(-?\\d+)/);
                if(u){moves.push({type:"U",x:+u[1],y:+u[2],fx:x,fy:y});x=+u[1];y=+u[2];}
                else if(d){moves.push({type:"D",x:+d[1],y:+d[2],fx:x,fy:y});x=+d[1];y=+d[2];}
              }return moves;
            }
            function drawDot(x,y,color,label,oy){
              ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=color+"35";ctx.fill();
              ctx.beginPath();ctx.arc(x,y,4.5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();
              ctx.strokeStyle="#fff";ctx.lineWidth=1.2;ctx.stroke();
              ctx.fillStyle=color;ctx.font="bold 10px monospace";ctx.fillText(label,x+9,y+oy);
            }
            function draw(){
              const rect=canvas.parentElement.getBoundingClientRect();
              canvas.width=rect.width;canvas.height=rect.height;
              const W=canvas.width,H=canvas.height;
              ctx.clearRect(0,0,W,H);
              if(!segments.length){ctx.fillStyle="#334455";ctx.font="12px monospace";
                ctx.textAlign="center";ctx.fillText("PASTE HPGL -> RENDER",W/2,H/2);return;}
              // Document view: inverse transform of the plugin's coord().
              // coord: HPGL_x=(maxY-docY), HPGL_y=(maxX-docX)
              // inverse: docX ~ -HPGL_y, docY ~ -HPGL_x
              // screen: screen_x=docX=-hy, screen_y=docY=-hx (SVG Y down = screen Y down)
              // Visualization only - the HPGL output to the machine is unchanged.
              let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
              for(const s of segments){
                const ax=-s.fy, ay=-s.fx, bx=-s.y, by=-s.x;
                minX=Math.min(minX,ax,bx);minY=Math.min(minY,ay,by);
                maxX=Math.max(maxX,ax,bx);maxY=Math.max(maxY,ay,by);
              }
              const dW=maxX-minX||1,dH=maxY-minY||1,pad=60;
              const baseScale=Math.min((W-pad*2)/dW,(H-pad*2)/dH);
              const scale=baseScale*userZoom;
              const offX=pad+(W-pad*2-dW*scale)/2+userPanX,offY=pad+(H-pad*2-dH*scale)/2+userPanY;
              // SX/SY: raw hpgl coordinates -> document screen view
              const SX=(hx,hy)=>offX+((-hy)-minX)*scale;
              const SY=(hx,hy)=>offY+((-hx)-minY)*scale;
              document.getElementById("scaleLine").style.width=(50*HPM*scale)+"px";
              document.getElementById("coords").innerHTML=
                "Zoom: "+userZoom.toFixed(1)+"x";
              // limit: during animation = currentStep; else = progress scrubber value
              const limit=animating?currentStep:progressLimit;
              if(document.getElementById("grid").checked){
                ctx.strokeStyle="rgba(30,60,100,0.25)";ctx.lineWidth=0.5;
                const step=400*scale;
                for(let x=offX%step;x<W;x+=step){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
                for(let y=offY%step;y<H;y+=step){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
              }
              if(document.getElementById("showTravel").checked){
                ctx.strokeStyle="rgba(255,170,0,0.35)";ctx.lineWidth=0.8;ctx.setLineDash([4,4]);
                for(let i=0;i<limit;i++)if(segments[i].type==="U"){
                  ctx.beginPath();ctx.moveTo(SX(segments[i].fx,segments[i].fy),SY(segments[i].fx,segments[i].fy));
                  ctx.lineTo(SX(segments[i].x,segments[i].y),SY(segments[i].x,segments[i].y));ctx.stroke();}
                ctx.setLineDash([]);
              }
              for(let i=0;i<limit;i++)if(segments[i].type==="D"){
                ctx.strokeStyle="rgba(0,238,187,0.15)";ctx.lineWidth=4;
                ctx.beginPath();ctx.moveTo(SX(segments[i].fx,segments[i].fy),SY(segments[i].fx,segments[i].fy));
                ctx.lineTo(SX(segments[i].x,segments[i].y),SY(segments[i].x,segments[i].y));ctx.stroke();
                ctx.strokeStyle="#00eebb";ctx.lineWidth=1.5;
                ctx.beginPath();ctx.moveTo(SX(segments[i].fx,segments[i].fy),SY(segments[i].fx,segments[i].fy));
                ctx.lineTo(SX(segments[i].x,segments[i].y),SY(segments[i].x,segments[i].y));ctx.stroke();
              }
              if(document.getElementById("showPoints").checked){
                const cuts=segments.filter(m=>m.type==="D");
                if(cuts.length>0){
                  drawDot(SX(cuts[0].fx,cuts[0].fy),SY(cuts[0].fx,cuts[0].fy),"#00ff00","START",12);
                  drawDot(SX(cuts[cuts.length-1].x,cuts[cuts.length-1].y),SY(cuts[cuts.length-1].x,cuts[cuts.length-1].y),"#ff0000","END",-12);
                }
              }
              // Marker at current position (animation OR scrubber)
              if(limit>0&&limit<=segments.length){
                const s=segments[limit-1];
                ctx.beginPath();ctx.arc(SX(s.x,s.y),SY(s.x,s.y),4,0,Math.PI*2);
                ctx.fillStyle=s.type==="D"?"#00ffcc":"#ffdd00";ctx.fill();
              }
            }
            function process(){
              segments=parseHPGL(document.getElementById("hpglInput").value);
              const cuts=segments.filter(m=>m.type==="D");
              let total=0;for(const m of cuts)total+=Math.hypot(m.x-m.fx,m.y-m.fy);
              let mnX=Infinity,mnY=Infinity,mxX=-Infinity,mxY=-Infinity;
              for(const m of segments){mnX=Math.min(mnX,m.fx,m.x);mnY=Math.min(mnY,m.fy,m.y);
                mxX=Math.max(mxX,m.fx,m.x);mxY=Math.max(mxY,m.fy,m.y);}
              document.getElementById("stats").innerHTML=
                "Commands: <span>"+segments.length+"</span> | "+
                "Cut: <span>"+cuts.length+"</span> | "+
                "Size: <span>"+((mxX-mnX)/HPM).toFixed(1)+"x"+((mxY-mnY)/HPM).toFixed(1)+" mm</span> | "+
                "Length: <span>"+(total/HPM).toFixed(1)+" mm</span>";
              // Set scrubber range
              const sc=document.getElementById("progress");
              sc.max=segments.length; sc.value=segments.length;
              progressLimit=segments.length;
              currentStep=0;draw();
            }
            function animate(){
              if(!segments.length)return;
              animating=!animating;
              const btn=document.getElementById("animBtn");
              if(animating){btn.textContent="STOP";btn.classList.add("stop");currentStep=0;
                const spd=+document.getElementById("speed").value;
                function loop(){if(!animating)return;currentStep++;
                  document.getElementById("progress").value=currentStep;draw();
                  if(currentStep<segments.length)animFrame=setTimeout(loop,120-spd);
                  else{animating=false;btn.textContent="ANIMATE";btn.classList.remove("stop");
                    progressLimit=segments.length;}
                }loop();
              }else{clearTimeout(animFrame);btn.textContent="ANIMATE";btn.classList.remove("stop");
                progressLimit=currentStep;draw();}
            }
            // Progress scrubber
            document.getElementById("progress").addEventListener("input",function(){
              if(animating){animating=false;clearTimeout(animFrame);
                document.getElementById("animBtn").textContent="ANIMATE";
                document.getElementById("animBtn").classList.remove("stop");}
              progressLimit=+this.value;draw();
            });
            // Zoom with mouse wheel (toward cursor)
            canvas.addEventListener("wheel",function(e){
              e.preventDefault();
              const rect=canvas.getBoundingClientRect();
              const mx=e.clientX-rect.left,my=e.clientY-rect.top;
              const factor=e.deltaY<0?1.15:1/1.15;
              const newZoom=Math.max(0.5,Math.min(30,userZoom*factor));
              // Keep the point under the cursor fixed
              userPanX=mx-(mx-userPanX)*(newZoom/userZoom);
              userPanY=my-(my-userPanY)*(newZoom/userZoom);
              userZoom=newZoom;draw();
            },{passive:false});
            // Pan by dragging
            canvas.addEventListener("mousedown",function(e){
              isPanning=true;panStartX=e.clientX-userPanX;panStartY=e.clientY-userPanY;
              canvas.style.cursor="grabbing";
            });
            window.addEventListener("mousemove",function(e){
              if(!isPanning)return;
              userPanX=e.clientX-panStartX;userPanY=e.clientY-panStartY;draw();
            });
            window.addEventListener("mouseup",function(){isPanning=false;canvas.style.cursor="grab";});
            document.getElementById("resetView").onclick=function(){
              userZoom=1;userPanX=0;userPanY=0;draw();
            };
            document.getElementById("renderBtn").onclick=process;
            document.getElementById("animBtn").onclick=animate;
            ["showTravel","grid","showPoints"].forEach(id=>document.getElementById(id).onchange=draw);
            window.addEventListener("resize",draw);
            canvas.style.cursor="grab";
        """).strip()

        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>HPGL Viewer SkyCut v3</title>
<style>{css}</style></head><body>
<h3 style="margin:0;color:#00eebb;font-size:14px">HPGL Viewer - SkyCut v5</h3>
<textarea id="hpglInput"></textarea>
<div class="controls">
  <button id="renderBtn">RENDER</button>
  <button id="animBtn">ANIMATE</button>
  <button id="resetView">RESET VIEW</button>
  <label><input type="checkbox" id="showTravel" checked> Pen up</label>
  <label><input type="checkbox" id="grid" checked> Grid</label>
  <label><input type="checkbox" id="showPoints" checked> Points</label>
  <label>Speed: <input type="range" id="speed" min="5" max="100" value="40" style="width:60px"></label>
</div>
<div class="controls">
  <label style="flex:1">Progress: <input type="range" id="progress" min="0" max="100" value="100" style="width:100%"></label>
</div>
<div class="stats" id="stats">-</div>
<div class="canvas-wrap">
  <canvas id="canvas"></canvas>
  <div class="coords" id="coords"></div>
  <div class="scale-ind"><div class="scale-line" id="scaleLine"></div><span>50mm</span></div>
</div>
<script>
{js}
document.getElementById("hpglInput").value=`{hpgl_escaped}`;
process();
</script></body></html>"""

    def _send_to_cutter(self, output):
        CHUNK = 4096
        data  = output.encode()
        try:
            with socket.create_connection(
                    (self.options.ip, self.options.port), timeout=180) as s:
                sent = 0
                while sent < len(data):
                    s.sendall(data[sent:sent+CHUNK])
                    sent += CHUNK
                s.shutdown(socket.SHUT_WR)
            inkex.errormsg(f"Sent OK ({len(data)} bytes)")
        except OSError as e:
            inkex.errormsg(f"Send error ({self.options.ip}:{self.options.port}): {e}")


if __name__ == "__main__":
    SkyCutV5Eng().run()
