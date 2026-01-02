#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Corner Markers (L-shaped) – Inkscape extension
# Copyright (C) 2025 Anton Kutrubiev
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import inkex
from inkex import PathElement
from inkex.paths import CubicSuperPath
import socket
import os
import math

# Константи
SCALE = 40  # 1 mm = 40 plotter units
STEPS_PER_SEGMENT = 16

def cubic_point(p0, c1, c2, p1, t):
    x = ((1 - t)**3 * p0[0] +
         3 * (1 - t)**2 * t * c1[0] +
         3 * (1 - t) * t**2 * c2[0] +
         t**3 * p1[0])
    y = ((1 - t)**3 * p0[1] +
         3 * (1 - t)**2 * t * c1[1] +
         3 * (1 - t) * t**2 * c2[1] +
         t**3 * p1[1])
    return x, y

def extend_path_for_overcut(points, overcut_mm):
    """
    Добавя overcut към затворена пътека.
    points: списък от (x, y) в mm
    overcut_mm: разстояние за удължаване (>0)
    Връща: списък с допълнителна точка в края, ако пътеката е затворена.
    """
    if overcut_mm <= 0 or len(points) < 2:
        return points

    # Проверка дали пътеката е затворена: първата ≈ последната
    first = points[0]
    last = points[-1]
    if abs(first[0] - last[0]) < 0.01 and abs(first[1] - last[1]) < 0.01:
        # Вземаме предпоследната и последната точка за посока
        if len(points) >= 2:
            p_prev = points[-2]
            p_last = points[-1]
        else:
            return points

        dx = p_last[0] - p_prev[0]
        dy = p_last[1] - p_prev[1]
        length = math.hypot(dx, dy)
        if length > 0.001:
            dx_norm = dx / length
            dy_norm = dy / length
            overcut_x = p_last[0] + dx_norm * overcut_mm
            overcut_y = p_last[1] + dy_norm * overcut_mm
            return points + [(overcut_x, overcut_y)]
    return points

class SendToSkyCutD24(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--save_hpgl", type=inkex.Boolean, default=False)
        pars.add_argument("--output_path", type=str, default="skycut_output.hpgl")
        pars.add_argument("--paper_size", type=str, default="a4p")
        pars.add_argument("--ip", type=str, default="192.168.0.233")
        pars.add_argument("--port", type=int, default=8080)
        pars.add_argument("--knife_offset_mm", type=float, default=0.30)
        pars.add_argument("--overcut_mm", type=float, default=0.30)  # ← NOVO

    def effect(self):
        svg = self.svg
        knife_offset_mm = self.options.knife_offset_mm
        overcut_mm = self.options.overcut_mm

        # === ИЗБОР НА РАЗМЕР НА МЕДИЯТА ===
        paper_sizes = {
            'a4p': (210.0, 297.0),
            'a4l': (297.0, 210.0),
            'a3p': (297.0, 420.0),
            'a3l': (420.0, 297.0),
        }
        page_width_mm, page_height_mm = paper_sizes.get(self.options.paper_size, (210.0, 297.0))

        # === Мащаб от viewBox към mm ===
        viewbox = svg.get('viewBox')
        if viewbox:
            vb_vals = list(map(float, viewbox.split()))
            vb_width = vb_vals[2]
            vb_height = vb_vals[3]
            scale_x = page_width_mm / vb_width
            scale_y = page_height_mm / vb_height
        else:
            scale_x = 1.0
            scale_y = 1.0

        knife_offset_u = knife_offset_mm * SCALE

        # === Mark слой ===
        mark_layer = None
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label and 'mark' in layer.label.lower():
                mark_layer = layer
                break
        if mark_layer is None:
            inkex.errormsg("❌ Няма слой 'Mark'!")
            return

        marker_points = []
        for elem in mark_layer.iterdescendants():
            if isinstance(elem, PathElement):
                path = elem.path.to_absolute()
                for seg in path:
                    if hasattr(seg, 'x') and hasattr(seg, 'y'):
                        x_mm = seg.x * scale_x
                        y_mm = seg.y * scale_y
                        marker_points.append((x_mm, y_mm))
                        break

        if len(marker_points) != 4:
            inkex.errormsg(f"❌ Очакват се 4 маркера, намерени: {len(marker_points)}")
            return

        xs = [p[0] for p in marker_points]
        ys = [p[1] for p in marker_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        work_width_mm = max_x - min_x
        work_height_mm = max_y - min_y

        if work_width_mm > page_width_mm + 0.1 or work_height_mm > page_height_mm + 0.1:
            inkex.errormsg(
                f"⚠️ Работната зона ({work_width_mm:.1f}×{work_height_mm:.1f} mm) "
                f"излиза извън избрания размер: {page_width_mm}×{page_height_mm} mm!"
            )

        work_width_u = int(work_width_mm * SCALE)
        work_height_u = int(work_height_mm * SCALE)
        page_width_u = int(page_width_mm * SCALE)
        page_height_u = int(page_height_mm * SCALE)
        margin_left_u = int(min_x * SCALE)
        margin_bottom_u = int(min_y * SCALE)

                # === Cut слой ===
        cut_layer = None
        for layer in svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.label and layer.label.strip().lower() == 'cut':
                cut_layer = layer
                break
        if cut_layer is None:
            inkex.errormsg("❌ Няма слой с точно име 'Cut'!")
            return

        path_data = []
        for elem in cut_layer.iterdescendants():
            if isinstance(elem, PathElement):
                color = elem.style.get('stroke', '#000000').lower()
                if color in ('#000000', 'black', 'rgb(0,0,0)'):
                    priority = 0
                elif color in ('#ff0000', 'red', 'rgb(255,0,0)'):
                    priority = 2
                else:
                    priority = 1
                path_data.append((elem.path, color, priority))

        if not path_data:
            inkex.errormsg("❌ Няма пътища в слой 'Cut'!")
            return

        path_data.sort(key=lambda x: x[2])

        # === Генериране на HP-GL ===
        hpgl = [
            "IN",
            f"FSIZE{work_height_u},{work_width_u}",
            f"CMD:32,{page_height_u},{page_width_u},{margin_left_u},{margin_bottom_u};",
            "CMD:18,1;",
            "CMD:35,1,2,0;",
            f"TB26,{work_height_u},{work_width_u}"
        ]

        current_tool = None
        for path, color, priority in path_data:
            tool = "P0" if color in ('#000000', 'black', 'rgb(0,0,0)') else "P1"
            if tool != current_tool:
                hpgl.append(f"{tool};")
                current_tool = tool

            # Генерираме всички точки от пътеката в mm
            all_points_mm = []
            csp = CubicSuperPath(path.to_absolute())
            for subpath in csp:
                if len(subpath) < 2:
                    continue
                prev = subpath[0][1]
                for i in range(1, len(subpath)):
                    p0 = prev
                    c1 = subpath[i-1][2]
                    c2 = subpath[i][0]
                    p1 = subpath[i][1]

                    p0_mm = (p0[0] * scale_x, p0[1] * scale_y)
                    c1_mm = (c1[0] * scale_x, c1[1] * scale_y)
                    c2_mm = (c2[0] * scale_x, c2[1] * scale_y)
                    p1_mm = (p1[0] * scale_x, p1[1] * scale_y)

                    for s in range(STEPS_PER_SEGMENT + 1):
                        t = s / STEPS_PER_SEGMENT
                        x, y = cubic_point(p0_mm, c1_mm, c2_mm, p1_mm, t)
                        all_points_mm.append((x, y))

                    prev = p1

            # === Прилагаме overcut САМО за P1 и ако е >0 ===
            if tool == "P1" and overcut_mm > 0:
                all_points_mm = extend_path_for_overcut(all_points_mm, overcut_mm)

            # === Преобразуваме точките в HP-GL команди ===
            first_point = None
            for x_orig, y_orig in all_points_mm:
                if tool == "P1":
                    x_orig += knife_offset_mm

                x_local = x_orig - min_x
                y_local = y_orig - min_y
                x_flipped = work_width_mm - x_local
                x_hpgl = work_height_mm - y_local
                y_hpgl = x_flipped

                x_u = int(round(x_hpgl * SCALE))
                y_u = int(round(y_hpgl * SCALE))

                if first_point is None:
                    first_point = (x_u, y_u)
                    hpgl.append(f"U{x_u},{y_u};")
                else:
                    hpgl.append(f"D{x_u},{y_u};")

        hpgl.extend(["U0,0;", "@;", "@;"])
        hpgl_text = "\n".join(hpgl)

        # === Запазване или изпращане ===
        if self.options.save_hpgl:
            output_path = self.options.output_path.strip()
            if not output_path:
                inkex.errormsg("❌ Празен път за запазване!")
                return
            if not os.path.isabs(output_path):
                output_path = os.path.join(os.path.dirname(__file__), output_path)
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(hpgl_text)
                inkex.errormsg(f"✅ HP-GL записан в: {output_path}")
            except Exception as e:
                inkex.errormsg(f"❌ Грешка при запис: {e}")
        else:
            ip = self.options.ip.strip()
            port = self.options.port
            try:
                with socket.create_connection((ip, port), timeout=90) as sock:
                    sock.sendall((hpgl_text + "\n").encode("utf-8"))
                inkex.errormsg("✅ Успешно изпратено към SkyCut D24!")
            except Exception as e:
                inkex.errormsg(f"❌ Неуспех: {e}")

if __name__ == "__main__":
    SendToSkyCutD24().run()
