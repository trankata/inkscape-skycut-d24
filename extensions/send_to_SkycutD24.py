#!/usr/bin/env python3
import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath
import socket
import math

SCALE = 40 
STEPS_PER_SEGMENT = 16

def cubic_point(p0, c1, c2, p1, t):
    x = ((1 - t)**3 * p0[0] + 3 * (1 - t)**2 * t * c1[0] + 3 * (1 - t) * t**2 * c2[0] + t**3 * p1[0])
    y = ((1 - t)**3 * p0[1] + 3 * (1 - t)**2 * t * c1[1] + 3 * (1 - t) * t**2 * c2[1] + t**3 * p1[1])
    return x, y

class SendToSkyCutD24(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--save_hpgl", type=inkex.Boolean, default=False)
        pars.add_argument("--output_path", type=str, default="skycut_output.hpgl")
        pars.add_argument("--paper_size", type=str, default="a4p")
        pars.add_argument("--ip", type=str, default="192.168.0.233")
        pars.add_argument("--port", type=int, default=8080)
        pars.add_argument("--knife_offset_mm", type=float, default=0.30)
        pars.add_argument("--overcut_mm", type=float, default=1.00)

    def effect(self):
        svg = self.svg
        k_off = self.options.knife_offset_mm
        ov_mm = self.options.overcut_mm

        paper_sizes = {
            'a4p': (210.0, 297.0), 
            'a4l': (297.0, 210.0),
            'a3p': (297.0, 420.0),  # А3 портрет
            'a3l': (420.0, 297.0)   # А3 ландшафт
        }
        
        page_width_mm, page_height_mm = paper_sizes.get(self.options.paper_size, (210.0, 297.0))

        # Дебъг информация
        inkex.errormsg(f"✅ Избрана медия: {self.options.paper_size}")
        inkex.errormsg(f"📏 Размери: {page_width_mm} × {page_height_mm} мм")
    
        viewbox = svg.get_viewbox()
        scale_x = page_width_mm / viewbox[2] if viewbox[2] else 1.0
        scale_y = page_height_mm / viewbox[3] if viewbox[3] else 1.0

        mark_layer = next((l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']") if l.label and 'mark' in l.label.lower()), None)
        cut_layer = next((l for l in svg.xpath("//svg:g[@inkscape:groupmode='layer']") if l.label and l.label.strip().lower() == 'cut'), None)

        if mark_layer is None or cut_layer is None:
            inkex.errormsg("❌ Липсва слой Mark или Cut")
            return

        marker_points = []
        for elem in mark_layer.iterdescendants():
            if isinstance(elem, PathElement) and elem.get('data-type') != 'triangle':
                path = elem.path.to_absolute()
                seg = path[0]
                pt_x = seg.end.x if hasattr(seg, 'end') else seg.x
                pt_y = seg.end.y if hasattr(seg, 'end') else seg.y
                marker_points.append((pt_x * scale_x, pt_y * scale_y))

        min_x, min_y = min(p[0] for p in marker_points), min(p[1] for p in marker_points)
        max_x, max_y = max(p[0] for p in marker_points), max(p[1] for p in marker_points)

        work_width_mm, work_height_mm = max_x - min_x, max_y - min_y
        
        # КЛЮЧОВА ПРОМЯНА: FSIZE трябва да използва page_ размери за А3!
        hpgl = [
            "IN", f"FSIZE{int(page_height_mm*SCALE)},{int(page_width_mm*SCALE)}",
            f"CMD:32,{int(page_height_mm*SCALE)},{int(page_width_mm*SCALE)},{int(min_x*SCALE)},{int(min_y*SCALE)};",
            "CMD:18,1;", "CMD:35,1,2,0;", f"TB26,{int(work_height_mm*SCALE)},{int(work_width_mm*SCALE)}"
        ]

        path_data = []
        for elem in cut_layer.iterdescendants():
            if isinstance(elem, PathElement):
                stroke = elem.style.get('stroke')
                color = str(stroke).strip().lower() if stroke else ""
                
                # ЛОГИКА ЗА ЦВЕТОВЕ
                is_black = any(c in color for c in ('#000000', 'black', '#000', '#000000ff', 'rgb(0,0,0)', 'rgb(0,0,0,1)'))
                is_red = any(c in color for c in ('#ff0000', 'red', '#f00','#ff0000ff', 'rgb(255,0,0)'))

                # ДЕБЪГ
                inkex.errormsg(f"DEBUG: color='{color}'")
                inkex.errormsg(f"DEBUG: is_black={is_black}, is_red={is_red}")

                if is_black:
                    tool, priority = "P0", 0  # Биговане - Първо
                    inkex.errormsg("DEBUG: ✅ ЗАДАВА P0 ЗА ЧЕРНО!")
                elif is_red:
                    tool, priority = "P1", 2  # Рязане Червено - Последно
                    inkex.errormsg("DEBUG: Задава P1 за червено")
                else:
                    tool, priority = "P1", 1  # Други цветове - Второ
                    inkex.errormsg(f"DEBUG: Задава P1 за цвят: {color}")

                path = elem.path.to_absolute()
                if elem.transform: 
                    path = path.transform(elem.transform)
                path_data.append({'path': path, 'tool': tool, 'priority': priority})

        # Сортиране по дефинирания приоритет
        path_data.sort(key=lambda x: x['priority'])

        current_tool = None
        for p_info in path_data:
            if p_info['tool'] != current_tool:
                hpgl.append(f"{p_info['tool']};")
                current_tool = p_info['tool']

            csp = CubicSuperPath(p_info['path'])
            for subpath in csp:
                if len(subpath) < 2: continue
                pts = []
                for i in range(1, len(subpath)):
                    p0 = (subpath[i-1][1][0] * scale_x, subpath[i-1][1][1] * scale_y)
                    c1 = (subpath[i-1][2][0] * scale_x, subpath[i-1][2][1] * scale_y)
                    c2 = (subpath[i][0][0] * scale_x, subpath[i][0][1] * scale_y)
                    p1 = (subpath[i][1][0] * scale_x, subpath[i][1][1] * scale_y)
                    for s in range(STEPS_PER_SEGMENT):
                        pts.append(cubic_point(p0, c1, c2, p1, s/STEPS_PER_SEGMENT))
                pts.append((subpath[-1][1][0] * scale_x, subpath[-1][1][1] * scale_y))

                is_closed = math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1]) < 0.2
                final_pts = list(pts)
                
                # Оверкът само за P1 инструменти
                if ov_mm > 0 and is_closed and p_info['tool'] == "P1":
                    acc = 0
                    last_p = pts[0]
                    for j in range(1, len(pts)):
                        d = math.hypot(pts[j][0]-last_p[0], pts[j][1]-last_p[1])
                        if d < 0.05: continue
                        if acc + d <= ov_mm:
                            final_pts.append(pts[j])
                            acc += d
                            last_p = pts[j]
                        else:
                            r = (ov_mm - acc) / d
                            final_pts.append((last_p[0] + (pts[j][0]-last_p[0])*r, 
                                            last_p[1] + (pts[j][1]-last_p[1])*r))
                            break

                last_tx, last_ty = None, None
                for i in range(len(final_pts)):
                    px, py = final_pts[i]
                    # Нож офсет само за P1 инструменти
                    if p_info['tool'] == "P1" and k_off > 0:
                        if i < len(final_pts)-1:
                            dx, dy = final_pts[i+1][0]-px, final_pts[i+1][1]-py
                        else:
                            dx, dy = px-final_pts[i-1][0], py-final_pts[i-1][1]
                        dist = math.hypot(dx, dy)
                        if dist > 0.001:
                            px += (dx/dist)*k_off
                            py += (dy/dist)*k_off

                    x_l, y_l = px - min_x, py - min_y
                    x_hpgl, y_hpgl = work_height_mm - y_l, work_width_mm - x_l
                    tx, ty = int(round(x_hpgl*SCALE)), int(round(y_hpgl*SCALE))
                    
                    if tx != last_tx or ty != last_ty:
                        hpgl.append(f"{'U' if i == 0 else 'D'}{tx},{ty};")
                        last_tx, last_ty = tx, ty

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "\n".join(hpgl)

        if self.options.save_hpgl:
            with open(self.options.output_path, "w") as f: f.write(output)
            inkex.errormsg(f"✅ HPGL записан в: {self.options.output_path}")
        else:
            try:
                with socket.create_connection((self.options.ip, self.options.port), timeout=180) as s:
                    s.sendall(output.encode())
                inkex.errormsg("✅ Файлът е изпратен успешно!")
            except Exception as e:
                inkex.errormsg(f"❌ Грешка при изпращане: {e}")

if __name__ == "__main__":
    SendToSkyCutD24().run()
