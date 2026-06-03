#!/usr/bin/env python3
import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath, ZoneClose
import socket
import math
import tempfile
import webbrowser
from itertools import groupby

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCALE = 40
STEPS_PER_SEGMENT = 20
MIN_DIST_MM = 0.05
CURVE_STEP_MM = 1.0

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

def resample_by_length(pts, step_len, is_closed):
    if len(pts) < 2 or step_len <= 0:
        return pts
    work = list(pts)
    if is_closed and math.hypot(work[-1][0]-work[0][0],
                                work[-1][1]-work[0][1]) < 0.001:
        work = work[:-1]
    if len(work) < 2:
        return pts
    segments = []
    total = 0.0
    for i in range(len(work)-1):
        p0 = work[i]; p1 = work[i+1]
        d = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
        segments.append((p0, p1, d)); total += d
    if is_closed:
        p0 = work[-1]; p1 = work[0]
        d = math.hypot(p1[0]-p0[0], p1[1]-p0[1])
        segments.append((p0, p1, d)); total += d
    if total < 0.001:
        return pts
    steps = max(3, int(round(total / step_len)))
    step = total / steps
    result = []
    seg_i = 0; seg_start = 0.0
    for k in range(steps):
        target = k * step
        while seg_i < len(segments):
            p0, p1, d = segments[seg_i]
            if d < 0.001:
                seg_start += d; seg_i += 1; continue
            if target <= seg_start + d + 1e-9:
                t = (target - seg_start) / d
                x = p0[0] + (p1[0]-p0[0]) * t
                y = p0[1] + (p1[1]-p0[1]) * t
                result.append((x, y)); break
            seg_start += d; seg_i += 1
    return result

def dedup_pts(pts, min_dist=0.001):
    if not pts: return pts
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0]-out[-1][0], p[1]-out[-1][1]) > min_dist:
            out.append(p)
    return out

def collinear_clean(pts):
    if len(pts) <= 2: return pts
    cleaned = [pts[0], pts[1]]
    for pt in pts[2:]:
        a = cleaned[-2]; b = cleaned[-1]
        area = abs((b[0]-a[0])*(pt[1]-a[1]) - (b[1]-a[1])*(pt[0]-a[0]))
        if area < 0.001 and math.hypot(pt[0]-a[0], pt[1]-a[1]) > 0.001:
            cleaned[-1] = pt
        else:
            cleaned.append(pt)
    return cleaned

def rotate_to_least_curved(pts, min_arc_len=5.0):
    """Ротира точките така, че старт/край да е на най-малко извитото място.
    Използва прозорец от 15 точки (~15mm при CURVE_STEP_MM=1) за по-надеждна оценка."""
    n = len(pts)
    if n < 5:
        return pts
    # Прозорец от 15 точки или 1/4 от контура, което е по-малко
    half_w = min(7, n // 4)
    if half_w < 2:
        return pts
    best_i = 0
    best_deviation = float('inf')
    for i in range(n):
        # Вземаме точки от -half_w до +half_w около i
        p0 = pts[(i - half_w) % n]
        p_mid = pts[i]
        p1 = pts[(i + half_w) % n]
        dx = p1[0] - p0[0]; dy = p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < min_arc_len:
            continue
        # Перпендикулярно разстояние на средната точка от хордата p0-p1
        dist = abs(dy * p_mid[0] - dx * p_mid[1] + p1[0]*p0[1] - p1[1]*p0[0]) / length
        if dist < best_deviation:
            best_deviation = dist
            best_i = i
    if best_deviation < float('inf'):
        return pts[best_i:] + pts[:best_i]
    return pts

def apply_corner_offset_scal(pts, k_off, is_closed):
    if k_off <= 0 or len(pts) < 3:
        return list(pts), [], (0.0, 0.0)
    MIN_ANGLE = math.radians(5)
    work = list(pts)
    if is_closed and math.hypot(work[-1][0]-work[0][0],
                                work[-1][1]-work[0][1]) < 0.001:
        work = work[:-1]
    n = len(work)

    def seg_dir(a, b):
        dx = b[0]-a[0]; dy = b[1]-a[1]
        d = math.hypot(dx, dy)
        if d < 0.001: return None, None
        return dx/d, dy/d

    def corner_arc(apex, in_nx, in_ny, out_nx, out_ny):
        dot   = max(-1.0, min(1.0, in_nx*out_nx + in_ny*out_ny))
        angle = math.acos(dot)
        cross = in_nx*out_ny - in_ny*out_nx
        if angle < MIN_ANGLE or abs(cross) < 1e-9: return []
        entry = (apex[0] + in_nx  * k_off, apex[1] + in_ny  * k_off)
        exit_ = (apex[0] + out_nx * k_off, apex[1] + out_ny * k_off)
        angle_in  = math.atan2(in_ny,  in_nx)
        angle_out = math.atan2(out_ny, out_nx)
        delta = angle_out - angle_in
        if cross > 0:
            while delta <= 0: delta += math.tau
        else:
            while delta >= 0: delta -= math.tau
        arc_steps = max(2, int(abs(math.degrees(delta)) / 15))
        arc = [entry]
        for s in range(1, arc_steps):
            a = angle_in + delta * (s / arc_steps)
            arc.append((apex[0] + math.cos(a) * k_off,
                        apex[1] + math.sin(a) * k_off))
        arc.append(exit_)
        return arc

    result = []; start_arc = []; overcut_dir = (0.0, 0.0)
    for i in range(n):
        apex     = work[i]
        prev_idx = (i - 1) % n
        next_idx = (i + 1) % n
        if not is_closed and (i == 0 or i == n-1):
            result.append(apex); continue
        in_nx,  in_ny  = seg_dir(work[prev_idx], apex)
        out_nx, out_ny = seg_dir(apex, work[next_idx])
        if in_nx is None or out_nx is None:
            result.append(apex); continue
        arc = corner_arc(apex, in_nx, in_ny, out_nx, out_ny)
        if not arc:
            result.append(apex); continue
        if is_closed and i == 0:
            result.append(arc[0])
            start_arc = arc[1:]
            overcut_dir = (out_nx, out_ny)
        else:
            result.extend(arc)
    return result, start_arc, overcut_dir

def overcut_along_path(pts, ov_dist):
    """Следва контура напред от pts[0] за ov_dist мм и връща точките по пътя."""
    work = list(pts)
    # Ако последната точка съвпада с първата (затворен), премахни дупликата
    if len(work) >= 2 and math.hypot(work[-1][0]-work[0][0], work[-1][1]-work[0][1]) < 0.001:
        work = work[:-1]
    phase2 = []
    if ov_dist <= 0 or len(work) < 2:
        return phase2
    acc = 0.0; prev = work[0]; added = False
    for j in range(1, len(work)):
        cur = work[j]
        d = math.hypot(cur[0]-prev[0], cur[1]-prev[1])
        if d < 0.001: prev = cur; continue
        if acc + d >= ov_dist:
            r = (ov_dist - acc) / d
            phase2.append((prev[0]+(cur[0]-prev[0])*r,
                           prev[1]+(cur[1]-prev[1])*r))
            added = True; break
        phase2.append(cur); acc += d; prev = cur
    if not added and len(work) > 1:
        phase2.append(work[1])
    return phase2

def arc_lead_in(phase1, tk_mm):
    """Връща lead-in траекторията по дъгата ПРЕДИ стартовата точка.

    Резултатът е списък [lead_start, ..., phase1[0]] —
    ножът се вдига на lead_start (с U), реже до phase1[0] (с D-серия),
    и е вече ориентиран правилно когато достигне шева.

    Алгоритъм: вървим НАЗАД по контура от phase1[-1] към phase1[0]
    за разстояние tk_mm. Получените точки обръщаме и добавяме phase1[0]
    в края — получаваме посоката "напред" към шева.
    """
    if tk_mm <= 0 or len(phase1) < 3:
        return []
    # Обратен контур: phase1[-1], phase1[-2], ..., phase1[0]
    # (тръгва от точката непосредствено преди старта)
    back = list(reversed(phase1))
    # overcut_along_path върви от back[0]=phase1[-1] напред в обратна посока
    raw = overcut_along_path(back, tk_mm)
    if not raw:
        return []
    # raw = [точки от phase1[-1] навътре по обратната посока до tk_mm]
    # Обръщаме: lead[0] = крайна_назад_точка (lead-in старт)
    #           lead[-1] = точка близо до phase1[-1] (= непосредствено преди phase1[0])
    lead = list(reversed(raw))
    # Добавяме phase1[0] — финалната точка на lead-in (= шевът)
    lead.append(phase1[0])
    return lead

# ---------------------------------------------------------------------------
# HP-GL emission
# ---------------------------------------------------------------------------
def _emit_open_path(hpgl, pts, is_closed, coord):
    """Емитира P0 или отворен P1 path — без knife offset, overcut или lead-in."""
    final_pts = dedup_pts(list(pts))
    final_pts = collinear_clean(final_pts)
    if not final_pts:
        return
    stx, sty = coord(final_pts[0][0], final_pts[0][1])
    hpgl.append(f"U{stx},{sty};")
    last_rx, last_ry = final_pts[0]
    last_tx, last_ty = stx, sty
    for i in range(1, len(final_pts)):
        px, py = final_pts[i]
        if i != len(final_pts) - 1 and math.hypot(px-last_rx, py-last_ry) < MIN_DIST_MM:
            continue
        tx, ty = coord(px, py)
        if tx != last_tx or ty != last_ty:
            hpgl.append(f"D{tx},{ty};")
            last_tx, last_ty = tx, ty
            last_rx, last_ry = px, py
    if is_closed and len(final_pts) > 1:
        first_pt = final_pts[0]
        if math.hypot(first_pt[0]-last_rx, first_pt[1]-last_ry) > 0.01:
            tx, ty = coord(first_pt[0], first_pt[1])
            if (tx, ty) != (last_tx, last_ty):
                hpgl.append(f"D{tx},{ty};")

def emit_path(hpgl, pts, is_closed, is_curved, k_off, ov_mm, tk_mm,
              start_arc, overcut_dir, coord, overcut_curved_mm):
    base_start = pts[0]
    phase1 = list(pts)

    if start_arc and len(phase1) >= 2:
        dx = base_start[0] - phase1[-1][0]
        dy = base_start[1] - phase1[-1][1]
        dist = math.hypot(dx, dy)
        if dist > 0.001:
            nx, ny = dx/dist, dy/dist
            shift_x = nx * k_off; shift_y = ny * k_off
            phase1.append((base_start[0]+shift_x, base_start[1]+shift_y))
            phase1.extend([(p[0]+shift_x, p[1]+shift_y) for p in start_arc])
        else:
            phase1.extend(start_arc)

    phase1 = dedup_pts(phase1)
    phase1 = collinear_clean(phase1)

    # ---------- Овъркът (overcut) ----------
    phase2 = []
    if is_curved:
        if overcut_curved_mm > 0:
            # Следваме phase1 напред от стартовата точка по дъгата
            phase2 = overcut_along_path(phase1, overcut_curved_mm)
    elif math.hypot(*overcut_dir) > 0.001:
        ov_dist = ov_mm + (k_off if start_arc else 0.0)
        if ov_dist > 0:
            ov_s = phase1[-1]
            ox, oy = overcut_dir
            phase2 = [(ov_s[0]+ox*ov_dist, ov_s[1]+oy*ov_dist)]
    else:
        phase2 = overcut_along_path(phase1, ov_mm)

    phase2 = dedup_pts(phase2)

    # ---------- Начална точка, lead-in и turnaround ----------
    # stx/sty е координатата на phase1[0] — стартовата точка на рязането.
    # Запазваме я за финалното U при криви затворени пътища.
    stx, sty = coord(phase1[0][0], phase1[0][1])

    if tk_mm > 0 and is_curved and is_closed and len(phase1) > 3:
        # За криви затворени пътища: lead-in по дъгата.
        # Спускаме ножа малко ПРЕДИ стартовата точка и рязаме до нея —
        # ножът е вече ориентиран правилно когато минава шева.
        lead = arc_lead_in(phase1, tk_mm)
        if lead:
            lpx, lpy = coord(lead[0][0], lead[0][1])
            # U до lead-in точката, после D — без D на същата точка
            hpgl.append(f"U{lpx},{lpy};")
            for lp in lead[1:]:
                ltx, lty = coord(lp[0], lp[1])
                hpgl.append(f"D{ltx},{lty};")
            # last_tx/ty = stx/sty защото lead завършва точно на phase1[0]
        else:
            hpgl.append(f"U{stx},{sty};")

    elif tk_mm > 0 and not is_curved and len(phase1) > 1:
        # За прави пътища: turnaround — отиди назад по посоката, после напред
        fdx = phase1[1][0]-phase1[0][0]; fdy = phase1[1][1]-phase1[0][1]
        fd  = math.hypot(fdx, fdy)
        if fd > 0.001:
            nx = fdx/fd; ny = fdy/fd
            ptx, pty = coord(phase1[0][0]-nx*tk_mm, phase1[0][1]-ny*tk_mm)
            hpgl.append(f"U{ptx},{pty};")
            hpgl.append(f"D{ptx},{pty};")
            hpgl.append(f"D{stx},{sty};")
        else:
            hpgl.append(f"U{stx},{sty};")
    else:
        hpgl.append(f"U{stx},{sty};")

    emit_from = 1

    # ---------- Извеждане на phase1 ----------
    last_rx, last_ry = phase1[0]
    last_tx, last_ty = stx, sty
    for i in range(emit_from, len(phase1)):
        px, py = phase1[i]
        if i != len(phase1)-1 and math.hypot(px-last_rx, py-last_ry) < MIN_DIST_MM:
            continue
        tx, ty = coord(px, py)
        if tx != last_tx or ty != last_ty:
            hpgl.append(f"D{tx},{ty};")
            last_tx, last_ty = tx, ty
            last_rx, last_ry = px, py

    # ---------- Извеждане на phase2 (овъркът) ----------
    for px, py in phase2:
        tx, ty = coord(px, py)
        if tx != last_tx or ty != last_ty:
            hpgl.append(f"D{tx},{ty};")
            last_tx, last_ty = tx, ty
            last_rx, last_ry = px, py

    # ---------- Затваряне само за прави затворени пътища ----------
    # При криви овъркътът вече затвори контура — не добавяме D назад до старта.
    if is_closed and not is_curved and len(phase1) > 1:
        first_pt = phase1[0]
        dist_to_start = math.hypot(first_pt[0] - last_rx, first_pt[1] - last_ry)
        if dist_to_start > 0.01:
            tx, ty = coord(first_pt[0], first_pt[1])
            if (tx, ty) != (last_tx, last_ty):
                hpgl.append(f"D{tx},{ty};")
                last_tx, last_ty = tx, ty

    # Вдигане на ножа — при криви затворени се връщаме на стартовата точка
    if is_closed and is_curved:
        hpgl.append(f"U{stx},{sty};")
    else:
        hpgl.append(f"U{last_tx},{last_ty};")

# ---------------------------------------------------------------------------
# SVG extraction
# ---------------------------------------------------------------------------
def _stroke_to_tool(elem):
    """Връща (tool, priority) спрямо цвета на stroke-а."""
    stroke = elem.style.get('stroke')
    color  = str(stroke).strip().lower() if stroke else ""
    if any(c in color for c in ('#000000', 'black', '#000', '#000000ff', 'rgb(0,0,0)')):
        return "P0", 0
    if any(c in color for c in ('#ff0000', 'red', '#f00', '#ff0000ff', 'rgb(255,0,0)')):
        return "P1", 2
    return "P1", 1

def _path_is_closed(abs_path):
    """Проверява дали абсолютен path е затворен — само по ZoneClose или съвпадение на
    координатите на първата и последната точка (работи върху трансформирания abs_path)."""
    segs = list(abs_path)
    if any(isinstance(seg, ZoneClose) for seg in segs):
        return True
    if len(segs) >= 2:
        try:
            def _pt(seg):
                return (seg.end.x, seg.end.y) if hasattr(seg, 'end') else None
            p0 = _pt(segs[0])
            p1 = _pt(segs[-1])
            if p0 and p1 and math.hypot(p1[0]-p0[0], p1[1]-p0[1]) < 0.01:
                return True
        except Exception:
            pass
    return False

def process_elements(cut_layer, scale_x=1.0, scale_y=1.0):
    path_data = []
    for elem in cut_layer.iterdescendants():
        if not isinstance(elem, PathElement):
            continue
        tool, priority = _stroke_to_tool(elem)

        abs_path = elem.path.to_absolute()
        composed = elem.composed_transform()
        if composed:
            abs_path = abs_path.transform(composed)
        elif elem.transform:
            abs_path = abs_path.transform(elem.transform)

        # is_closed се проверява върху трансформирания abs_path
        is_closed_svg = _path_is_closed(abs_path)

        csp = CubicSuperPath(abs_path)
        for subpath in csp:
            if len(subpath) < 2: continue
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
                    for s in range(STEPS_PER_SEGMENT):
                        pts.append(cubic_point(p0, c1, c2, p1, s/STEPS_PER_SEGMENT))
            pts.append((subpath[-1][1][0]*scale_x, subpath[-1][1][1]*scale_y))
            if has_curve and is_closed_svg:
                pts = resample_by_length(pts, CURVE_STEP_MM, True)
            if pts:
                path_data.append({
                    'pts': pts, 'tool': tool, 'priority': priority,
                    'is_closed': is_closed_svg, 'has_curve': has_curve,
                })
    return path_data

# ---------------------------------------------------------------------------
# Nesting / Route
# ---------------------------------------------------------------------------
def point_in_polygon(point, poly):
    """Ray casting — стандартна имплементация.
    Xinters се пресмята само когато p1y != p2y, без uninitialised достъп."""
    x, y = point
    inside = False
    n = len(poly)
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if p1y == p2y:
            p1x, p1y = p2x, p2y
            continue
        if not (min(p1y, p2y) < y <= max(p1y, p2y)):
            p1x, p1y = p2x, p2y
            continue
        xinters = p1x + (y - p1y) * (p2x - p1x) / (p2y - p1y)
        if x < xinters:
            inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def _build_spatial_cache(paths):
    """Изчислява и кешира centroid и bounding box за всеки затворен path.
    Връща (centroids, bboxes) — None за отворени пътища."""
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
    """Изчислява дълбочината на влагане на всеки path.
    Използва кеширани centroid и bbox за O(n²) вместо O(n³)."""
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
    """Групира пътищата в острови (root + вложени форми).
    Използва кешираните centroids вместо да ги преизчислява."""
    closed_indices = [i for i, d in enumerate(depths) if d >= 0]
    roots = {}
    root_set = [i for i in closed_indices if depths[i] == 0]
    for i in closed_indices:
        if depths[i] == 0:
            roots[i] = i
        else:
            cx, cy = centroids[i]
            for j in root_set:
                if point_in_polygon((cx, cy), paths[j]['pts']):
                    roots[i] = j
                    break
            else:
                roots[i] = i
    island_dict = {}
    for i in closed_indices:
        root = roots.get(i, i)
        island_dict.setdefault(root, []).append(i)
    open_indices = [i for i, d in enumerate(depths) if d == -1]
    for i in open_indices:
        island_dict[i] = [i]
    return list(island_dict.values())

def sort_island_paths(island_idx_list, paths, depths, nesting_order):
    closed = [i for i in island_idx_list if depths[i] >= 0]
    open_paths = [i for i in island_idx_list if depths[i] == -1]
    if nesting_order == 'inside_first':
        closed.sort(key=lambda i: depths[i], reverse=True)
    else:
        closed.sort(key=lambda i: depths[i])
    groups = {}
    for i in closed:
        d = depths[i]
        groups.setdefault(d, []).append(i)
    result = []
    for d in sorted(groups.keys(), reverse=(nesting_order=='inside_first')):
        group = groups[d]
        if len(group) > 1:
            pts_list = [(paths[idx]['pts'][0], idx) for idx in group]
            # Nearest-neighbor за начален ред, после 2-opt за по-добър маршрут
            ordered = nearest_neighbor_sort_items(pts_list, lambda x: x[0])
            if len(ordered) > 3:
                ordered = two_opt_items(ordered, lambda x: x[0])
            result.extend([idx for _, idx in ordered])
        else:
            result.extend(group)
    result.extend(open_paths)
    return result

def nearest_neighbor_sort_items(items, get_start_point):
    if len(items) <= 1:
        return items
    result = [items[0]]
    remaining = list(items[1:])
    while remaining:
        last_pt = get_start_point(result[-1])
        best_i = min(range(len(remaining)),
                     key=lambda k: math.hypot(get_start_point(remaining[k])[0]-last_pt[0],
                                              get_start_point(remaining[k])[1]-last_pt[1]))
        result.append(remaining.pop(best_i))
    return result

def two_opt_items(items, get_start_point):
    """2-opt route optimisation.
    Работи върху масив от индекси (order) — разстоянията се взимат
    от оригиналния orig_pts масив по индекс, без ре-индексиране при размяна."""
    if len(items) <= 3:
        return items

    orig_pts = [get_start_point(it) for it in items]
    n = len(orig_pts)
    order = list(range(n))

    def d(a, b):
        pa, pb = orig_pts[a], orig_pts[b]
        return math.hypot(pa[0]-pb[0], pa[1]-pb[1])

    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = order[i-1], order[i]
                c = order[j]
                d_next = order[j+1] if j+1 < n else None
                old_cost = d(a, b) + (d(c, d_next) if d_next is not None else 0)
                new_cost = d(a, c) + (d(b, d_next) if d_next is not None else 0)
                if new_cost < old_cost - 0.001:
                    order[i:j+1] = order[i:j+1][::-1]
                    improved = True
    return [items[k] for k in order]

# ---------------------------------------------------------------------------
# Main extension class
# ---------------------------------------------------------------------------
class SkyCutNesting(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--use_markers",       type=inkex.Boolean, default=False)
        pars.add_argument("--paper_size",        type=str,           default="a4p")
        pars.add_argument("--auto_nesting",      type=inkex.Boolean, default=True)
        pars.add_argument("--nesting_order",     type=str,           default="inside_first")
        pars.add_argument("--ip",                type=str,           default="192.168.0.233")
        pars.add_argument("--port",              type=int,           default=8080)
        pars.add_argument("--knife_offset_mm",   type=float,         default=0.30)
        pars.add_argument("--overcut_mm",        type=float,         default=1.00)
        pars.add_argument("--overcut_curved_mm", type=float,         default=0.30)
        pars.add_argument("--turn_knife_mm",     type=float,         default=0.50)
        pars.add_argument("--save_hpgl",         type=inkex.Boolean, default=False)
        pars.add_argument("--output_path",       type=str,           default="skycut_pro_output.hpgl")
        pars.add_argument("--debug",             type=inkex.Boolean, default=False)

    def effect(self):
        output = self._build_hpgl()
        if output is None:
            return
        if self.options.save_hpgl:
            import os
            out_path = self.options.output_path.strip()
            if not out_path:
                inkex.errormsg("Изходният файл не е зададен"); return
            out_dir = os.path.dirname(out_path) or "."
            if not os.path.isdir(out_dir):
                inkex.errormsg(f"Директорията не съществува: {out_dir}"); return
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output)
                inkex.errormsg(f"HPGL saved: {out_path}")
            except OSError as e:
                inkex.errormsg(f"Грешка при запис: {e}"); return
            html_content = self._build_viewer_html(output)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8")
            tmp.write(html_content)
            tmp.close()
            webbrowser.open(f"file://{tmp.name}")
        else:
            self._send_to_cutter(output)

    def _build_hpgl(self):
        svg           = self.svg
        k_off         = self.options.knife_offset_mm
        ov_mm         = self.options.overcut_mm
        ov_curved_mm  = self.options.overcut_curved_mm
        tk_mm         = self.options.turn_knife_mm
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
        scale = min(page_w / viewbox[2] if viewbox[2] else 1.0,
                    page_h / viewbox[3] if viewbox[3] else 1.0)
        scale_x = scale_y = scale

        if debug:
            inkex.errormsg(f"DEBUG: auto_nesting={auto_nesting}, order={nesting_order}, "
                           f"scale={scale:.3f}, overcut_curved={ov_curved_mm}")

        cut_layer = next(
            (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
             if l.label and l.label.strip().lower() == 'cut'), None)
        if cut_layer is None:
            inkex.errormsg("Липсва слой Cut"); return None

        all_paths = process_elements(cut_layer, scale_x, scale_y)
        if not all_paths:
            inkex.errormsg("Няма намерени пътища за рязане"); return None

        all_paths.sort(key=lambda x: x['priority'])
        prioritized_groups = []
        for _, grp in groupby(all_paths, key=lambda x: x['priority']):
            prioritized_groups.append(list(grp))

        final_path_sequence = []

        for group in prioritized_groups:
            if auto_nesting and any(p['is_closed'] for p in group):
                depths, centroids = compute_depths(group)
                islands = group_into_islands(group, depths, centroids)
                ordered_islands = []
                for island_idx_list in islands:
                    ordered_indices = sort_island_paths(island_idx_list, group, depths, nesting_order)
                    ordered_islands.append(ordered_indices)
                island_start_points = []
                for island in ordered_islands:
                    first_idx = island[0]
                    start_pt = group[first_idx]['pts'][0]
                    island_start_points.append((start_pt, island))
                sorted_islands = nearest_neighbor_sort_items(island_start_points, lambda x: x[0])
                sorted_islands = [isl for _, isl in sorted_islands]
                if len(sorted_islands) > 3:
                    items_2opt = [(group[isl[0]]['pts'][0], isl) for isl in sorted_islands]
                    items_2opt = two_opt_items(items_2opt, lambda x: x[0])
                    sorted_islands = [isl for _, isl in items_2opt]
                for island in sorted_islands:
                    for idx in island:
                        final_path_sequence.append(group[idx])
            else:
                items = list(group)
                items = nearest_neighbor_sort_items(items, lambda p: p['pts'][0])
                if len(items) > 3:
                    items = two_opt_items(items, lambda p: p['pts'][0])
                final_path_sequence.extend(items)

        if use_markers:
            mark_layer = next(
                (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
                 if l.label and 'mark' in l.label.lower()), None)
            if mark_layer is None:
                inkex.errormsg("Липсва слой Mark"); return None

            marker_points = []
            for elem in mark_layer.iterdescendants():
                if isinstance(elem, PathElement) and elem.get('data-type') != 'triangle':
                    path = elem.path.to_absolute()
                    seg  = path[1] if len(path) > 1 else path[0]
                    try:
                        pt_x = seg.end.x if hasattr(seg,'end') else seg.x
                        pt_y = seg.end.y if hasattr(seg,'end') else seg.y
                        marker_points.append((pt_x*scale_x, pt_y*scale_y))
                    except AttributeError:
                        continue

            if not marker_points:
                inkex.errormsg("Слоят Mark не съдържа валидни елементи"); return None

            min_x = min(p[0] for p in marker_points)
            min_y = min(p[1] for p in marker_points)
            max_x = max(p[0] for p in marker_points)
            max_y = max(p[1] for p in marker_points)
            work_w = max_x - min_x
            work_h = max_y - min_y

            def coord(px, py):
                tx = int(round((work_h - (py - min_y)) * SCALE))
                ty = int(round((work_w - (px - min_x)) * SCALE))
                return tx, ty

            hpgl = [
                "IN;", "PA;",
                f"FSIZE{int(page_h*SCALE)},{int(page_w*SCALE)};",
                f"CMD:32,{int(page_h*SCALE)},{int(page_w*SCALE)},"
                f"{int(min_x*SCALE)},{int(min_y*SCALE)};",
                "CMD:18,1;", "CMD:35,1,2,0;",
                f"TB26,{int(work_h*SCALE)},{int(work_w*SCALE)};",
            ]
            if debug:
                inkex.errormsg(f"DEBUG: Markers={len(marker_points)}, "
                               f"work={work_w:.1f}x{work_h:.1f}mm")
        else:
            all_x = [p[0] for item in final_path_sequence for p in item['pts']]
            all_y = [p[1] for item in final_path_sequence for p in item['pts']]
            max_x_bb = max(all_x); max_y_bb = max(all_y)
            def coord(px, py):
                tx = int(round((max_y_bb - py) * SCALE))
                ty = int(round((max_x_bb - px) * SCALE))
                return tx, ty
            hpgl = ["IN;", "PA;", "CMD:18,1;", "CMD:35,1,2,0;"]

        current_tool = None
        for item in final_path_sequence:
            if item['tool'] != current_tool:
                hpgl.append(f"{item['tool']};")
                current_tool = item['tool']

            pts       = item['pts']
            is_closed = item['is_closed']
            is_curved = item.get('has_curve', False)
            # Knife offset с ъглова корекция само за прави затворени пътища (P1)
            use_koff  = (item['tool'] == "P1" and k_off > 0 and not is_curved)

            if debug:
                inkex.errormsg(f"DEBUG: pts={len(pts)} closed={is_closed} "
                               f"curved={is_curved} tool={item['tool']}")

            if use_koff and is_closed:
                work_pts, start_arc, overcut_dir = apply_corner_offset_scal(
                    pts, k_off, is_closed)
            else:
                work_pts = list(pts); start_arc = []; overcut_dir = (0.0, 0.0)

            if is_closed:
                if math.hypot(work_pts[-1][0]-work_pts[0][0],
                              work_pts[-1][1]-work_pts[0][1]) < 0.001:
                    base_cycle = list(work_pts[:-1])
                else:
                    base_cycle = list(work_pts)
                if item['tool'] == "P1" and is_curved and len(base_cycle) > 3:
                    base_cycle = rotate_to_least_curved(base_cycle, min_arc_len=5.0)
            else:
                base_cycle = list(work_pts)

            if item['tool'] == "P1" and is_closed:
                emit_path(hpgl, base_cycle, is_closed, is_curved,
                          k_off, ov_mm, tk_mm, start_arc, overcut_dir, coord, ov_curved_mm)
            else:
                _emit_open_path(hpgl, base_cycle, is_closed, coord)

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "".join(hpgl)

        if debug:
            inkex.errormsg(f"DEBUG: Total commands: {len(hpgl)}")

        return output

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
              let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
              for(const s of segments){minX=Math.min(minX,s.fx,s.x);minY=Math.min(minY,s.fy,s.y);
                maxX=Math.max(maxX,s.fx,s.x);maxY=Math.max(maxY,s.fy,s.y);}
              const dW=maxX-minX||1,dH=maxY-minY||1,pad=60;
              const scale=Math.min((W-pad*2)/dW,(H-pad*2)/dH);
              const offX=pad+(W-pad*2-dW*scale)/2,offY=pad+(H-pad*2-dH*scale)/2;
              const tx=x=>offX+(x-minX)*scale,ty=y=>offY+(maxY-y)*scale;
              document.getElementById("scaleLine").style.width=(50*HPM*scale)+"px";
              document.getElementById("coords").innerHTML=
                "X:"+minX+"-"+maxX+" ("+((maxX-minX)/HPM).toFixed(1)+"mm)<br>"+
                "Y:"+minY+"-"+maxY+" ("+((maxY-minY)/HPM).toFixed(1)+"mm)";
              const limit=animating?currentStep:segments.length;
              if(document.getElementById("grid").checked){
                ctx.strokeStyle="rgba(30,60,100,0.25)";ctx.lineWidth=0.5;
                const step=400*scale;
                for(let x=offX%step;x<W;x+=step){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
                for(let y=offY%step;y<H;y+=step){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
              }
              if(document.getElementById("showTravel").checked){
                ctx.strokeStyle="rgba(255,170,0,0.35)";ctx.lineWidth=0.8;ctx.setLineDash([4,4]);
                for(let i=0;i<limit;i++)if(segments[i].type==="U"){
                  ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));
                  ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();}
                ctx.setLineDash([]);
              }
              for(let i=0;i<limit;i++)if(segments[i].type==="D"){
                ctx.strokeStyle="rgba(0,238,187,0.15)";ctx.lineWidth=4;
                ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));
                ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();
                ctx.strokeStyle="#00eebb";ctx.lineWidth=1.5;
                ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));
                ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();
              }
              if(document.getElementById("showPoints").checked){
                const cuts=segments.filter(m=>m.type==="D");
                if(cuts.length>0){
                  drawDot(tx(cuts[0].fx),ty(cuts[0].fy),"#00ff00","START",12);
                  drawDot(tx(cuts[cuts.length-1].x),ty(cuts[cuts.length-1].y),"#ff0000","END",-12);
                }
              }
              if(animating&&currentStep>0){
                const s=segments[currentStep-1];
                ctx.beginPath();ctx.arc(tx(s.x),ty(s.y),4,0,Math.PI*2);
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
              currentStep=0;draw();
            }
            function animate(){
              if(!segments.length)return;
              animating=!animating;
              const btn=document.getElementById("animBtn");
              if(animating){btn.textContent="STOP";btn.classList.add("stop");currentStep=0;
                const spd=+document.getElementById("speed").value;
                function loop(){if(!animating)return;currentStep++;draw();
                  if(currentStep<segments.length)animFrame=setTimeout(loop,120-spd);
                  else{animating=false;btn.textContent="ANIMATE";btn.classList.remove("stop");}
                }loop();
              }else{clearTimeout(animFrame);btn.textContent="ANIMATE";btn.classList.remove("stop");draw();}
            }
            document.getElementById("renderBtn").onclick=process;
            document.getElementById("animBtn").onclick=animate;
            ["showTravel","grid","showPoints"].forEach(id=>document.getElementById(id).onchange=draw);
            window.addEventListener("resize",draw);
        """).strip()

        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>HPGL Viewer SkyCut</title>
<style>{css}</style></head><body>
<h3 style="margin:0;color:#00eebb;font-size:14px">HPGL Viewer SkyCut</h3>
<textarea id="hpglInput"></textarea>
<div class="controls">
  <button id="renderBtn">RENDER</button>
  <button id="animBtn">ANIMATE</button>
  <label><input type="checkbox" id="showTravel" checked> Pen up</label>
  <label><input type="checkbox" id="grid" checked> Grid</label>
  <label><input type="checkbox" id="showPoints" checked> Points</label>
  <label>Speed: <input type="range" id="speed" min="5" max="100" value="40" style="width:60px"></label>
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
        return html


    def _send_to_cutter(self, output):
        """Изпраща HPGL към машината на chunks от 4KB за надеждна работа при голям файл."""
        CHUNK = 4096
        data = output.encode()
        try:
            with socket.create_connection(
                    (self.options.ip, self.options.port), timeout=180) as s:
                sent = 0
                while sent < len(data):
                    chunk = data[sent:sent + CHUNK]
                    s.sendall(chunk)
                    sent += len(chunk)
                s.shutdown(socket.SHUT_WR)
            inkex.errormsg(f"Sent OK ({len(data)} bytes)")
        except OSError as e:
            inkex.errormsg(f"Send error ({self.options.ip}:{self.options.port}): {e}")

if __name__ == "__main__":
    SkyCutNesting().run()
