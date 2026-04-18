#!/usr/bin/env python3
import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath, ZoneClose
import socket
import math

SCALE = 40
STEPS_PER_SEGMENT = 16
MIN_DIST_MM = 0.05

def cubic_point(p0, c1, c2, p1, t):
    mt = 1 - t
    x = mt**3*p0[0] + 3*mt**2*t*c1[0] + 3*mt*t**2*c2[0] + t**3*p1[0]
    y = mt**3*p0[1] + 3*mt**2*t*c1[1] + 3*mt*t**2*c2[1] + t**3*p1[1]
    return x, y

class SendToSkyCutD24NoMarkers(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--ip", type=str, default="192.168.0.233")
        pars.add_argument("--port", type=int, default=8080)
        pars.add_argument("--knife_offset_mm", type=float, default=0.30)
        pars.add_argument("--overcut_mm", type=float, default=1.00)
        pars.add_argument("--save_hpgl", type=inkex.Boolean, default=False)
        pars.add_argument("--output_path", type=str, default="skycut_output.hpgl")

    def effect(self):
        k_off = self.options.knife_offset_mm
        ov_mm = self.options.overcut_mm

        # Намиране на слой 'Cut'
        cut_layer = next((l for l in self.svg.xpath("//svg:g[@inkscape:groupmode='layer']")
                         if l.label and l.label.strip().lower() == 'cut'), None)

        if cut_layer is None:
            inkex.errormsg("❌ Слой 'Cut' не е намерен!")
            return

        path_data = []
        all_x, all_y = [], []

        for elem in cut_layer.iterdescendants():
            if isinstance(elem, PathElement):
                stroke = elem.style.get('stroke')
                color = str(stroke).strip().lower() if stroke else ""

                is_black = any(c in color for c in ('#000000', 'black', '#000', '#000000ff', 'rgb(0,0,0)'))
                is_red   = any(c in color for c in ('#ff0000', 'red', '#f00', '#ff0000ff', 'rgb(255,0,0)'))

                if is_black:
                    tool, priority = "P0", 0
                elif is_red:
                    tool, priority = "P1", 2
                else:
                    tool, priority = "P1", 1

                abs_path = elem.path.to_absolute()

                # ПОПРАВКА 1: composed_transform() за пълната трансформация вкл. групи
                composed = elem.composed_transform()
                if composed:
                    abs_path = abs_path.transform(composed)
                elif elem.transform:
                    abs_path = abs_path.transform(elem.transform)

                # ПОПРАВКА 2: ZoneClose за надеждна проверка на затвореност
                is_closed_svg = any(isinstance(seg, ZoneClose) for seg in elem.path.to_absolute())

                csp = CubicSuperPath(abs_path)
                for subpath in csp:
                    if len(subpath) < 2:
                        continue
                    pts = []
                    for i in range(1, len(subpath)):
                        p0 = subpath[i-1][1]
                        c1 = subpath[i-1][2]
                        c2 = subpath[i][0]
                        p1 = subpath[i][1]
                        for s in range(STEPS_PER_SEGMENT):
                            pts.append(cubic_point(p0, c1, c2, p1, s / STEPS_PER_SEGMENT))
                    pts.append(tuple(subpath[-1][1]))

                    if pts:
                        for p in pts:
                            all_x.append(p[0])
                            all_y.append(p[1])
                        path_data.append({
                            'pts': pts,
                            'tool': tool,
                            'priority': priority,
                            'is_closed': is_closed_svg
                        })

        if not path_data:
            inkex.errormsg("❌ Няма обекти за рязане!")
            return

        max_x, max_y = max(all_x), max(all_y)
        path_data.sort(key=lambda x: x['priority'])

        hpgl = ["IN", "CMD:18,1;", "CMD:35,1,2,0;"]
        current_tool = None

        for item in path_data:
            if item['tool'] != current_tool:
                hpgl.append(f"{item['tool']};")
                current_tool = item['tool']

            pts       = item['pts']
            is_closed = item['is_closed']
            final_pts = list(pts)

            # Overcut
            if item['tool'] == "P1" and ov_mm > 0 and is_closed:
                acc    = 0
                last_p = pts[0]
                for j in range(1, len(pts)):
                    d = math.hypot(pts[j][0] - last_p[0], pts[j][1] - last_p[1])
                    if d < 0.001:
                        continue
                    if acc + d >= ov_mm:
                        r = (ov_mm - acc) / d
                        final_pts.append((
                            last_p[0] + (pts[j][0] - last_p[0]) * r,
                            last_p[1] + (pts[j][1] - last_p[1]) * r
                        ))
                        break
                    final_pts.append(pts[j])
                    acc   += d
                    last_p = pts[j]

            # ПОПРАВКА 3: Посока на първия сегмент за knife offset на началната точка
            # Така началото и краят имат еднакъв offset → не разминаване
            first_dx, first_dy = 0.0, 0.0
            if item['tool'] == "P1" and k_off > 0 and is_closed and len(final_pts) > 1:
                for j in range(1, len(final_pts)):
                    fdx = final_pts[j][0] - final_pts[0][0]
                    fdy = final_pts[j][1] - final_pts[0][1]
                    fd  = math.hypot(fdx, fdy)
                    if fd > 0.001:
                        first_dx = fdx / fd
                        first_dy = fdy / fd
                        break

            last_tx, last_ty       = None, None
            last_real_x, last_real_y = -9999, -9999
            first_hpgl_point       = None  # ПОПРАВКА 4: за точно затваряне

            for i in range(len(final_pts)):
                px, py = final_pts[i]

                dist_from_last = math.hypot(px - last_real_x, py - last_real_y)
                if i != 0 and i != len(final_pts) - 1 and dist_from_last < MIN_DIST_MM:
                    continue

                curr_px, curr_py = px, py
                if item['tool'] == "P1" and k_off > 0:
                    if i == 0 and is_closed and (first_dx != 0.0 or first_dy != 0.0):
                        # Начална точка → посока на първия сегмент
                        curr_px += first_dx * k_off
                        curr_py += first_dy * k_off
                    elif i < len(final_pts) - 1:
                        dx, dy = final_pts[i+1][0] - px, final_pts[i+1][1] - py
                        dist = math.hypot(dx, dy)
                        if dist > 0.001:
                            curr_px += (dx / dist) * k_off
                            curr_py += (dy / dist) * k_off
                    else:
                        dx, dy = px - final_pts[i-1][0], py - final_pts[i-1][1]
                        dist = math.hypot(dx, dy)
                        if dist > 0.001:
                            curr_px += (dx / dist) * k_off
                            curr_py += (dy / dist) * k_off

                tx = int(round((max_y - curr_py) * SCALE))
                ty = int(round((max_x - curr_px) * SCALE))

                if tx != last_tx or ty != last_ty:
                    cmd = 'U' if i == 0 else 'D'
                    hpgl.append(f"{cmd}{tx},{ty};")

                    if i == 0:
                        first_hpgl_point = (tx, ty)

                    last_tx, last_ty     = tx, ty
                    last_real_x, last_real_y = px, py

            # ПОПРАВКА 4: Затваряме точно на началната HPGL точка
            if is_closed and ov_mm > 0 and item['tool'] == "P1" and first_hpgl_point:
                ftx, fty = first_hpgl_point
                if ftx != last_tx or fty != last_ty:
                    hpgl.append(f"D{ftx},{fty};")

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "\n".join(hpgl)

        if self.options.save_hpgl:
            with open(self.options.output_path, "w") as f:
                f.write(output)
            inkex.errormsg(f"✅ HPGL записан в: {self.options.output_path}")
        else:
            try:
                with socket.create_connection((self.options.ip, self.options.port), timeout=180) as s:
                    s.sendall(output.encode())
                    s.shutdown(socket.SHUT_WR)
                inkex.errormsg("✅ Успешно изпращане (No Markers Mode)")
            except Exception as e:
                inkex.errormsg(f"❌ Грешка: {e}")

if __name__ == "__main__":
    SendToSkyCutD24NoMarkers().run()
