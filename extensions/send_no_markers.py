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
import math
import os

SCALE = 40  # 1 mm = 40 plotter units
STEPS_PER_SEGMENT = 8

def cubic_point(p0, c1, c2, p1, t):
    mt = 1 - t
    return (
        mt*mt*mt*p0[0] + 3*mt*mt*t*c1[0] + 3*mt*t*t*c2[0] + t*t*t*p1[0],
        mt*mt*mt*p0[1] + 3*mt*mt*t*c1[1] + 3*mt*t*t*c2[1] + t*t*t*p1[1]
    )

def extend_path_for_overcut(points, overcut_mm):
    if overcut_mm <= 0 or len(points) < 2:
        return points
    first = points[0]
    last = points[-1]
    if abs(first[0] - last[0]) < 0.01 and abs(first[1] - last[1]) < 0.01:
        if len(points) >= 2:
            p_prev = points[-2]
            p_last = points[-1]
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

class SendToSkyCutD24NoMarkers(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--ip", type=str, default="192.168.0.233")
        pars.add_argument("--port", type=int, default=8080)
        pars.add_argument("--knife_offset_mm", type=float, default=0.10)
        pars.add_argument("--overcut_mm", type=float, default=0.60)
        pars.add_argument("--save_hpgl", type=inkex.Boolean, default=False)
        pars.add_argument("--output_path", type=str, default="skycut_output.hpgl")

    def effect(self):
        knife_offset_mm = self.options.knife_offset_mm
        overcut_mm = self.options.overcut_mm

        cut_layer = None
        for layer in self.svg.xpath("//svg:g[@inkscape:groupmode='layer']"):
            if layer.get('inkscape:label') == 'Cut':
                cut_layer = layer
                break
        if cut_layer is None:
            inkex.errormsg("❌ No layer named 'Cut' found!")
            return

        path_data = []
        all_points = []
        for elem in cut_layer.iterdescendants():
            if isinstance(elem, PathElement):
                color = elem.style.get('stroke', '#000000').lower()
                if color in ('#000000', 'black', 'rgb(0,0,0)'):
                    priority = 0
                elif color in ('#ff0000', 'red', 'rgb(255,0,0)'):
                    priority = 2
                else:
                    priority = 1
                path_data.append((elem, priority))
                csp = CubicSuperPath(elem.path.to_absolute())
                for subpath in csp:
                    for i in range(len(subpath)):
                        x = subpath[i][0][0]
                        y = subpath[i][0][1]
                        all_points.append((x, y))

        if not path_data:
            inkex.errormsg("❌ No paths in 'Cut' layer!")
            return
        if not all_points:
            inkex.errormsg("❌ No points found!")
            return

        # === Намиране на bounding box ===
        min_x = min(p[0] for p in all_points)
        max_x = max(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_y = max(p[1] for p in all_points)

        hpgl = ["IN", "CMD:18,1;", "CMD:35,1,2,0;"]
        path_data.sort(key=lambda x: x[1])
        current_tool = None

        for elem, priority in path_data:
            tool = "P0" if priority == 0 else "P1"
            if tool != current_tool:
                hpgl.append(f"{tool};")
                current_tool = tool

            points_mm = []
            csp = CubicSuperPath(elem.path.to_absolute())
            for subpath in csp:
                if len(subpath) < 2:
                    continue
                prev = subpath[0][1]
                for i in range(1, len(subpath)):
                    p0 = prev
                    c1 = subpath[i-1][2]
                    c2 = subpath[i][0]
                    p1 = subpath[i][1]
                    for s in range(STEPS_PER_SEGMENT + 1):
                        t = s / STEPS_PER_SEGMENT
                        x, y = cubic_point(p0, c1, c2, p1, t)
                        points_mm.append((x, y))
                    prev = p1

            if tool == "P1" and overcut_mm > 0:
                points_mm = extend_path_for_overcut(points_mm, overcut_mm)

            for i, (x, y) in enumerate(points_mm):
                if tool == "P1":
                    x += knife_offset_mm

                # === ТВОЯТА ИДЕЯ: долу-десен = (0,0) ===
                # Локални координати спрямо долу-десен ъгъл
                dx = max_x - x   # 0 = дясно
                dy = max_y - y   # 0 = долу

                # === За SkyCut D24: разменяме X и Y ===
                x_u = int(round(dy * SCALE))
                y_u = int(round(dx * SCALE))

                cmd = "U" if i == 0 else "D"
                hpgl.append(f"{cmd}{x_u},{y_u};")

        hpgl.extend(["U0,0;", "@;", "@;"])
        hpgl_text = "\n".join(hpgl)

        if self.options.save_hpgl:
            output_path = self.options.output_path.strip()
            if not output_path:
                inkex.errormsg("❌ Output path is empty!")
                return
            if not os.path.isabs(output_path):
                output_path = os.path.join(os.path.dirname(__file__), output_path)
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(hpgl_text)
                inkex.errormsg(f"✅ HP-GL saved to:\n{output_path}")
            except Exception as e:
                inkex.errormsg(f"❌ Save failed: {e}")
        else:
            try:
                with socket.create_connection((self.options.ip, self.options.port), timeout=90) as sock:
                    sock.sendall((hpgl_text + "\n").encode("utf-8"))
                inkex.errormsg("✅ Successfully sent to SkyCut D24!")
            except Exception as e:
                inkex.errormsg(f"❌ Failed to send: {e}")

if __name__ == "__main__":
    SendToSkyCutD24NoMarkers().run()
