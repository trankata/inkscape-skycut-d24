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

def is_path_closed(points, tolerance=0.01):
    """Проверява дали пътеката е затворена."""
    if len(points) < 3:
        return False
    first_x, first_y = points[0]
    last_x, last_y = points[-1]
    return (abs(first_x - last_x) < tolerance and 
            abs(first_y - last_y) < tolerance)

def create_real_overcut(points, overcut_mm):
    """
    Създава истински overcut: повтаря част от пътя.
    Машината тръгва от първата точка, затваря контура,
    после тръгва да повтаря същия път и спира след overcut_mm.
    """
    if overcut_mm <= 0 or len(points) < 3:
        return points
    
    if not is_path_closed(points):
        return points
    
    total_length = 0.0
    segment_lengths = []
    
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        length = math.hypot(x2 - x1, y2 - y1)
        segment_lengths.append(length)
        total_length += length
    
    if total_length == 0:
        return points
    
    remaining_overcut = overcut_mm
    overcut_points = []
    
    for i in range(1, len(points) - 1):
        if remaining_overcut <= 0:
            break
            
        x1, y1 = points[i-1]
        x2, y2 = points[i]
        
        segment_length = segment_lengths[i-1]
        
        if remaining_overcut >= segment_length:
            overcut_points.append((x2, y2))
            remaining_overcut -= segment_length
        else:
            ratio = remaining_overcut / segment_length
            stop_x = x1 + (x2 - x1) * ratio
            stop_y = y1 + (y2 - y1) * ratio
            overcut_points.append((stop_x, stop_y))
            remaining_overcut = 0
            break
    
    return points + overcut_points

class SendToSkyCutD24(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--save_hpgl", type=inkex.Boolean, default=False)
        pars.add_argument("--output_path", type=str, default="skycut_output.hpgl")
        pars.add_argument("--paper_size", type=str, default="a4p")
        pars.add_argument("--ip", type=str, default="192.168.0.233")
        pars.add_argument("--port", type=int, default=8080)
        pars.add_argument("--knife_offset_mm", type=float, default=0.30)
        pars.add_argument("--overcut_mm", type=float, default=0.30)

    def effect(self):
        svg = self.svg
        knife_offset_mm = self.options.knife_offset_mm
        overcut_mm = self.options.overcut_mm

        paper_sizes = {
            'a4p': (210.0, 297.0),
            'a4l': (297.0, 210.0),
            'a3p': (297.0, 420.0),
            'a3l': (420.0, 297.0),
        }
        page_width_mm, page_height_mm = paper_sizes.get(self.options.paper_size, (210.0, 297.0))

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
                # ПРОМЯНА ТУК: Игнорираме триъгълника
                if elem.get('data-type') == 'triangle':
                    continue  # Пропускаме триъгълника!
                    
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
                
                # Проверка за черен цвят
                is_black = False
                if color in ('#000000', 'black', '#000', 'rgb(0,0,0)', 'rgb(0, 0, 0)'):
                    is_black = True
                elif color.startswith('#') and color.lower() in ('#000000', '#000'):
                    is_black = True
                elif color.startswith('rgb(0,0,0') or color.startswith('rgb(0, 0, 0'):
                    is_black = True
                elif color == '#000':
                    is_black = True
                
                if is_black:
                    tool = "P0"
                    priority = 0  # Първи - черни пътища
                    has_overcut = False
                else:
                    # Проверка за червен цвят
                    is_red = False
                    if color in ('#ff0000', 'red', '#f00', 'rgb(255,0,0)', 'rgb(255, 0, 0)'):
                        is_red = True
                    elif color.startswith('#') and color.lower() in ('#ff0000', '#f00'):
                        is_red = True
                    elif color.startswith('rgb(255,0,0') or color.startswith('rgb(255, 0, 0'):
                        is_red = True
                    
                    if is_red:
                        tool = "P1"
                        priority = 2  # Трети - червени пътища (последни)
                        has_overcut = True
                    else:
                        tool = "P1"
                        priority = 1  # Втори - други цветове
                        has_overcut = True
                
                path_data.append({
                    'path': elem.path,
                    'tool': tool,
                    'priority': priority,
                    'has_overcut': has_overcut
                })

        if not path_data:
            inkex.errormsg("❌ Няма пътища в слой 'Cut'!")
            return

        # Сортираме по priority: 0 (черни), 1 (други), 2 (червени)
        path_data.sort(key=lambda x: x['priority'])

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
        for path_info in path_data:
            tool = path_info['tool']
            has_overcut = path_info['has_overcut']
            
            if tool != current_tool:
                hpgl.append(f"{tool};")
                current_tool = tool

            all_points_mm = []
            csp = CubicSuperPath(path_info['path'].to_absolute())
            
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

            if has_overcut and overcut_mm > 0:
                all_points_mm = create_real_overcut(all_points_mm, overcut_mm)

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
