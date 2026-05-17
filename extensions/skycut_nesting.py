#!/usr/bin/env python3
import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath, ZoneClose
import socket
import math
from itertools import groupby

SCALE = 40
STEPS_PER_SEGMENT = 20
MIN_DIST_MM = 0.05
CURVE_STEP_MM = 1.0


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


def overcut_along_path(pts, ov_dist):
    work = list(pts)
    if math.hypot(work[-1][0]-work[0][0], work[-1][1]-work[0][1]) < 0.001:
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
        phase2.append(work[1])  # втората точка = правилна посока
    return phase2


def emit_path(hpgl, pts, is_closed, is_curved, k_off, ov_mm, tk_mm,
              start_arc, overcut_dir, coord):
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
            phase1.append(base_start)
            phase1.extend(start_arc)
    else:
        if math.hypot(phase1[-1][0]-base_start[0],
                      phase1[-1][1]-base_start[1]) > 0.001:
            phase1.append(base_start)

    phase1 = dedup_pts(phase1)
    phase1 = collinear_clean(phase1)

    phase2 = []
    if is_curved:
        phase2 = overcut_along_path(pts, ov_mm)
    elif math.hypot(*overcut_dir) > 0.001:
        ov_dist = ov_mm + (k_off if start_arc else 0.0)
        if ov_dist > 0:
            ov_s = phase1[-1]
            ox, oy = overcut_dir
            phase2 = [(ov_s[0]+ox*ov_dist, ov_s[1]+oy*ov_dist)]
    else:
        phase2 = overcut_along_path(pts, ov_mm)

    phase2 = dedup_pts(phase2)

    if tk_mm > 0 and not is_curved and len(phase1) > 1:
        fdx = phase1[1][0]-phase1[0][0]; fdy = phase1[1][1]-phase1[0][1]
        fd  = math.hypot(fdx, fdy)
        if fd > 0.001:
            nx = fdx/fd; ny = fdy/fd
            ptx, pty = coord(phase1[0][0]-nx*tk_mm, phase1[0][1]-ny*tk_mm)
            stx, sty = coord(phase1[0][0], phase1[0][1])
            hpgl.append(f"U{ptx},{pty};")
            hpgl.append(f"D{ptx},{pty};")
            hpgl.append(f"D{stx},{sty};")
            emit_from = 1
        else:
            stx, sty = coord(phase1[0][0], phase1[0][1])
            hpgl.append(f"U{stx},{sty};"); emit_from = 1
    else:
        stx, sty = coord(phase1[0][0], phase1[0][1])
        hpgl.append(f"U{stx},{sty};")
        if is_curved:
            hpgl.append(f"D{stx},{sty};")
        emit_from = 1

    last_rx, last_ry = phase1[0]; last_tx = last_ty = None
    for i in range(emit_from, len(phase1)):
        px, py = phase1[i]
        if i != len(phase1)-1 and math.hypot(px-last_rx, py-last_ry) < MIN_DIST_MM:
            continue
        tx, ty = coord(px, py)
        if tx != last_tx or ty != last_ty:
            hpgl.append(f"D{tx},{ty};")
            last_tx = tx; last_ty = ty; last_rx = px; last_ry = py

    for px, py in phase2:
        tx, ty = coord(px, py)
        if tx != last_tx or ty != last_ty:
            hpgl.append(f"D{tx},{ty};")
            last_tx = tx; last_ty = ty

    hpgl.append(f"U{last_tx},{last_ty};")


def process_elements(cut_layer, scale_x=1.0, scale_y=1.0):
    path_data = []
    for elem in cut_layer.iterdescendants():
        if not isinstance(elem, PathElement):
            continue
        stroke   = elem.style.get('stroke')
        color    = str(stroke).strip().lower() if stroke else ""
        is_black = any(c in color for c in ('#000000','black','#000','#000000ff','rgb(0,0,0)'))
        is_red   = any(c in color for c in ('#ff0000','red','#f00','#ff0000ff','rgb(255,0,0)'))
        if is_black:   tool, priority = "P0", 0
        elif is_red:   tool, priority = "P1", 2
        else:          tool, priority = "P1", 1

        abs_path = elem.path.to_absolute()
        composed = elem.composed_transform()
        if composed:         abs_path = abs_path.transform(composed)
        elif elem.transform: abs_path = abs_path.transform(elem.transform)

        is_closed_svg = any(isinstance(seg, ZoneClose)
                            for seg in elem.path.to_absolute())
        if not is_closed_svg:
            try:
                segs = list(elem.path.to_absolute())
                if len(segs) >= 2:
                    f0 = segs[0]; fl = segs[-1]
                    fx = f0.end.x if hasattr(f0,'end') else getattr(f0,'x',None)
                    fy = f0.end.y if hasattr(f0,'end') else getattr(f0,'y',None)
                    lx = fl.end.x if hasattr(fl,'end') else getattr(fl,'x',None)
                    ly = fl.end.y if hasattr(fl,'end') else getattr(fl,'y',None)
                    if fx is not None and lx is not None:
                        if math.hypot(lx-fx, ly-fy) < 0.01:
                            is_closed_svg = True
            except Exception:
                pass

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


def point_in_polygon(point, poly):
    """Ray casting algorithm. point = (x,y), poly = list of (x,y). Returns True if inside."""
    x, y = point
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n+1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def compute_depths(paths):
    """Assign nesting depth to each closed path. Depth 0 = outermost."""
    n = len(paths)
    depths = [0]*n
    # Build containment matrix (simple O(n^2) using bounding box + point-in-poly)
    for i in range(n):
        if not paths[i]['is_closed']:
            depths[i] = -1  # mark open paths as not participating
            continue
        poly_i = paths[i]['pts']
        # representative point: first point or centroid
        rep_i = (sum(p[0] for p in poly_i)/len(poly_i), sum(p[1] for p in poly_i)/len(poly_i))
        # count how many paths contain rep_i
        count = 0
        for j in range(n):
            if i == j: continue
            if not paths[j]['is_closed']: continue
            poly_j = paths[j]['pts']
            # quick bounding box check
            minx_j = min(p[0] for p in poly_j)
            maxx_j = max(p[0] for p in poly_j)
            miny_j = min(p[1] for p in poly_j)
            maxy_j = max(p[1] for p in poly_j)
            if rep_i[0] < minx_j or rep_i[0] > maxx_j or rep_i[1] < miny_j or rep_i[1] > maxy_j:
                continue
            if point_in_polygon(rep_i, poly_j):
                count += 1
        depths[i] = count
    return depths


def group_into_islands(paths, depths):
    """Group paths into islands (list of lists). Each island contains paths that belong together.
    An island is defined by a root path (depth=0) and all paths that are inside it (depth>0)
    but not inside any other root. For multiple separate depth=0 paths, they are different islands.
    Open paths (depth=-1) become separate islands of their own."""
    closed_indices = [i for i, d in enumerate(depths) if d >= 0]
    # map each closed path to its root (the smallest-depth containing path)
    # Since depths are absolute counts, root is any path with depth=0 that contains this path.
    # However, for paths with depth>0, we need to find the immediate parent? For island grouping,
    # we can assign each path to the outermost containing path (depth=0) that contains it.
    # If there are multiple depth=0 (separate islands), then each path will be inside exactly one depth=0.
    roots = {}
    for i in closed_indices:
        if depths[i] == 0:
            roots[i] = i   # root points to itself
        else:
            # find a depth=0 that contains this path's representative point
            rep_i = (sum(p[0] for p in paths[i]['pts'])/len(paths[i]['pts']),
                     sum(p[1] for p in paths[i]['pts'])/len(paths[i]['pts']))
            for j in closed_indices:
                if depths[j] == 0 and point_in_polygon(rep_i, paths[j]['pts']):
                    roots[i] = j
                    break
            else:
                # fallback: treat as separate island (should not happen for valid nesting)
                roots[i] = i
    # Build island groups
    island_dict = {}
    for i in closed_indices:
        root = roots.get(i, i)
        island_dict.setdefault(root, []).append(i)
    # Also handle open paths (depth=-1) as separate islands each
    open_indices = [i for i, d in enumerate(depths) if d == -1]
    for i in open_indices:
        island_dict[i] = [i]   # each open path alone
    # Convert to list of lists
    islands = list(island_dict.values())
    return islands


def sort_island_paths(island_idx_list, paths, depths, nesting_order):
    """Sort paths within one island according to nesting_order.
    Returns a list of path indices in cutting order for this island.
    """
    # Separate closed paths (depth>=0) and open paths (depth==-1)
    closed = [i for i in island_idx_list if depths[i] >= 0]
    open_paths = [i for i in island_idx_list if depths[i] == -1]
    # Sort closed by depth according to order
    if nesting_order == 'inside_first':
        # deeper first (higher depth)
        closed.sort(key=lambda i: depths[i], reverse=True)
    else:  # outside_first
        closed.sort(key=lambda i: depths[i])  # shallower first
    # For paths with same depth, optionally apply nearest neighbor to reduce travel
    # Group by depth
    groups = {}
    for i in closed:
        d = depths[i]
        groups.setdefault(d, []).append(i)
    result = []
    for d in sorted(groups.keys(), reverse=(nesting_order=='inside_first')):
        group = groups[d]
        if len(group) > 1:
            # Apply nearest neighbor reordering within same depth
            # Use first point of each path as reference
            pts_list = [(paths[idx]['pts'][0], idx) for idx in group]
            # simple greedy
            ordered = [pts_list[0]]
            remaining = pts_list[1:]
            while remaining:
                last_pt = ordered[-1][0]
                best_i = 0
                best_d = float('inf')
                for i, (pt, idx) in enumerate(remaining):
                    d2 = math.hypot(pt[0]-last_pt[0], pt[1]-last_pt[1])
                    if d2 < best_d:
                        best_d = d2
                        best_i = i
                ordered.append(remaining.pop(best_i))
            result.extend([idx for _, idx in ordered])
        else:
            result.extend(group)
    # Append open paths (they have no depth) in original order (or could be sorted by position)
    result.extend(open_paths)
    return result


def nearest_neighbor_sort_items(items, get_start_point):
    """Generic nearest neighbor sort for list of items, using a function to get start point (x,y)."""
    if len(items) <= 1:
        return items
    result = [items[0]]
    remaining = items[1:]
    while remaining:
        last_pt = get_start_point(result[-1])
        best_i = 0
        best_d = float('inf')
        for i, it in enumerate(remaining):
            pt = get_start_point(it)
            d = math.hypot(pt[0]-last_pt[0], pt[1]-last_pt[1])
            if d < best_d:
                best_d = d
                best_i = i
        result.append(remaining.pop(best_i))
    return result


def two_opt_items(items, get_start_point):
    """2-opt improvement on a list of items."""
    if len(items) <= 3:
        return items

    def total_dist(order):
        d = 0.0
        for i in range(1, len(order)):
            a = get_start_point(order[i-1])
            b = get_start_point(order[i])
            d += math.hypot(b[0]-a[0], b[1]-a[1])
        return d

    improved = True
    best = list(items)
    while improved:
        improved = False
        for i in range(1, len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + best[i:j+1][::-1] + best[j+1:]
                if total_dist(candidate) < total_dist(best) - 0.001:
                    best = candidate
                    improved = True
    return best


class SkyCutNesting(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--use_markers",     type=inkex.Boolean, default=False)
        pars.add_argument("--paper_size",      type=str,           default="a4p")
        pars.add_argument("--auto_nesting",    type=inkex.Boolean, default=True)
        pars.add_argument("--nesting_order",   type=str,           default="inside_first")
        pars.add_argument("--ip",              type=str,           default="192.168.0.233")
        pars.add_argument("--port",            type=int,           default=8080)
        pars.add_argument("--knife_offset_mm", type=float,         default=0.30)
        pars.add_argument("--overcut_mm",      type=float,         default=1.00)
        pars.add_argument("--turn_knife_mm",   type=float,         default=0.50)
        pars.add_argument("--save_hpgl",       type=inkex.Boolean, default=False)
        pars.add_argument("--output_path",     type=str,           default="test_skycut_output.hpgl")
        pars.add_argument("--debug",           type=inkex.Boolean, default=False)

    def effect(self):
        svg          = self.svg
        k_off        = self.options.knife_offset_mm
        ov_mm        = self.options.overcut_mm
        tk_mm        = self.options.turn_knife_mm
        debug        = self.options.debug
        use_markers  = self.options.use_markers
        auto_nesting = self.options.auto_nesting
        nesting_order = self.options.nesting_order

        paper_sizes = {
            'a4p': (210.0, 297.0), 'a4l': (297.0, 210.0),
            'a3p': (297.0, 420.0), 'a3l': (420.0, 297.0),
        }
        page_w, page_h = paper_sizes.get(self.options.paper_size, (210.0, 297.0))

        viewbox = svg.get_viewbox()
        scale_x = page_w / viewbox[2] if viewbox[2] else 1.0
        scale_y = page_h / viewbox[3] if viewbox[3] else 1.0

        if debug:
            inkex.errormsg(f"DEBUG: auto_nesting={auto_nesting}, order={nesting_order}, "
                           f"scales={scale_x:.3f},{scale_y:.3f}")

        cut_layer = next(
            (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
             if l.label and l.label.strip().lower() == 'cut'), None)
        if cut_layer is None:
            inkex.errormsg("Липсва слой Cut"); return

        # Extract paths
        all_paths = process_elements(cut_layer, scale_x, scale_y)
        if not all_paths:
            inkex.errormsg("Няма намерени пътища за рязане"); return

        # Separate by priority (0,1,2) because P0 and P1 are different tools
        all_paths.sort(key=lambda x: x['priority'])
        prioritized_groups = []
        for _, grp in groupby(all_paths, key=lambda x: x['priority']):
            prioritized_groups.append(list(grp))

        final_path_sequence = []

        for group in prioritized_groups:
            if auto_nesting and any(p['is_closed'] for p in group):
                # Compute depths for all paths in this group (only closed matter, open get -1)
                depths = compute_depths(group)
                # Group into islands
                islands = group_into_islands(group, depths)
                ordered_islands = []
                # For each island, produce ordered list of path indices (within group)
                for island_idx_list in islands:
                    ordered_indices = sort_island_paths(island_idx_list, group, depths, nesting_order)
                    ordered_islands.append(ordered_indices)
                # Now order islands themselves by nearest neighbor using first point of first path in each island
                island_start_points = []
                for island in ordered_islands:
                    first_idx = island[0]
                    start_pt = group[first_idx]['pts'][0]
                    island_start_points.append((start_pt, island))
                # Sort islands by nearest neighbor
                sorted_islands = nearest_neighbor_sort_items(island_start_points, lambda x: x[0])
                sorted_islands = [isl for _, isl in sorted_islands]
                # Optionally apply 2-opt on islands (global optimization)
                if len(sorted_islands) > 3:
                    # Convert to list of items for 2-opt: each item is (start_pt, island)
                    items_2opt = [(group[isl[0]]['pts'][0], isl) for isl in sorted_islands]
                    items_2opt = two_opt_items(items_2opt, lambda x: x[0])
                    sorted_islands = [isl for _, isl in items_2opt]
                # Flatten into final path list for this priority group
                for island in sorted_islands:
                    for idx in island:
                        final_path_sequence.append(group[idx])
            else:
                # Original behavior: nearest neighbor + 2-opt on entire group
                # But we need to consider open/closed? Original sorted by start point.
                # We'll use the original nearest neighbor on the group directly
                # First, make a copy of group items
                items = list(group)
                # Nearest neighbor sort
                items = nearest_neighbor_sort_items(items, lambda p: p['pts'][0])
                # 2-opt improvement
                if len(items) > 3:
                    items = two_opt_items(items, lambda p: p['pts'][0])
                final_path_sequence.extend(items)

        # Now final_path_sequence contains all paths in desired order
        # Build coordinate system (same as original)
        if use_markers:
            mark_layer = next(
                (l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']")
                 if l.label and 'mark' in l.label.lower()), None)
            if mark_layer is None:
                inkex.errormsg("Липсва слой Mark"); return

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
                inkex.errormsg("Слоят Mark не съдържа валидни елементи"); return

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
            # No markers: coordinate from bounding box
            all_x = [p[0] for item in final_path_sequence for p in item['pts']]
            all_y = [p[1] for item in final_path_sequence for p in item['pts']]
            max_x_bb = max(all_x); max_y_bb = max(all_y)
            def coord(px, py):
                tx = int(round((max_y_bb - py) * SCALE))
                ty = int(round((max_x_bb - px) * SCALE))
                return tx, ty
            hpgl = ["IN;", "PA;", "CMD:18,1;", "CMD:35,1,2,0;"]

        # Generate HPGL commands
        current_tool = None
        for item in final_path_sequence:
            if item['tool'] != current_tool:
                hpgl.append(f"{item['tool']};")
                current_tool = item['tool']

            pts       = item['pts']
            is_closed = item['is_closed']
            is_curved = item.get('has_curve', False)
            use_koff  = (item['tool'] == "P1" and k_off > 0)

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
            else:
                base_cycle = list(work_pts)

            if item['tool'] == "P1" and is_closed:
                emit_path(hpgl, base_cycle, is_closed, is_curved,
                          k_off, ov_mm, tk_mm, start_arc, overcut_dir, coord)
            else:
                final_pts = dedup_pts(base_cycle)
                final_pts = collinear_clean(final_pts)
                if not final_pts: continue

                stx, sty = coord(final_pts[0][0], final_pts[0][1])
                hpgl.append(f"U{stx},{sty};")
                if is_curved:
                    hpgl.append(f"D{stx},{sty};")

                last_rx, last_ry = final_pts[0]
                last_tx, last_ty = stx, sty
                for i in range(1, len(final_pts)):
                    px, py = final_pts[i]
                    if (i != len(final_pts)-1 and
                            math.hypot(px-last_rx, py-last_ry) < MIN_DIST_MM):
                        continue
                    tx, ty = coord(px, py)
                    if tx != last_tx or ty != last_ty:
                        hpgl.append(f"D{tx},{ty};")
                        last_tx = tx; last_ty = ty
                        last_rx = px; last_ry = py

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "".join(hpgl)

        if debug:
            inkex.errormsg(f"DEBUG: Total commands: {len(hpgl)}")

        if self.options.save_hpgl:
            with open(self.options.output_path, "w") as f:
                f.write(output)
            inkex.errormsg(f"HPGL saved: {self.options.output_path}")
            import webbrowser, tempfile
            html_content = self._build_viewer_html(output)
            tmp = tempfile.NamedTemporaryFile(
                suffix=".html", delete=False, mode="w", encoding="utf-8")
            tmp.write(html_content)
            tmp.close()
            webbrowser.open(f"file://{tmp.name}")
        else:
            try:
                with socket.create_connection(
                        (self.options.ip, self.options.port), timeout=180) as s:
                    s.sendall(output.encode())
                    s.shutdown(socket.SHUT_WR)
                inkex.errormsg("Sent OK")
            except Exception as e:
                inkex.errormsg(f"Send error: {e}")

    def _build_viewer_html(self, hpgl_data):
        hpgl_escaped = hpgl_data.replace('\\', '\\\\').replace('`', '\\`')
        lines = [
            '<!DOCTYPE html>',
            '<html lang="en"><head><meta charset="UTF-8">',
            '<title>HPGL Viewer SkyCut</title>',
            '<style>',
            '* { box-sizing: border-box; }',
            'body { margin:0; padding:10px; background:#0a0f1a; color:#c8d8e8;',
            '  font-family:monospace; height:100vh; display:flex; flex-direction:column; gap:8px; }',
            'textarea { width:100%; height:80px; background:#0a1520; border:1px solid #1a3050;',
            '  color:#7ec8a0; padding:8px; font-size:10px; resize:vertical; }',
            '.controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }',
            'button { background:transparent; border:1px solid #00eebb; color:#00eebb;',
            '  padding:5px 10px; cursor:pointer; border-radius:4px; font-size:11px; }',
            'button:hover { background:rgba(0,238,187,0.15); }',
            'button.stop { border-color:#ff5050; color:#ff5050; }',
            'label { font-size:10px; color:#8899aa; display:flex; align-items:center; gap:4px; cursor:pointer; }',
            '.canvas-wrap { flex:1; position:relative; min-height:300px;',
            '  border:1px solid #1a3050; border-radius:4px; overflow:hidden; background:#060b14; }',
            'canvas { display:block; width:100%; height:100%; }',
            '.stats { font-size:10px; color:#557799; display:flex; gap:10px; flex-wrap:wrap; }',
            '.stats span { color:#00eebb; }',
            '.scale-ind { position:absolute; bottom:10px; right:10px;',
            '  background:rgba(10,15,26,0.85); border:1px solid #1a3050;',
            '  padding:4px 8px; border-radius:3px; font-size:9px; display:flex; align-items:center; gap:6px; }',
            '.scale-line { height:2px; background:#00eebb; }',
            '.coords { position:absolute; top:10px; left:10px;',
            '  background:rgba(10,15,26,0.85); border:1px solid #1a3050;',
            '  padding:4px 8px; border-radius:3px; font-size:9px; color:#8899aa; }',
            '</style></head><body>',
            '<h3 style="margin:0;color:#00eebb;font-size:14px">HPGL Viewer SkyCut</h3>',
            '<textarea id="hpglInput"></textarea>',
            '<div class="controls">',
            '  <button id="renderBtn">RENDER</button>',
            '  <button id="animBtn">ANIMATE</button>',
            '  <label><input type="checkbox" id="showTravel" checked> Pen up</label>',
            '  <label><input type="checkbox" id="grid" checked> Grid</label>',
            '  <label><input type="checkbox" id="showPoints" checked> Points</label>',
            '  <label>Speed: <input type="range" id="speed" min="5" max="100" value="40" style="width:60px"></label>',
            '</div>',
            '<div class="stats" id="stats">-</div>',
            '<div class="canvas-wrap">',
            '  <canvas id="canvas"></canvas>',
            '  <div class="coords" id="coords"></div>',
            '  <div class="scale-ind"><div class="scale-line" id="scaleLine"></div><span>50mm</span></div>',
            '</div>',
            '<script>',
            'const canvas=document.getElementById("canvas"),ctx=canvas.getContext("2d");',
            'let segments=[],animating=false,animFrame=null,currentStep=0;',
            'const HPM=40;',
            'function parseHPGL(text){',
            '  const moves=[],lines=text.replace(/\\r/g,"").split(/[\\n;]+/);',
            '  let x=0,y=0;',
            '  for(let line of lines){',
            '    line=line.trim().toUpperCase();',
            '    if(!line||line==="IN"||line==="PA"||line.startsWith("P1")||line.startsWith("P0")||',
            '       line.startsWith("CMD:")||line==="@"||line.startsWith("TB")||line.startsWith("FSIZE"))continue;',
            '    const u=line.match(/^U\\s*(-?\\d+)\\s*,\\s*(-?\\d+)/);',
            '    const d=line.match(/^D\\s*(-?\\d+)\\s*,\\s*(-?\\d+)/);',
            '    if(u){moves.push({type:"U",x:+u[1],y:+u[2],fx:x,fy:y});x=+u[1];y=+u[2];}',
            '    else if(d){moves.push({type:"D",x:+d[1],y:+d[2],fx:x,fy:y});x=+d[1];y=+d[2];}',
            '  }return moves;',
            '}',
            'function drawDot(x,y,color,label,oy){',
            '  ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=color+"35";ctx.fill();',
            '  ctx.beginPath();ctx.arc(x,y,4.5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();',
            '  ctx.strokeStyle="#fff";ctx.lineWidth=1.2;ctx.stroke();',
            '  ctx.fillStyle=color;ctx.font="bold 10px monospace";ctx.fillText(label,x+9,y+oy);',
            '}',
            'function draw(){',
            '  const rect=canvas.parentElement.getBoundingClientRect();',
            '  canvas.width=rect.width;canvas.height=rect.height;',
            '  const W=canvas.width,H=canvas.height;',
            '  ctx.clearRect(0,0,W,H);',
            '  if(!segments.length){ctx.fillStyle="#334455";ctx.font="12px monospace";',
            '    ctx.textAlign="center";ctx.fillText("PASTE HPGL -> RENDER",W/2,H/2);return;}',
            '  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;',
            '  for(const s of segments){minX=Math.min(minX,s.fx,s.x);minY=Math.min(minY,s.fy,s.y);',
            '    maxX=Math.max(maxX,s.fx,s.x);maxY=Math.max(maxY,s.fy,s.y);}',
            '  const dW=maxX-minX||1,dH=maxY-minY||1,pad=60;',
            '  const scale=Math.min((W-pad*2)/dW,(H-pad*2)/dH);',
            '  const offX=pad+(W-pad*2-dW*scale)/2,offY=pad+(H-pad*2-dH*scale)/2;',
            '  const tx=x=>offX+(x-minX)*scale,ty=y=>offY+(maxY-y)*scale;',
            '  document.getElementById("scaleLine").style.width=(50*HPM*scale)+"px";',
            '  document.getElementById("coords").innerHTML=',
            '    "X:"+minX+"-"+maxX+" ("+((maxX-minX)/HPM).toFixed(1)+"mm)<br>"+',
            '    "Y:"+minY+"-"+maxY+" ("+((maxY-minY)/HPM).toFixed(1)+"mm)";',
            '  const limit=animating?currentStep:segments.length;',
            '  if(document.getElementById("grid").checked){',
            '    ctx.strokeStyle="rgba(30,60,100,0.25)";ctx.lineWidth=0.5;',
            '    const step=400*scale;',
            '    for(let x=offX%step;x<W;x+=step){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}',
            '    for(let y=offY%step;y<H;y+=step){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}',
            '  }',
            '  if(document.getElementById("showTravel").checked){',
            '    ctx.strokeStyle="rgba(255,170,0,0.35)";ctx.lineWidth=0.8;ctx.setLineDash([4,4]);',
            '    for(let i=0;i<limit;i++)if(segments[i].type==="U"){',
            '      ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));',
            '      ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();}',
            '    ctx.setLineDash([]);',
            '  }',
            '  for(let i=0;i<limit;i++)if(segments[i].type==="D"){',
            '    ctx.strokeStyle="rgba(0,238,187,0.15)";ctx.lineWidth=4;',
            '    ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));',
            '    ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();',
            '    ctx.strokeStyle="#00eebb";ctx.lineWidth=1.5;',
            '    ctx.beginPath();ctx.moveTo(tx(segments[i].fx),ty(segments[i].fy));',
            '    ctx.lineTo(tx(segments[i].x),ty(segments[i].y));ctx.stroke();',
            '  }',
            '  if(document.getElementById("showPoints").checked){',
            '    const cuts=segments.filter(m=>m.type==="D");',
            '    if(cuts.length>0){',
            '      drawDot(tx(cuts[0].fx),ty(cuts[0].fy),"#00ff00","START",12);',
            '      drawDot(tx(cuts[cuts.length-1].x),ty(cuts[cuts.length-1].y),"#ff0000","END",-12);',
            '    }',
            '  }',
            '  if(animating&&currentStep>0){',
            '    const s=segments[currentStep-1];',
            '    ctx.beginPath();ctx.arc(tx(s.x),ty(s.y),4,0,Math.PI*2);',
            '    ctx.fillStyle=s.type==="D"?"#00ffcc":"#ffdd00";ctx.fill();',
            '  }',
            '}',
            'function process(){',
            '  segments=parseHPGL(document.getElementById("hpglInput").value);',
            '  const cuts=segments.filter(m=>m.type==="D");',
            '  let total=0;for(const m of cuts)total+=Math.hypot(m.x-m.fx,m.y-m.fy);',
            '  let mnX=Infinity,mnY=Infinity,mxX=-Infinity,mxY=-Infinity;',
            '  for(const m of segments){mnX=Math.min(mnX,m.fx,m.x);mnY=Math.min(mnY,m.fy,m.y);',
            '    mxX=Math.max(mxX,m.fx,m.x);mxY=Math.max(mxY,m.fy,m.y);}',
            '  document.getElementById("stats").innerHTML=',
            '    "Commands: <span>"+segments.length+"</span> | "+',
            '    "Cut: <span>"+cuts.length+"</span> | "+',
            '    "Size: <span>"+((mxX-mnX)/HPM).toFixed(1)+"x"+((mxY-mnY)/HPM).toFixed(1)+" mm</span> | "+',
            '    "Length: <span>"+(total/HPM).toFixed(1)+" mm</span>";',
            '  currentStep=0;draw();',
            '}',
            'function animate(){',
            '  if(!segments.length)return;',
            '  animating=!animating;',
            '  const btn=document.getElementById("animBtn");',
            '  if(animating){btn.textContent="STOP";btn.classList.add("stop");currentStep=0;',
            '    const spd=+document.getElementById("speed").value;',
            '    function loop(){if(!animating)return;currentStep++;draw();',
            '      if(currentStep<segments.length)animFrame=setTimeout(loop,120-spd);',
            '      else{animating=false;btn.textContent="ANIMATE";btn.classList.remove("stop");}',
            '    }loop();',
            '  }else{clearTimeout(animFrame);btn.textContent="ANIMATE";btn.classList.remove("stop");draw();}',
            '}',
            'document.getElementById("renderBtn").onclick=process;',
            'document.getElementById("animBtn").onclick=animate;',
            '["showTravel","grid","showPoints"].forEach(id=>document.getElementById(id).onchange=draw);',
            'window.addEventListener("resize",draw);',
        ]
        hpgl_line = 'document.getElementById("hpglInput").value=`' + hpgl_escaped + '`;'
        lines.append(hpgl_line)
        lines.append('process();')
        lines.append('</script></body></html>')
        return '\n'.join(lines)

if __name__ == "__main__":
    SkyCutNesting().run()
