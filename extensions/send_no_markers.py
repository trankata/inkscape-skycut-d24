#!/usr/bin/env python3
import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath
import socket
import math

# Константи за мащабиране и прецизност
SCALE = 40 
STEPS_PER_SEGMENT = 10 

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
                color = str(stroke).lower() if stroke else ""
                
                # Приоритизация по цвят
                is_black = any(c in color for c in ('#000000', 'black', '#000', 'rgb(0,0,0)'))
                is_red = any(c in color for c in ('#ff0000', 'red', '#f00', 'rgb(255,0,0)'))

                if is_black:
                    tool, priority, has_oc = "P0", 0, False
                elif is_red:
                    tool, priority, has_oc = "P1", 2, True
                else:
                    tool, priority, has_oc = "P1", 1, True

                abs_path = elem.path.to_absolute()
                if elem.transform: abs_path = abs_path.transform(elem.transform)

                csp = CubicSuperPath(abs_path)
                for subpath in csp:
                    pts = []
                    for i in range(1, len(subpath)):
                        p0, c1, c2, p1 = subpath[i-1][1], subpath[i-1][2], subpath[i][0], subpath[i][1]
                        for s in range(STEPS_PER_SEGMENT):
                            t = s / STEPS_PER_SEGMENT
                            mt = 1 - t
                            pts.append((
                                mt**3*p0[0] + 3*mt**2*t*c1[0] + 3*mt*t**2*c2[0] + t**3*p1[0],
                                mt**3*p0[1] + 3*mt**2*t*c1[1] + 3*mt*t**2*c2[1] + t**3*p1[1]
                            ))
                    pts.append(subpath[-1][1])
                    
                    if pts:
                        for p in pts:
                            all_x.append(p[0]); all_y.append(p[1])
                        path_data.append({'pts': pts, 'tool': tool, 'priority': priority, 'has_oc': has_oc})

        if not path_data:
            inkex.errormsg("❌ Няма обекти за рязане в слой 'Cut'!")
            return

        max_x, max_y = max(all_x), max(all_y)
        path_data.sort(key=lambda x: x['priority'])

        hpgl = ["IN", "CMD:18,1;", "CMD:35,1,2,0;"]
        current_tool = None
        
        for item in path_data:
            if item['tool'] != current_tool:
                hpgl.append(f"{item['tool']};")
                current_tool = item['tool']

            pts = item['pts']
            # Проверка дали пътят е затворен за оверкът
            is_closed = math.hypot(pts[0][0]-pts[-1][0], pts[0][1]-pts[-1][1]) < 0.2
            
            final_pts = list(pts)
            # Логика за добавяне на оверкът
            if item['has_oc'] and ov_mm > 0 and is_closed:
                accumulated = 0
                last_p = pts[0]
                for j in range(1, len(pts)):
                    d_step = math.hypot(pts[j][0] - last_p[0], pts[j][1] - last_p[1])
                    if d_step < 0.05: continue 
                    
                    if accumulated + d_step <= ov_mm:
                        final_pts.append(pts[j])
                        accumulated += d_step
                        last_p = pts[j]
                    else:
                        ratio = (ov_mm - accumulated) / d_step
                        final_p = (last_p[0] + (pts[j][0] - last_p[0]) * ratio,
                                   last_p[1] + (pts[j][1] - last_p[1]) * ratio)
                        final_pts.append(final_p)
                        break

            # Генериране на HPGL команди с филтър за дубликати
            last_tx, last_ty = None, None
            for i in range(len(final_pts)):
                curr = final_pts[i]
                px, py = curr[0], curr[1]

                # Knife Offset компенсация
                if item['tool'] == "P1" and k_off > 0:
                    if i < len(final_pts) - 1:
                        p_next = final_pts[i+1]
                        dx, dy = p_next[0]-curr[0], p_next[1]-curr[1]
                    else:
                        p_prev = final_pts[i-1]
                        dx, dy = curr[0]-p_prev[0], curr[1]-p_prev[1]
                    
                    dist = math.hypot(dx, dy)
                    if dist > 0.001:
                        px += (dx/dist) * k_off
                        py += (dy/dist) * k_off
                
                # Мащабиране към координати на плотера
                tx, ty = int(round((max_y - py) * SCALE)), int(round((max_x - px) * SCALE))
                
                # ФИЛТЪР: Пишем командата само ако позицията е различна от последната
                if tx != last_tx or ty != last_ty:
                    hpgl.append(f"{'U' if i == 0 else 'D'}{tx},{ty};")
                    last_tx, last_ty = tx, ty

        hpgl.extend(["U0,0;", "@;", "@;"])
        output = "\n".join(hpgl)

        # Изход (Файл или Сокет)
        if self.options.save_hpgl:
            try:
                with open(self.options.output_path, "w") as f:
                    f.write(output)
                inkex.errormsg(f"✅ HPGL записан в: {self.options.output_path}")
            except Exception as e: inkex.errormsg(f"❌ Грешка при запис: {e}")
        else:
            try:
                with socket.create_connection((self.options.ip, self.options.port), timeout=10) as s:
                    s.sendall(output.encode())
                inkex.errormsg(f"✅ Изпратено успешно към {self.options.ip}")
            except Exception as e: inkex.errormsg(f"❌ Грешка при изпращане: {e}")

if __name__ == "__main__":
    SendToSkyCutD24NoMarkers().run()
